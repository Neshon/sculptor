"""Справочник: реестр групп, поля, заглушки, названия, строка запроса."""

import datetime
from unittest import mock

from django.db import DatabaseError
from django.http import QueryDict
from django.test import SimpleTestCase

from ..export import EXPORT_LABELS, csv_response, export_stamp
from ..matching import is_dash, is_placeholder, normalize, usable
from ..querystring import (
    reset_filters,
    sort_state,
    toggle_sort,
    with_page,
    with_params,
)
from ..registry import (
    CATEGORIES,
    MAIN_CATEGORIES,
    REPLACEMENT_CATEGORIES,
    counterpart,
    get_category,
    ordered_fields,
)
from ..views import MAIN_FIELDS, MAIN_LEFT, MAIN_RIGHT, _split_fields


def query(text):
    return QueryDict(text, mutable=False)


class MatchingTests(SimpleTestCase):
    """Заглушки не должны участвовать в сопоставлении записей."""

    def test_common_placeholders(self):
        for value in ("---", "?", "-", "n/a", "нет", "TBD", "", "  "):
            with self.subTest(value=value):
                self.assertTrue(is_placeholder(value))

    def test_real_values_are_not_placeholders(self):
        for value in ("GRM188R71H104KA93D", "0603", "10 мкФ"):
            with self.subTest(value=value):
                self.assertFalse(is_placeholder(value))

    def test_case_and_spaces_are_ignored(self):
        self.assertEqual(normalize("  N/A  "), "n/a")
        self.assertTrue(is_placeholder("  N/A  "))

    def test_usable_returns_empty_for_placeholders(self):
        self.assertEqual(usable("---"), "")
        self.assertEqual(usable(None), "")

    def test_usable_keeps_the_value_trimmed(self):
        self.assertEqual(usable("  PN-1  "), "PN-1")

    def test_dash_is_narrower_than_placeholder(self):
        """Где слова несут смысл, годится только is_dash.

        «Нет» в артикуле не значит ничего, а в ответе «в реестре МПТ — нет»
        значит ровно то, что написано. Поэтому проверки две, а не одна.
        """
        for value in ("", "  ", "-", "---", "—", "?"):
            with self.subTest(value=value, dash=True):
                self.assertTrue(is_dash(value))
                self.assertTrue(is_placeholder(value))

        for value in ("нет", "n/a", "TBD", "не указано"):
            with self.subTest(value=value, dash=False):
                self.assertFalse(is_dash(value))
                self.assertTrue(is_placeholder(value))



class RegistryTests(SimpleTestCase):
    """Реестр собирает 27 таблиц и правильно связывает рабочие с заменами."""

    def test_all_tables_registered(self):
        self.assertEqual(len(CATEGORIES), 27)
        self.assertEqual(len(MAIN_CATEGORIES), 14)
        self.assertEqual(len(REPLACEMENT_CATEGORIES), 13)

    def test_parts_view_is_not_registered(self):
        # Parts — объект уровня PostgreSQL, Django его не касается
        self.assertNotIn("parts", CATEGORIES)

    def test_replacement_tables_are_prefixed(self):
        for category in REPLACEMENT_CATEGORIES:
            with self.subTest(table=category.table):
                self.assertTrue(category.table.startswith("z_"))
                self.assertTrue(category.replacement)

    def test_counterpart_is_symmetric(self):
        resistor = get_category("resistor")
        pair = counterpart(resistor)
        self.assertEqual(pair.table, "z_RESISTOR")
        self.assertEqual(counterpart(pair), resistor)

    def test_pcb_has_no_replacement_table(self):
        self.assertIsNone(counterpart(get_category("pcb")))

    def test_replacement_inherits_columns_of_its_main_table(self):
        # набор колонок у замены берётся у рабочей таблицы, кроме тех
        # полей, которых в ней физически нет
        main = get_category("capacitor")
        pair = counterpart(main)
        self.assertEqual(main.extra_columns, pair.extra_columns)
        self.assertIn("value", pair.columns)

    def test_allegro_columns_only_in_main_tables(self):
        self.assertIn("allegro_pcb_footprint", get_category("capacitor").columns)
        self.assertNotIn("allegro_pcb_footprint",
                         get_category("capacitorreplacement").columns)

    def test_pcb_skips_vendor_and_package(self):
        columns = get_category("pcb").columns
        self.assertNotIn("vendor", columns)
        self.assertNotIn("package", columns)

    def test_unknown_slug(self):
        self.assertIsNone(get_category("нет такой группы"))



