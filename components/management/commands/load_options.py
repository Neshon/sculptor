"""Первичное наполнение справочника из уже введённых данных.

    python manage.py load_options --field smt_tht
    python manage.py load_options --field package --table RESISTOR --table z_RESISTOR

Столбец создаётся, если его ещё нет; значения собираются запросом DISTINCT
по указанным таблицам. Команда идемпотентная: повторный запуск ничего не
дублирует и не трогает то, что уже поправили руками.
"""

from django.core.management.base import BaseCommand, CommandError

from components.models import OptionField, OptionValue
from components.options import source_categories, values_in_data


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

    def handle(self, *args, **options):
        wanted = set(options["tables"] or [])
        for field in options["fields"]:
            self.collect(field, wanted, options["limit_to_tables"])

    def collect(self, field, wanted, limit_to_tables):

        categories = source_categories(field, wanted)
        if not categories:
            raise CommandError(f"Поле «{field}» не найдено ни в одной таблице")

        # столбец ищется вместе с набором таблиц: один и тот же столбец
        # может быть заведён отдельно для разных групп
        tables = sorted(c.table for c in categories) if limit_to_tables else []
        option_field, _ = OptionField.objects.get_or_create(
            field=field, tables=tables)

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
