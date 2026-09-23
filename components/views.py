"""Веб-интерфейс библиотеки: список, карточка, создание, правка, удаление.

Остальное — по своим модулям: помощники списка в :mod:`components.listing`,
импорт внешних ссылок в :mod:`components.link_views`, картинка посадочного
места в :mod:`components.image_views`, глобальный поиск в
:mod:`components.search_views`, журнал изменений в
:mod:`components.change_views`.
"""

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.utils.text import slugify
from django.views import View

from boards.stats import bom_coverage
from boards.usage import find_usages, usage_summary
from users.roles import admin_only, component_editor

from .cache import COUNTS_KEY, cached
from .db import fallback, unavailable
from .duplicates import CHECKS, DEFAULT_CHECK, find_duplicates
from .editing import ComponentDraft
from .export import csv_response, export_stamp
from .filter_forms import FilterForm
from .forms import group_fields
from .history import history, record_deletion
from .image_views import footprint_of
from .listing import (
    PAGE_SIZES,
    category_or_404,
    fetch,
    filter_choices,
    page_size,
    sorted_queryset,
)
from .matching import usable
from .models import FootprintImage, StepRenderJob
from .querystring import with_params
from .registry import MAIN_CATEGORIES, REPLACEMENT_CATEGORIES, counterpart
from .step import normalize_footprint

RELATED_LIMIT = 50
DUPLICATE_PAGE_SIZE = 50


def _read_only_redirect(request, category):
    """Уводит из группы, которую менять нельзя. Иначе возвращает None.

    Проверка нужна и форме, и удалению, а список групп «только для
    чтения» ведёт реестр — значит, и ответ на неё должен быть один.
    """
    if not category.read_only:
        return None
    messages.warning(request, f"«{category.title}» открыт только для чтения.")
    return redirect("components:list", slug=category.slug)


# ---- главная -------------------------------------------------------------

def _count_rows():
    """Сколько записей в каждой рабочей группе. Возвращает (строки, сбои)."""
    rows, failed = [], []
    for category in MAIN_CATEGORIES:
        with unavailable(category.table, failed):
            rows.append({"table": category.table,
                         "count": category.model.objects.count()})
    return rows, failed


def dashboard(request):
    """Стартовая страница: сколько чего лежит в справочнике.

    Четырнадцать ``COUNT(*)`` по большим таблицам — заметная цена для
    страницы, которую открывают чаще всех остальных, поэтому счётчики
    кэшируются. В кэш кладутся только числа: категории в нём хранить нельзя,
    да и незачем — они и так под рукой.
    """
    counted, failed = cached(COUNTS_KEY, _count_rows)

    by_table = {item["table"]: item["count"] for item in counted}
    rows = [{"category": category, "count": by_table[category.table]}
            for category in MAIN_CATEGORIES if category.table in by_table]

    top = max((row["count"] for row in rows), default=0) or 1
    for row in rows:
        row["share"] = round(row["count"] / top * 100)
    rows.sort(key=lambda row: -row["count"])

    return render(request, "components/dashboard.html", {
        # насколько состав плат опирается на библиотеку, а не на текст из файла
        "coverage": bom_coverage(),
        "rows": rows,
        "total": sum(row["count"] for row in rows),
        "failed": failed,
        "replacement_categories": REPLACEMENT_CATEGORIES,
    })


# ---- список --------------------------------------------------------------

def component_list(request, slug):
    category = category_or_404(slug)
    model = category.model

    filters = filter_choices(category, request.GET)
    filter_form = FilterForm(request.GET or None, filters=filters)

    queryset = (model.objects.all()
                .search(request.GET.get("q"))
                .apply_filters(request.GET, category.filter_fields))
    queryset, sort, direction = sorted_queryset(queryset, category, request)

    if request.GET.get("export") == "csv":
        return _export_csv(category, queryset,
                           request.user.get_username())

    per_page = page_size(request)
    paginator = Paginator(queryset, per_page)
    page = paginator.get_page(request.GET.get("page"))

    columns = category.verbose_columns
    rows = [{"obj": obj,
             "cells": [(name, getattr(obj, name)) for name, _ in columns]}
            for obj in page.object_list]

    # HTMX просит только панель — фильтры и таблицу (list.html#panel):
    # фильтры сужают друг друга, и обновлять одну таблицу нельзя. Обычный
    # запрос получает страницу целиком
    template = ("components/list.html#panel" if getattr(request, "htmx", False)
                else "components/list.html")
    return render(request, template, {
        "category": category,
        "columns": columns,
        "rows": rows,
        "page": page,
        "paginator": paginator,
        "filter_form": filter_form,
        "sort": sort,
        "dir": direction,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "export_url": with_params(request.GET, export="csv"),
    })


