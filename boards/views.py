"""Платы: список, состав по ревизиям, импорт BOM.

Выгрузка состава вынесена в :mod:`boards.export`, сравнение ревизий —
в :mod:`boards.diff`.
"""

from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers

from components import lookup, similar
from components.listing import PAGE_SIZES, page_size
from components.querystring import with_params
from components.views import PREVIEW_TARGET
from config.htmx import targets
from users.roles import board_editor
from components.refs import resolve
from components.registry import category_by_table, get_category
from servers.boards_bridge import sync_board

from .diff import revision_diff
from .export import exporter
from . import checklists, listing
from .forms import (BoardForm, BoardItemForm, BoardRevisionCreateForm,
                    BoardRevisionForm, BomUploadForm, ChecklistForm,
                    ListFilterForm)
from .importer import BomParseError, parse_bom
from .linking import (MANUAL_MATCHES, MATCH_HINT, MATCH_PICK, build_index,
                      component_values, hint_details, hints_for,
                      link_items)
from .models import Board, BoardItem, BoardRevision
from .revisions import sort_key
from .search import items_queryset
from .storing import store_revision

PAGE_SIZE = 50
ITEM_PAGE_SIZE = 50

# Сколько компонентов показывать при выборе в состав. Постраничного вывода
# здесь нет намеренно: каждая страница — это запрос в каждую из 27 таблиц,
# а ищут тут конкретный артикул, а не листают библиотеку. Когда совпадений
# больше, дешевле уточнить запрос, и страница об этом прямо говорит.
LIBRARY_LIMIT = 50


def item_search(request):
    """Полный список строк состава, найденных по запросу.

    Раздел «составы плат» в глобальном поиске (components:search) показывает
    только первые несколько совпадений; эта страница — то же самое без
    ограничения, с постраничным выводом, как и список плат. Пагинация здесь
    работает по queryset, а не по готовому списку: страница читает из базы
    только свою порцию строк, даже если совпадений тысячи.
    """
    term = (request.GET.get("q") or "").strip()
    items = items_queryset(term) if term else BoardItem.objects.none()

    page = Paginator(items, ITEM_PAGE_SIZE).get_page(request.GET.get("page"))
    return render(request, "boards/item_search.html",
                 {"page": page, "term": term})


def board_list(request):
    """Список плат — устроен так же, как список компонентов.

    Поиск, фильтры с галочками, сортировка по колонкам, число строк на
    странице, выгрузка CSV и краткая карточка платы справа. Что за колонки
    и фильтры — в :mod:`boards.listing`.
    """
    table = listing.BOARDS
    params = request.GET

    # варианты фильтров — по всем платам, а не по найденным поиском: так
    # же, как у компонентов, фильтры сужают только друг друга
    filters = table.filter_choices(Board.objects.all(), params)
    filter_form = ListFilterForm(
        params or None, filters=filters,
        hint="OY PN, наименование, разработчик, номера GCT, децимальный номер")

    boards = table.filtered(
        table.search(Board.objects.select_related("current_revision")
                     .with_counts(), params.get("q")),
        params)
    boards, sort, direction = table.sorted_queryset(boards, params)

    if params.get("export") == "csv":
        return table.export(boards.iterator(chunk_size=500), "boards.csv",
                            request.user.get_username())

    per_page = page_size(request)
    page = Paginator(boards, per_page).get_page(params.get("page"))

    # HTMX просит только панель — фильтры и таблицу (list.html#panel),
    # как у списка компонентов
    template = ("boards/list.html#panel" if getattr(request, "htmx", False)
                else "boards/list.html")
    return render(request, template, {
        "table": table,
        "rows": table.rows(page.object_list),
        "page": page,
        "paginator": page.paginator,
        "filter_form": filter_form,
        "sort": sort,
        "dir": direction,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "export_url": with_params(params, export="csv"),
        "list_url": reverse("boards:list"),
    })


