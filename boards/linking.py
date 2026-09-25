"""Связывание строк BOM с записями в библиотеке компонентов.

Связь ставится двумя способами, и оба — один раз, при появлении строки.

Строки из файла сопоставляет импорт: артикул из BOM ищется в библиотеке, и
найденное — имя таблицы и первичный ключ — записывается в саму строку.
Сравнивать артикулы при каждом показе состава было бы и дорого, и хрупко:
регистр, пробелы, заглушки вроде «---». Индекс для этого строится одним
проходом по всем таблицам: 27 запросов на импорт вместо двух запросов на
каждую из сотен строк.

Строку, добавленную в состав человеком, сопоставлять не нужно вовсе:
компонент он выбрал сам, запись известна. Оттуда же берутся и поля строки —
:func:`component_values`.

Поиск под одну строку по введённому артикулу здесь когда-то был
(``find_component``). Он понадобился ручному вводу артикулов в состав, а
вместе с ним и убран: угадывать больше нечего.
"""

from components import similar
from components.db import unavailable
from components.matching import usable
from components.registry import category_by_table, scan

# порядок правил: сначала внутренний номер, затем артикул производителя
MATCH_GBT = "gbt"
MATCH_VENDOR = "vendor"
# А это правило не ищет ничего: компонент указал человек, выбрав его в
# библиотеке. Оно надёжнее двух предыдущих — сравнивать артикулы не надо,
# запись известна, — и по нему видно, что связь не угадана
MATCH_PICK = "pick"
# И это тоже связь, поставленная человеком: строка из BOM-файла не нашла
# пары, а человек подтвердил подсказку (см. hints_for). Отдельным кодом, а
# не MATCH_PICK: поля строки здесь из файла, а не из карточки, и по
# подписи должно быть видно, что пару подобрали по подсказке
MATCH_HINT = "hint"
# Связи, указанные человеком. Пересчёт по артикулам (relink_boards) их не
# трогает: указывают их как раз тогда, когда артикулы не совпали или
# записей с ними несколько, и автоматика выбрала бы не то
MANUAL_MATCHES = (MATCH_PICK, MATCH_HINT)

# Как правила называть людям. В базе — короткие коды, и выбором поля
# (choices) их не сделать: смена choices у поля — миграция ради подписей.
MATCH_LABELS = {
    MATCH_GBT: "по GBT PN",
    MATCH_VENDOR: "по Vendor PN и Vendor",
    MATCH_PICK: "выбран в библиотеке",
    MATCH_HINT: "подтверждён по подсказке",
}
# пустое правило — связи нет: компонента в библиотеке не нашлось
NO_MATCH_LABEL = "не сопоставлено"


def match_label(match):
    """Подпись правила; незнакомый код показывается как есть."""
    if not match:
        return NO_MATCH_LABEL
    return MATCH_LABELS.get(match, match)

# Поля строки состава, которые заполняются из карточки выбранного
# компонента. Список — это ровно те колонки BOM, которые есть и в
# библиотеке: количество, обозначения и комментарий берутся из платы, а не
# из компонента, и здесь их нет.
#
# Переносятся они один раз, при добавлении строки, и дальше живут своей
# жизнью: состав — документ, и правка описания в библиотеке не меняет уже
# выпущенный BOM. Что в библиотеке сейчас — видно по ссылке на карточку.
COPIED_FIELDS = ("vendor_pn", "vendor", "country", "oy_id", "oy_pn",
                 "gbt_pn", "group", "subgroup", "description", "smt_tht")


def component_values(obj):
    """Значения полей компонента в виде, годном для строки состава.

    ``None`` в библиотеке — обычное дело (колонки необязательные), а в
    строке состава поля не допускают ``NULL``: приводим к пустой строке
    здесь, а не в трёх местах вызова.
    """
    return {name: (getattr(obj, name, "") or "").strip()
            for name in COPIED_FIELDS}


def build_index():
    """Готовит два словаря: по GBT PN и по паре Vendor PN + Vendor."""
    by_gbt, by_vendor = {}, {}

    for category, values in scan(("id", "gbt_pn", "vendor_pn", "vendor")):
        target = (category.table, values["id"])

        gbt = usable(values.get("gbt_pn")).lower()
        if gbt:
            by_gbt.setdefault(gbt, target)

        vendor_pn = usable(values.get("vendor_pn")).lower()
        vendor = usable(values.get("vendor")).lower()
        if vendor_pn and vendor:
            by_vendor.setdefault((vendor_pn, vendor), target)

    return by_gbt, by_vendor