class ColumnWidthTests(SimpleTestCase):
    """Колонки списка постоянной ширины (COLUMN_CHARS, list.html, app.css)."""

    def test_width_follows_the_data(self):
        from ..registry import COLUMN_CHARS, DEFAULT_COLUMN_CHARS, column_chars

        self.assertEqual(column_chars("vendor_pn", "Vendor PN"),
                         COLUMN_CHARS["vendor_pn"])
        # параметр группы без своей записи — общая ширина
        self.assertEqual(column_chars("value", "Value"), DEFAULT_COLUMN_CHARS)

    def test_column_is_not_narrower_than_a_header_word(self):
        # заголовок переносится по пробелам: слово длиннее колонки вылезло
        # бы на соседнюю
        from ..registry import SORT_MARK_CHARS, column_chars

        self.assertEqual(column_chars("frequency", "Frequency-tolerance"),
                         len("Frequency-tolerance") + SORT_MARK_CHARS)

    def test_header_wraps_by_words(self):
        from ..registry import header_lines

        self.assertEqual(header_lines("Output Current, A", 8), 3)
        self.assertEqual(header_lines("Output Current, A", 10), 2)
        self.assertEqual(header_lines("Package", 7), 1)

    def test_column_widens_so_the_header_fits_two_lines(self):
        # «Output Current, A» в общие 10 знаков встал бы в три строки —
        # выше шапки
        from ..registry import (
            DEFAULT_COLUMN_CHARS,
            HEADER_LINES,
            SORT_MARK_CHARS,
            column_chars,
            header_lines,
        )

        chars = column_chars("output_current_a", "Output Current, A")
        self.assertGreater(chars, DEFAULT_COLUMN_CHARS)
        self.assertLessEqual(header_lines("Output Current, A", chars - SORT_MARK_CHARS),
                             HEADER_LINES)

    def test_no_list_header_is_taller_than_the_head(self):
        from ..registry import HEADER_LINES, SORT_MARK_CHARS, header_lines

        for category in CATEGORIES.values():
            for (name, label), chars in zip(category.verbose_columns,
                                            category.column_widths, strict=True):
                if chars is None:
                    continue
                with self.subTest(table=category.table, column=name):
                    self.assertLessEqual(
                        header_lines(label, chars - SORT_MARK_CHARS), HEADER_LINES)

    def test_every_list_has_widths_for_all_columns(self):
        from ..registry import FLEX_COLUMN

        for category in CATEGORIES.values():
            with self.subTest(table=category.table):
                self.assertEqual(len(category.column_widths), len(category.columns))
                flex = [name for name, width in
                        zip(category.columns, category.column_widths, strict=True)
                        if width is None]
                # остаток ширины уходит ровно в одну колонку — описание
                self.assertEqual(flex, [FLEX_COLUMN])
                self.assertEqual(category.fixed_count, len(category.columns) - 1)
                self.assertEqual(category.fixed_chars,
                                 sum(w for w in category.column_widths if w))

    def test_list_template_uses_the_widths(self):
        from django.template.loader import get_template

        source = get_template("components/list.html").template.source
        self.assertIn("<colgroup>", source)
        self.assertIn("category.column_widths", source)
        self.assertIn("--fixed-chars: {{ category.fixed_chars }}", source)


class PhysicalFieldsTests(SimpleTestCase):
    """Габариты и температура вынесены в общий класс — кроме PCB, где их нет."""

    LIFTED = ("dimensions_mm", "height_mm", "temperature_min_c",
             "temperature_max_c")

    def test_every_group_except_pcb_has_them(self):
        for category in MAIN_CATEGORIES + REPLACEMENT_CATEGORIES:
            names = {f.name for f in category.model._meta.fields}
            has_all = all(name in names for name in self.LIFTED)
            if category.table == "PCB":
                self.assertFalse(has_all, "у PCB этих колонок в базе нет")
            else:
                self.assertTrue(has_all, category.table)

    def test_definitions_are_identical_everywhere_they_appear(self):
        # определения должны совпадать не только по факту наследования,
        # но и по db_column: иначе в базе это были бы разные колонки
        for name in self.LIFTED:
            columns = {
                get_category(slug).model._meta.get_field(name).db_column
                for slug in CATEGORIES if slug != "pcb"
            }
            self.assertEqual(len(columns), 1, (name, columns))