def _group_by_position(items):
    """Позиция и её замены идут одной группой."""
    groups, current = [], None
    for item in items:
        if item.is_main or current is None:
            current = {"main": item if item.is_main else None,
                       "substitutes": [] if item.is_main else [item],
                       "position": item.position}
            groups.append(current)
        else:
            current["substitutes"].append(item)
    return groups


def board_detail(request, pk):
    """Карточка платы: сведения и список ревизий.

    Состава здесь нет намеренно. Плата — это модель: у неё назначение, тип
    и перечень ревизий, а состав всегда принадлежит конкретной ревизии.
    Показывать на одной странице и то и другое значит смешивать два
    уровня — читающий перестаёт понимать, к чему относится таблица.

    Список ревизий устроен как список компонентов: поиск, фильтры,
    сортировка, выгрузка и краткая карточка ревизии справа. Ревизий у
    платы единицы, поэтому отбор идёт в базе, а сортировка — в памяти, по
    счётчику из номера (см. :mod:`boards.listing`).

    Один адрес отдаёт три ответа: страницу, панель со списком ревизий
    (запрос HTMX от его фильтров) и краткую карточку платы для списка плат
    (запрос в панель #list-preview).
    """
    board = get_object_or_404(
        Board.objects.select_related("current_revision"), pk=pk)

    if targets(request, PREVIEW_TARGET):
        return _board_preview(request, board)

    params = request.GET
    # прежние ссылки вида ?rev=2 ведут теперь на страницу ревизии
    number = params.get("rev")
    if number:
        chosen = (board.revisions.filter(number=number).first()
                  if number.isdigit() else None)
        if chosen is None:
            raise Http404("Такой ревизии нет")
        return redirect(chosen.get_absolute_url())

    table = listing.REVISIONS
    revisions = board.revisions.all()
    filters = table.filter_choices(revisions, params)
    filter_form = ListFilterForm(
        params or None, filters=filters,
        hint="OY PN, наименования PCB и BOM, ревизии, стадия, номера GCT, "
             "децимальные номера")

    found = list(table.filtered(table.search(revisions, params.get("q")),
                                params))
    # «текущая» спрашивает плату у ревизии — она уже прочитана
    for revision in found:
        revision.board = board
    found, sort, direction = table.sorted_list(found, params)

    if params.get("export") == "csv":
        return table.export(found, f"{board.base_pn or board.pk}-revisions.csv",
                            request.user.get_username())

    per_page = page_size(request)
    page = Paginator(found, per_page).get_page(params.get("page"))

    template = ("boards/detail.html#panel" if getattr(request, "htmx", False)
                else "boards/detail.html")
    response = render(request, template, {
        "board": board,
        "current": board.current_revision,
        "revision_total": revisions.count(),
        "table": table,
        "rows": table.rows(page.object_list),
        "page": page,
        "paginator": page.paginator,
        "filter_form": filter_form,
        "sort": sort,
        "dir": direction,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "export_url": with_params(params, export="csv"),
        "list_url": board.get_absolute_url(),
    })
    # тот же адрес отдаёт и краткую карточку — см. config.htmx.targets
    patch_vary_headers(response, ("HX-Target",))
    return response


def _board_preview(request, board):
    """Краткая карточка платы — панель справа от списка плат.

    Только то, что читают за пару секунд: снимок, наименование, тип,
    назначение и текущая ревизия. Список ревизий и описание целиком —
    в карточке.
    """
    response = render(request, "boards/detail.html#preview", {
        "board": board,
        "current": board.current_revision,
        "revision_total": board.revisions.count(),
    })
    patch_vary_headers(response, ("HX-Target",))
    return response


