"""История изменений компонента: что записывать и как показывать.

Правки в 27 таблиц компонентов приходят из двух мест — с формы на сайте и
из админки, — и записывать историю нужно в обоих. Поэтому сравнение «было —
стало» собрано здесь, а не в представлении: иначе один из двух путей рано
или поздно остался бы без истории, и та молча перестала бы быть полной.

Сравнивается состояние до правки со состоянием после, а не список полей,
которые форма считает изменёнными. Разница важна: при сохранении пустые
поля превращаются в ``---`` (см. ``components.forms``), а ``Created``
проставляется само. Форма об этом не знает, а история должна показывать то,
что в самом деле попало в базу.
"""

from datetime import date

from django.contrib.auth import get_user_model
from .db import distinct_values, fallback
from .models import ComponentChange
from .querystring import values_of

# Что в историю не пишем: суррогатный ключ пользователю ничего не говорит,
# а «Created» проставляется автоматически при заведении и потом не меняется.
IGNORED_FIELDS = frozenset({"id", "created"})

SITE = "сайт"
ADMIN = "админка"

# сколько правок показывать в карточке
CARD_LIMIT = 25


def snapshot(instance):
    """Значения всех полей записи — то, с чем потом сравнивать."""
    return {field.name: getattr(instance, field.name, None)
            for field in instance._meta.fields
            if field.name not in IGNORED_FIELDS}


def _text(value):
    """Значение в виде строки — такой, какой её видит пользователь.

    Пустое и заглушка ``---`` — для истории одно и то же: «не заполнено».
    Иначе замена пустой строки на ``---`` при сохранении попадала бы в
    историю как изменение, хотя для человека ничего не изменилось.
    """
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text in {"---", "-", "?"} else text


def diff(before, after, model):
    """Список изменившихся полей: имя, подпись, было, стало."""
    fields = list(model._meta.fields)
    labels = {f.name: str(f.verbose_name) for f in fields}
    # порядок полей — как в модели, чтобы читалось так же, как карточка;
    # неизвестное поле (переименовали, убрали) уходит в конец
    order = {f.name: index for index, f in enumerate(fields)}
    last = len(order)

    changed = []
    for name, new_value in after.items():
        old_text, new_text = _text(before.get(name)), _text(new_value)
        if old_text == new_text:
            continue
        changed.append({"field": name, "label": labels.get(name, name),
                        "old": old_text, "new": new_text})

    changed.sort(key=lambda item: order.get(item["field"], last))
    return changed


def record(instance, table, user, before=None, source=SITE):
    """Записывает правку в историю. Возвращает запись или None.

    ``before`` — снимок до правки; пусто означает заведение новой записи, и
    тогда в историю попадают заполненные поля как «стало».

    История — не часть сохранения компонента: если записать её не удалось,
    сама правка уже в базе и терять её из-за этого нельзя. Поэтому ошибка
    базы здесь гасится.
    """
    before = before or {}
    after = snapshot(instance)
    changed = diff(before, after, type(instance))
    if not changed:
        return None

    action = (ComponentChange.UPDATED if before
              else ComponentChange.CREATED)
    return _save(table, instance.pk, user, action, source, changed)


def record_deletion(instance, table, user, source=SITE):
    """Записывает удаление компонента вместе с тем, что в нём было.

    Значения сохраняются здесь и больше нигде: карточки у удалённой записи
    не останется, а вопрос «что там было до удаления» возникает как раз
    после него. Смотреть — в админке, раздел «История изменений».

    Вызывается до ``delete()``, пока запись ещё цела и у неё есть ключ.
    """
    values = snapshot(instance)
    labels = {f.name: str(f.verbose_name) for f in instance._meta.fields}
    changes = [{"field": name, "label": labels.get(name, name),
                "old": _text(value), "new": ""}
               for name, value in values.items() if _text(value)]

    return _save(table, instance.pk, user, ComponentChange.DELETED, source,
                 changes)