def resolve(item, index):
    """Возвращает (таблица, id, правило) для строки состава."""
    by_gbt, by_vendor = index

    gbt = usable(item.get("gbt_pn")).lower()
    if gbt and gbt in by_gbt:
        table, pk = by_gbt[gbt]
        return table, pk, MATCH_GBT

    vendor_pn = usable(item.get("vendor_pn")).lower()
    vendor = usable(item.get("vendor")).lower()
    if vendor_pn and vendor and (vendor_pn, vendor) in by_vendor:
        table, pk = by_vendor[(vendor_pn, vendor)]
        return table, pk, MATCH_VENDOR

    return "", None, ""


def link_items(items, index=None):
    """Проставляет ссылки на компоненты в разобранных строках BOM."""
    index = index or build_index()
    linked = 0
    for item in items:
        table, pk, match = resolve(item, index)
        item["component_table"] = table
        item["component_id"] = pk
        item["component_match"] = match
        linked += int(pk is not None)
    return linked


# --- подсказки для строк без пары -------------------------------------------
#
# Импорт связывает строку, только если артикул нашёлся точно. Остальные
# остаются «не сопоставлено», хотя часто компонент в библиотеке есть, просто
# записан иначе: «2N7002KTB_R1» в BOM против «2N7002KTB», другой
# разделитель, или тот же Vendor PN, но производитель написан по-другому
# («TI» и «Texas Instruments»). Подсказки показывают такие пары, а связь
# ставит человек — угаданная связь в составе хуже отсутствующей.

HINT_LIMIT = 3

# по каким полям строки ищем похожее; GBT PN первым — как и в resolve()
HINT_FIELDS = (("gbt_pn", "GBT PN"), ("vendor_pn", "Vendor PN"))

# что показать рядом с подсказкой, чтобы решить, та ли это деталь
DETAIL_FIELDS = ("vendor", "description")


def hints_for(item, prepared, limit=HINT_LIMIT):
    """Похожие артикулы библиотеки для строки состава без связи.

    ``item`` — строка состава (или что угодно с полями ``gbt_pn`` и
    ``vendor_pn``), ``prepared`` — ``similar.prepare(similar.library_index())``.
    Возвращает подсказки ``similar.hint`` с полем ``field``: по какому
    артикулу строки найдено.

    Только точные правила — тот же артикул, другие разделители, суффикс
    упаковки. Нестрогое сравнение здесь выключено: на живом составе все
    «похожие артикулы» оказались соседними номиналами и допусками
    («GRM31CR61E226KE15L» → «…ME15D»), а опечаток в BOM, выгруженном из
    САПР, почти не бывает. Ложная подсказка тут хуже отсутствующей.
    """
    best = {}
    for name, label in HINT_FIELDS:
        pn = usable(getattr(item, name, ""))
        if not pn:
            continue
        for key, entry, score, reason in similar.similar(pn, prepared,
                                                         fuzzy=False):
            # одна запись находится по обоим полям — остаётся лучшая оценка
            if key not in best or score > best[key]["score"]:
                best[key] = {**similar.hint(entry, score, reason),
                             "field": label}
    # при равной оценке остаётся порядок полей: совпадение по GBT PN выше
    return sorted(best.values(), key=lambda hint: -hint["score"])[:limit]


def hint_details(hints):
    """``{(таблица, ключ): {"vendor", "description"}}`` для пачки подсказок.

    Один запрос на таблицу, а не на подсказку: на странице их десятки.
    Недоступная таблица не роняет страницу — у её подсказок просто не
    будет подробностей.
    """
    by_table = {}
    for hint in hints:
        by_table.setdefault(hint["table"], set()).add(hint["pk"])

    details = {}
    for table, keys in by_table.items():
        category = category_by_table(table)
        if category is None:
            continue
        fields = category.available(("id", *DETAIL_FIELDS))
        with unavailable(table):
            for row in (category.model.objects.filter(pk__in=keys)
                        .order_by().values(*fields)):
                details[(table, row.pop("id"))] = row
    return details
