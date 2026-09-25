"""Тесты раздела пользователей — без базы, как и в остальных разделах.

    python manage.py test users
"""

from unittest import mock

from django.db import DatabaseError
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import reverse

from . import access
from .models import AccessEvent
from .roles import ROLE_ENGINEER, ROLE_LIBRARIAN, ROLE_TOPOLOGY

factory = RequestFactory()


class RoleChangesTests(SimpleTestCase):
    """Что выдать и что снять — только среди ролей проекта."""

    def test_diff(self):
        added, removed = access.role_changes(
            {ROLE_ENGINEER, ROLE_TOPOLOGY}, [ROLE_LIBRARIAN, ROLE_TOPOLOGY])
        self.assertEqual(added, [ROLE_LIBRARIAN])
        self.assertEqual(removed, [ROLE_ENGINEER])

    def test_foreign_groups_untouched(self):
        # чужие группы страница не показывает — и снимать их не должна
        added, removed = access.role_changes({"Бухгалтерия"}, ["Кто-то ещё"])
        self.assertEqual((added, removed), ([], []))


class ClientIpTests(SimpleTestCase):
    def request(self, forwarded=""):
        extra = {"HTTP_X_FORWARDED_FOR": forwarded} if forwarded else {}
        return factory.get("/", REMOTE_ADDR="10.0.0.5", **extra)

    @override_settings(USE_X_FORWARDED_HOST=False)
    def test_header_ignored_without_proxy(self):
        # без прокси заголовок присылает сам клиент — верить ему нельзя
        self.assertEqual(access.client_ip(self.request("1.2.3.4")), "10.0.0.5")

    @override_settings(USE_X_FORWARDED_HOST=True)
    def test_first_forwarded_address_behind_proxy(self):
        self.assertEqual(
            access.client_ip(self.request("192.168.1.7, 10.0.0.1")),
            "192.168.1.7")

    def test_no_request(self):
        self.assertIsNone(access.client_ip(None))


class ActorTests(SimpleTestCase):
    """Кто меняет роль — запоминается на время запроса и только на него."""

    def test_actor_set_during_request_and_reset_after(self):
        seen = []
        middleware = access.ActorMiddleware(
            lambda request: seen.append(access.current_actor()))
        request = factory.get("/")
        request.user = mock.Mock(is_authenticated=True,
                                 **{"get_username.return_value": "admin"})
        middleware(request)
        self.assertEqual(seen, ["admin"])
        self.assertEqual(access.current_actor(), access.OUTSIDE_REQUEST)

    def test_outside_request(self):
        self.assertEqual(access.current_actor(), "командная строка")


class RecordTests(SimpleTestCase):
    def test_journal_failure_does_not_break_login(self):
        with mock.patch.object(AccessEvent.objects, "create",
                               side_effect=DatabaseError("нет таблицы")):
            self.assertIsNone(access.record(AccessEvent.LOGIN, "ivanov"))

    def test_fields_written(self):
        request = factory.get("/", REMOTE_ADDR="10.0.0.5",
                              HTTP_USER_AGENT="Firefox")
        with mock.patch.object(AccessEvent.objects, "create") as create:
            access.record(AccessEvent.ROLE_ADDED, "ivanov", request,
                          actor="admin", detail=ROLE_LIBRARIAN)
        self.assertEqual(create.call_args.kwargs, {
            "kind": "role_added", "username": "ivanov", "actor": "admin",
            "detail": ROLE_LIBRARIAN, "ip": "10.0.0.5",
            "user_agent": "Firefox"})

    def test_failed_login_keeps_only_username(self):
        with mock.patch.object(access, "record") as record:
            access.on_login_failed(None, {"username": "ivanov",
                                          "password": "********"})
        self.assertEqual(record.call_args.args[:2],
                         (AccessEvent.LOGIN_FAILED, "ivanov"))

    def test_logout_without_session_not_recorded(self):
        with mock.patch.object(access, "record") as record:
            access.on_logout(None, factory.get("/"), None)
        record.assert_not_called()


class GroupsSignalTests(SimpleTestCase):
    """Смена ролей пишется любым путём: с сайта, из админки, init_roles."""

    def changed(self, action, pairs, instance=None):
        instance = instance or mock.Mock()
        with mock.patch.object(access, "_pairs_for", return_value=pairs), \
                mock.patch.object(access, "record") as record:
            access.on_groups_changed(None, instance, action, False, {1})
        return [(call.args[0], call.args[1], call.kwargs["detail"])
                for call in record.call_args_list]

    def test_added_roles_only(self):
        # группы, не являющиеся ролями проекта, в журнал не идут
        written = self.changed("post_add", [("ivanov", ROLE_LIBRARIAN),
                                            ("ivanov", "Бухгалтерия")])
        self.assertEqual(written, [("role_added", "ivanov", ROLE_LIBRARIAN)])

    def test_removed(self):
        written = self.changed("post_remove", [("ivanov", ROLE_ENGINEER)])
        self.assertEqual(written, [("role_removed", "ivanov", ROLE_ENGINEER)])

    def test_clear_remembers_groups_before(self):
        instance = mock.Mock()
        self.changed("pre_clear", [("ivanov", ROLE_TOPOLOGY)], instance)
        with mock.patch.object(access, "record") as record:
            access.on_groups_changed(None, instance, "post_clear", False, None)
        self.assertEqual(record.call_args.kwargs["detail"], ROLE_TOPOLOGY)
        self.assertEqual(record.call_args.args[0], "role_removed")


