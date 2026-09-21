"""Тесты справочника компонентов.

Базы данных они не требуют (``SimpleTestCase``): проверяется то, что
считается в Python, — заглушки в данных, порядок полей, реестр категорий
и сборка строки запроса. Сюда же закрытость сайта: неавторизованного
разворачивают в middleware, до базы дело не доходит.

    python manage.py test components
"""

from io import BytesIO
from unittest import mock

import datetime
import re
import shutil
from contextlib import contextmanager
from pathlib import Path

from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.template import Context, Template
from django.shortcuts import resolve_url
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from django.db import DatabaseError

from .db import fallback, unavailable
from .duplicates import (CHECKS, DEFAULT_CHECK, MATCH_RULES, _key,
                         _rule_filter)
from .export import EXPORT_LABELS, csv_response, export_stamp
from . import links as links_module
from .links import (LinkFileError, build_suggest_index, candidates,
                    match, read_rows, suggest)
from .forms import NOT_COPIED, sample_initial
from .history import author_logins, diff, snapshot
from .forms import (ARTICLE_FIELDS, FIELD_VALIDATORS, REQUIRED_FIELDS,
                    REQUIRED_MESSAGE, URL_FIELDS, URL_VALIDATOR,
                    StepImageForm)
from .views import MAIN_FIELDS, MAIN_LEFT, MAIN_RIGHT, _split_fields
from .management.commands.render_step_images import (
    models_in, normalize)
from . import step
from .matching import is_dash, is_placeholder, normalize, usable
from .querystring import sort_state, toggle_sort, with_page, with_params
from .registry import (CATEGORIES, MAIN_CATEGORIES, REPLACEMENT_CATEGORIES,
                       counterpart, get_category, ordered_fields)


def query(text):
    return QueryDict(text, mutable=False)





class DbFallbackTests(SimpleTestCase):
    """Недоступная база деградирует предсказуемо — и попадает в журнал.

    Раньше это было написано заново в сорока восьми местах и почти везде
    молча: отличить «дублей нет» от «проверка не отработала» было нельзя.
    """

    def test_fallback_returns_value_and_logs(self):
        @fallback("запасное", "тестовая выборка")
        def boom():
            raise DatabaseError("нет такой таблицы")

        with self.assertLogs("components.db", level="WARNING") as logs:
            self.assertEqual(boom(), "запасное")
        self.assertIn("тестовая выборка", logs.output[0])

    def test_fallback_calls_factory_so_callers_do_not_share(self):
        """Изменяемое запасное значение задаётся фабрикой, а не объектом."""
        @fallback(list)
        def boom():
            raise DatabaseError("нет такой таблицы")

        with self.assertLogs("components.db", level="WARNING"):
            first, second = boom(), boom()
        first.append("x")
        self.assertEqual(second, [])

    def test_fallback_does_not_swallow_other_errors(self):
        """Гасится только отказ базы: чужую ошибку прятать нельзя."""
        @fallback(None)
        def boom():
            raise ValueError("это не про базу")

        with self.assertRaises(ValueError):
            boom()

    def test_unavailable_skips_the_step_and_collects_the_name(self):
        failed, seen = [], []
        for table in ("RESISTOR", "СЛОМАНА", "CAPACITOR"):
            with self.assertLogs("components.db", level="WARNING") \
                    if table == "СЛОМАНА" else _nothing():
                with unavailable(table, failed):
                    if table == "СЛОМАНА":
                        raise DatabaseError("нет прав")
                    seen.append(table)
        self.assertEqual(seen, ["RESISTOR", "CAPACITOR"])
        self.assertEqual(failed, ["СЛОМАНА"])


@contextmanager
def _nothing():
    yield


class TemplateCommentTests(SimpleTestCase):
    """Комментарий `{# … #}` должен умещаться в одну строку.

    Django разбирает теги без флага DOTALL, поэтому `{# … #}`, растянутый
    на две строки, тегом не считается — и уезжает в страницу обычным
    текстом, прямо пользователю. Отказа при этом нет: шаблон
    отрисовывается, тесты зелёные, а на странице посреди формы висит
    заметка для разработчика. Для многострочных пояснений есть
    `{% comment %}`.

    Тест дешёвый и ловит целый класс молчаливых опечаток, поэтому проходит
    по всем шаблонам проекта, а не только по своим.
    """

    # {# … #}, внутри которого встретился перевод строки
    MULTILINE = re.compile(r"\{#(?:(?!#\}).)*?\n(?:(?!#\}).)*?#\}", re.S)

    def test_no_multiline_hash_comments(self):
        root = Path(settings.BASE_DIR)
        offenders = []
        for path in sorted(root.rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            for found in self.MULTILINE.finditer(text):
                line = text[:found.start()].count("\n") + 1
                offenders.append(f"{path.relative_to(root)}:{line}")
        self.assertEqual(
            offenders, [],
            "многострочный {# … #} не вырезается и попадёт в страницу; "
            "используйте {% comment %}: " + ", ".join(offenders))


class ClosedSiteTests(SimpleTestCase):
    """Без входа не открывается ни одна страница, кроме трёх исключений.

    Запросов к базе здесь нет и быть не должно: неавторизованного разворачивают
    в middleware, до представления дело не доходит.
    """

    def test_anonymous_is_sent_to_login(self):
        # изображения плат в этом списке не случайно: их отдаёт Django, а не
        # прокси, и закрыты они тем же middleware, что и страницы
        for url in ("/", "/boards/", "/servers/", "/changes/", "/search/",
                    "/media/boards/example.jpg"):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response.url.startswith(reverse("login")),
                                f"{url} ведёт не на форму входа: {response.url}")

    def test_query_string_survives_the_redirect(self):
        """Ссылку на отфильтрованный список присылают друг другу.

        Если вход теряет строку запроса, коллега после входа попадает на
        пустой список и не понимает, что ему прислали.
        """
        response = self.client.get("/boards/?q=HSBP&type=backplane")
        self.assertIn("q%3DHSBP", response.url)
        self.assertIn("type%3Dbackplane", response.url)

    def test_open_paths_are_marked_and_only_them(self):
        """Открытое помечено login_not_required, остальное — нет."""
        for url in ("/healthz/", reverse("login"), reverse("logout")):
            with self.subTest(url=url, open=True):
                view = resolve(url).func
                self.assertIs(getattr(view, "login_required", True), False)

        for url in ("/boards/", "/servers/", "/changes/",
                    "/media/boards/example.jpg"):
            with self.subTest(url=url, open=False):
                view = resolve(url).func
                self.assertIs(getattr(view, "login_required", True), True)


