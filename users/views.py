"""Страницы раздела пользователей: свой профиль, роли сотрудников, журнал доступа."""

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.auth.views import PasswordChangeView
from django.core.paginator import Paginator
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy

from components.db import distinct_values
from components.history import author_names
from components.models import ComponentChange
from components.querystring import values_of

from .access import role_changes
from .forms import AccessFilterForm, UserCreateForm
from .models import AccessEvent
from .roles import ROLES, admin_only

# сколько своих правок и входов показывать в профиле: остальное — по ссылке
PROFILE_LIMIT = 10
LOG_PAGE_SIZE = 50


# ---- профиль -----------------------------------------------------------------

def role_rows(user):
    """Роли проекта: у каких сотрудник есть и что каждая даёт.

    Профиль показывает из них те, что есть, — метками рядом с именем.
    """
    names = set(user.groups.values_list("name", flat=True))
    return [{"name": name, "description": description, "has": name in names}
            for name, description in ROLES.items()]


def profile(request):
    """Свой профиль: кто я, что мне можно, что я недавно делал.

    Правок в справочнике журнал хранит по логину — по нему и отбираем; вся
    история — по ссылке на журнал с фильтром по себе.
    """
    user = request.user
    login = user.get_username()
    changes = list(ComponentChange.objects.filter(author=login)
                   [:PROFILE_LIMIT])
    events = list(AccessEvent.objects.filter(username=login)
                  .exclude(kind=AccessEvent.LOGOUT)[:PROFILE_LIMIT])
    return render(request, "users/profile.html", {
        "profile": user,
        "roles": role_rows(user),
        "changes": changes,
        "changes_total": ComponentChange.objects.filter(author=login).count(),
        "changes_url": reverse("components:changes") + f"?author={login}",
        "events": events,
    })


# ---- смена пароля ----------------------------------------------------------------

class PasswordChange(PasswordChangeView):
    """Сотрудник меняет свой пароль сам — начальный задаёт администратор.

    Штатное представление Django: старый пароль спрашивается (чужая
    незакрытая сессия не должна менять пароль владельца), новый проходит
    AUTH_PASSWORD_VALIDATORS, а сессия после смены обновляется — сотрудника
    не выбрасывает на вход. Своё здесь — только шаблон и возврат в профиль
    с сообщением.
    """

    template_name = "users/password.html"
    success_url = reverse_lazy("users:profile")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Пароль изменён.")
        return response


# ---- роли сотрудников ----------------------------------------------------------

def role_field(user_pk):
    """Имя поля формы с ролями одного сотрудника."""
    return f"roles-{user_pk}"


@admin_only
def roles(request):
    """Сотрудники и их роли — галочками, одной формой.

    Суперпользователя и «статус персонала» здесь не меняют: это доступ к
    админке и ко всему сразу, и выдаётся он там, осознанно. Здесь — только
    роли проекта. Что и кому поменяли, пишет журнал доступа (сигналом, см.
    users/access.py) — страница об этом не заботится.
    """
    users = list(get_user_model().objects.order_by("-is_active", "username")
                 .prefetch_related("groups"))

    if request.method == "POST":
        groups = {group.name: group
                  for group in Group.objects.filter(name__in=ROLES)}
        missing = set(ROLES) - set(groups)
        if missing:
            messages.error(request, "Не заведены роли: " + ", ".join(sorted(missing))
                           + ". Выполните manage.py init_roles.")
            return redirect("users:roles")

        changed = 0
        with transaction.atomic():
            for user in users:
                current = {group.name for group in user.groups.all()}
                added, removed = role_changes(
                    current, request.POST.getlist(role_field(user.pk)))
                if added:
                    user.groups.add(*(groups[name] for name in added))
                if removed:
                    user.groups.remove(*(groups[name] for name in removed))
                changed += len(added) + len(removed)

        if changed:
            messages.success(request, f"Изменено ролей: {changed}.")
        else:
            messages.info(request, "Роли не изменились.")
        return redirect("users:roles")

    rows = []
    for user in users:
        names = {group.name for group in user.groups.all()}
        rows.append({"user": user, "field": role_field(user.pk),
                     "roles": [(name, name in names) for name in ROLES]})
    return render(request, "users/roles.html", {
        "rows": rows,
        "role_headers": list(ROLES.items()),
    })


# ---- новый сотрудник -----------------------------------------------------------

@admin_only
def create_user(request):
    """Новый сотрудник: учётная запись, начальный пароль и роли.

    Учётная запись и роли — в одной транзакции: сотрудник без ролей, которые
    ему отметили, хуже, чем незаведённый, — его сочли бы заведённым как
    надо. Роли выдаются тем же ``groups.add``, что и на странице ролей,
    поэтому журнал доступа видит и заведение, и каждую роль (сигналы,
    users/access.py).
    """
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        wanted = form.cleaned_data["roles"]
        groups = list(Group.objects.filter(name__in=wanted))
        missing = set(wanted) - {group.name for group in groups}
        if missing:
            # без этой проверки роль молча не выдалась бы
            form.add_error("roles", "Не заведены роли: "
                           + ", ".join(sorted(missing))
                           + ". Выполните manage.py init_roles.")
        else:
            with transaction.atomic():
                user = form.save()
                if groups:
                    user.groups.add(*groups)
            messages.success(
                request, f"Сотрудник {user.get_full_name()} "
                         f"({user.get_username()}) заведён.")
            return redirect("users:roles")
    return render(request, "users/user_form.html", {"form": form})


# ---- журнал доступа ------------------------------------------------------------

def access_queryset(params):
    """Записи журнала по фильтрам; неизвестные значения не сужают выборку."""
    found = AccessEvent.objects.all()
    known = dict(AccessEvent.KINDS)
    kinds = [kind for kind in values_of(params, "kind") if kind in known]
    if kinds:
        found = found.filter(kind__in=kinds)
    usernames = values_of(params, "username")
    if usernames:
        found = found.filter(username__in=usernames)
    return found


@admin_only
def access_log(request):
    """Журнал доступа: входы, неудачные попытки, выходы, смена ролей."""
    usernames = sorted(distinct_values(AccessEvent.objects.all(), "username"))
    page = Paginator(access_queryset(request.GET), LOG_PAGE_SIZE).get_page(
        request.GET.get("page"))
    # имена вместо логинов — одним запросом на страницу, как в журнале
    # изменений; логин остаётся в подсказке
    events = list(page.object_list)
    names = author_names([e.username for e in events]
                         + [e.actor for e in events])
    for event in events:
        event.username_display = names.get(event.username) or event.username
        event.actor_display = names.get(event.actor) or event.actor
    return render(request, "users/access_log.html", {
        "page": page,
        "events": events,
        "filter_form": AccessFilterForm(request.GET or None,
                                        usernames=usernames),
    })
