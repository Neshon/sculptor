"""Выпадающие списки для полей компонентов.

Колонки в базе остаются текстовыми — их читает сторонний софт, и менять
тип на внешний ключ нельзя. Справочник задаёт только то, какие поля
показываются списком, в каких таблицах это работает и какие значения
доступны для выбора.

Настраивается в админке: раздел «Конструктор выпадающих списков».
"""

from .cache import OPTIONS_KEY, cached
from .db import distinct_values, fallback, unavailable
from .models import OptionField
from .registry import CATEGORIES, category_by_table


def table_options(table):
    """Списки значений для таблицы: ``{имя поля: [значения]}``.

    Спрашивают об этом на каждую форму и на каждый набор фильтров, а меняется
    справочник только из админки, поэтому ответ кэшируется и сбрасывается при
    правке (см. ``components.apps``).
    """
    return cached(OPTIONS_KEY.format(table=table),
                  lambda: _table_options(table))


@fallback(dict, "справочник выпадающих списков")
def _table_options(table):
    """Тот же ответ, но всегда из базы.

    Если справочник пуст, таблица ещё не создана или база недоступна —
    возвращается пустой словарь, и поля остаются обычными текстовыми.
    """
    fields = (OptionField.objects
              .filter(is_active=True)
              .prefetch_related("values"))
    # общий список (таблицы не указаны) и список, заданный именно для
    # этой таблицы. Второй важнее: подгруппы у резисторов и разъёмов
    # разные, и общий набор для них смысла не имеет
    common, specific = {}, {}
    for option_field in fields:
        values = [v.value for v in option_field.values.all() if v.is_active]
        if not values:
            continue
        if not option_field.tables:
            common.setdefault(option_field.field, []).extend(values)
        elif table in option_field.tables:
            specific.setdefault(option_field.field, []).extend(values)

    merged = {**common, **specific}
    return {name: sorted(set(values)) for name, values in merged.items()}


def option_values(field, table):
    """Значения одного поля для конкретной таблицы."""
    return table_options(table).get(field, [])


def table_choices():
    """Список таблиц для выбора в админке."""
    return [(c.table, f"{c.table} — {c.title}") for c in CATEGORIES.values()]


# ---- проверки для конструктора в админке ---------------------------------

# Поля, которые списком быть не могут: служебные, артикулы и ссылки — у
# каждой записи своё значение, и список из них был бы копией таблицы.
# Длинный текст (Description, Notice) и даты отсеиваются по типу поля.
NOT_OPTION_FIELDS = ("id", "created", "author", "oy_id", "oy_pn", "vendor_pn",
                     "gbt_pn", "tracker_url", "datasheet")


def field_choices(current=""):
    """``[(имя поля, подпись)]`` для выбора столбца.

    Раньше столбец вписывали руками, и опечатка («smt-tht», «SMT_THT»)
    ничего не ломала — и ничего не делала: список заводился, но ни в одной
    форме не появлялся. Выбор из полей, которые правда есть в таблицах,
    такого не допускает.

    ``current`` — значение уже заведённого столбца. Если его в списке нет
    (поле убрали из модели), оно всё равно попадает в выбор: иначе запись
    нельзя было бы даже открыть и сохранить, не сменив столбец.
    """
    from django.db import models

    labels = {}
    for category in CATEGORIES.values():
        for field in category.model._meta.fields:
            # TextField — не наследник CharField, так что длинный текст
            # отсеивается здесь же
            if (field.name in NOT_OPTION_FIELDS
                    or not isinstance(field, models.CharField)):
                continue
            labels.setdefault(field.name, str(field.verbose_name))

    if current and current not in labels:
        labels[current] = current
    return sorted(((name, f"{label} — {name}") for name, label in labels.items()),
                  key=lambda pair: pair[1].lower())


def tables_without(field, tables):
    """Отмеченные таблицы, в которых такой колонки нет.

    Поля Allegro есть только в рабочих таблицах: список футпринтов,
    отмеченный для замен, на них не повлиял бы — и никто бы этого не
    заметил.
    """
    return [table for table in tables
            if (category := category_by_table(table)) is not None
            and field not in category.field_names]


def overlapping(tables, others):
    """Записи из ``others``, чьи таблицы пересекаются с ``tables``.

    ``others`` — пары ``(запись, её таблицы)`` того же столбца. Пустой набор
    таблиц значит «во всех». Общая запись и своя для таблицы — не
    пересечение, а задуманная схема: своя важнее общей (``_table_options``).
    Пересекаются две общие или две своих с общей таблицей: их значения
    молча сливались, и откуда взялось лишнее, из формы было не понять.
    """
    mine = set(tables)
    found = []
    for other, their in others:
        their = set(their or ())
        if (not mine and not their) or (mine & their):
            found.append((other, sorted(mine & their)))
    return found


def source_categories(field, tables=()):
    """Таблицы, из которых собирать значения столбца.

    Отмеченные таблицы, где колонка есть; ничего не отмечено — все, где
    она есть.
    """
    wanted = set(tables or ())
    return [c for c in CATEGORIES.values()
            if field in c.field_names and (not wanted or c.table in wanted)]


def values_in_data(categories, field):
    """``(значения, непрочитанные таблицы)`` — что в столбце уже записано.

    Одно на админку («Добавить значения из данных») и команду
    ``load_options``: собирать по-разному значило бы получить разные списки
    из одних и тех же данных.

    Недоступная таблица не роняет сбор — её имя попадает во второй список,
    и вызывающий говорит о ней человеку: молча отдать неполный список хуже,
    чем сказать, откуда он неполный.
    """
    found, failed = set(), []
    for category in categories:
        with unavailable(category.table, failed):
            filled = (category.model.objects
                      .exclude(**{f"{field}__isnull": True})
                      .exclude(**{field: ""}))
            found.update(v.strip() for v in distinct_values(filled, field)
                         if v and v.strip())
    return sorted(found), failed


def parse_values(text):
    """Значения из поля «Новые значения»: по одному в строке.

    Пробелы по краям срезаются, пустые строки и повторы пропускаются,
    порядок — как ввели. Регистр не трогается: «SMT» и «smt» в данных
    бывают разными значениями, и решать за человека, что это опечатка,
    нельзя.
    """
    seen = []
    for line in (text or "").splitlines():
        value = line.strip()
        if value and value not in seen:
            seen.append(value)
    return seen