class ProfileTests(SimpleTestCase):
    def user(self, roles=(), superuser=False, staff=False):
        user = mock.Mock(is_authenticated=True, is_superuser=superuser,
                         is_staff=staff)
        user._role_names = frozenset(roles)
        return user

    def test_all_roles_listed_with_mark(self):
        from .views import role_rows
        user = mock.Mock()
        user.groups.values_list.return_value = [ROLE_ENGINEER]
        rows = {row["name"]: row["has"] for row in role_rows(user)}
        self.assertEqual(rows, {ROLE_ENGINEER: True, ROLE_TOPOLOGY: False,
                                ROLE_LIBRARIAN: False})


class AccessLogFilterTests(SimpleTestCase):
    def test_unknown_kind_ignored(self):
        from django.http import QueryDict

        from .views import access_queryset
        query = access_queryset(QueryDict("kind=login|nonsense&username=ivanov"))
        sql = str(query.query)
        self.assertIn("login", sql)
        self.assertNotIn("nonsense", sql)
        self.assertIn("ivanov", sql)


class UserAdminTests(SimpleTestCase):
    def test_employee_block(self):
        from django.contrib import admin

        from .models import User
        fieldsets = dict(admin.site._registry[User].fieldsets)
        self.assertEqual(fieldsets["Сотрудник"]["fields"],
                         ("department", "position"))

    def test_access_log_read_only(self):
        from django.contrib import admin
        model_admin = admin.site._registry[AccessEvent]
        self.assertFalse(model_admin.has_add_permission(None))
        self.assertFalse(model_admin.has_change_permission(None))


class UrlTests(SimpleTestCase):
    def test_pages_are_routed(self):
        self.assertEqual(reverse("users:profile"), "/users/profile/")
        self.assertEqual(reverse("users:roles"), "/users/roles/")
        self.assertEqual(reverse("users:access-log"), "/users/access/")
        self.assertEqual(reverse("users:create"), "/users/new/")
        self.assertEqual(reverse("users:password"), "/users/password/")

    def test_closed_for_anonymous(self):
        # сайт закрыт целиком: новые страницы — не исключение
        for name in ("users:profile", "users:roles", "users:access-log",
                     "users:create", "users:password"):
            with self.subTest(name=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])


class UserCreatedSignalTests(SimpleTestCase):
    """Заведение сотрудника пишет журнал доступа — любым путём (сигнал)."""

    def user(self):
        return mock.Mock(get_username=mock.Mock(return_value="ivanov"))

    def test_created_is_recorded_with_actor(self):
        with mock.patch.object(access, "record") as record,                 mock.patch.object(access, "current_actor", return_value="admin"):
            access.on_user_saved(None, self.user(), created=True)
        record.assert_called_once_with(AccessEvent.USER_CREATED, "ivanov",
                                       actor="admin")

    def test_edit_and_fixtures_are_not(self):
        # правка учётной записи — не заведение; фикстуры — перенос данных
        with mock.patch.object(access, "record") as record:
            access.on_user_saved(None, self.user(), created=False)
            access.on_user_saved(None, self.user(), created=True, raw=True)
        record.assert_not_called()


class UserCreateFormTests(SimpleTestCase):
    """Форма нового сотрудника (users/forms.py) — без базы: только устройство."""

    def form(self):
        from .forms import UserCreateForm

        return UserCreateForm()

    def test_name_is_required(self):
        # журналы показывают сотрудника по имени: одного логина мало
        form = self.form()
        self.assertTrue(form.fields["last_name"].required)
        self.assertTrue(form.fields["first_name"].required)
        self.assertFalse(form.fields["email"].required)

    def test_roles_are_project_roles_only(self):
        from .roles import ROLES

        self.assertEqual([value for value, _ in self.form().fields["roles"].choices],
                         list(ROLES))
        self.assertFalse(self.form().fields["roles"].required)

    def test_no_superuser_or_staff_here(self):
        # доступ ко всему и к админке выдаётся в админке, осознанно
        for name in ("is_superuser", "is_staff", "groups"):
            self.assertNotIn(name, self.form().fields)

    def test_browser_does_not_fill_the_admin_password(self):
        form = self.form()
        for name in ("password1", "password2"):
            self.assertEqual(form.fields[name].widget.attrs["autocomplete"],
                             "new-password")

    def test_role_rows_mark_chosen(self):
        from .forms import UserCreateForm

        form = UserCreateForm(data={"roles": [ROLE_LIBRARIAN]})
        marks = {name: checked for name, _, checked in form.role_rows()}
        self.assertTrue(marks[ROLE_LIBRARIAN])
        self.assertFalse(marks[ROLE_ENGINEER])


class PasswordChangeTests(SimpleTestCase):
    """Смена своего пароля (users.views.PasswordChange)."""

    def test_old_password_is_asked(self):
        # оставленный открытым сеанс не должен давать сменить пароль
        from django.contrib.auth.forms import PasswordChangeForm

        from .views import PasswordChange

        self.assertTrue(issubclass(PasswordChange().get_form_class(),
                                   PasswordChangeForm))
        self.assertIn("old_password", PasswordChangeForm.base_fields)

    def test_back_to_profile(self):
        from .views import PasswordChange

        self.assertEqual(str(PasswordChange.success_url), reverse("users:profile"))

    def test_profile_links_to_it_and_has_no_roles_panel(self):
        from django.template.loader import get_template

        source = get_template("users/profile.html").template.source
        self.assertIn("{% url 'users:password' %}", source)
        self.assertNotIn("роли и права", source)