def revision_detail(request, pk, number):
    """Страница ревизии: своя карточка и свой состав из BOM.

    Запрос в панель #list-preview — от списка ревизий в карточке платы —
    получает краткую карточку ревизии.
    """
    board = get_object_or_404(
        Board.objects.select_related("current_revision"), pk=pk)
    revision = _revision_or_404(board, number)
    # Чек-листы читаются из поля ревизии, запроса к базе не делают: раньше
    # на ту же страницу уходило три — строки, заполненные и всего.
    done, total = checklists.progress(revision)

    if targets(request, PREVIEW_TARGET):
        response = render(request, "boards/revision.html#preview", {
            "board": board,
            "revision": revision,
            "item_count": revision.item_count,
            "position_count": revision.position_count,
            "checklist_done": done,
            "checklist_total": total,
        })
        patch_vary_headers(response, ("HX-Target",))
        return response

    response = render(request, "boards/revision.html", {
        "board": board,
        "revision": revision,
        # состав живёт на своей странице, здесь нужны только счётчики
        "item_count": revision.item_count,
        "position_count": revision.position_count,
        "checklists": checklists.groups_for(revision),
        "checklist_done": done,
        "checklist_total": total,
    })
    patch_vary_headers(response, ("HX-Target",))
    return response


def revision_bom(request, pk, number):
    """Состав ревизии: строки BOM и отличия от предыдущей ревизии.

    Отдельной страницей: в BOM бывает под тысячу строк, и карточка вместе с
    ними превращалась в ленту, где ни реквизиты прочитать, ни состав
    просмотреть.
    """
    board = get_object_or_404(
        Board.objects.select_related("current_revision"), pk=pk)
    revisions = sorted(board.revisions.all(), key=sort_key, reverse=True)
    revision = _revision_or_404(board, number)

    # состав показывается как он записан в BOM: значения из библиотеки не
    # подставляются, поэтому и читать её здесь не нужно
    items = list(revision.items.all())

    # выгрузка отдаёт то, что было в файле: это документ, а не витрина
    export = exporter(request.GET.get("export"))
    if export is not None:
        return export(board, revision, items,
                      username=request.user.get_username())

    # предыдущая ревизия — предшествующий по ревизии, а не по времени загрузки
    position = revisions.index(revision) if revision in revisions else -1
    previous = (revisions[position + 1]
                if 0 <= position and position + 1 < len(revisions) else None)

    return render(request, "boards/bom.html", {
        "board": board,
        "revision": revision,
        "previous": previous,
        "groups": _group_by_position(items),
        "item_count": len(items),
        # состав уже в памяти — считаем по нему, а не отдельными запросами
        "position_count": sum(1 for i in items if i.is_main),
        "unlinked_count": sum(1 for i in items if not i.is_linked),
        "linked_count": sum(1 for i in items if i.is_linked),
        "diff": revision_diff(previous, items) if previous else None,
    })