class FieldOrderTests(SimpleTestCase):
    """Порядок полей задан явно, а не тем, как сработало наследование."""

    def test_identification_fields_come_first(self):
        names = [f.name for f in ordered_fields(get_category("resistor").model)]
        self.assertEqual(names[:4], ["vendor_pn", "oy_pn", "oy_id", "gbt_pn"])

    def test_surrogate_key_goes_last(self):
        for category in CATEGORIES.values():
            with self.subTest(table=category.table):
                names = [f.name for f in category.ordered_fields]
                self.assertEqual(names[-1], "id")

    def test_group_parameters_follow_the_common_ones(self):
        names = [f.name for f in get_category("capacitor").ordered_fields]
        self.assertLess(names.index("notice"), names.index("dielectric_type"))

    def test_every_field_is_listed_exactly_once(self):
        for category in CATEGORIES.values():
            with self.subTest(table=category.table):
                names = [f.name for f in category.ordered_fields]
                expected = {f.name for f in category.model._meta.fields}
                self.assertEqual(len(names), len(expected))
                self.assertEqual(set(names), expected)



class QueryStringTests(SimpleTestCase):
    """Фильтры и сортировка не должны терять друг друга и залипать на странице."""

    def test_page_is_dropped_when_filters_change(self):
        self.assertEqual(with_params(query("page=5&vendor=Yageo"), vendor="TDK"),
                         "?vendor=TDK")

    def test_empty_value_removes_the_parameter(self):
        self.assertEqual(with_params(query("vendor=Yageo&q=x"), vendor=""),
                         "?q=x")

    def test_other_parameters_are_kept(self):
        result = with_params(query("q=abc&sort=vendor"), dir="desc")
        self.assertIn("q=abc", result)
        self.assertIn("sort=vendor", result)
        self.assertIn("dir=desc", result)

    def test_empty_query_stays_valid(self):
        self.assertEqual(with_params(query(""), page=""), "?")

    def test_page_url_keeps_filters(self):
        result = with_page(query("q=abc&page=2"), 3)
        self.assertIn("q=abc", result)
        self.assertIn("page=3", result)
        self.assertNotIn("page=2", result)

    def test_first_click_sorts_ascending(self):
        self.assertEqual(toggle_sort(query(""), "vendor"),
                         "?sort=vendor&dir=asc")

    def test_second_click_reverses(self):
        self.assertEqual(toggle_sort(query("sort=vendor&dir=asc"), "vendor"),
                         "?sort=vendor&dir=desc")

    def test_another_column_starts_over(self):
        self.assertEqual(toggle_sort(query("sort=vendor&dir=desc"), "package"),
                         "?sort=package&dir=asc")

    def test_sort_state_reported_only_for_the_active_column(self):
        params = query("sort=vendor&dir=desc")
        self.assertEqual(sort_state(params, "vendor"), "desc")
        self.assertEqual(sort_state(params, "package"), "")

    def test_reset_drops_filters_but_keeps_the_view(self):
        # сброс убирает отбор, а сортировку и число строк оставляет: это вид
        # списка, после сброса он не должен становиться другим
        result = reset_filters(query(
            "q=abc&vendor=TDK|Yageo&page=3&sort=vendor&dir=desc&per_page=50"))
        self.assertEqual(result, "?sort=vendor&dir=desc&per_page=50")

    def test_reset_of_bare_filters_is_the_bare_list(self):
        self.assertEqual(reset_filters(query("q=abc&vendor=TDK")), "")
        self.assertEqual(reset_filters(query("sort=&per_page=")), "")


class FilteringTests(SimpleTestCase):
    """Когда показывать «Сбросить» (listing.filtering)."""

    def setUp(self):
        from ..registry import CATEGORIES
        self.category = CATEGORIES["diode"]

    def filtering(self, text):
        from ..listing import filtering
        return filtering(query(text), self.category)

    def test_search_and_chosen_values_narrow_the_list(self):
        self.assertTrue(self.filtering("q=smbj"))
        self.assertTrue(self.filtering("vendor=Vishay"))

    def test_view_parameters_alone_do_not(self):
        # сняв последнюю галочку, человек остаётся с числом строк и
        # сортировкой в адресе — кнопка сброса над несуженным списком лишняя
        self.assertFalse(self.filtering("per_page=50&sort=vendor&dir=desc&page=2"))
        self.assertFalse(self.filtering("q=++&vendor="))



