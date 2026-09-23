"""Журнал изменений: вся библиотека и одна правка подробно.

Вынесено из :mod:`components.views`. Что и как записывается — в
:mod:`components.history`; здесь только показ.
"""

from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import get_object_or_404, render

from .filter_forms import ChangeFilterForm
from .history import log_authors, log_queryset, with_authors
from .listing import PAGE_SIZES, page_size
from .models import ComponentChange
from .refs import resolve
from .registry import CATEGORIES

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
    try:
        paginator = Paginator(log_queryset(filters), per_page)
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

    return render(request, "components/change.html", {
        "change": change,
        "category": category,
        "object": obj,
        "matches": matches,
    })