@board_editor
def revision_checklist(request, pk, number):
    """Заполнение чек-листов ревизии.

    Все строки правятся одной формой: ходить по странице на каждый из
    двух десятков документов — работа ради работы.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    # Досоздавать строки больше не нужно: состав задан шаблоном, и строка
    # есть потому, что она в шаблоне. Пополнили шаблон — она появилась у
    # всех ревизий сразу, включая заведённые год назад.
    form = ChecklistForm(request.POST or None, revision=revision)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Чек-листы сохранены.")
        return redirect(revision.get_absolute_url())

    return render(request, "boards/checklist.html", {
        "board": board, "revision": revision,
        "form": form, "groups": form.groups})


@board_editor
def board_import(request):
    """Загрузка одного или нескольких BOM-файлов за раз."""
    form = BomUploadForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        uploads = sorted(form.cleaned_data["file"], key=lambda f: f.name)

        # индекс библиотеки строится один раз на всю пачку, а не на файл
        try:
            index = build_index()
        except DatabaseError as exc:
            messages.error(request, f"База недоступна: {exc}")
            return render(request, "boards/import.html", {"form": form})

        results = [_import_one(request, upload, index) for upload in uploads]
        loaded = [r for r in results if r["ok"]]
        failed = [r for r in results if not r["ok"]]

        if loaded:
            messages.success(
                request, f"Загружено файлов: {len(loaded)} из {len(results)}.")
        if failed:
            messages.error(
                request,
                "Не разобраны: " + ", ".join(r["name"] for r in failed))

        # один файл — сразу открываем его ревизию
        if len(results) == 1 and loaded:
            return redirect(loaded[0]["revision"].get_absolute_url())

        return render(request, "boards/import.html",
                      {"form": BomUploadForm(), "results": results})

    return render(request, "boards/import.html", {"form": form})


def _import_one(request, upload, index):
    """Разбирает и сохраняет один файл. Ошибка не прерывает остальные."""
    result = {"name": upload.name, "ok": False, "error": "", "revision": None,
              "unlinked": 0, "lines": 0}
    try:
        header, items = parse_bom(upload)
    except BomParseError as exc:
        result["error"] = str(exc)
        return result

    try:
        linked = link_items(items, index)
        revision = store_revision(header, items,
                                  request.user.get_username())
    except DatabaseError as exc:
        result["error"] = f"база отклонила запись: {exc}"
        return result

    result.update(ok=True, revision=revision, lines=len(items),
                  unlinked=len(items) - linked)
    return result


@board_editor
def revision_create(request, pk):
    """Новая ревизия платы руками — когда BOM-файла ещё нет.

    Состав у такой ревизии пустой: он наполняется импортом BOM или
    построчно. Карточка и чек-листы заводятся сразу — ради них ревизия
    обычно и создают до файла.
    """
    board = get_object_or_404(Board, pk=pk)
    # request.FILES: в карточке ревизии загружают снимки платы
    form = BoardRevisionCreateForm(request.POST or None, request.FILES or None,
                                   board=board)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            revision = form.save(commit=False)
            revision.board = board
            revision.apply_pn(form.cleaned_data["oy_pn"])
            revision.number = board.next_revision_number()
            # BOM у такой ревизии ещё не загружали: отметка о загрузке
            # остаётся пустой, и это правда, а не пропуск
            revision.save()

            # первая ревизия платы сразу становится текущим: иначе плата
            # осталась бы без состава, хотя ревизия у неё уже есть
            if board.current_revision_id is None:
                board.set_current(revision)
            sync_board(board)

        messages.success(request, f"Ревизия {revision.oy_pn} заведена.")
        return redirect(revision.get_absolute_url())

    return render(request, "boards/revision_form.html",
                  {"board": board, "revision": None, "form": form})


@board_editor
def revision_edit(request, pk, number):
    """Правка карточки ревизии."""
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    # request.FILES: в карточке ревизии загружают снимки платы
    form = BoardRevisionForm(request.POST or None, request.FILES or None,
                             instance=revision)

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Карточка ревизии {revision.label} сохранена.")
        return redirect(revision.get_absolute_url())

    return render(request, "boards/revision_form.html",
                  {"board": board, "revision": revision, "form": form})


@board_editor
def revision_delete(request, pk, number):
    """Удаление ревизии вместе с его составом и чек-листами.

    Если удаляют текущая ревизия, текущим становится следующий по ревизии —
    плата не должна остаться без состава, пока у неё есть другие ревизии.
    Ссылка `Board.current_revision` обнулилась бы и сама (SET_NULL), но
    молча: список плат показал бы прочерк там, где данные есть.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)

    if request.method == "POST":
        was_current = revision.is_current
        label = revision.oy_pn or revision.label

        with transaction.atomic():
            revision.delete()
            if was_current:
                left = sorted(board.revisions.all(), key=sort_key, reverse=True)
                board.set_current(left[0] if left else None)

        messages.success(request, f"Ревизия {label} удалена.")
        return redirect(board.get_absolute_url())

    return render(request, "boards/revision_confirm_delete.html",
                  {"board": board, "revision": revision,
                   "checklist_done": checklists.progress(revision)[0]})


@board_editor
def revision_activate(request, pk, number):
    """Возврат к прежней ревизии: она снова становится текущей."""
    board = get_object_or_404(Board, pk=pk)
    revision = get_object_or_404(BoardRevision, board=board, number=number)
    if request.method == "POST":
        board.set_current(revision)
        messages.success(
            request, f"Текущей ревизией {board.base_pn} стала {revision.number}.")
    return redirect(revision.get_absolute_url())