def _export_csv(category, queryset, username=""):
    """Выгрузка списка компонентов с отметкой о том, кто её сделал.

    Отметка стоит перед таблицей, как в выгрузке состава платы: файл уходит
    в переписку, и по нему должно быть видно, кто и когда его достал. Из-за
    неё заголовок колонок — третья строка, а не первая; Excel это
    переживает, а читающему CSV программой нужен пропуск двух строк.
    """
    fields = category.ordered_fields
    filename = f"{slugify(category.table) or category.slug}.csv"
    rows = ([getattr(obj, f.name) for f in fields]
            for obj in queryset.iterator(chunk_size=500))
    return csv_response(filename, [str(f.verbose_name) for f in fields], rows,
                        preamble=export_stamp(username))


# ---- карточка ------------------------------------------------------------

def _related_by_oy_id(category, obj, oy_id):
    """Аналоги: записи с тем же OY ID в этой таблице и в парной ей.

    Заглушки вроде «---» и «?» сюда не доходят — по ним в аналоги попало бы
    всё, у чего OY ID тоже не заполнен.
    """
    if not oy_id:
        return []
    sources = [c for c in (category, counterpart(category)) if c is not None]
    # оригиналы идут первыми, замены следом
    sources.sort(key=lambda c: c.replacement)

    related = []
    for source in sources:
        found = source.model.objects.filter(oy_id=oy_id)
        if source.slug == category.slug:
            found = found.exclude(pk=obj.pk)
        related += [{"obj": item, "category": source}
                    for item in found[:RELATED_LIMIT]]
    return related[:RELATED_LIMIT]


# Что показывается в «основных характеристиках», в этом порядке. Всё
# остальное уходит во вкладку «Параметры».
#
# Список общий для всех групп и задан явно, а не вычислен: «основное» —
# это то, по чему компонент опознают и заказывают, и оно одинаково у
# конденсатора и у микросхемы. Параметры же у каждой группы свои, их
# десятки, и в карточке они раньше шли сплошной лентой вперемешку с
# артикулами. Поля, которых в таблице нет (у замен, например, нет
# Allegro), просто не выводятся.
# Основные характеристики: два столбца с заданным составом и порядком.
#
# Столбцы разложены здесь, а не сеткой в разметке, потому что состав строк
# плавает: незаполненные поля в карточку не попадают. Сетка раскладывала бы
# то, что осталось, по порядку — и при паре пустых полей Group уезжал бы во
# второй столбец, а Datasheet в первый. Слева — чем компонент опознают,
# справа — сопровождение: ссылки, статус, кто и когда завёл.
MAIN_LEFT = ("vendor_pn", "vendor", "oy_id", "oy_pn", "gbt_pn", "group",
             "subgroup")
MAIN_RIGHT = ("tracker_url", "datasheet", "country", "notice", "status",
              "author", "created")
MAIN_FIELDS = MAIN_LEFT + MAIN_RIGHT

# Description стоит над характеристиками отдельной строкой, а не в списке.
# Это единственное поле, которое читают фразой, а не парой «подпись —
# значение»: в ряду коротких значений оно занимало две строки и ломало
# колонку, а прочитать его хотят первым.
DESCRIPTION_FIELD = "description"


def _split_fields(filled):
    """Делит заполненные поля: описание, левый столбец, правый, остальные.

    Основные идут в порядке :data:`MAIN_LEFT` и :data:`MAIN_RIGHT`, а не в
    порядке колонок таблицы: читают их сверху вниз, и артикул должен
    стоять первым, где бы он ни лежал в схеме. Остальные сохраняют
    табличный порядок — своего у них нет, и задал его тот, кто вёл
    таблицу.
    """
    by_name = {name: row for row in filled for name in (row[2],)}
    description = by_name.get(DESCRIPTION_FIELD)
    left = [by_name[name] for name in MAIN_LEFT if name in by_name]
    right = [by_name[name] for name in MAIN_RIGHT if name in by_name]
    skip = set(MAIN_FIELDS) | {DESCRIPTION_FIELD}
    rest = [row for row in filled if row[2] not in skip]
    return description, left, right, rest


