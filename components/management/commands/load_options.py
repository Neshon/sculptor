"""Первичное наполнение справочника из уже введённых данных.

    python manage.py load_options --field smt_tht
    python manage.py load_options --field package --table RESISTOR --table z_RESISTOR
    python manage.py load_options --field vendor --per-group

Столбец создаётся, если его ещё нет; значения собираются запросом DISTINCT
по указанным таблицам. Команда идемпотентная: повторный запуск ничего не
дублирует и не трогает то, что уже поправили руками.

``--per-group`` — свой список на каждую группу: рабочая таблица вместе со
своими заменами (``options.group_tables``). Так заведены подгруппы и
производители: у каждой группы свои, и общий список на все таблицы был бы
длинным и чужим для каждой из них.
"""

from django.core.management.base import BaseCommand, CommandError

from components.models import OptionField, OptionValue
from components.options import group_tables, source_categories, values_in_data
from components.registry import table_title


class Command(BaseCommand):
    help = "Собирает значения столбца из таблиц компонентов в справочник"

    def add_arguments(self, parser):
        parser.add_argument("--field", action="append", dest="fields",
                            required=True,
                            help="имя поля модели; можно указать несколько раз")
        parser.add_argument("--table", action="append", dest="tables",
                            help="таблица-источник (по умолчанию все, где есть поле)")
        parser.add_argument("--limit-to-tables", action="store_true",
                            help="ограничить действие столбца этими же таблицами")
        parser.add_argument("--per-group", action="store_true",
                            help="свой список на каждую группу: таблица и её замены")

    def handle(self, *args, **options):
        if options["per_group"] and options["tables"]:
            raise CommandError("--per-group сам раскладывает таблицы по "
                               "группам — --table с ним не нужен")
        wanted = set(options["tables"] or [])
        for field in options["fields"]:
            if not options["per_group"]:
                self.collect(field, wanted, options["limit_to_tables"])
                continue
            groups = group_tables(field)
            if not groups:
                raise CommandError(f"Поле «{field}» не найдено ни в одной таблице")
            for tables in groups:
                # подпись — чтобы в админке различать списки одного
                # столбца: иначе там четырнадцать одинаковых «vendor»
                self.collect(field, set(tables), True,
                             label=f"{field}: {table_title(tables[0])}")
            # Общий список поле не теряет, но и не действует там, где есть
            # свой (options._table_options), а в админке их пересечение —
            # ошибка формы. Молча удалять его нельзя: в нём могли быть
            # значения, заведённые руками
            if OptionField.objects.filter(field=field, tables=[],
                                          is_active=True).exists():
                self.stderr.write(self.style.WARNING(
                    f"У столбца «{field}» есть и общий список на все таблицы — "
                    f"теперь он перекрыт списками групп. Отключите его в "
                    f"админке, в «Конструкторе выпадающих списков»."))

    def collect(self, field, wanted, limit_to_tables, label=""):

        categories = source_categories(field, wanted)
        if not categories:
            raise CommandError(f"Поле «{field}» не найдено ни в одной таблице")

        # столбец ищется вместе с набором таблиц: один и тот же столбец
        # может быть заведён отдельно для разных групп
        tables = sorted(c.table for c in categories) if limit_to_tables else []
        option_field, _ = OptionField.objects.get_or_create(
            field=field, tables=tables, defaults={"label": label})

        # сбор — общий с админкой («Добавить значения из данных»)
        found, failed = values_in_data(categories, field)
        for table in failed:
            self.stderr.write(self.style.WARNING(
                f"{table}: таблица не прочиталась, её значения не собраны"))

        added = 0
        for value in found:
            _, is_new = OptionValue.objects.get_or_create(
                option_field=option_field, value=value)
            added += int(is_new)

        self.stdout.write(self.style.SUCCESS(
            f"Столбец «{field}»: значений всего {option_field.values.count()}, "
            f"добавлено {added}. Таблиц-источников: {len(categories)}."))