@board_editor
def board_delete(request, pk):
    """Удаление платы вместе с ревизиями и позицией-двойником.

    На плату ссылается позиция из раздела изделий, и ссылка защищённая:
    без явного удаления позиции запрос падал бы с ProtectedError прямо в
    лицо. А если этой позицией пользуются составы изделий, удалять нельзя
    вовсе — иначе состав молча потеряет плату.
    """
    board = get_object_or_404(Board, pk=pk)
    item = twin_item(board)
    used_in = list(item.used_in.select_related("parent")) if item else []

    if request.method == "POST":
        if used_in:
            messages.error(
                request,
                "Плата входит в состав позиций раздела «Серверы» — сначала уберите её оттуда: "
                + ", ".join(sorted({line.parent.oy_pn for line in used_in})))
            return redirect(board.get_absolute_url())

        name = board.base_pn
        with transaction.atomic():
            if item is not None:
                item.delete()
            board.delete()
        messages.success(request,
                         f"Плата {name} удалена вместе со всеми ревизиями.")
        return redirect("boards:list")

    return render(request, "boards/confirm_delete.html",
                  {"board": board, "item": item, "used_in": used_in})


# ---- ведение платы руками, без файла BOM ---------------------------------

@board_editor
def board_create(request):
    """Заводит плату. Ревизии к ней добавляются импортом BOM.

    Пустая ревизия здесь больше не создаётся: она существовала ради шапки,
    которую плата дублировала, а теперь шапка целиком принадлежит ревизии
    и браться ей неоткуда.
    """
    form = BoardForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            board = form.save(commit=False)
            # файла не было: плата заводится руками
            board.imported_by = request.user.get_username()
            board.save()
            sync_board(board)

        messages.success(request, f"Плата {board.base_pn} заведена. "
                                  f"Теперь загрузите её BOM.")
        return redirect(board.get_absolute_url())

    return render(request, "boards/board_form.html", {"form": form})


@board_editor
def board_edit(request, pk):
    """Правка карточки платы: номер, наименование, описание."""
    board = get_object_or_404(Board, pk=pk)
    # request.FILES: в карточке платы загружают изображения
    form = BoardForm(request.POST or None, request.FILES or None, instance=board)

    if request.method == "POST" and form.is_valid():
        board = form.save()
        sync_board(board)
        messages.success(request, f"Плата {board.base_pn} сохранена.")
        return redirect(board.get_absolute_url())

    return render(request, "boards/board_form.html",
                  {"form": form, "board": board})


def bom_url(revision):
    """Страница состава ревизии: туда возвращают правки строк BOM."""
    return reverse("boards:bom", args=[revision.board_id, revision.number])


def twin_item(board):
    """Позиция изделий, представляющая эту плату. Нет — значит None."""
    from servers.models import Item

    return Item.objects.filter(board=board).first()


def _revision_or_404(board, number=None):
    if number is None:
        revision = board.current_revision or board.revisions.first()
    else:
        revision = get_object_or_404(BoardRevision, board=board, number=number)
    if revision is None:
        raise Http404("У платы нет ни одной ревизии")
    return revision