class MediaRouteTests(SimpleTestCase):
    """Изображения плат отдаются и без DEBUG.

    Раньше маршрут подключался только при ``DEBUG``, и в контейнере, где он
    выключен, ``/media/...`` отвечал 404 при файлах, лежащих на месте.
    Ошибка вылезала только на сервере, поэтому проверка нужна именно на
    маршрут, а не на отдачу файла.
    """

    def test_route_exists_regardless_of_debug(self):
        for debug in (True, False):
            with self.subTest(debug=debug), self.settings(DEBUG=debug):
                match = resolve("/media/boards/example.jpg")
                self.assertEqual(match.url_name, "media")
                self.assertEqual(match.kwargs["path"], "boards/example.jpg")

    def test_nested_paths_reach_the_view(self):
        # upload_to раскладывает снимки по подкаталогам, и маршрут должен
        # пропускать слэши внутри пути, а не только имя файла
        match = resolve("/media/boards/2026/09/top.jpg")
        self.assertEqual(match.kwargs["path"], "boards/2026/09/top.jpg")


class LoginPageTests(SimpleTestCase):
    """Форма входа своя, а не админская.

    Админская ``AdminAuthenticationForm`` отказывает всем, у кого не стоит
    «Статус персонала». Роли в библиотеке — обычные группы Django, is_staff
    у схемотехника и тополога нет, поэтому через админскую форму они войти
    не могли вовсе. Тест держит именно это: LOGIN_URL не должен снова
    уехать в админку.
    """

    def test_login_url_is_not_the_admin_one(self):
        self.assertNotEqual(resolve_url(settings.LOGIN_URL),
                            reverse("admin:login"))

    def test_login_page_opens_without_login(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)

    def test_login_page_has_both_fields(self):
        response = self.client.get(reverse("login"))
        body = response.content.decode()
        self.assertIn('name="username"', body)
        self.assertIn('name="password"', body)
        # «куда шли» — иначе после входа всех бросает на главную
        self.assertIn('name="next"', body)




class CrispyFieldTests(SimpleTestCase):
    """Строка формы рисуется одним шаблоном, класс ставится по типу виджета.

    Шаблон отрисовывается по-настоящему; база не нужна. Тест держит две
    вещи, каждая из которых ломается тихо: разметку строки (её раньше
    копировали в восемь шаблонов и она уже начала расходиться) и полноту
    CRISPY_CLASS_CONVERTERS — забытый тип виджета даёт поле без оформления,
    а не ошибку.
    """

    class Sample(forms.Form):
        pn = forms.CharField(label="Номер", required=True)
        note = forms.CharField(label="Примечание", required=False,
                               widget=forms.Textarea)
        kind = forms.ChoiceField(label="Вид", choices=[("a", "A")],
                                 required=False)
        approved = forms.BooleanField(label="Утверждена", required=False)

    def render(self, form, name):
        template = Template(
            "{% load crispy_forms_tags %}{{ field|as_crispy_field }}")
        return template.render(Context({"field": form[name]}))

    def test_row_markup_is_ours(self):
        html = self.render(self.Sample(), "pn")
        self.assertIn('class="formrow', html)
        self.assertIn("Номер", html)
        # звёздочка обязательного поля
        self.assertIn('class="req"', html)

    def test_optional_field_has_no_star(self):
        self.assertNotIn('class="req"', self.render(self.Sample(), "note"))

    def test_converters_give_each_widget_its_class(self):
        cases = {"pn": "field", "note": "field--area", "kind": "field--select"}
        for name, expected in cases.items():
            with self.subTest(field=name):
                self.assertIn(expected, self.render(self.Sample(), name))

    def test_checkbox_stays_without_the_field_class(self):
        """Флажку ширина во всю строку ни к чему."""
        html = self.render(self.Sample(), "approved")
        self.assertIn('type="checkbox"', html)
        self.assertNotIn('class="field"', html)

    def test_errors_are_shown_on_the_row(self):
        form = self.Sample(data={"pn": ""})
        form.is_valid()
        html = self.render(form, "pn")
        self.assertIn("has-error", html)
        self.assertIn("errors", html)



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


class DuplicateKeyTests(SimpleTestCase):
    """Ключи, по которым записи считаются дублями."""

    def setUp(self):
        self.MAIN = get_category("resistor")
        self.REPLACEMENT = get_category("resistorreplacement")

    def test_default_check_is_known(self):
        self.assertIn(DEFAULT_CHECK, CHECKS)

    def test_vendor_key_is_the_part_number_alone(self):
        # производитель в ключ не входит: артикул опознаёт деталь сам, а
        # разнобой в написании вендора («LITE-ON», «Lite-On») прятал бы
        # дубли вместо того, чтобы их показывать
        self.assertEqual(_key("vendor", {"vendor_pn": "PN-1"}, self.MAIN),
                         "pn-1")

    def test_vendor_key_ignores_the_vendor_field(self):
        one = _key("vendor", {"vendor_pn": "PN-1", "vendor": "Yageo"},
                   self.MAIN)
        other = _key("vendor", {"vendor_pn": "PN-1", "vendor": "YAGEO"},
                     self.MAIN)
        self.assertEqual(one, other)

    def test_placeholders_do_not_make_a_key(self):
        self.assertIsNone(_key("gbt", {"gbt_pn": "---"}, self.MAIN))
        self.assertIsNone(_key("vendor", {"vendor_pn": "?"}, self.MAIN))

    def test_oy_id_key_is_scoped_to_the_table(self):
        key = _key("oy_id", {"oy_id": "ID_R_000221"}, self.MAIN)
        self.assertEqual(key, "RESISTOR · id_r_000221")

    def test_replacement_tables_are_excluded_from_oy_id_check(self):
        # у аналогов общий OY ID — это норма, а не дубль
        self.assertIsNone(_key("oy_id", {"oy_id": "ID_R_000221"},
                               self.REPLACEMENT))


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


