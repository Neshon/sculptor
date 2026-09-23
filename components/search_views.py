"""Глобальный поиск: компоненты всех групп, платы и строки их составов.

Вынесено из :mod:`components.views`. Сам обход таблиц — в
:mod:`components.lookup`, он общий с выбором компонента в состав платы.
"""

from urllib.parse import urlencode

from django.shortcuts import render
from django.urls import reverse

from boards.search import search_boards, search_items

from .lookup import matches

SEARCH_PREVIEW = 10


# ---- поиск ---------------------------------------------------------------

def _search_components(term):
    """Совпадения по всем таблицам компонентов: рабочим и заменам.

    Сам обход — в :mod:`components.lookup`, он общий с выбором компонента в
    состав платы. Здесь остаётся только показ: превью по группам и точное
    число совпадений.

    Точное число нужно лишь тогда, когда совпадений больше, чем помещается
    в превью: таблиц двадцать семь, и ``COUNT`` по каждой из них — это
    двадцать семь лишних запросов там, где ответ и так виден по длине
    превью.
    """
    results, total = [], 0
    for category, queryset, objects, has_more in matches(term, SEARCH_PREVIEW):
        count = queryset.count() if has_more else len(objects)
        total += count
        results.append({
            "category": category,
            "objects": objects,
            "count": count,
            "url": (reverse("components:list", args=[category.slug])
                    + "?" + urlencode({"q": term})),
        })
    # сначала рабочие группы, внутри каждой части — по числу совпадений
    results.sort(key=lambda r: (r["category"].replacement, -r["count"]))
    return results, total


def global_search(request):
    """Поиск по всем группам, а также по платам и их составам."""
    term = (request.GET.get("q") or "").strip()
    results, total = [], 0
    boards, boards_count = [], 0
    board_items, board_items_count = [], 0

    if term:
        boards, boards_count = search_boards(term)
        board_items, board_items_count = search_items(term)
        results, total = _search_components(term)
        total += boards_count + board_items_count

    return render(request, "components/search.html", {
        "term": term,
        "results": results,
        "total": total,
        "boards": boards,
        "boards_count": boards_count,
        "board_items": board_items,
        "board_items_count": board_items_count,
    })
