"""Списки плат и ревизий — устроены так же, как список компонентов.

Поиск, фильтры с галочками, которые сужают друг друга, сортировка по любой
колонке, выбор числа строк, выгрузка CSV и краткая карточка справа. Правила
у всех трёх списков одни: человек переходит из компонентов в платы и не
должен переучиваться.

Список компонентов строится по реестру (``components.registry``): колонки
там — поля неуправляемых таблиц. Здесь модели свои, и колонки описаны
явно: какой текст показать, сколько знаков отвести, как сортировать.
Ширина считается тем же правилом, что у компонентов
(``registry.column_chars``), — поэтому и шапка у всех списков в две строки.

Сортировка у двух списков разная, и это не небрежность. Плат сотни —
сортирует база (``order``). Ревизий у платы единицы, а их правильный
порядок — по счётчику из номера, которого в базе нет («1.02» новее «1.1»,
см. ``revisions.sort_key``), — поэтому ревизии сортируются в Python
(``key``).
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

from django.db.models import Case, Q, Value, When
from django.utils import timezone

from components.export import csv_response, export_stamp
from components.matching import is_dash
from components.querystring import values_of
from components.registry import column_chars

from .models import BOARD_TYPES
from .pn import canonical
from .revisions import revision_counter, sort_key
from .search import revision_match

DATE_FORMAT = "%d.%m.%Y"


def _date(value):
    """Дата без времени; у полей с временем — в местном поясе."""
    if value is None:
        return ""
    if hasattr(value, "hour") and timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime(DATE_FORMAT)


def _text(value):
    return "" if value is None else str(value).strip()


@dataclass(frozen=True)
class Column:
    """Колонка списка.

    ``value`` — текст ячейки (он же в подсказке и в выгрузке). ``chars`` —
    ширина по данным в знаках; ``None`` — колонка, которой достаётся
    остаток ширины (как описание у компонентов). Сортируется колонка
    базой по ``order`` или в Python по ``key``.
    """

    name: str
    label: str
    value: Callable
    chars: int | None = None
    order: object = None
    key: Callable | None = None
    # класс ячейки: pn — данные моноширинным, desc — текст
    kind: str = "pn"


@dataclass(frozen=True)
class Filter:
    """Фильтр с галочками над списком.

    ``labels`` — подписи значений и их порядок в списке (тип платы хранится
    кодом, а показывается словами). ``codes`` — если значение в адресе не
    то, что в базе: «утверждена» — это ``approved=True``. ``order`` —
    порядок значений, когда он не алфавитный (ревизии — по счётчику).
    """

    name: str
    label: str
    labels: dict | None = None
    codes: dict | None = None
    order: Callable | None = None

    def apply(self, queryset, values):
        if self.codes:
            values = [self.codes[v] for v in values if v in self.codes]
        return queryset.filter(**{f"{self.name}__in": values})

    def choices(self, queryset):
        """Пары (значение, подпись) — только те, что встречаются в выборке."""
        # пустой order_by: иначе поля Meta.ordering попадают в DISTINCT, и
        # одно значение приходит столько раз, сколько у него записей
        present = set(queryset.order_by().values_list(self.name, flat=True)
                      .distinct())
        if self.codes:
            return [(code, self.labels[code]) for code, value in self.codes.items()
                    if value in present]
        present = {value for value in present
                   if _text(value) and not is_dash(_text(value))}
        if self.labels:
            return [(value, label) for value, label in self.labels.items()
                    if value in present]
        return [(value, value) for value in
                sorted(present, key=self.order or str.casefold)]


@dataclass
class Table:
    """Описание списка: колонки, фильтры, поиск и сортировка по умолчанию."""

    columns: tuple
    filters: tuple
    search: Callable
    # порядок без выбранной сортировки — только для списков в памяти
    default: Callable | None = None
    # ширины колонок по порядку: знаки или None у гибкой
    column_widths: tuple = field(init=False)
    fixed_chars: int = field(init=False)
    fixed_count: int = field(init=False)

    def __post_init__(self):
        self.column_widths = tuple(
            None if c.chars is None else column_chars(c.name, c.label, c.chars)
            for c in self.columns)
        fixed = [width for width in self.column_widths if width is not None]
        self.fixed_chars = sum(fixed)
        self.fixed_count = len(fixed)

    @property
    def headers(self):
        """Колонки вместе с шириной — шаблону так проще, чем двумя списками."""
        return list(zip(self.columns, self.column_widths, strict=True))

    def column(self, name):
        return next((c for c in self.columns if c.name == name), None)

    # --- отбор ------------------------------------------------------------

    def filtered(self, queryset, params, skip=None):
        """Выборка по фильтрам из строки запроса. ``skip`` — какой не учитывать."""
        for item in self.filters:
            if item.name == skip:
                continue
            values = values_of(params, item.name)
            if values:
                queryset = item.apply(queryset, values)
        return queryset

    def filter_choices(self, queryset, params):
        """``[(имя, подпись, [(значение, подпись)])]`` для формы фильтров.

        Фильтры сужают друг друга, как у компонентов: в каждом остаются
        значения, которые встречаются при уже выбранных остальных. Свои
        значения фильтр не учитывает — иначе, выбрав одно, второе к нему
        было бы не добавить. Фильтр, где выбирать не из чего, не
        показывается — если только в нём уже что-то не выбрано.
        """
        found = []
        for item in self.filters:
            choices = item.choices(self.filtered(queryset, params, item.name))
            if choices or values_of(params, item.name):
                found.append((item.name, item.label, choices))
        return found

    # --- сортировка -------------------------------------------------------

    def sort_params(self, params):
        """``(колонка или None, направление)`` из строки запроса."""
        column = self.column(params.get("sort") or "")
        direction = "desc" if params.get("dir") == "desc" else "asc"
        return column, direction

    def sorted_queryset(self, queryset, params):
        """Сортировка базой. Без выбранной колонки — порядок модели."""
        column, direction = self.sort_params(params)
        if column is None or column.order is None:
            return queryset, "", direction
        order = column.order
        if isinstance(order, str):
            expression = f"-{order}" if direction == "desc" else order
        else:
            expression = order.desc() if direction == "desc" else order.asc()
        # ключ вторым: при равных значениях порядок страниц не должен
        # меняться от запроса к запросу, иначе запись переезжает на соседнюю
        return queryset.order_by(expression, "pk"), column.name, direction

    def sorted_list(self, items, params):
        """Сортировка в памяти. Пустые значения — в конце при любом направлении:
        «сначала пустые» при обратной сортировке прятали бы заполненное."""
        column, direction = self.sort_params(params)
        if column is None or column.key is None:
            return (sorted(items, key=self.default, reverse=True)
                    if self.default else list(items)), "", direction
        filled = [item for item in items if _text(column.value(item))]
        empty = [item for item in items if not _text(column.value(item))]
        filled.sort(key=column.key, reverse=direction == "desc")
        return filled + empty, column.name, direction

    # --- показ и выгрузка -------------------------------------------------

    def rows(self, objects):
        """Строки таблицы: объект, адрес карточки и тексты ячеек."""
        return [{"obj": obj, "url": obj.get_absolute_url(),
                 "cells": [(column, _text(column.value(obj)))
                           for column in self.columns]}
                for obj in objects]

    def export(self, objects, filename, username=""):
        """CSV с теми же колонками и текстом, что на странице, и отметкой о выгрузке."""
        rows = ([_text(column.value(obj)) for column in self.columns]
                for obj in objects)
        return csv_response(filename, [c.label for c in self.columns], rows,
                            preamble=export_stamp(username))


# --- платы -------------------------------------------------------------------

TYPE_LABELS = dict(BOARD_TYPES)

# Тип хранится кодом, а сортировать надо по тому, что видно, — по подписи
TYPE_ORDER = Case(*(When(board_type=code, then=Value(label))
                    for code, label in BOARD_TYPES),
                  default=Value(""))


def search_boards(queryset, term):
    """Номер (с точками и без), наименование и номера ревизий.

    Номер могут набрать и с точками, и без: в базе он хранится без них.
    Номера GCT и децимальные живут у ревизий — какие именно поля, решает
    ``search.revision_match``, общий с глобальным поиском.
    """
    term = (term or "").strip()
    if not term:
        return queryset
    return queryset.filter(
        Q(base_pn__icontains=term) | Q(base_pn__icontains=canonical(term))
        | Q(name__icontains=term) | Q(developer__icontains=term)
        | revision_match(term)).distinct()


def _current(board):
    revision = board.current_revision
    return (revision.oy_pn or revision.label) if revision else ""


BOARDS = Table(
    columns=(
        Column("base_pn", "OY PN", lambda b: b.base_pn, 20, order="base_pn"),
        Column("name", "Наименование", lambda b: b.name, order="name",
               kind="desc"),
        Column("board_type", "Тип платы",
               lambda b: TYPE_LABELS.get(b.board_type, b.board_type), 17,
               order=TYPE_ORDER),
        Column("developer", "Разработчик", lambda b: b.developer, 16,
               order="developer"),
        Column("current", "Текущая ревизия", _current, 20,
               order="current_revision__oy_pn"),
        Column("revisions", "Ревизий", lambda b: b.revision_count, 7,
               order="revisions_total", kind="num"),
        Column("imported_at", "Обновлено", lambda b: _date(b.imported_at), 10,
               order="imported_at"),
    ),
    filters=(
        Filter("board_type", "Тип платы", labels=TYPE_LABELS),
        Filter("developer", "Разработчик"),
    ),
    search=search_boards,
)


# --- ревизии платы -------------------------------------------------------------

REVISION_SEARCH = (
    "oy_pn", "pcb_name", "bom_name", "board_rev", "bom_rev", "stage",
    "gct_pcb", "gct_bom", "previous_revision", "decimal_pcba", "decimal_pcb",
)

APPROVED = {"yes": True, "no": False}
APPROVED_LABELS = {"yes": "утверждена", "no": "не утверждена"}


def search_revisions(queryset, term):
    term = (term or "").strip()
    if not term:
        return queryset
    condition = Q()
    for name in REVISION_SEARCH:
        condition |= Q(**{f"{name}__icontains": term})
    return queryset.filter(condition)


def _facts(revision):
    """Дополнительные сведения одной строкой — стадия стоит своей колонкой."""
    return " · ".join(f"{label}: {value}" for label, value in revision.extra_facts
                      if label != revision._meta.get_field("stage").verbose_name)


def _approved(revision):
    if not revision.approved:
        return "нет"
    return f"да · {_date(revision.approved_at)}" if revision.approved_at else "да"


def _casefold(getter):
    return lambda obj: _text(getter(obj)).casefold()


def _oy_pn(revision):
    return revision.oy_pn or revision.label


REVISIONS = Table(
    columns=(
        Column("oy_pn", "OY PN", _oy_pn, 22, key=_casefold(_oy_pn)),
        Column("pcb_name", "Наименование PCB", lambda r: r.pcb_name, 18,
               key=_casefold(lambda r: r.pcb_name)),
        Column("bom_name", "Наименование BOM", lambda r: r.bom_name, 18,
               key=_casefold(lambda r: r.bom_name)),
        Column("board_rev", "Rev", lambda r: r.board_rev, 6,
               key=sort_key),
        Column("bom_rev", "Rev BOM", lambda r: r.bom_rev, 7,
               key=lambda r: (r.bom_rev.casefold(), sort_key(r))),
        Column("current", "Текущая", lambda r: "да" if r.is_current else "", 8,
               key=lambda r: r.is_current),
        Column("stage", "Стадия", lambda r: r.stage, 14,
               key=_casefold(lambda r: r.stage)),
        Column("imported_at", "BOM загружен", lambda r: _date(r.imported_at), 10,
               key=lambda r: r.imported_at),
        Column("approved", "Утверждена", _approved, 13,
               key=lambda r: (r.approved, r.approved_at or date.min)),
        Column("facts", "Дополнительные сведения", _facts, kind="desc",
               key=_casefold(_facts)),
    ),
    filters=(
        Filter("board_rev", "Rev",
               order=lambda value: (revision_counter(value), value)),
        Filter("bom_rev", "Rev BOM"),
        Filter("variant", "Исполнение"),
        Filter("stage", "Стадия"),
        Filter("approved", "Утверждена", labels=APPROVED_LABELS,
               codes=APPROVED),
    ),
    search=search_revisions,
    # новые ревизии сверху — как и было в карточке платы
    default=sort_key,
)
