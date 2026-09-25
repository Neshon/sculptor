"""Журнал изменений: вся библиотека и одна правка подробно.

Вынесено из :mod:`components.views`. Что и как записывается — в
:mod:`components.history`; здесь только показ.
"""

from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, render
from django.utils.cache import patch_vary_headers

from config.htmx import targets

from .filter_forms import ChangeFilterForm
from .history import (
    log_authors,
    log_filtering,
    log_order,
    log_queryset,
    with_authors,
)
from .listing import PAGE_SIZES, page_size
from .models import ComponentChange
from .querystring import reset_filters
from .refs import resolve
from .registry import CATEGORIES
from .views import PREVIEW_TARGET

# ---- история изменений ---------------------------------------------------

LOG_PAGE_SIZE = 50


def change_log(request):
    """Журнал изменений по всей библиотеке.

    В карточке видна история одного компонента, и этого не хватает в двух
    случаях. Первый — вопрос «кто и когда правил это на прошлой неделе»,
    когда неизвестно, какой именно компонент смотреть. Второй — удаления:
    карточки у удалённой записи нет, и до сих пор такие записи можно было
    увидеть только в админке.
    """
    filters = request.GET
    per_page = page_size(request)
    order, sort, direction = log_order(filters)
    try:
        paginator = Paginator(log_queryset(filters).order_by(*order), per_page)
        page = paginator.get_page(filters.get("page"))
        rows = with_authors(list(page.object_list))
        total = paginator.count
    except DatabaseError:
        page, paginator, rows, total = None, None, [], 0

    filter_form = ChangeFilterForm(
        filters or None,
        actions=ComponentChange.ACTIONS,
        authors=log_authors(),
        tables=[c.table for c in CATEGORIES.values()])

    # как у списка компонентов: HTMX просит только панель — фильтры и
    # таблицу (changes.html#panel), обычный запрос получает страницу целиком
    template = ("components/changes.html#panel"
                if getattr(request, "htmx", False)
                else "components/changes.html")
    return render(request, template, {
        "page": page,
        "paginator": paginator,
        "rows": rows,
        "total": total,
        "per_page": per_page,
        "page_sizes": PAGE_SIZES,
        "filter_form": filter_form,
        "since": filters.get("since", ""),
        "until": filters.get("until", ""),
        "sort": sort,
        "dir": direction,
        "filtering": log_filtering(filters),
        "reset_query": reset_filters(filters),
    })


def duplicate_matches(items, lookup=resolve):
    """Записи, с которыми совпал дубль, — со ссылкой на те, что ещё есть.

    Совпавшую запись могли удалить позже, и ссылка на неё вела бы на 404:
    такой ссылка не даётся, строка остаётся справкой. Записей тут единицы
    (duplicates.MATCH_LIMIT), так что запрос на каждую не страшен.
    """
    matches = []
    for item in items or []:
        _, found = lookup(item.get("table"), item.get("id"))
        matches.append({**item,
                        "url": found.get_absolute_url() if found else ""})
    return matches


# Что краткая версия показывает у заведения и удаления: по этим полям деталь
# узнают. Остальное там — не «что поменялось», а вся запись целиком, полсотни
# строк, и в панели за ними не видно, о какой детали речь.
PREVIEW_IDENTITY = ("vendor_pn", "description")


def preview_changes(action, changes):
    """``(поля для панели, сколько не показано)``.

    У правки — все изменившиеся поля. У заведения и удаления — только
    Vendor PN и Description: остальное целиком на странице правки. У
    удалённой записи они ещё и единственное, по чему её узнать: карточки
    больше нет.
    """
    changes = list(changes or [])
    if action not in (ComponentChange.CREATED, ComponentChange.DELETED):
        return changes, 0
    shown = [item for item in changes if item.get("field") in PREVIEW_IDENTITY]
    return shown, len(changes) - len(shown)


def component_change(request, pk):
    """Подробности одной правки: кто, когда и что именно поменял.

    Открывается из карточки в отдельной вкладке, поэтому здесь есть ссылка
    обратно на компонент — вернуться «назад» в новой вкладке некуда.

    Компонент к этому моменту могли удалить или переименовать: история
    хранится отдельно и переживает запись. Тогда показываем то, что знаем,
    и говорим, что компонента больше нет.
    """
    change = get_object_or_404(ComponentChange, pk=pk)
    with_authors([change])
    # «таблицы такой нет» и «запись уже удалили» — разные сообщения на
    # странице, поэтому разрешение отдаёт обе половины отдельно
    category, obj = resolve(change.component_table, change.component_id)

    matches = duplicate_matches(change.changes) if change.is_duplicate else []

    context = {
        "change": change,
        "category": category,
        "object": obj,
        "matches": matches,
    }
    # Краткая версия — в панель рядом с журналом (changes.html, preview.js),
    # как карточка компонента рядом с его списком: тот же адрес, что у
    # строки, поэтому без скрипта строка ведёт на правку целиком
    if targets(request, PREVIEW_TARGET):
        context["items"], context["more"] = preview_changes(
            change.action, change.changes)
        response = render(request, "components/change.html#preview", context)
        patch_vary_headers(response, ("HX-Target",))
        return response
    return render(request, "components/change.html", context)
