"""Сайт целиком: закрытость, вход, шаблоны, HTMX, версия, база."""

import re
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from django import forms
from django.conf import settings
from django.db import DatabaseError
from django.shortcuts import resolve_url
from django.template import Context, Template
from django.test import SimpleTestCase
from django.urls import resolve, reverse

from ..db import fallback, unavailable


@contextmanager
def _nothing():
    yield


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



class UserModelTests(SimpleTestCase):
    """Своя модель пользователя встаёт на таблицы стандартного.

    Переезд существующей базы (sql/move_user_to_users.sql) — это
    переименование таблиц, и имена, которые он даёт, должны совпадать с
    теми, что ждёт модель. Разойдись они — после переезда Django искал бы
    таблицы, которых нет.
    """

    def test_project_uses_its_own_user(self):
        from django.contrib.auth import get_user_model

        self.assertEqual(settings.AUTH_USER_MODEL, "users.User")
        self.assertEqual(get_user_model()._meta.label, "users.User")

    def test_tables_match_the_migration_script(self):
        from django.contrib.auth import get_user_model

        user = get_user_model()
        self.assertEqual(user._meta.db_table, "users_user")
        self.assertEqual(user.groups.through._meta.db_table,
                         "users_user_groups")
        self.assertEqual(user.user_permissions.through._meta.db_table,
                         "users_user_user_permissions")

    def test_key_is_a_plain_integer(self):
        # как у стандартного пользователя: с BigAutoField Django решил бы
        # расширить колонку существующей таблицы
        from django.contrib.auth import get_user_model
        from django.db import models

        pk = get_user_model()._meta.pk
        self.assertIsInstance(pk, models.AutoField)
        self.assertNotIsInstance(pk, models.BigAutoField)

    def test_roles_live_with_users(self):
        from users import roles

        self.assertTrue(roles.ROLES)



class HtmxMiddlewareTests(SimpleTestCase):
    """Запросы за куском страницы (config/htmx.py)."""

    def run_middleware(self, response, htmx=True):
        from django.test import RequestFactory

        from config.htmx import HtmxMiddleware

        headers = {"HTTP_HX_REQUEST": "true"} if htmx else {}
        request = RequestFactory().get("/", **headers)
        result = HtmxMiddleware(lambda req: response)(request)
        return request, result

    def test_request_is_marked(self):
        from django.http import HttpResponse

        request, _ = self.run_middleware(HttpResponse("ok"))
        self.assertTrue(request.htmx)
        request, _ = self.run_middleware(HttpResponse("ok"), htmx=False)
        self.assertFalse(request.htmx)

    def test_redirect_becomes_a_full_page_jump(self):
        # истёкшая сессия: без подмены HTMX вставил бы страницу входа
        # внутрь таблицы
        from django.http import HttpResponseRedirect

        _, response = self.run_middleware(HttpResponseRedirect("/login/?next=/"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["HX-Redirect"], "/login/?next=/")

    def test_ordinary_redirect_is_left_alone(self):
        from django.http import HttpResponseRedirect

        _, response = self.run_middleware(HttpResponseRedirect("/x/"),
                                          htmx=False)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response.has_header("HX-Redirect"))

    def test_response_varies_by_htmx_header(self):
        # один адрес отдаёт то страницу, то фрагмент — кэш должен это знать
        from django.http import HttpResponse

        _, response = self.run_middleware(HttpResponse("ok"), htmx=False)
        self.assertIn("HX-Request", response["Vary"])

    def test_middleware_wraps_the_login_check(self):
        # выше по списку — значит, видит перенаправление на вход
        chain = settings.MIDDLEWARE
        self.assertLess(chain.index("config.htmx.HtmxMiddleware"),
                        chain.index("django.contrib.auth.middleware.LoginRequiredMiddleware"))