def record_duplicate(instance, table, user, matches, source=SITE):
    """Записывает, что компонент заведён поверх уже похожего.

    Форма такие совпадения не пропускает молча — она отказывает и требует
    подтверждения (``components.forms``). Подтверждение бывает законным:
    иногда это правда разные детали. Но след должен остаться, иначе
    выяснить, откуда в библиотеке взялась пара близнецов, будет не по чему.

    Пишется отдельной записью, а не полем в записи о заведении: это разные
    события, и по списку истории видно оба.
    """
    changes = [{"table": match["category"].table,
                "id": match["obj"].pk,
                "title": match["obj"].display_title(),
                "reason": match.get("reason", "")}
               for match in matches]
    if not changes:
        return None

    return _save(table, instance.pk, user, ComponentChange.DUPLICATE, source,
                 changes)


def image_changes(footprint, old="", new=""):
    """Что записать о картинке: одно «поле» — имя STEP-файла до и после.

    Формат тот же, что у правки полей, — запись журнала показывает его
    обычной таблицей «было — стало», без отдельной разметки. Удаление —
    это «после» пустое, первая загрузка — пустое «до».

    Посадочное место стоит в подписи: картинка общая для всех компонентов
    с ним, и по записи должно быть видно, что поменялось не только здесь.
    """
    return [{"field": "image",
             "label": f"Изображение посадочного места {footprint}",
             "old": old or "", "new": new or ""}]


def record_image(table, component_id, author, footprint, old="", new="",
                 source=SITE):
    """Записывает загрузку, замену или удаление картинки посадочного места.

    Ставится тому компоненту, из карточки которого действовали: журнал
    ведётся по компонентам, а у картинки своего нет. ``author`` —
    пользователь или уже логин строкой: рендер идёт в фоне, и к моменту
    записи запроса с пользователем давно нет, есть только логин в заявке.
    """
    if not table or component_id is None:
        return None
    return _save(table, component_id, author, ComponentChange.IMAGE, source,
                 image_changes(footprint, old, new))


@fallback(None, "запись в журнал изменений")
def _save(table, component_id, user, action, source, changes):
    """Общая запись в журнал. Ошибка базы гасится — см. record()."""
    return ComponentChange.objects.create(
        component_table=table, component_id=component_id,
        author=_username(user), action=action, source=source,
        changes=changes)


def _username(user):
    # логин строкой — у записей из фона, где пользователя-объекта уже нет
    if isinstance(user, str):
        return user
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    return user.get_username()


@fallback(dict, "имена сотрудников для журнала")
def author_names(logins):
    """``{логин: «Фамилия Имя»}`` для тех, у кого имя заполнено.

    Одним запросом на всю страницу, а не по запросу на строку.

    В журнале хранится логин, а не имя: логин у сотрудника один и не
    меняется, а фамилия может смениться — и тогда старые записи остались бы
    подписаны по-старому. Имя подставляется при показе, поэтому история
    всегда согласована с текущим списком пользователей.
    """
    logins = {login for login in logins if login}
    if not logins:
        return {}

    User = get_user_model()
    found = User.objects.filter(username__in=logins).values_list(
        "username", "first_name", "last_name")

    names = {}
    for login, first, last in found:
        full = f"{last} {first}".strip()
        if full:
            names[login] = full
    return names


def with_authors(changes):
    """Проставляет каждой записи ``author_display``.

    Если имя не заполнено или учётную запись удалили, остаётся логин: в
    журнале лучше показать логин, чем прочерк.
    """
    names = author_names(change.author for change in changes)
    for change in changes:
        change.author_display = names.get(change.author) or change.author
    return changes