class ExportStampTests(SimpleTestCase):
    """Отметка о выгрузке — одна на все форматы и разделы.

    Файл уходит в переписку и на диск R, и через месяц по нему уже не
    понять, из какого он состояния базы и кто его достал.
    """

    def read(self, response):
        import csv as csv_module
        from io import StringIO
        text = response.content.decode("utf-8").lstrip("\ufeff")
        return list(csv_module.reader(StringIO(text), delimiter=";"))

    def test_stamp_goes_before_the_table(self):
        response = csv_response(
            "x.csv", ["A", "B"], [[1, 2]],
            preamble=export_stamp("ivanov",
                                  when=datetime.datetime(2026, 9, 15, 16, 40)))
        lines = self.read(response)
        self.assertEqual(lines[0], [EXPORT_LABELS[0], "15.09.2026 16:40"])
        self.assertEqual(lines[1], [EXPORT_LABELS[1], "ivanov"])
        # пустая строка отделяет шапку от таблицы — так её видит Excel
        self.assertEqual(lines[2], [])
        self.assertEqual(lines[3], ["A", "B"])
        self.assertEqual(lines[4], ["1", "2"])

    def test_without_preamble_headers_stay_first(self):
        """Выгрузки изделий отметки не получают: их читают программами."""
        lines = self.read(csv_response("x.csv", ["A", "B"], [[1, 2]]))
        self.assertEqual(lines[0], ["A", "B"])

    def test_stamp_is_written_even_without_a_user(self):
        stamp = export_stamp("")
        self.assertEqual(stamp[1], [EXPORT_LABELS[1], ""])
        self.assertTrue(stamp[0][1])



class AllegroFilterTests(SimpleTestCase):
    """Фильтры по символу и посадочному месту Allegro — у всех групп сразу.

    Дописываются реестром в конец набора группы, а не руками в каждую
    строку FILTER_FIELDS: новая группа иначе осталась бы без них.
    """

    ALLEGRO = ("allegro_schematic_part", "allegro_pcb_footprint")

    def names(self, slug):
        return [name for name, _ in CATEGORIES[slug].filters]

    def test_every_group_with_filters_gets_them_last(self):
        for category in MAIN_CATEGORIES:
            if category.slug == "pcb":
                continue
            with self.subTest(category.slug):
                self.assertEqual(tuple(self.names(category.slug)[-2:]),
                                 self.ALLEGRO)

    def test_own_filters_stay_in_front(self):
        self.assertEqual(self.names("capacitor")[0], "vendor")

    def test_board_keeps_no_filters(self):
        # у PCB фильтров нет намеренно, а посадочное место у платы скрыто
        self.assertEqual(self.names("pcb"), [])

    def test_replacement_tables_have_no_allegro_columns(self):
        for category in REPLACEMENT_CATEGORIES:
            with self.subTest(category.slug):
                self.assertFalse(set(self.names(category.slug)) &
                                 set(self.ALLEGRO))

    def test_labels_come_from_the_model(self):
        labels = dict(CATEGORIES["connector"].filters)
        self.assertEqual(str(labels["allegro_pcb_footprint"]),
                         "Allegro PCB Footprint")



class MainFieldsTests(SimpleTestCase):
    """Деление полей карточки на основные и параметры группы.

    Основные — то, по чему компонент опознают и заказывают: одинаково у
    конденсатора и у микросхемы. Параметры у каждой группы свои, их
    десятки, и в общем списке они тонули.
    """

    def rows(self, *names):
        # (подпись, значение, имя поля) — как их складывает карточка
        return [(name.upper(), "x", name) for name in names]

    def test_columns_keep_their_order(self):
        # порядок задан списком, а не порядком колонок в таблице:
        # артикул читают первым, где бы он ни лежал в схеме
        _, left, right, _ = _split_fields(
            self.rows("subgroup", "vendor_pn", "created", "tracker_url"))
        self.assertEqual([row[2] for row in left], ["vendor_pn", "subgroup"])
        self.assertEqual([row[2] for row in right], ["tracker_url", "created"])

    def test_column_membership_does_not_drift(self):
        # ключевое: пустые поля выпадают, но оставшиеся не переезжают из
        # столбца в столбец — иначе Group прыгал бы вправо от записи к записи
        _, left, right, _ = _split_fields(self.rows("vendor_pn", "created"))
        self.assertEqual([row[2] for row in left], ["vendor_pn"])
        self.assertEqual([row[2] for row in right], ["created"])

    def test_everything_else_goes_to_the_tab(self):
        _, left, right, rest = _split_fields(
            self.rows("vendor_pn", "capacitance", "package"))
        self.assertEqual([row[2] for row in left], ["vendor_pn"])
        self.assertEqual(right, [])
        self.assertEqual([row[2] for row in rest], ["capacitance", "package"])

    def test_rest_keeps_the_table_order(self):
        # у параметров своего порядка нет, и выдумывать его не за что:
        # порядок колонок задал тот, кто вёл таблицу
        _, _, _, rest = _split_fields(self.rows("b_param", "a_param"))
        self.assertEqual([row[2] for row in rest], ["b_param", "a_param"])

    def test_description_is_taken_out_of_every_list(self):
        # оно показывается фразой над характеристиками, а не парой
        # «подпись — значение», и попасть в списки не должно
        description, left, right, rest = _split_fields(
            self.rows("vendor_pn", "description"))
        self.assertEqual(description[2], "description")
        for rows in (left, right, rest):
            self.assertNotIn("description", [row[2] for row in rows])

    def test_missing_description_is_not_an_error(self):
        description, _, _, _ = _split_fields(self.rows("vendor_pn"))
        self.assertIsNone(description)

    def test_missing_fields_are_simply_absent(self):
        # в таблицах замен половины основных полей нет
        _, left, right, rest = _split_fields(self.rows("vendor_pn"))
        self.assertEqual(len(left), 1)
        self.assertEqual((right, rest), ([], []))

    def test_no_field_is_listed_twice(self):
        self.assertEqual(len(MAIN_FIELDS), len(set(MAIN_FIELDS)))

    def test_columns_do_not_overlap(self):
        self.assertEqual(set(MAIN_LEFT) & set(MAIN_RIGHT), set())