class HtmxTemplateTests(SimpleTestCase):
    """Фрагменты, которые отдаются на запросы HTMX."""

    def job(self, status="queued", minutes_ago=0):
        import datetime as dt

        from django.utils import timezone

        from ..models import StepRenderJob

        job = StepRenderJob(pk=5, status=status, source_name="SOT-23.step")
        job.created = timezone.now() - dt.timedelta(minutes=minutes_ago)
        return job

    def render_job(self, job, htmx_enabled=True, show_failures=False):
        from django.template.loader import render_to_string

        return render_to_string("components/_render_job.html", {
            "job": job, "htmx_enabled": htmx_enabled,
            "show_failures": show_failures})

    def test_list_panel_fragment_exists(self):
        # вид отдаёт его на запрос HTMX; пропади фрагмент из шаблона —
        # список сломался бы только у тех, у кого HTMX включён
        from django.template.loader import get_template

        get_template("components/list.html#panel")

    def test_filters_are_refreshed_with_the_table(self):
        # фильтры сужают друг друга: обнови HTMX одну таблицу — в списках
        # остались бы варианты первой загрузки страницы
        from django.template.loader import get_template

        source = get_template("components/list.html").template.source
        start = source.index("{% partialdef panel")
        end = source.index("{% endpartialdef")
        self.assertIn('id="list-filters"', source[start:end])

    def test_paging_replaces_rows_only(self):
        # переход по страницам не трогает ни форму, ни заголовки колонок:
        # форма от пересборки «прыгала», а заголовки мигали
        from django.template.loader import get_template

        source = get_template("components/list.html").template.source
        pager = source[source.index('id="list-pager"'):]
        pager = pager[:pager.index(">")]
        self.assertIn('hx-target="#list-rows"', pager)
        self.assertIn('hx-select-oob="#list-pager"', pager)
        self.assertIn('<tbody id="list-rows">', source)

    def test_active_job_polls_itself(self):
        html = self.render_job(self.job())
        self.assertIn('hx-trigger="every 3s"', html)
        self.assertIn("/render-jobs/5/", html)

    def test_without_htmx_the_block_asks_to_reload(self):
        html = self.render_job(self.job(), htmx_enabled=False)
        self.assertNotIn("hx-get", html)
        self.assertIn("Обновите страницу", html)

    def test_crashed_render_is_not_polled(self):
        # упавший рендер уже не закончится — спрашивать о нём незачем
        html = self.render_job(self.job("running", minutes_ago=30))
        self.assertNotIn("hx-get", html)

    def test_wrapper_stays_when_there_is_nothing_to_say(self):
        # HTMX заменяет блок по id: исчезни обёртка — следующему ответу
        # некуда было бы лечь
        html = self.render_job(self.job("failed"), show_failures=False)
        self.assertIn('id="render-job"', html)



class VersionTests(SimpleTestCase):
    """Версия задаётся в одном месте и доходит до шапки."""

    def test_version_is_semantic(self):
        from config import __version__

        self.assertRegex(__version__, r"^\d+\.\d+\.\d+$")

    def test_header_gets_the_same_version(self):
        from config import __version__

        from ..context_processors import version

        self.assertEqual(version(None)["app_version"], __version__)

    def test_changelog_describes_the_current_version(self):
        # версию подняли, а в журнал не записали — так и расходятся
        from config import __version__

        changelog = (Path(settings.BASE_DIR) / "CHANGELOG.md").read_text(
            encoding="utf-8")
        self.assertIn(f"## {__version__}", changelog)



class SchemaGuardTests(SimpleTestCase):
    """migrate не заводит второй набор таблиц мимо своей схемы.

    Если схему Django переименовали, а POSTGRES_SCHEMA оставили прежним,
    migrate увидел бы чистую базу и завёл рядом пустые таблицы. Проверка
    перед миграциями такое останавливает.
    """

    def run_guard(self, homes, path):
        from ..schema_guard import check_before_migrate

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



class PluralTests(SimpleTestCase):
    """Счётчики на страницах: «1 запись», «3 записи», «11 записей»."""

    FORMS = "запись,записи,записей"

    def word(self, number):
        from ..templatetags.components_extras import plural
        return plural(number, self.FORMS)

    def test_forms(self):
        cases = {0: "записей", 1: "запись", 2: "записи", 4: "записи",
                 5: "записей", 11: "записей", 14: "записей", 21: "запись",
                 22: "записи", 111: "записей", 152: "записи", 1001: "запись"}
        for number, word in cases.items():
            with self.subTest(number=number):
                self.assertEqual(self.word(number), f"{number} {word}")

    def test_not_a_number_does_not_break_the_page(self):
        self.assertEqual(self.word(""), " записей")