def log_queryset(filters):
    """Записи журнала по фильтрам. Возвращает queryset, а не список.

    Постраничный показ читает из базы только свою порцию: записей в журнале
    со временем станет больше, чем во всей библиотеке — правок у компонента
    много, а компонент один.

    ``filters`` — строка запроса (``QueryDict``) или обычный словарь;
    неизвестные и пустые значения игнорируются, поэтому чужой параметр в
    адресе ничего не ломает.

    Событие, сотрудник и таблица принимают по нескольку значений, как
    фильтры над списком компонентов: ``?action=created|deleted`` — это
    «добавлен или удалён». Разные фильтры между собой по-прежнему по «и».
    """
    found = ComponentChange.objects.all()

    # неизвестное событие отбрасывается, а не превращается в пустой ответ:
    # ссылку с событием, которое потом переименуют, лучше показать шире,
    # чем пустой
    known = dict(ComponentChange.ACTIONS)
    actions = [value for value in values_of(filters, "action")
               if value in known]
    if actions:
        found = found.filter(action__in=actions)

    tables = values_of(filters, "table")
    if tables:
        found = found.filter(component_table__in=tables)

    authors = values_of(filters, "author")
    if authors:
        found = found.filter(author__in=authors)

    since = _date(filters.get("since"))
    if since:
        found = found.filter(created__date__gte=since)

    until = _date(filters.get("until"))
    if until:
        # включительно: «по 5 сентября» человек понимает как «весь день»
        found = found.filter(created__date__lte=until)

    return found


# Сортировка журнала щелчком по заголовку, как у списка компонентов.
# Компонент — по таблице, затем по ключу: так правки одной записи стоят
# рядом. «Полей изменено» не сортируется: это длина JSON, и считать её в
# базе ради сортировки незачем.
LOG_SORTS = {
    "action": ("action",),
    "created": ("created",),
    "author": ("author",),
    "component": ("component_table", "component_id"),
}
# без выбранной сортировки — новые сверху, как и было
LOG_DEFAULT_ORDER = ("-created", "-id")


def log_order(params):
    """``(поля для order_by, sort, dir)`` по строке запроса.

    Последним всегда идёт ``-id``: у правок одной секунды и одного автора
    порядок иначе был бы случайным и менялся бы от страницы к странице.
    Неизвестная колонка — порядок по умолчанию, а не ошибка.
    """
    sort = params.get("sort") or ""
    if sort not in LOG_SORTS:
        return LOG_DEFAULT_ORDER, "", "asc"
    direction = "desc" if params.get("dir") == "desc" else "asc"
    prefix = "-" if direction == "desc" else ""
    return ((*(prefix + name for name in LOG_SORTS[sort]), "-id"),
            sort, direction)


def log_filtering(filters):
    """Сужен ли журнал — выбрано ли событие, сотрудник, таблица или дата.

    Решает, показывать ли «Сбросить» (как ``listing.filtering`` у списка
    компонентов): число строк и сортировка в адресе — не отбор.
    """
    return (any(values_of(filters, key) for key in ("action", "table", "author"))
            or bool(_date(filters.get("since")) or _date(filters.get("until"))))


def _date(value):
    """Дата из поля формы (``2026-09-05``) или None."""
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def author_logins():
    """Логины, встречающиеся в журнале, по одному разу.

    Через ``distinct_values``: у журнала есть сортировка по умолчанию, и без
    её сброса сотрудник попадал в список столько раз, сколько правок
    сделал. Порядок здесь не нужен: вызывающий сортирует логины сам.
    """
    return distinct_values(ComponentChange.objects.exclude(author=""),
                           "author")


@fallback(list, "список авторов журнала")
def log_authors():
    """Логины, встречающиеся в журнале, с именами — для выпадающего списка.

    Отдаёт пары ``(логин, как показать)``. Список короткий: сотрудников
    единицы, а не тысячи.
    """
    logins = sorted(author_logins())
    names = author_names(logins)
    return [(login, names.get(login) or login) for login in logins]


@fallback(list, "история правок компонента")
def history(table, component_id, limit=CARD_LIMIT):
    """Последние правки компонента — для списка в карточке."""
    found = list(ComponentChange.objects
                 .filter(component_table=table, component_id=component_id)
                 [:limit])
    return with_authors(found)