class DuplicateCheckRulesTests(SimpleTestCase):
    """Правила проверки «нет ли уже такого компонента» при заведении."""

    def rules_for(self, **values):
        """Какие правила сработают на этих значениях (запросов не делает)."""
        cleaned = {name: usable(values.get(name))
                   for _, fields in MATCH_RULES for name in fields}
        return [label for label, fields in MATCH_RULES
                if _rule_filter(fields, cleaned) is not None]

    def test_rules_are_the_ones_asked_for(self):
        self.assertEqual([label for label, _ in MATCH_RULES],
                         ["Vendor PN", "GBT PN"])

    def test_both_rules_fire_when_everything_is_filled(self):
        self.assertEqual(
            self.rules_for(vendor_pn="GRM188", vendor="Murata", gbt_pn="GBT-1"),
            ["Vendor PN", "GBT PN"])

    def test_vendor_pn_alone_is_enough(self):
        # артикул опознаёт деталь сам; производитель в ключ не входит —
        # разнобой в его написании прятал бы дубли, а не показывал
        self.assertEqual(self.rules_for(vendor_pn="GRM188"), ["Vendor PN"])

    def test_vendor_alone_does_not_trigger_a_search(self):
        # по одному производителю нашлась бы вся его номенклатура
        self.assertEqual(self.rules_for(vendor="Murata"), [])

    def test_gbt_alone_is_enough(self):
        self.assertEqual(self.rules_for(gbt_pn="GBT-1"), ["GBT PN"])

    def test_placeholders_do_not_trigger_a_search(self):
        # иначе нашлось бы всё, у чего поле тоже не заполнено
        for blank in ("---", "?", "n/a", ""):
            with self.subTest(blank=blank):
                self.assertEqual(
                    self.rules_for(vendor_pn=blank, vendor=blank, gbt_pn=blank),
                    [])

    def test_partial_placeholder_disables_only_its_rule(self):
        # заглушка в одном поле выключает только своё правило, второе
        # работает: правила однополевые, и общего у них ничего нет
        self.assertEqual(
            self.rules_for(vendor_pn="---", gbt_pn="GBT-1"), ["GBT PN"])
        self.assertEqual(
            self.rules_for(vendor_pn="GRM188", gbt_pn="---"), ["Vendor PN"])

    def test_vendor_placeholder_no_longer_disables_the_search(self):
        # раньше «---» в Vendor выключал главную проверку целиком: пара
        # считалась неполной, и дубль по артикулу проходил незамеченным
        self.assertEqual(
            self.rules_for(vendor_pn="GRM188", vendor="---"), ["Vendor PN"])


class LinkCandidateTests(SimpleTestCase):
    """Из названия задачи достаются возможные артикулы — без догадок о формате."""

    def test_longest_piece_comes_first(self):
        # длинный кусок надёжнее короткого: сначала пробуем его
        found = candidates("Создание резистора WR06X472 JTL")
        self.assertEqual(found[0], "Создание резистора WR06X472 JTL")
        self.assertIn("WR06X472 JTL", found)
        self.assertIn("WR06X472", found)

    def test_non_breaking_space_is_handled(self):
        # выгрузка трекера ставит его сплошь и рядом
        self.assertIn("MMBT3904-7-F",
                      candidates("Создание транзистора\u00a0MMBT3904-7-F"))

    def test_glued_prefix_is_split(self):
        # «ИндуктивностьWPN4020H3R3MT» — пробел потерян при вводе
        self.assertIn("WPN4020H3R3MT", candidates("ИндуктивностьWPN4020H3R3MT"))

    def test_russian_words_are_not_candidates(self):
        # в артикулах есть латиница или цифры; «Отсутствует» — это описание
        self.assertEqual(candidates("Создание соединителя Отсутствует"), [])

    def test_placeholder_task_gives_nothing(self):
        self.assertEqual(candidates("Создание соединителя ---"), [])
        self.assertEqual(candidates("Создание винта -"), [])

    def test_empty_input(self):
        self.assertEqual(candidates(""), [])
        self.assertEqual(candidates(None), [])


class LinkMatchTests(SimpleTestCase):
    """Сопоставление идёт по базе: побеждает самый длинный найденный артикул."""

    def index(self, vendor=(), gbt=()):
        def side(pns):
            return {pn.lower(): {"pn": pn, "targets": [("RESISTOR", i)]}
                    for i, pn in enumerate(pns, 1)}
        return side(vendor), side(gbt)

    def test_plain_part_number(self):
        targets, piece, rule = match("Создание транзистора MMBT3904-7-F",
                                     self.index(vendor=["MMBT3904-7-F"]))
        self.assertEqual(piece, "MMBT3904-7-F")
        self.assertEqual(rule, "Vendor PN")
        self.assertEqual(targets, [("RESISTOR", 1)])

    def test_multi_word_part_number_wins_over_its_prefix(self):
        # если в базе есть «WR06X472 JTL», берём его целиком, а не «WR06X472»
        index = self.index(vendor=["WR06X472 JTL", "WR06X472"])
        _, piece, _ = match("Создание резистора WR06X472 JTL", index)
        self.assertEqual(piece, "WR06X472 JTL")

    def test_falls_back_to_shorter_piece(self):
        index = self.index(vendor=["WR06X472"])
        _, piece, _ = match("Создание резистора WR06X472 JTL", index)
        self.assertEqual(piece, "WR06X472")

    def test_case_is_ignored(self):
        _, piece, _ = match("Создание диода bav99-7-f",
                            self.index(vendor=["BAV99-7-F"]))
        self.assertEqual(piece, "bav99-7-f")

    def test_gbt_is_the_fallback_rule(self):
        targets, piece, rule = match("Создание резистора GBT-123",
                                     self.index(gbt=["GBT-123"]))
        self.assertEqual(rule, "GBT PN")
        self.assertEqual(piece, "GBT-123")

    def test_vendor_wins_over_gbt(self):
        index = self.index(vendor=["X1"], gbt=["X1"])
        _, _, rule = match("Резистор X1", index)
        self.assertEqual(rule, "Vendor PN")

    def test_one_task_can_hit_several_records(self):
        # один артикул может стоять и в основной таблице, и в заменах
        index = ({"x1": {"pn": "X1",
                         "targets": [("RESISTOR", 1), ("z_RESISTOR", 7)]}}, {})
        targets, _, _ = match("Резистор X1", index)
        self.assertEqual(len(targets), 2)

    def test_nothing_found(self):
        targets, piece, rule = match("Создание резистора WR06X472",
                                     self.index(vendor=["ДРУГОЕ1"]))
        self.assertEqual((targets, piece, rule), ([], "", ""))


