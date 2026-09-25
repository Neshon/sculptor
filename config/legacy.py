"""Старые адреса компонентов — до переезда раздела под ``/components/``.

Раньше компоненты жили в корне сайта: ``/resistor/1435/``,
``/search/?q=...``, ``/changes/``. Такие ссылки разосланы коллегам,
вставлены в трекер и в заметки к платам, и терять их нельзя. Маршрут стоит
последним в ``config/urls.py`` и ловит всё, что не узнали остальные: если
тот же путь есть под ``/components/``, отправляет туда вместе со строкой
запроса, иначе отвечает обычным 404.
"""

from django.http import Http404
from django.shortcuts import redirect
from django.urls import Resolver404, resolve

PREFIX = "/components/"


def legacy_target(path):
    """Новый адрес для старого пути без ведущей косой черты, или ``None``.

    Путь без косой черты в конце пробуется и с ней. Этот маршрут ловит
    любой адрес, и штатное дописывание косой черты (``APPEND_SLASH``) до
    него не доходит: оно срабатывает, только когда адрес без черты не
    узнан, — а узнан он всегда, здесь. Поэтому черту дописываем сами, и
    сначала к самому адресу: ``/boards`` — это ``/boards/``, а
    ``/components/resistor`` — ``/components/resistor/``, а не группа
    «components» под новым префиксом.
    """
    candidates = []
    if not path.endswith("/"):
        candidates.append(f"/{path}/")
    if not path.startswith(PREFIX.lstrip("/")):
        candidates.append(PREFIX + path)
        if not path.endswith("/"):
            candidates.append(f"{PREFIX}{path}/")
    for candidate in candidates:
        try:
            match = resolve(candidate)
        except Resolver404:
            continue
        # неузнанный путь доходит сюда же — это не адрес, а этот маршрут
        if match.url_name != "legacy":
            return candidate
    return None


def legacy_redirect(request, path):
    """Переадресация со старого адреса компонента на новый.

    Временная (302), а не постоянная: браузер запоминает 301 навсегда, и
    если в корне потом появится новый раздел, у того, кто однажды открыл
    этот адрес раньше, он так и уводил бы в компоненты. Только чтение:
    форма, отправленная на старый адрес, после переадресации потеряла бы
    данные.
    """
    target = legacy_target(path)
    if target is None or request.method not in ("GET", "HEAD"):
        raise Http404(path)
    query = request.META.get("QUERY_STRING", "")
    return redirect(f"{target}?{query}" if query else target)