def _borrowed_image(related):
    """Картинка соседа по OY ID — для записей без своего посадочного места.

    Нужна заменам. Колонки Allegro PCB Footprint в таблицах замен нет
    (см. ``AllegroFields``), значит картинку по ней не найти никогда, а
    показать деталь надо: замена — тот же компонент с тем же OY ID, и
    рендер корпуса у них общий.

    Ищем среди тех же записей, что уже собраны для вкладки «Аналоги», —
    лишнего запроса за ними не будет, а картинки всех соседей берутся
    одним запросом. Рабочие таблицы просматриваются раньше замен: только
    у них и есть посадочное место.

    Возвращает ``(картинка, чья она)`` — вторым идёт запись соседа, чтобы
    карточка могла сказать, чей это рендер, и дать ссылку на него.
    """
    if not related:
        return None, None

    targets = sorted(related, key=lambda item: item["category"].replacement)
    found = FootprintImage.for_footprints(
        footprint_of(item["obj"]) for item in targets)

    for item in targets:
        image = found.get(normalize_footprint(footprint_of(item["obj"])))
        if image:
            return image, item
    return None, None


def component_detail(request, slug, pk):
    category = category_or_404(slug)
    obj = fetch(category, pk)
    # суррогатный id — служебный, пользователю он ничего не говорит
    fields = [(f.verbose_name, getattr(obj, f.name), f.name)
              for f in category.ordered_fields
              if not (f.primary_key and f.get_internal_type() == "AutoField")
              and f.name not in category.hidden_fields]
    filled = [f for f in fields if f[1] not in (None, "")]
    description, left_fields, right_fields, other_fields = \
        _split_fields(filled)

    oy_id = usable(getattr(obj, "oy_id", ""))
    # где этот компонент стоит на платах: по связи из импорта,
    # а если её нет — по артикулам
    usages, matched_by = find_usages(obj, category.table)

    related = _related_by_oy_id(category, obj, oy_id)
    # Картинка ищется по посадочному месту в момент показа, а не хранится
    # у записи: так её сразу видят и новые компоненты с известным
    # footprint, и те, что завели в базу другие программы
    image = FootprintImage.for_footprint(footprint_of(obj))
    # своего места нет — показываем соседскую, но не молча: карточка
    # скажет, чья она, и даст на неё ссылку
    borrowed_from = None
    if image is None:
        image, borrowed_from = _borrowed_image(related)

    return render(request, "components/detail.html", {
        "category": category,
        "object": obj,
        "left_fields": left_fields,
        "right_fields": right_fields,
        "other_fields": other_fields,
        "description": description,
        "usages": usages,
        "usage_match": matched_by,
        "changes": history(category.table, obj.pk),
        "pair": counterpart(category),
        "oy_id": oy_id,
        "related": related,
        "related_limit": RELATED_LIMIT,
        "image": image,
        "borrowed_from": borrowed_from,
        # без посадочного места картинке не к чему привязаться
        "has_footprint_field": (
            hasattr(category.model, "allegro_pcb_footprint")
            and "allegro_pcb_footprint" not in category.hidden_fields),
        # картинка может как раз готовиться — карточка скажет об этом
        "job": StepRenderJob.latest_for(footprint_of(obj)),
    })


# ---- создание и правка ---------------------------------------------------

@method_decorator(component_editor, name="dispatch")
class ComponentEditView(View):
    """Создание и правка — одна форма на все случаи.

    Здесь только то, что про запрос: права, откуда взять образец и
    основной компонент, перенаправления и сообщения. Что в форме заперто,
    откуда значения и как сохранять — в :class:`components.editing.ComponentDraft`.
    """

    template_name = "components/form.html"

    def dispatch(self, request, slug, pk=None, *args, **kwargs):
        category = category_or_404(slug)
        read_only = _read_only_redirect(request, category)
        if read_only is not None:
            return read_only

        source = None
        if category.replacement and pk is None:
            source, refused = self._require_source(request, category, slug)
            if refused is not None:
                return refused

        obj = category.model() if pk is None else fetch(category, pk)
        # компонент, с которого списываем параметры («Добавить по образцу»)
        sample = (self._find_sample(request, category) if obj.pk is None
                  else None)
        self.draft = ComponentDraft(category, obj, source=source, sample=sample)
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _find_sample(request, category):
        """Компонент из ?like= — образец для нового.

        Берётся только из этой же группы: у соседней таблицы другой набор
        полей, и перенос превратился бы в угадывание. Пропавший или
        неверный ключ — не ошибка: форма просто откроется пустой.
        """
        pk = request.GET.get("like")
        if not pk:
            return None
        try:
            return category.model.objects.filter(pk=pk).first()
        except (DatabaseError, ValueError, TypeError):
            return None

    @staticmethod
    def _require_source(request, category, slug):
        """Замену заводят только из карточки основного компонента.

        OY ID берётся оттуда: без него аналог не с чем связать. Возвращает
        ``(основной компонент, None)`` или ``(None, перенаправление)``.
        """
        origin = counterpart(category)
        source_pk = request.POST.get("from") or request.GET.get("from")
        source = None
        if origin and source_pk:
            try:
                source = origin.model.objects.filter(pk=source_pk).first()
            except (DatabaseError, ValueError, TypeError):
                source = None

        if source is None:
            messages.warning(
                request,
                "Замену можно добавить только из карточки основного "
                "компонента — в блоке «аналоги по OY ID».")
            return None, redirect("components:list",
                                  slug=origin.slug if origin else slug)

        if not usable(source.oy_id):
            messages.warning(
                request,
                f"У компонента {source.display_title()} не заполнен OY ID — "
                f"сначала укажите его, иначе замену не с чем связать.")
            return None, redirect(source.get_absolute_url())

        return source, None

    def render_form(self, request, form):
        draft = self.draft
        return render(request, self.template_name, {
            "category": draft.category,
            "form": form,
            "sections": group_fields(form),
            "object": None if draft.created else draft.obj,
            "source": draft.source,
            "sample": draft.sample,
            "oy_id": draft.oy_id,
            "oy_id_hint": draft.oy_id_hint,
        })

    def get(self, request):
        return self.render_form(request, self.draft.build_form())

    def post(self, request):
        draft = self.draft
        form = draft.build_form(request.POST)
        if not form.is_valid():
            messages.error(request, _invalid_form_message(form))
            return self.render_form(request, form)

        try:
            obj = draft.save(form, request.user)
        except DatabaseError as exc:
            messages.error(request, f"База отклонила запись: {exc}")
            return self.render_form(request, form)

        messages.success(
            request,
            f"Компонент {obj.display_title()} "
            + ("добавлен." if draft.created else "сохранён."))
        return redirect("components:detail", slug=draft.category.slug,
                        pk=obj.pk)