class LinkFileTests(SimpleTestCase):
    """Чтение CSV со ссылками: колонки по заголовку, кодировка угадывается."""

    def upload(self, text, encoding="utf-8-sig"):
        """Имитирует файл, пришедший из формы, — байтами."""
        return BytesIO(text.encode(encoding))

    GOOD = ("Ключ,Задача\n"
            "https://tracker/OYLIB-1,Создание транзистора MMBT3904-7-F\n"
            "https://tracker/OYLIB-2,Создание резистора WR06X472\n")

    def test_rows_are_read(self):
        rows = read_rows(self.upload(self.GOOD))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["url"], "https://tracker/OYLIB-1")
        self.assertEqual(rows[0]["title"],
                         "Создание транзистора MMBT3904-7-F")

    def test_windows_encoding_is_understood(self):
        # выгрузку часто пересохраняют в Excel под Windows
        rows = read_rows(self.upload(self.GOOD, encoding="cp1251"))
        self.assertEqual(len(rows), 2)
        self.assertIn("транзистора", rows[0]["title"])

    def test_column_order_does_not_matter(self):
        text = ("Задача,Ключ\n"
                "Создание диода BAV99-7-F,https://tracker/OYLIB-3\n")
        rows = read_rows(self.upload(text))
        self.assertEqual(rows[0]["url"], "https://tracker/OYLIB-3")

    def test_rows_without_url_or_title_are_skipped(self):
        text = ("Ключ,Задача\n"
                "https://tracker/OYLIB-1,Создание диода BAV99-7-F\n"
                ",Создание диода без ссылки\n"
                "https://tracker/OYLIB-9,\n")
        self.assertEqual(len(read_rows(self.upload(text))), 1)

    def test_missing_columns_are_reported(self):
        with self.assertRaises(LinkFileError) as caught:
            read_rows(self.upload("a,b\n1,2\n"))
        self.assertIn("Ключ", str(caught.exception))

    def test_empty_file(self):
        with self.assertRaises(LinkFileError):
            read_rows(self.upload(""))

    def test_header_without_rows(self):
        with self.assertRaises(LinkFileError):
            read_rows(self.upload("Ключ,Задача\n"))


class SuggestTests(SimpleTestCase):
    """Предположения для ненайденных: артикул тот же, записан иначе."""

    def buckets(self, *pns):
        """Подготовленные структуры подбора по «библиотеке» из этих артикулов."""
        index = ({pn.lower(): {"pn": pn, "targets": [("TRANSISTOR", i)]}
                  for i, pn in enumerate(pns, 1)}, {})
        return build_suggest_index(index)

    def test_extra_suffix_in_the_task(self):
        # «2N7002KTB_R1» в задаче против «2N7002KTB» в библиотеке
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB"))
        self.assertEqual(hints[0]["pn"], "2N7002KTB")
        self.assertEqual(hints[0]["reason"], "в задаче лишний суффикс")

    def test_different_separators(self):
        hints = suggest("Создание транзистора MMBT3904 7 F",
                        self.buckets("MMBT3904-7-F"))
        self.assertEqual(hints[0]["pn"], "MMBT3904-7-F")
        self.assertEqual(hints[0]["reason"],
                         "запись отличается только разделителями")

    def test_library_part_number_is_longer(self):
        hints = suggest("Создание микросхемы LM5066IPMHE",
                        self.buckets("LM5066IPMHE/NOPB"))
        self.assertEqual(hints[0]["pn"], "LM5066IPMHE/NOPB")

    def test_original_spelling_is_kept(self):
        # подсказка показывает артикул так, как он в базе, а не ключом
        hints = suggest("Создание диода bav99-7-f", self.buckets("BAV99-7-F"))
        self.assertEqual(hints[0]["pn"], "BAV99-7-F")

    def test_nothing_similar(self):
        self.assertEqual(suggest("Создание соединителя ZZZZ99999",
                                 self.buckets("2N7002KTB")), [])

    def test_most_likely_comes_first(self):
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB", "2N7002KT", "2N7002"))
        self.assertEqual(hints[0]["pn"], "2N7002KTB")

    def test_limit_is_respected(self):
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB", "2N7002KT", "2N7002K",
                                     "2N7002"),
                        limit=2)
        self.assertLessEqual(len(hints), 2)

    def test_task_without_a_part_number(self):
        self.assertEqual(suggest("Создание винта -", self.buckets("2N7002KTB")),
                         [])

    def test_typo_is_still_caught(self):
        # последний символ другой — точных правил не хватит, работает
        # нестрогое сравнение
        hints = suggest("Создание диода BAV99-7-X", self.buckets("BAV99-7-F"))
        self.assertTrue(hints)
        self.assertEqual(hints[0]["pn"], "BAV99-7-F")

    def test_suggestion_links_to_the_card(self):
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB"))
        self.assertTrue(hints[0]["url"].endswith("/1/"))

    def test_suggestion_carries_what_the_button_needs(self):
        # кнопка «Добавить» шлёт таблицу и ключ — без них ссылку не завести
        hint = suggest("Создание транзистора 2N7002KTB_R1",
                       self.buckets("2N7002KTB"))[0]
        self.assertEqual(hint["table"], "TRANSISTOR")
        self.assertEqual(hint["pk"], 1)