class DistinctValuesTests(SimpleTestCase):
    """distinct по колонке — без полей сортировки модели в запросе."""

    def test_default_ordering_dropped(self):
        from ..db import distinct_values
        from ..models import ComponentChange
        # у журнала сортировка по -created, -id: с ней distinct различал бы
        # строки по времени правки
        query = distinct_values(ComponentChange.objects.all(), "author").query
        self.assertEqual(query.order_by, ())
        self.assertFalse(query.default_ordering)
        self.assertTrue(query.distinct)

    def test_order_by_column_itself(self):
        from ..db import distinct_values
        category = get_category("resistor")
        query = distinct_values(category.model.objects.all(), "vendor",
                                order=True).query
        self.assertEqual(query.order_by, ("vendor",))



class DisplayTitleTests(SimpleTestCase):
    """Название компонента — первое заполненное поле, заглушки не в счёт."""

    def title(self, **fields):
        return get_category("connector").model(pk=428, **fields).display_title()

    def test_first_filled(self):
        self.assertEqual(self.title(vendor_pn="WIQ0150009", oy_pn="X"),
                         "WIQ0150009")

    def test_placeholder_skipped(self):
        # раньше выходило «Компонент --- удалён»
        self.assertEqual(self.title(vendor_pn="---", oy_pn="?",
                                    description="DDR4 RDIMM"),
                         "DDR4 RDIMM")

    def test_nothing_filled(self):
        self.assertEqual(self.title(vendor_pn="---"), "#428")



class ComponentTitlesTests(SimpleTestCase):
    """Названия компонентов для журнала — по запросу на таблицу."""

    def titles(self, pairs, found):
        from ..refs import component_titles
        category = get_category("resistor")
        rows = [category.model(pk=pk, **fields) for pk, fields in found.items()]
        manager = mock.Mock()
        manager.filter.return_value.order_by.return_value.only.return_value = rows
        with mock.patch.object(category.model, "objects", manager):
            return component_titles(pairs), manager

    def test_found_deleted_and_unknown(self):
        titles, manager = self.titles(
            [("RESISTOR", 1), ("RESISTOR", 2), ("RESISTOR", 1),
             ("NO_SUCH_TABLE", 5)],
            {1: {"vendor_pn": "R1", "oy_pn": "", "description": ""}})
        self.assertEqual(titles, {("RESISTOR", 1): "R1",
                                  ("RESISTOR", 2): None})
        manager.filter.assert_called_once_with(pk__in={1, 2})

    def test_placeholder_is_not_a_title(self):
        # у разъёмов без Vendor PN в журнале стояло «---»
        titles, _ = self.titles(
            [("RESISTOR", 1), ("RESISTOR", 2)],
            {1: {"vendor_pn": "---", "oy_pn": "R0402-1K", "description": ""},
             2: {"vendor_pn": "---", "oy_pn": "?", "description": "---"}})
        self.assertEqual(titles, {("RESISTOR", 1): "R0402-1K",
                                  ("RESISTOR", 2): "#2"})

    def test_unreadable_table_stays_unknown(self):
        from ..refs import component_titles
        category = get_category("resistor")
        manager = mock.Mock()
        manager.filter.side_effect = DatabaseError("нет таблицы")
        with mock.patch.object(category.model, "objects", manager):
            self.assertEqual(component_titles([("RESISTOR", 1)]), {})