@board_editor
def item_pick(request, pk, number):
    """Выбор компонента из библиотеки в состав ревизии.

    Ручной ввод артикула и поиск по библиотеке решают разные задачи.
    Артикул вводят, когда компонента в библиотеке ещё нет: строка
    сохранится как введена и останется помеченной ``?``. А когда он там
    есть — искать его глазами в карточке, чтобы потом переписать артикул в
    поле, значит делать работу, которую база уже сделала: опечатка в одном
    знаке даёт строку без связи, и замечают это не сразу.

    Поэтому здесь ищут по всем 27 таблицам сразу и выбирают запись, а
    поля строки заполняются из неё — см. :func:`item_edit`.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)

    term = (request.GET.get("q") or "").strip()
    category = get_category((request.GET.get("group") or "").strip())
    found, truncated = lookup.flat(term, LIBRARY_LIMIT,
                                   [category] if category else None)

    # Что из найденного уже стоит в этой ревизии. Повторно добавить не
    # запрещаем — один компонент честно бывает в составе дважды, под разными
    # позициями, — но сказать об этом надо: чаще это всё-таки промах.
    used = set(revision.items.exclude(component_id__isnull=True)
               .values_list("component_table", "component_id"))

    rows = [{"category": found_category,
             "object": obj,
             "used": (found_category.table, obj.pk) in used,
             "url": _pick_url(board, revision, found_category, obj)}
            for found_category, obj in found]

    return render(request, "boards/item_pick.html", {
        "board": board, "revision": revision,
        # в списке групп и таблицы замен: строкой S в состав ставят именно
        # их, и сузить поиск до одной такой таблицы — законное желание
        "term": term, "category": category,
        "categories": lookup.searchable(),
        "rows": rows, "truncated": truncated, "limit": LIBRARY_LIMIT,
    })


def _pick_url(board, revision, category, obj):
    """Форма новой строки с уже выбранным компонентом."""
    return (reverse("boards:item-create", args=[board.pk, revision.number])
            + "?" + urlencode({"from": category.slug, "id": obj.pk}))


def _picked(request, item):
    """Компонент, из которого заполняется строка: ``(категория, запись)``.

    Для новой строки он приходит из адреса (``?from=слаг&id=ключ``) — туда
    его кладёт страница выбора. Для уже сохранённой берётся её собственная
    связь, если её поставил человек — выбором или подтвердив подсказку:
    её карточку показывают рядом с формой. У строки из BOM-файла своей карточки может и не быть — тогда
    показывать нечего, но править строку это не мешает.

    ``(None, None)`` значит «компонента нет»: у новой строки это причина
    отправить человека выбирать, у сохранённой — просто отсутствие панели
    справа. Ошибочный или устаревший ключ в адресе даёт то же самое, а не
    ошибку.
    """
    if item.pk and item.component_match in MANUAL_MATCHES:
        return resolve(item.component_table, item.component_id)

    slug = (request.POST.get("from") or request.GET.get("from") or "").strip()
    pk = (request.POST.get("id") or request.GET.get("id") or "").strip()
    category = get_category(slug)
    if category is None or not pk:
        return None, None

    try:
        return category, category.model.objects.filter(pk=pk).first()
    except (DatabaseError, ValueError, TypeError):
        return None, None


# Сколько строк без пары разбирать на одной странице подсказок. Подбор
# идёт по всей библиотеке на каждую строку, и тысяча строк свежего BOM
# разом — это секунды ожидания; постранично каждая страница быстрая
HINT_PAGE_SIZE = 50


def item_hints(request, pk, number):
    """Строки состава без пары и похожие на них записи библиотеки.

    Видят страницу все, кто видит состав, — подсказка полезна и тому, кто
    просто разбирается, что за деталь. Связать строку по подсказке могут
    только те, кто правит платы.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)

    unlinked = revision.items.filter(component_id__isnull=True)
    page = Paginator(unlinked, HINT_PAGE_SIZE).get_page(request.GET.get("page"))

    # индекс строится, только если на странице есть что подбирать
    rows = [{"item": item} for item in page.object_list]
    if rows:
        prepared = similar.prepare(similar.library_index())
        for row in rows:
            row["hints"] = hints_for(row["item"], prepared)
        details = hint_details(h for row in rows for h in row["hints"])
        for row in rows:
            for hint in row["hints"]:
                hint.update(details.get((hint["table"], hint["pk"]), {}))

    return render(request, "boards/item_hints.html", {
        "board": board, "revision": revision,
        "page": page, "rows": rows, "total": page.paginator.count,
    })