class SkipExistingTests(SimpleTestCase):
    """Повторная загрузка не показывает то, что уже заведено.

    Тесты не ходят в базу: список уже заведённых ссылок подставляется
    вместо запроса, а проверяется само правило раскладки строк.
    """

    INDEX = ({"2n7002ktb": {"pn": "2N7002KTB",
                            "targets": [("TRANSISTOR", 1)]},
              "bav99-7-f": {"pn": "BAV99-7-F",
                            "targets": [("DIODE", 2)]}}, {})

    ROWS = [
        {"url": "https://t/1", "title": "Создание транзистора 2N7002KTB"},
        {"url": "https://t/2", "title": "Создание диода BAV99-7-F"},
        {"url": "https://t/3", "title": "Создание транзистора 2N7002KTB_R1"},
    ]

    def resolve(self, existing, rows=None, index=None):
        """Раскладка строк при заданном наборе уже существующих ссылок."""
        pairs = set(existing)
        urls = {url for url, _, _ in pairs}
        with mock.patch.object(links_module, "_existing_links",
                               return_value=(pairs, urls)):
            return links_module.resolve_rows(rows or self.ROWS,
                                             index or self.INDEX)

    def test_nothing_is_hidden_on_the_first_import(self):
        matched, unmatched, already = self.resolve([])
        self.assertEqual(len(matched), 2)
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(already, [])

    def test_written_rows_disappear_on_reimport(self):
        matched, unmatched, already = self.resolve([
            ("https://t/1", "TRANSISTOR", 1), ("https://t/2", "DIODE", 2)])
        self.assertEqual(matched, [])
        self.assertEqual(len(already), 2)
        # осталась только та строка, с которой ещё нужно разобраться
        self.assertEqual([row["title"] for row in unmatched],
                         ["Создание транзистора 2N7002KTB_R1"])

    def test_suggestion_confirmed_by_hand_also_disappears(self):
        # кнопка «Добавить» рядом с предположением ставит ссылку на
        # компонент, чей артикул с задачей точно не совпал
        _, unmatched, already = self.resolve([
            ("https://t/3", "TRANSISTOR", 1)])
        self.assertEqual(unmatched, [])
        self.assertEqual(len(already), 1)

    def test_row_stays_until_every_record_is_linked(self):
        # один артикул может стоять в основной таблице и в заменах;
        # пока связана не каждая, работа не закончена
        index = ({"2n7002ktb": {"pn": "2N7002KTB",
                                "targets": [("TRANSISTOR", 1),
                                            ("z_TRANSISTOR", 9)]}}, {})
        matched, _, already = self.resolve(
            [("https://t/1", "TRANSISTOR", 1)], rows=[self.ROWS[0]],
            index=index)
        self.assertEqual(len(matched), 1)
        self.assertEqual(already, [])

    def test_skipping_can_be_turned_off(self):
        matched, unmatched, already = links_module.resolve_rows(
            self.ROWS, self.INDEX, skip_existing=False)
        self.assertEqual(already, [])
        self.assertEqual(len(matched) + len(unmatched), 3)


class HistoryDiffTests(SimpleTestCase):
    """История правок: что считается изменением, а что нет.

    Модель здесь поддельная — сравнение работает с любым объектом, у
    которого есть ``_meta.fields``, и настоящая таблица компонентов для
    проверки не нужна.
    """

    class Field:
        def __init__(self, name, verbose):
            self.name, self.verbose_name = name, verbose

    class Fake:
        def __init__(self, **values):
            for field in HistoryDiffTests.FIELDS:
                setattr(self, field.name, values.get(field.name))

    FIELDS = [Field("id", "id"), Field("vendor_pn", "Vendor PN"),
              Field("value", "Value"), Field("created", "Created"),
              Field("notice", "Notice")]

    def setUp(self):
        meta = type("Meta", (), {"fields": self.FIELDS})()
        self.Fake._meta = meta

    def changed(self, before, after):
        return {item["field"]: (item["old"], item["new"])
                for item in diff(snapshot(before), snapshot(after), self.Fake)}

    def test_changed_field_is_recorded_with_both_values(self):
        result = self.changed(self.Fake(vendor_pn="WR06"),
                              self.Fake(vendor_pn="WR06X"))
        self.assertEqual(result, {"vendor_pn": ("WR06", "WR06X")})

    def test_untouched_fields_are_not_recorded(self):
        result = self.changed(self.Fake(vendor_pn="WR06", value="10k"),
                              self.Fake(vendor_pn="WR06X", value="10k"))
        self.assertNotIn("value", result)

    def test_empty_becoming_placeholder_is_not_a_change(self):
        # при сохранении пустые поля превращаются в «---»: для человека
        # ничего не изменилось, и в историю это попадать не должно
        result = self.changed(self.Fake(value=""), self.Fake(value="---"))
        self.assertEqual(result, {})

    def test_placeholder_replaced_by_value_is_a_change(self):
        result = self.changed(self.Fake(value="?"), self.Fake(value="4.7k"))
        self.assertEqual(result, {"value": ("", "4.7k")})

    def test_id_and_created_are_never_recorded(self):
        self.assertNotIn("id", snapshot(self.Fake()))
        self.assertNotIn("created", snapshot(self.Fake()))

    def test_creation_shows_filled_fields_as_new(self):
        result = {item["field"]: (item["old"], item["new"])
                  for item in diff({}, snapshot(self.Fake(vendor_pn="NEW-PN")),
                                   self.Fake)}
        self.assertEqual(result, {"vendor_pn": ("", "NEW-PN")})

    def test_fields_keep_model_order(self):
        before = self.Fake(notice="a", vendor_pn="b", value="c")
        after = self.Fake(notice="A", vendor_pn="B", value="C")
        names = [item["field"]
                 for item in diff(snapshot(before), snapshot(after), self.Fake)]
        self.assertEqual(names, ["vendor_pn", "value", "notice"])

    def test_label_comes_from_the_model(self):
        changed = diff(snapshot(self.Fake(vendor_pn="A")),
                       snapshot(self.Fake(vendor_pn="B")), self.Fake)
        self.assertEqual(changed[0]["label"], "Vendor PN")


