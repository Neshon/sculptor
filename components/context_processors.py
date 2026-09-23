"""Навигация доступна всем шаблонам без ручной передачи в контекст."""

from django.conf import settings

from config import __version__

from users.roles import can_edit_boards, can_edit_components, is_admin
from .registry import MAIN_CATEGORIES, REPLACEMENT_CATEGORIES


def navigation(request):
    return {
        "nav_categories": MAIN_CATEGORIES,
        "nav_replacements": REPLACEMENT_CATEGORIES,
    }


def permissions(request):
    """Права текущего пользователя — чтобы шаблоны не рисовали лишних кнопок."""
    user = getattr(request, "user", None)
    if user is None:
        return {}
    return {
        "can_edit_components": can_edit_components(user),
        "can_edit_boards": can_edit_boards(user),
        "is_admin": is_admin(user),
    }


def htmx(request):
    """Включён ли HTMX и пришёл ли запрос за фрагментом.

    ``htmx_enabled`` — файл htmx на месте (config/settings.py). Шаблоны
    ставят атрибуты hx-* только тогда: без библиотеки они ничего не делают,
    зато страница честно работает обычными переходами.
    """
    return {"htmx_enabled": settings.HTMX_ENABLED,
            "htmx_request": getattr(request, "htmx", False)}


def version(request):
    """Версия системы — для шапки. Одна на весь проект: config/__init__.py."""
    return {"app_version": __version__}