@board_editor
def item_link(request, pk, number, item_pk):
    """Связывает строку без пары с записью, которую подсказал подбор.

    Меняется только связь: поля строки остаются такими, как в BOM-файле, —
    состав это документ, и подсказка его не переписывает. Уже связанную
    строку здесь не перевязывают: её связь или найдена точно, или указана
    человеком, и менять её молча из списка подсказок нельзя.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    item = get_object_or_404(BoardItem, pk=item_pk, revision=revision)
    back = reverse("boards:item-hints", args=[board.pk, revision.number])
    page = (request.POST.get("page") or "").strip()
    if page.isdigit():
        back += "?" + urlencode({"page": page})

    if request.method != "POST":
        return redirect(back)
    if item.is_linked:
        messages.info(request, f"Позиция {item.position} уже связана.")
        return redirect(back)

    table = (request.POST.get("component_table") or "").strip()
    category = category_by_table(table)
    try:
        component = (category.model.objects.filter(
            pk=request.POST.get("component_id")).first()
            if category else None)
    except (DatabaseError, ValueError, TypeError):
        component = None
    if component is None:
        messages.error(request, "Компонент не найден — возможно, его удалили.")
        return redirect(back)

    item.component_table = category.table
    item.component_id = component.pk
    item.component_match = MATCH_HINT
    item.save(update_fields=["component_table", "component_id",
                             "component_match"])
    messages.success(request, f"Позиция {item.position} связана с "
                              f"{component.display_title()}.")
    return redirect(back)


@board_editor
def item_edit(request, pk, number, item_pk=None):
    """Заведение и правка строки состава.

    Новая строка заводится только из библиотеки: без выбранного компонента
    заполнять её нечем, поэтому такой запрос уходит на страницу выбора.
    Ручного ввода артикулов больше нет — см. :class:`BoardItemForm`.

    Правка открыта у любой строки, в том числе пришедшей из BOM-файла и не
    нашедшей себе карточки: править в ней можно то же самое — позицию,
    обозначения, количество, комментарий. Артикулы остаются такими, какими
    их выпустили в файле.
    """
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    item = (get_object_or_404(BoardItem, pk=item_pk, revision=revision)
            if item_pk else BoardItem(revision=revision))

    category, component = _picked(request, item)
    if item.pk is None and component is None:
        # Пришли на «новую строку» без компонента: либо по старой ссылке,
        # либо выбранную запись уже удалили. Отправлять на пустую форму
        # незачем — сохранить её всё равно будет нечем.
        messages.info(request, "Выберите компонент, который добавляете в состав.")
        return redirect("boards:item-pick", pk=board.pk, number=revision.number)

    form = BoardItemForm(request.POST or None, instance=item)

    if request.method == "POST" and form.is_valid():
        item = form.save(commit=False)
        item.revision = revision

        if item.position is None:
            item.position = revision.next_position(item.kind)

        if item.pk is None:
            # Связь известна точно — компонент указал человек, искать её по
            # артикулам незачем. Поля переносятся здесь же и только здесь:
            # повторять перенос при каждой правке значило бы, что правка
            # количества молча подтягивает в выпущенный состав новое
            # описание из библиотеки, а состав это документ.
            for name, value in component_values(component).items():
                setattr(item, name, value)
            item.component_table = category.table
            item.component_id = component.pk
            item.component_match = MATCH_PICK

        item.save()
        messages.success(request, f"Позиция {item.position} сохранена.")
        return redirect(bom_url(revision))

    return render(request, "boards/item_form.html", {
        "form": form, "board": board, "revision": revision,
        "item": item if item.pk else None,
        "component": component, "category": category,
    })


@board_editor
def item_delete(request, pk, number, item_pk):
    board = get_object_or_404(Board, pk=pk)
    revision = _revision_or_404(board, number)
    item = get_object_or_404(BoardItem, pk=item_pk, revision=revision)
    if request.method == "POST":
        position = item.position
        item.delete()
        messages.success(request, f"Позиция {position} удалена.")
    # возвращаем к составу той ревизии, где правили, а не к карточке платы
    return redirect(bom_url(revision))