class SampleInitialTests(SimpleTestCase):
    """«Добавить по образцу»: что переносится в новую форму, а что нет."""

    # поддельная модель: в ней должно быть каждое поле из NOT_COPIED —
    # иначе «не перенеслось» и «в модели такого нет» неразличимы, и
    # добавленное в список поле тест молча пропустит
    FIELDS = ("id", "vendor_pn", "vendor", "oy_pn", "oy_id", "gbt_pn",
              "tracker_url", "group", "package", "value", "datasheet",
              "author", "created", "notice")

    class Field:
        def __init__(self, name):
            self.name = name

    class Fake:
        def __init__(self, **values):
            for name in SampleInitialTests.FIELDS:
                setattr(self, name, values.get(name, f"<{name}>"))

    def setUp(self):
        self.Fake._meta = type("Meta", (), {
            "fields": [self.Field(name) for name in self.FIELDS]})()

    def test_identity_fields_are_not_copied(self):
        # скопировать их значило бы завести дубль, а образец нужен ровно
        # для обратного — для похожей, но другой детали
        initial = sample_initial(self.Fake())
        for name in ("vendor_pn", "vendor", "gbt_pn", "oy_id", "tracker_url"):
            self.assertNotIn(name, initial)

    def test_datasheet_is_not_copied(self):
        # документация у каждого артикула своя: перенесённая ссылка вела бы
        # не на тот файл, а такую ошибку заметить труднее, чем пустое поле
        self.assertNotIn("datasheet", sample_initial(self.Fake()))

    def test_service_fields_are_not_copied(self):
        initial = sample_initial(self.Fake())
        for name in ("id", "author", "created"):
            self.assertNotIn(name, initial)

    def test_parameters_are_copied(self):
        initial = sample_initial(self.Fake(group="CAPACITOR", value="10n"))
        self.assertEqual(initial["group"], "CAPACITOR")
        self.assertEqual(initial["value"], "10n")

    def test_every_excluded_field_exists_in_the_fake(self):
        # страховка для теста ниже: сравнивать состав можно, только если
        # поддельная модель знает все поля, которые не переносятся
        self.assertEqual(set(NOT_COPIED) - set(self.FIELDS), set())

    def test_nothing_else_is_dropped(self):
        initial = sample_initial(self.Fake())
        skipped = set(self.FIELDS) - set(initial)
        self.assertEqual(skipped, set(NOT_COPIED))


class AuthorFilterTests(SimpleTestCase):
    """Список сотрудников в фильтре журнала — по одному разу каждый.

    Запрос строится, но не выполняется: проверяется его форма, а не данные.
    Этого достаточно — ошибка была именно в форме запроса.
    """

    def test_duplicates_are_removed_by_the_database(self):
        self.assertTrue(author_logins().query.distinct)

    def test_default_ordering_does_not_leak_into_the_query(self):
        # Ровно эта утечка и давала сотрудника столько раз, сколько правок
        # он сделал: поля сортировки журнала попадали в запрос рядом с
        # автором, и строки с разным временем правки становились разными
        query = author_logins().query
        self.assertFalse(query.default_ordering)
        self.assertEqual(query.order_by, ())

    def test_only_the_login_is_selected(self):
        self.assertEqual(author_logins().query.values_select, ("author",))


class StepUploadFormTests(SimpleTestCase):
    """Проверка присланного STEP-файла — до чтения содержимого.

    Разбирать файл, чтобы потом отклонить его по размеру, незачем: рендер
    дорогой, а отказ дешёвый.
    """

    class FakeUpload:
        def __init__(self, name, size):
            self.name = name
            self.size = size

    def form(self, upload=None, drop=False):
        data = {"step-drop_image": "on"} if drop else {}
        files = {"step-step_file": upload} if upload else {}
        return StepImageForm(data, files)

    def test_empty_submission_asks_for_a_file(self):
        # на отдельной странице пустая отправка — скорее забытый файл, чем
        # «ничего не меняем»: молча вернуть в карточку значило бы дать
        # понять, что картинка загрузилась
        form = self.form()
        self.assertFalse(form.is_valid())
        self.assertIn("Выберите STEP-файл", form.non_field_errors())

    def test_delete_alone_is_enough(self):
        self.assertTrue(self.form(drop=True).is_valid())

    def test_wrong_extension_is_rejected(self):
        with self.assertRaises(ValidationError):
            step.check(self.FakeUpload("model.sldprt", 1024))

    def test_stp_is_accepted(self):
        # у STEP два расширения, и .stp встречается не реже
        step.check(self.FakeUpload("MODEL.STP", 1024))

    def test_oversized_file_is_rejected(self):
        with self.assertRaises(ValidationError):
            step.check(self.FakeUpload("model.step", step.MAX_BYTES + 1))

    def test_upload_and_delete_together_make_no_sense(self):
        form = StepImageForm({"step-drop_image": "on"},
                             {"step-step_file": self.FakeUpload("m.step", 10)})
        self.assertFalse(form.is_valid())


class StepImagePathTests(SimpleTestCase):
    """Куда ложится файл картинки посадочного места.

    Одна папка на всю библиотеку и один файл на посадочное место. Имя
    STEP-файла в путь не идёт: у трёх деталей подряд он называется
    `part.step`.
    """

    class FakeImage:
        footprint = "SODFL100X250X050"
        key = "sodfl100x250x050"

    def test_name_comes_from_the_footprint(self):
        self.assertEqual(step.upload_path(self.FakeImage(), "render.png"),
                         "footprint_images/SODFL100X250X050.png")

    def test_footprint_cannot_escape_the_directory(self):
        image = self.FakeImage()
        image.footprint = "../../etc/passwd"
        self.assertEqual(step.upload_path(image, "render.png"),
                         "footprint_images/etc-passwd.png")

    def test_different_footprints_stay_different_files(self):
        # посторонние знаки заменяются, а не выбрасываются: иначе
        # «SOT/23» и «SOT23» дали бы один файл на два разных места
        self.assertNotEqual(step.safe_stem("SOT/23"), step.safe_stem("SOT23"))


