"""Журнал доступа: кто входил, откуда, кто кому менял роли.

Записи делают сигналы Django, а не страницы, и это главное. Роль можно
выдать на странице «Сотрудники и роли», в админке и командой init_roles;
войти — формой входа. Если бы журнал вела одна страница, изменения мимо
неё проходили бы бесследно — а спрашивают про них как раз тогда, когда
кто-то сделал что-то не тем путём.

Кто поменял роль, сигнал не знает: в нём нет запроса. Поэтому
:class:`ActorMiddleware` запоминает вошедшего на время запроса, а запись
берёт его оттуда. Вне запроса (init_roles, shell) автор — «командная
строка».
"""

import logging
from contextvars import ContextVar

from django.conf import settings
from django.contrib.auth.models import Group
from django.db import DatabaseError

from .roles import ROLES

logger = logging.getLogger(__name__)

# кто делает текущий запрос; вне запроса — пусто
_actor = ContextVar("access_actor", default="")
OUTSIDE_REQUEST = "командная строка"

USER_AGENT_LENGTH = 255


class ActorMiddleware:
    """Запоминает логин вошедшего на время запроса — для журнала ролей.

    ContextVar, а не поле на потоке: gunicorn работает потоками, и значение
    одного запроса не должно достаться другому. Сбрасывается в finally —
    иначе поток унёс бы его в следующий запрос.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        name = (user.get_username()
                if user is not None and user.is_authenticated else "")
        token = _actor.set(name)
        try:
            return self.get_response(request)
        finally:
            _actor.reset(token)


def current_actor():
    return _actor.get() or OUTSIDE_REQUEST


def client_ip(request):
    """Адрес клиента.

    За обратным прокси (DJANGO_BEHIND_PROXY) настоящий адрес в
    X-Forwarded-For — первым в списке. Без прокси этот заголовок присылает
    сам клиент, и верить ему нельзя: в журнал попал бы адрес, который он
    придумал. Поэтому читается он только тогда, когда прокси объявлен.
    """
    if request is None:
        return None
    if getattr(settings, "USE_X_FORWARDED_HOST", False):
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None


def record(kind, username, request=None, actor="", detail=""):
    """Пишет событие. Сбой журнала не мешает ни входу, ни смене роли.

    Не записать вход хуже, чем записать, но гораздо лучше, чем не пустить
    человека из-за того, что журнал недоступен.
    """
    from .models import AccessEvent

    agent = ""
    if request is not None:
        agent = request.META.get("HTTP_USER_AGENT", "")[:USER_AGENT_LENGTH]
    try:
        return AccessEvent.objects.create(
            kind=kind, username=(username or "")[:150], actor=actor[:150],
            detail=detail[:255], ip=client_ip(request), user_agent=agent)
    except DatabaseError as exc:
        logger.warning("журнал доступа недоступен: %s", exc)
        return None


# ---- вход и выход ------------------------------------------------------------

def on_login(sender, request, user, **kwargs):
    from .models import AccessEvent
    record(AccessEvent.LOGIN, user.get_username(), request)


def on_login_failed(sender, credentials, request=None, **kwargs):
    """Неудачная попытка — под тем логином, который ввели.

    Пароль в сигнал не попадает: Django вычищает его из ``credentials``
    заранее, а мы берём оттуда только логин.
    """
    from .models import AccessEvent
    record(AccessEvent.LOGIN_FAILED, credentials.get("username", ""), request)


def on_logout(sender, request, user, **kwargs):
    # выход по ссылке без входа — сессия уже истекла, писать нечего
    if user is None:
        return
    from .models import AccessEvent
    record(AccessEvent.LOGOUT, user.get_username(), request)


# ---- роли --------------------------------------------------------------------

def role_changes(current, wanted):
    """``(выдать, снять)`` — только среди ролей проекта (users.roles.ROLES).

    Прочие группы Django, если их кто-то завёл, страница ролей не
    показывает и трогать не должна.
    """
    roles = set(ROLES)
    current, wanted = set(current) & roles, set(wanted) & roles
    return sorted(wanted - current), sorted(current - wanted)


def on_groups_changed(sender, instance, action, reverse, pk_set, **kwargs):
    """Роль выдана или снята — любым путём.

    Связь «пользователь — группа» меняют с двух сторон: user.groups.add()
    (instance — пользователь, pk_set — группы) и group.user_set.add()
    (instance — группа, pk_set — пользователи). Очистку целиком
    (groups.clear()) сигнал присылает без pk_set, поэтому группы
    запоминаются до неё, в pre_clear.
    """
    from .models import AccessEvent

    if action == "pre_clear":
        instance._groups_before_clear = _pairs_for(instance, reverse, None)
        return
    if action == "post_clear":
        pairs = getattr(instance, "_groups_before_clear", [])
        kind = AccessEvent.ROLE_REMOVED
    elif action in ("post_add", "post_remove"):
        pairs = _pairs_for(instance, reverse, pk_set)
        kind = (AccessEvent.ROLE_ADDED if action == "post_add"
                else AccessEvent.ROLE_REMOVED)
    else:
        return

    actor = current_actor()
    for username, role in pairs:
        if role in ROLES:
            record(kind, username, actor=actor, detail=role)


def _pairs_for(instance, reverse, pk_set):
    """``[(логин, имя группы)]`` для изменения связи с любой стороны."""
    from django.contrib.auth import get_user_model

    if not reverse:
        groups = (Group.objects.filter(pk__in=pk_set) if pk_set is not None
                  else instance.groups.all())
        return [(instance.get_username(), group.name) for group in groups]
    users = (get_user_model().objects.filter(pk__in=pk_set)
             if pk_set is not None else instance.user_set.all())
    return [(user.get_username(), instance.name) for user in users]