def _invalid_form_message(form):
    """Что сказать, когда форма не прошла проверку.

    Названия полей с ошибками помогают найти их в длинной форме: полей под
    сотню, и «проверьте форму» без подсказки означало бы просмотр всех.
    """
    labels = [str(form.fields[name].label or name)
              for name in form.errors if name in form.fields]
    if not labels:
        return "Не сохранено — проверьте форму."
    return "Не сохранено — проверьте поля: " + ", ".join(labels)


# ---- удаление ------------------------------------------------------------

@component_editor
def component_delete(request, slug, pk):
    category = category_or_404(slug)
    read_only = _read_only_redirect(request, category)
    if read_only is not None:
        return read_only

    obj = fetch(category, pk)

    # где компонент стоит на платах и сколько у него аналогов —
    # это узнают до удаления, а не после
    boards, board_rows = usage_summary(obj, category.table)
    analogs = _analog_count(category, obj)
    risky = bool(boards or analogs)

    if request.method == "POST":
        if risky and not request.POST.get("confirm"):
            messages.error(
                request,
                "Компонент используется — подтвердите удаление галочкой.")
        else:
            title = obj.display_title()
            # пишем до удаления: после него не останется ни значений,
            # ни ключа, по которому эту запись можно опознать
            record_deletion(obj, category.table, request.user)
            # картинку не трогаем: она принадлежит посадочному месту, и
            # остальные компоненты на нём её по-прежнему показывают
            obj.delete()
            if board_rows:
                messages.warning(
                    request,
                    f"{board_rows} строк в составах плат остались без связи "
                    f"с библиотекой — теперь они показывают данные из файла.")
            messages.success(request, f"Компонент {title} удалён.")
            return redirect("components:list", slug=slug)

    return render(request, "components/confirm_delete.html", {
        "category": category,
        "object": obj,
        "boards": boards,
        "board_rows": board_rows,
        "analogs": analogs,
        "risky": risky,
    })


@fallback(0, "число аналогов по OY ID")
def _analog_count(category, obj):
    """Сколько записей в парной таблице делят с этой один OY ID."""
    pair = counterpart(category)
    oy_id = usable(getattr(obj, "oy_id", ""))
    if not pair or not oy_id:
        return 0
    return pair.model.objects.filter(oy_id=oy_id).count()


# ---- ревизия данных ------------------------------------------------------

@admin_only
def duplicates(request):
    """Ревизия данных: где в библиотеке задвоились записи."""
    check = request.GET.get("check", DEFAULT_CHECK)
    if check not in CHECKS:
        check = DEFAULT_CHECK
    term = (request.GET.get("q") or "").strip()
    groups, failed = find_duplicates(check, term)

    page = Paginator(groups, DUPLICATE_PAGE_SIZE).get_page(
        request.GET.get("page"))
    return render(request, "components/duplicates.html", {
        "check": check,
        "checks": CHECKS,
        "hint": CHECKS[check]["hint"],
        "term": term,
        "page": page,
        "total": len(groups),
        "records": sum(group["count"] for group in groups),
        "failed": failed,
    })