class FootprintKeyTests(SimpleTestCase):
    """Ключ, по которому компонент находит картинку своего места.

    Записи заводили разные люди и разные программы, и одно место в
    библиотеке встречается в разном написании. Картинка должна находиться
    по любому из них.
    """

    def test_case_and_spaces_do_not_matter(self):
        self.assertEqual(step.normalize_footprint("  SODFL100X250X050 "),
                         step.normalize_footprint("sodfl100x250x050"))

    def test_different_footprints_stay_different(self):
        self.assertNotEqual(step.normalize_footprint("SODFL100X250X050"),
                            step.normalize_footprint("SODFL100X250X060"))

    def test_empty_value_gives_an_empty_key(self):
        # у замен колонки нет вовсе, и в базе встречаются None и ""
        self.assertEqual(step.normalize_footprint(None), "")
        self.assertEqual(step.normalize_footprint("  "), "")


class StepRenderAvailabilityTests(SimpleTestCase):
    """Без установленных пакетов рендер отвечает понятным отказом.

    Это основной режим работы: в образ OCP не входит. Падать импортом на
    старте или пятистами строками трассировки при загрузке файла система
    не должна.
    """

    def test_missing_libraries_give_a_readable_error(self):
        try:
            import OCP  # noqa: F401
        except ImportError:
            pass
        else:
            self.skipTest("OCP установлен — проверять нечего")

        with self.assertRaises(step.StepRenderError) as caught:
            step.render_file("model.step")
        self.assertIn("не запускается", str(caught.exception))


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


class StepBatchMatchingTests(SimpleTestCase):
    """Пакетная загрузка: модель находит посадочное место по имени файла.

    Ничего умнее точного совпадения тут намеренно нет: картинка чужого
    посадочного места выглядит как правильная, и заметить подмену можно,
    только открыв модель.
    """

    def test_command_matches_like_the_card(self):
        # команда и карточка сравнивают одним правилом — иначе модель
        # записалась бы под ключом, по которому карточка её не найдёт
        self.assertIs(normalize, step.normalize_footprint)

    def make_dir(self, *names):
        import tempfile

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        for name in names:
            (directory / name).write_text("")
        return directory

    def test_only_step_files_are_taken(self):
        found, _ = models_in(self.make_dir("a.step", "b.stp", "readme.txt",
                                           "c.sldprt"))
        self.assertEqual(set(found), {"a", "b"})

    def test_same_name_twice_is_reported_not_guessed(self):
        # SLP2510P8.step и SLP2510P8.stp: какой из них правильный, знает
        # конструктор, а не команда
        found, duplicates = models_in(self.make_dir("m.step", "m.stp"))
        self.assertEqual(set(found), {"m"})
        self.assertEqual([path.name for path in duplicates], ["m.stp"])


class FieldFormatTests(SimpleTestCase):
    """Проверки формата полей формы компонента."""

    def check(self, name, value):
        FIELD_VALIDATORS[name](value)

    def test_ordinary_part_numbers_pass(self):
        for value in ("GRM155R61A104KA01D", "ID_V_000006", "L02U5V0NA-4C",
                      "12345678"):
            with self.subTest(value=value):
                self.check("gbt_pn", value)

    def test_cyrillic_lookalike_is_rejected(self):
        # «С» кириллическая: на вид не отличить, но поиск её не найдёт, и
        # на месте этой записи заведут вторую
        with self.assertRaises(ValidationError):
            self.check("oy_pn", "С0805")

    def test_placeholders_pass_untouched(self):
        # в большинстве записей тут «---», и требовать исправить поле,
        # которого человек не трогал, неправильно
        for blank in ("---", "?", "", "n/a"):
            with self.subTest(blank=blank):
                self.check("oy_id", blank)

    def test_every_article_field_is_checked(self):
        for name in ARTICLE_FIELDS:
            self.assertIn(name, FIELD_VALIDATORS)

    def test_allegro_rules_are_still_stricter(self):
        # у посадочного места набор уже: скобки и пробелы там не нужны
        with self.assertRaises(ValidationError):
            self.check("allegro_pcb_footprint", "CAP (0.1 uF)")


class TrackerUrlTests(SimpleTestCase):
    """Ссылка на задачу в трекере — адрес, и проверяется как адрес."""

    def test_full_address_passes(self):
        URL_VALIDATOR("https://tracker.yandex.ru/OYLIB-113")

    def test_bare_number_is_rejected(self):
        with self.assertRaises(ValidationError):
            URL_VALIDATOR("OYLIB-113")

    def test_placeholder_passes(self):
        URL_VALIDATOR("---")

    def test_the_field_is_the_tracker_one(self):
        self.assertEqual(URL_FIELDS, ("tracker_url",))


class RequiredMessageTests(SimpleTestCase):
    """Сообщение об обязательном поле не называет само поле.

    Подпись стоит рядом с полем, а в сводке ошибок её подставляет шаблон.
    Если бы текст повторял её сам, в сводке выходило бы «Description:
    заполните «Description»».
    """

    def test_message_does_not_repeat_the_label(self):
        for name in ("Description", "Vendor PN", "«"):
            self.assertNotIn(name, REQUIRED_MESSAGE.replace("«---»", ""))

    def test_message_covers_both_cases(self):
        # пустое поле и заглушка для того, кто потом ищет компонент, —
        # одно и то же, и текст у них общий
        self.assertIn("---", REQUIRED_MESSAGE)

    def test_required_fields_are_the_identifying_ones(self):
        self.assertEqual(REQUIRED_FIELDS, ("vendor_pn", "description"))


