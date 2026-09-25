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
        for url in ("/", "/boards/", "/servers/", "/components/",
                    "/components/changes/", "/components/search/",
                    # старый адрес: его переадресация тоже за входом
                    "/resistor/1435/",
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

        for url in ("/boards/", "/servers/", "/components/changes/",
                    "/", "/resistor/1435/", "/media/boards/example.jpg"):
            with self.subTest(url=url, open=False):
                view = resolve(url).func
                self.assertIs(getattr(view, "login_required", True), True)



class SectionUrlTests(SimpleTestCase):
    """Разделы под своими префиксами; старые адреса компонентов живы."""

    def test_components_live_under_their_prefix(self):
        self.assertEqual(reverse("components:dashboard"), "/components/")
        self.assertEqual(reverse("components:list", args=["resistor"]),
                         "/components/resistor/")
        self.assertEqual(reverse("components:detail", args=["resistor", 1435]),
                         "/components/resistor/1435/")
        self.assertEqual(reverse("components:search"), "/components/search/")

    def test_root_leads_to_the_library(self):
        self.assertEqual(resolve("/").url_name, "home")

    def test_old_addresses_find_their_new_place(self):
        from config.legacy import legacy_target

        cases = {
            "resistor/1435/": "/components/resistor/1435/",
            "resistor/1435/edit/": "/components/resistor/1435/edit/",
            "changes/": "/components/changes/",
            # без косой черты в конце — как набирают руками
            "resistor": "/components/resistor/",
            "boards": "/boards/",
            # уже новый адрес: дописать черту, а не искать группу «components»
            "components/resistor": "/components/resistor/",
        }
        for old, new in cases.items():
            with self.subTest(old=old):
                self.assertEqual(legacy_target(old), new)

    def test_unknown_address_is_not_redirected(self):
        from config.legacy import legacy_target

        self.assertIsNone(legacy_target("no/such/deep/path/here/"))
        self.assertIsNone(legacy_target("components/no/such/deep/path/"))

    def test_redirect_keeps_the_query(self):
        # ссылку на поиск и на отфильтрованный список присылают друг другу
        from django.test import RequestFactory

        from config.legacy import legacy_redirect

        request = RequestFactory().get("/search/?q=RC0402&page=2")
        response = legacy_redirect(request, "search/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "/components/search/?q=RC0402&page=2")

    def test_forms_are_not_redirected(self):
        # данные формы после переадресации пропали бы молча
        from django.http import Http404
        from django.test import RequestFactory

        from config.legacy import legacy_redirect

        request = RequestFactory().post("/resistor/new/")
        with self.assertRaises(Http404):
            legacy_redirect(request, "resistor/new/")


class SiteMenuTests(SimpleTestCase):
    """Меню разделов в шапке (base.html, #site-menu)."""

    def render(self, path, admin=False, editor=False):
        from django.contrib.auth.models import AnonymousUser
        from django.template.loader import render_to_string
        from django.test import RequestFactory

        request = RequestFactory().get(path)
        request.user = AnonymousUser()
        request.resolver_match = resolve(path)
        with mock.patch("components.context_processors.is_admin",
                        return_value=admin),                 mock.patch("components.context_processors.can_edit_components",
                           return_value=editor):
            return render_to_string("components/base.html", request=request)

    def rail(self, html):
        start = html.index('class="rail"')
        return html[start:html.index("</nav>", start)]

    def menu(self, html):
        start = html.index('id="site-menu"')
        return html[start:html.index("</nav>", start)]

    def test_button_opens_the_menu(self):
        html = self.render("/boards/")
        self.assertIn('popovertarget="site-menu"', html)
        self.assertRegex(html, r'<nav[^>]*id="site-menu"[^>]*popover')

    def test_menu_lists_the_sections(self):
        menu = self.menu(self.render("/boards/", admin=True))
        for name, url in (("SERVERS", "/servers/"), ("BOARDS", "/boards/"),
                          ("COMPONENTS", "/components/"),
                          ("USERS", reverse("users:roles"))):
            with self.subTest(section=name):
                self.assertIn(name, menu)
                self.assertIn(f'href="{url}"', menu)

    def test_users_only_for_admin(self):
        # раздел закрыт @admin_only: остальным пункт вёл бы на отказ
        self.assertNotIn("USERS", self.menu(self.render("/boards/")))

    def test_current_section_is_marked(self):
        menu = self.menu(self.render("/components/resistor/"))
        active = re.findall(r'drawer__link is-active"\s+href="([^"]+)"', menu)
        self.assertEqual(active, ["/components/"])

    def test_menu_has_no_tools(self):
        # дубли и импорт ссылок — кнопками над списком группы, не в меню
        menu = self.menu(self.render("/boards/", admin=True, editor=True))
        self.assertNotIn("TOOLS", menu)
        self.assertNotIn(reverse("components:duplicates"), menu)
        self.assertNotIn(reverse("components:link-import"), menu)

    def test_section_is_the_app(self):
        from ..context_processors import section

        self.assertEqual(section(resolve(reverse("components:duplicates"))), "components")
        self.assertEqual(section(resolve("/boards/")), "boards")
        self.assertEqual(section(None), "")

    def test_rail_only_in_components(self):
        # между разделами ходят через меню; у плат, серверов и сотрудников
        # левая панель только отнимала бы ширину у таблиц
        self.assertIn('class="rail"', self.render("/components/resistor/"))
        for path in ("/boards/", "/servers/", reverse("users:roles")):
            with self.subTest(path=path):
                self.assertNotIn('class="rail"', self.render(path, admin=True))

    def test_rail_holds_only_groups(self):
        # разделы — в меню; журнал, дубли и ссылки — кнопками над списком
        rail = self.rail(self.render("/components/resistor/", admin=True, editor=True))
        for url in ("/servers/", "/boards/", reverse("users:roles"),
                    reverse("components:duplicates"),
                    reverse("components:link-import"),
                    reverse("components:changes")):
            with self.subTest(url=url):
                self.assertNotIn(f'href="{url}"', rail)


class ListHeaderTests(SimpleTestCase):
    """Кнопки над списком группы (list.html)."""

    def test_component_pages_have_no_eyebrow(self):
        # строка над заголовком убрана во всём разделе компонентов: группы —
        # в левой панели, обратные ссылки — кнопками на самих страницах
        root = Path(settings.BASE_DIR) / "components" / "templates" / "components"
        offenders = [path.name for path in sorted(root.glob("*.html"))
                     if "legend__eyebrow" in path.read_text(encoding="utf-8")]
        self.assertEqual(offenders, [])

    def source(self):
        from django.template.loader import get_template

        return get_template("components/list.html").template.source

    def test_journal_sits_left_of_the_export(self):
        source = self.source()
        journal = source.index("{% url 'components:changes' %}")
        self.assertLess(journal, source.index('id="list-export"'))

    def test_journal_opens_unfiltered(self):
        # и из списка, и из карточки журнал открывается целиком, а не по
        # группе: сузить его можно на его же странице
        from django.template.loader import get_template

        for name in ("components/list.html", "components/detail.html"):
            with self.subTest(template=name):
                source = get_template(name).template.source
                self.assertNotIn("{% url 'components:changes' %}?", source)

    def test_tools_sit_by_the_journal(self):
        # между журналом и выгрузкой, каждый — только тому, кому открыт:
        # дубли — @admin_only, импорт ссылок — @component_editor
        source = self.source()
        journal = source.index("{% url 'components:changes' %}")
        export = source.index('id="list-export"')
        for url, role in (("components:duplicates", "is_admin"),
                          ("components:link-import", "can_edit_components")):
            with self.subTest(url=url):
                at = source.index(f"{{% url '{url}' %}}")
                self.assertTrue(journal < at < export)
                guard = source.rindex("{% if ", 0, at)
                self.assertIn(role, source[guard:source.index("%}", guard)])


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

    def test_empty_result_keeps_table_and_pager(self):
        # окошко таблицы всегда в 25 строк (rows.js): спрячь шаблон таблицу
        # на пустом результате — список съёживался бы, а переключатель
        # страниц уезжал вверх. Высоту строки rows.js берёт у строки-образца
        from django.template.loader import get_template

        source = get_template("components/list.html").template.source
        results = source[source.index('id="list-results"'):source.index('id="list-pager"')]
        self.assertNotIn("{% if rows %}", results)
        self.assertIn('data-rows="25"', results)
        rows = results[results.index('<tbody id="list-rows">'):results.index("</tbody>")]
        self.assertIn('class="rows-probe"', rows[rows.index("{% empty %}"):])

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


class PreviewTests(SimpleTestCase):
    """Краткая карточка справа от списка (detail.html#preview, preview.js)."""

    def request(self, htmx=True, target="list-preview"):
        from django.test import RequestFactory

        headers = {}
        if htmx:
            headers["HTTP_HX_REQUEST"] = "true"
        if target:
            headers["HTTP_HX_TARGET"] = target
        request = RequestFactory().get("/resistor/1435/", **headers)
        request.htmx = htmx
        return request

    def test_only_htmx_asking_for_the_panel_gets_it(self):
        from config.htmx import targets

        self.assertTrue(targets(self.request(), "list-preview"))
        # другой кусок той же страницы и обычный переход — карточка целиком
        self.assertFalse(targets(self.request(target="list-panel"), "list-preview"))
        self.assertFalse(targets(self.request(htmx=False), "list-preview"))

    def test_panel_id_matches_the_view(self):
        # вид узнаёт панель по её id; разойдись они — панель получила бы
        # целую страницу карточки
        from django.template.loader import get_template

        from ..views import PREVIEW_TARGET

        source = get_template("components/list.html").template.source
        self.assertIn(f'id="{PREVIEW_TARGET}"', source)

    def test_panel_lives_outside_the_list_fragment_and_needs_htmx(self):
        # внутри фрагмента смена фильтра стирала бы открытую карточку, а без
        # htmx панель пустая навсегда — грузить её нечем
        from django.template.loader import get_template

        source = get_template("components/list.html").template.source
        panel = source.index('id="list-preview"')
        self.assertGreater(panel, source.index("{% endpartialdef"))
        self.assertIn("{% if htmx_enabled %}", source[source.index("{% endpartialdef"):panel])
        # закреплена: стоит с самого начала, а не появляется с первым
        # щелчком — иначе таблица сжималась бы прямо под курсором
        tag = source[source.rindex("<aside", 0, panel):source.index(">", panel)]
        self.assertNotIn("hidden", tag)

    def detail_view(self, request, obj=None, image=None, related=None):
        from types import SimpleNamespace

        from django.http import HttpResponse

        from .. import views

        category = SimpleNamespace(table="RESISTOR", slug="resistor",
                                   ordered_fields=[], hidden_fields=())
        heavy = mock.Mock(side_effect=AssertionError("лишний запрос"))
        with mock.patch.object(views, "category_or_404", return_value=category), \
                mock.patch.object(views, "fetch",
                                  return_value=obj or SimpleNamespace(pk=1435)), \
                mock.patch.object(views, "find_usages", heavy), \
                mock.patch.object(views, "footprint_of", return_value=""), \
                mock.patch.object(views.FootprintImage, "for_footprint", return_value=image), \
                mock.patch.object(views, "history", heavy), \
                mock.patch.object(views, "_related_by_oy_id", related or heavy), \
                mock.patch.object(views, "render", return_value=HttpResponse("ok")) as render:
            response = views.component_detail(request, "resistor", 1435)
        return response, render

    def test_view_answers_the_panel_briefly(self):
        # применяемость, аналоги и историю панель не просит: её листают
        # стрелками, и каждый запрос повторялся бы на каждой строке
        response, render = self.detail_view(self.request())
        self.assertEqual(render.call_args.args[1], "components/detail.html#preview")
        # один адрес — два ответа: кэш браузера должен их различать
        self.assertIn("HX-Target", response["Vary"])

    def test_panel_borrows_the_image_like_the_card(self):
        # у замены своего посадочного места нет — панель показывает рендер
        # соседа по OY ID, как и карточка, и говорит, чей он
        from types import SimpleNamespace

        from .. import views

        neighbour = {"obj": SimpleNamespace(vendor_pn="RC0402"),
                     "category": SimpleNamespace(replacement=False)}
        shot = object()
        related = mock.Mock(return_value=[neighbour])
        with mock.patch.object(views, "_borrowed_image",
                               return_value=(shot, neighbour)) as borrowed:
            _, render = self.detail_view(
                self.request(), obj=SimpleNamespace(pk=1435, oy_id="OY-1"),
                related=related)
        borrowed.assert_called_once_with([neighbour])
        context = render.call_args.args[2]
        self.assertIs(context["image"], shot)
        self.assertIs(context["borrowed_from"], neighbour)

    def test_panel_skips_neighbours_when_it_has_its_own_image(self):
        # своя картинка есть — соседей не ищем: панель листают по строкам,
        # и запрос повторялся бы на каждой
        from types import SimpleNamespace

        shot = object()
        _, render = self.detail_view(
            self.request(), obj=SimpleNamespace(pk=1435, oy_id="OY-1"), image=shot)
        context = render.call_args.args[2]
        self.assertIs(context["image"], shot)
        self.assertIsNone(context["borrowed_from"])

    def test_preview_names_whose_image_it_borrowed(self):
        from types import SimpleNamespace

        neighbour = {"obj": SimpleNamespace(vendor_pn="RC0402FR-07110KL",
                                            get_absolute_url="/resistor/7/")}
        image = SimpleNamespace(image=SimpleNamespace(url="/media/fp.png"))
        html = self.render_preview(image=image, borrowed_from=neighbour)
        self.assertIn('src="/media/fp.png"', html)
        self.assertIn('href="/resistor/7/"', html)
        self.assertNotIn('href="/resistor/7/"', self.render_preview(image=image))

    def render_preview(self, **extra):
        import datetime as dt
        from types import SimpleNamespace

        from django.template.loader import render_to_string

        context = {
            "category": SimpleNamespace(table="RESISTOR", slug="resistor",
                                        read_only=False),
            "object": SimpleNamespace(pk=1435, vendor_pn="RC0402FR-07110KL",
                                      display_title="RC0402FR-07110KL",
                                      get_absolute_url="/resistor/1435/"),
            "description": ("Description", "Chip Resistor, 0402, 110 kOhm", "description"),
            "fields": [("Vendor", "Yageo", "vendor"),
                       ("Created", dt.date(2026, 2, 14), "created")],
            "more": 12,
            "image": None,
        }
        context.update(extra)
        return render_to_string("components/detail.html#preview", context)

    def test_preview_shows_the_essentials(self):
        html = self.render_preview()
        self.assertIn("RC0402FR-07110KL", html)
        self.assertIn("Chip Resistor, 0402, 110 kOhm", html)
        self.assertIn("14.02.2026", html)
        self.assertIn("Ещё 12 параметров", html)
        self.assertIn('href="/resistor/1435/"', html)
        # панель закреплена — закрывать её нечем
        self.assertNotIn("data-preview-close", html)

    def test_missing_image_leaves_a_placeholder(self):
        # та же рамка, что у картинки: панель не меняет высоту от строки к строке
        self.assertIn("stepshot__empty", self.render_preview(image=None))
        from types import SimpleNamespace

        image = SimpleNamespace(image=SimpleNamespace(url="/media/fp.png"))
        self.assertNotIn("stepshot__empty", self.render_preview(image=image))

    def test_title_is_the_vendor_pn_as_stored(self):
        # «---» остаётся «---»: подставленное описание читалось бы как артикул
        from types import SimpleNamespace

        obj = SimpleNamespace(pk=7, vendor_pn="---", display_title="Chip Resistor",
                              get_absolute_url="/resistor/7/")
        html = self.render_preview(object=obj, description=None)
        title = html[html.index("preview__title"):]
        title = title[:title.index("</div>")]
        self.assertIn("---", title)
        self.assertNotIn("Chip Resistor", title)

    def test_description_and_datasheet_take_three_lines(self):
        html = self.render_preview(fields=[
            ("Vendor", "Yageo", "vendor"),
            ("Datasheet", r"Datasheet\Resistor\Yageo.pdf", "datasheet")])
        # описание и Datasheet — по обёртке в три строки, остальные поля — нет
        self.assertEqual(html.count('class="preview__clamp"'), 2)

    def test_description_and_datasheet_stay_when_empty(self):
        from ..views import preview_fields

        fields = [("Vendor PN", "RC0402", "vendor_pn"),
                  ("Description", None, "description"),
                  ("Datasheet", "", "datasheet"),
                  ("Tracker URL", "", "tracker_url"),
                  ("Value", "10k", "value")]
        description, shown, more = preview_fields(fields)
        self.assertEqual(description[2], "description")
        # пустой Datasheet на месте, пустой Tracker URL — нет
        self.assertEqual([name for _, _, name in shown], ["vendor_pn", "datasheet"])
        self.assertEqual(more, 1)

    def test_brief_fields_leave_out_what_is_not_compared(self):
        from ..views import brief_fields

        fields = [("Vendor PN", "RC0402FR-07110KL", "vendor_pn"),
                  ("Group", "Resistor", "group"),
                  ("Subgroup", "Thick Film", "subgroup"),
                  ("Country", "Taiwan", "country"),
                  ("Notice", "---", "notice"),
                  ("Status", "Active", "status"),
                  ("Datasheet", "yageo.pdf", "datasheet")]
        self.assertEqual([name for _, _, name in brief_fields(fields)],
                         ["vendor_pn", "datasheet"])

    def test_edit_button_follows_the_role(self):
        self.assertNotIn("/edit/", self.render_preview())
        self.assertIn("/resistor/1435/edit/",
                      self.render_preview(can_edit_components=True))



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


class ChangelogTests(SimpleTestCase):
    """«Что нового»: разбор CHANGELOG.md (components/changelog.py)."""

    SAMPLE = """# Что нового

Версия — в `config/__init__.py`.

## 0.2.0

### Изменено

- **Первый пункт** с `кодом`
  и продолжением строки.
- Второй <b>пункт</b>.

### Обновление

1. Резервная копия.
2. Запуск:
   `migrate`.

## 0.1.0

Просто абзац.
"""

    def parsed(self):
        from ..changelog import parse
        return parse(self.SAMPLE)

    def test_versions_in_file_order(self):
        _, versions = self.parsed()
        self.assertEqual([v["number"] for v in versions], ["0.2.0", "0.1.0"])

    def test_sections_and_blocks(self):
        _, versions = self.parsed()
        changed, update = versions[0]["sections"]
        self.assertEqual((changed["title"], changed["blocks"][0]["kind"]),
                         ("Изменено", "ul"))
        self.assertEqual(update["blocks"][0]["kind"], "ol")
        # «Обновление» — для того, кто ставит версию, в окне оно свёрнуто
        self.assertEqual((changed["collapsed"], update["collapsed"]),
                         (False, True))

    def test_continuation_joins_the_item(self):
        _, versions = self.parsed()
        first = versions[0]["sections"][0]["blocks"][0]["items"][0]
        self.assertEqual(first, "<strong>Первый пункт</strong> с "
                                "<code>кодом</code> и продолжением строки.")
        step = versions[0]["sections"][1]["blocks"][0]["items"][1]
        self.assertEqual(step, "Запуск: <code>migrate</code>.")

    def test_html_in_the_file_is_text(self):
        # разметка вставляется в уже экранированный текст
        _, versions = self.parsed()
        second = versions[0]["sections"][0]["blocks"][0]["items"][1]
        self.assertIn("&lt;b&gt;пункт&lt;/b&gt;", second)

    def test_intro_and_text_before_sections(self):
        intro, versions = self.parsed()
        self.assertEqual(intro[0]["items"][0],
                         "Версия — в <code>config/__init__.py</code>.")
        # версия без «###»: абзац в разделе без заголовка
        section = versions[1]["sections"][0]
        self.assertEqual((section["title"], section["blocks"][0]["kind"]),
                         ("", "p"))

    def test_bold_inside_code_stays_as_is(self):
        from ..changelog import inline
        self.assertEqual(inline("`**x**`"), "<code>**x**</code>")

    def test_project_changelog_parses(self):
        # сам CHANGELOG.md: каждая версия разобралась и в ней что-то есть
        from ..changelog import load
        _, versions = load()
        self.assertTrue(versions)
        for version in versions:
            with self.subTest(version=version["number"]):
                self.assertTrue(version["sections"])

    def test_missing_file_is_empty(self):
        from .. import changelog
        with mock.patch.object(changelog, "changelog_path",
                               return_value=Path("/nonexistent/CHANGELOG.md")):
            self.assertEqual(changelog.load(), ([], []))