class SchemaGuardTests(SimpleTestCase):
    """migrate не заводит второй набор таблиц мимо своей схемы.

    Если схему Django переименовали, а POSTGRES_SCHEMA оставили прежним,
    migrate увидел бы чистую базу и завёл рядом пустые таблицы. Проверка
    перед миграциями такое останавливает.
    """

    def run_guard(self, homes, path):
        from .schema_guard import check_before_migrate

        with mock.patch("components.schema_guard.django_home",
                        return_value=(homes, path)):
            check_before_migrate(sender=None)

    def test_tables_outside_the_path_stop_migrate(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as caught:
            self.run_guard(["oy_system"], ["public"])
        # сообщение называет, где таблицы на самом деле
        self.assertIn("oy_system", str(caught.exception))

    def test_tables_in_the_path_pass(self):
        self.run_guard(["sculptor"], ["sculptor", "public"])

    def test_fresh_database_passes(self):
        # таблиц нет нигде — это первая установка, мешать ей нечем
        self.run_guard([], ["sculptor", "public"])

    def test_guard_is_connected(self):
        from django.apps import apps
        from django.db.models.signals import pre_migrate

        self.assertTrue(pre_migrate.has_listeners(
            sender=apps.get_app_config("components")))


class StepQueueTests(SimpleTestCase):
    """Каталог, где STEP-модели ждут воркера."""

    class FakeUpload:
        def __init__(self, data=b"ISO-10303-21;"):
            self.data = data

        def seek(self, position):
            pass

        def chunks(self):
            yield self.data

    def setUp(self):
        import tempfile

        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)

    def test_name_cannot_escape_the_queue(self):
        # имя приходит из записи в базе и не должно уводить из каталога,
        # даже если запись испорчена
        with self.settings(STEP_QUEUE_DIR=self.directory):
            self.assertEqual(step.queue_path("../../etc/passwd"),
                             self.directory / "passwd")

    def test_saved_file_gets_a_fresh_name(self):
        # две модели «part.step» подряд не должны затирать друг друга,
        # пока ждут воркера
        with self.settings(STEP_QUEUE_DIR=self.directory):
            first = step.save_to_queue(self.FakeUpload())
            second = step.save_to_queue(self.FakeUpload())
            self.assertNotEqual(first, second)
            self.assertEqual(step.queue_path(first).read_bytes(),
                             b"ISO-10303-21;")

    def test_queue_is_created_on_demand(self):
        nested = self.directory / "not" / "yet"
        with self.settings(STEP_QUEUE_DIR=nested):
            step.save_to_queue(self.FakeUpload())
        self.assertTrue(nested.is_dir())


class StepRenderJobTests(SimpleTestCase):
    """Заявка на рендер: что видит человек, пока картинка готовится."""

    def job(self, status, minutes_ago):
        import datetime as dt

        from django.utils import timezone

        from .models import StepRenderJob

        job = StepRenderJob(status=status)
        job.created = timezone.now() - dt.timedelta(minutes=minutes_ago)
        return job

    def test_fresh_queued_job_is_not_stuck(self):
        self.assertFalse(self.job("queued", 1).looks_stuck())

    def test_long_queued_job_looks_stuck(self):
        # обычно это значит, что воркер не запущен — и карточка должна
        # сказать об этом, а не показывать «готовится» бесконечно
        self.assertTrue(self.job("queued", 30).looks_stuck())

    def test_running_job_is_never_stuck(self):
        # её уже взяли; долгий рендер — не повод говорить о воркере
        self.assertFalse(self.job("running", 30).looks_stuck())

    def test_long_running_job_looks_crashed(self):
        # OpenCascade на битом файле роняет процесс целиком, и закрыть
        # заявку становится некому — карточка должна сказать об этом
        self.assertTrue(self.job("running", 30).looks_crashed())

    def test_fresh_running_job_is_not_crashed(self):
        self.assertFalse(self.job("running", 1).looks_crashed())

    def test_active_states(self):
        for status, active in (("queued", True), ("running", True),
                               ("done", False), ("failed", False),
                               ("superseded", False)):
            with self.subTest(status=status):
                self.assertIs(self.job(status, 0).is_active, active)


class RenderTaskTests(SimpleTestCase):
    """Рендер описан задачей фреймворка, а не функцией, зовущейся из вида.

    Тогда исполнитель выбирается настройкой: в запросе или отдельным
    воркером, — а код задачи один.
    """

    def test_render_is_a_task(self):
        from django.tasks import Task

        from .tasks import render_footprint_image

        self.assertIsInstance(render_footprint_image, Task)

    def test_task_goes_to_the_default_queue(self):
        # у бэкенда в базе очереди перечислены в настройках, и задача в
        # неизвестной очереди просто не будет принята
        from .tasks import render_footprint_image

        self.assertEqual(render_footprint_image.queue_name, "default")
        self.assertEqual(render_footprint_image.name, "render_footprint_image")


class RenderDispatchTests(SimpleTestCase):
    """Куда уходит заявка: в очередь воркера или в отдельный процесс.

    Главное здесь — чего не происходит: рендер никогда не идёт внутри
    запроса. Встроенный бэкенд задач выполнил бы его прямо там, и сайт
    стоял бы, пока модель рисуется.
    """

    def test_default_backend_would_run_in_the_request(self):
        from .tasks import runs_in_request

        self.assertTrue(runs_in_request())

    def test_without_a_worker_render_goes_to_a_process(self):
        from . import tasks

        with mock.patch.object(tasks, "runs_in_request", return_value=True), \
                mock.patch.object(tasks, "_spawn_render") as spawn, \
                mock.patch.object(tasks, "render_footprint_image") as queued:
            tasks.dispatch_render(7)
        spawn.assert_called_once_with(7)
        queued.enqueue.assert_not_called()

    def test_with_a_worker_render_goes_to_the_queue(self):
        from . import tasks

        with mock.patch.object(tasks, "runs_in_request", return_value=False), \
                mock.patch.object(tasks, "_spawn_render") as spawn, \
                mock.patch.object(tasks, "render_footprint_image") as queued:
            tasks.dispatch_render(7)
        queued.enqueue.assert_called_once_with(job_id=7)
        spawn.assert_not_called()

    def test_process_runs_the_render_command(self):
        import tempfile

        from . import tasks

        directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, directory)
        with self.settings(STEP_QUEUE_DIR=directory), \
                mock.patch.object(tasks.subprocess, "Popen") as popen:
            tasks._spawn_render(42)

        command = popen.call_args.args[0]
        self.assertEqual(command[-2:], ["render_job", "42"])
        # процесс не ждут: вызов вернулся, а результат вида не зависит от
        # того, сколько рисуется модель
        popen.return_value.wait.assert_not_called()
        self.assertTrue((directory / "render.log").exists())
