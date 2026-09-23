"""Фильтры над списками: компоненты и журнал изменений.

Вынесено из :mod:`components.forms`, где теперь только форма компонента.
Фильтры у двух списков должны выглядеть и вести себя одинаково, поэтому
выпадающий фильтр собирается в одном месте — :func:`filter_field`.
"""

from django import forms

from .querystring import values_of


class FilterSelect(forms.SelectMultiple):
    """Список фильтра: значения в строке запроса разделены вертикальной чертой.

    Браузер сам отправил бы их повторяющимся параметром; страница склеивает
    их в один — так ссылку проще прочитать и переслать. Разбор здесь нужен,
    чтобы форма отметила выбранное, когда страница открыта по такой ссылке.
    """

    def value_from_datadict(self, data, files, name):
        return values_of(data, name)


class FilterForm(forms.Form):
    """Фильтры над списком. Значения подставляются из самой таблицы.

    Каждый фильтр принимает несколько значений сразу: выбранные уходят в
    строку запроса одним и тем же именем (``?vendor=TDK&vendor=Murata``) и
    складываются по «или». Пустого варианта «все» в списке нет: пока ничего
    не выбрано, фильтр и так не применяется, а на кнопке стоит его название
    (его берёт из ``data-title`` скрипт выпадающего списка).
    """

    q = forms.CharField(required=False, label="Поиск")

    def __init__(self, *args, filters=(), **kwargs):
        """filters — список (имя поля, подпись, доступные значения)."""
        super().__init__(*args, **kwargs)
        # Класс здесь остаётся руками, в отличие от остальных форм: панель
        # фильтров рисуется в list.html напрямую ({{ form.q }}), мимо
        # crispy, — а значит и конвертеры до неё не доходят.
        # Кнопки «Применить» у фильтров нет. Выпадающие фильтры отправляют
        # форму сами (data-autosubmit), поиск — по мере ввода, с паузой
        # (data-autosubmit-typing, только с HTMX: без него каждая пауза
        # перезагружала бы страницу) или по Enter: у формы с одним
        # текстовым полем браузер отправляет её сам.
        #
        # hx-preserve: при обновлении панели поле остаётся тем же элементом.
        # Иначе HTMX подставил бы поле из ответа — со значением на момент
        # запроса, — и буквы, набранные, пока запрос шёл, пропали бы.
        self.fields["q"].widget.attrs.update(
            {"class": "field field--search", "type": "search",
             "placeholder": "Поиск по списку",
             # по каким полям ищет — в подсказке: в подписи не поместится
             "title": "PN, описание, производитель",
             "autocomplete": "off",
             "data-autosubmit-typing": "1",
             "hx-preserve": "true"})
        for name, label, values in filters:
            self.fields[name] = filter_field(label, [(v, v) for v in values])


def filter_field(label, choices):
    """Выпадающий фильтр с галочками — один на все списки сайта.

    ``choices`` — пары (значение, как показать). Подпись стоит на кнопке,
    пока ничего не выбрано; выбор отправляет форму сразу. Вид и поведение
    у фильтров компонентов и журнала должны совпадать, поэтому поле
    собирается здесь, а не в каждой форме заново.
    """
    return forms.MultipleChoiceField(
        required=False,
        label=label,
        choices=list(choices),
        widget=FilterSelect(attrs={
            "class": "field field--select",
            "data-autosubmit": "1",
            "data-title": str(label),
        }),
    )


class ChangeFilterForm(forms.Form):
    """Фильтры журнала изменений — теми же списками, что над компонентами.

    Поиска нет: в записи журнала хранится таблица и ключ компонента, а не
    его PN, и искать по ним нечего. Даты рисуются в шаблоне руками: как им
    применяться, зависит от того, есть ли HTMX (см. changes.html).

    Варианты передаёт вид: события — из ``ComponentChange.ACTIONS``,
    сотрудники — из журнала, таблицы — из реестра.
    """

    def __init__(self, *args, actions=(), authors=(), tables=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["action"] = filter_field("Событие", actions)
        self.fields["author"] = filter_field("Сотрудник", authors)
        self.fields["table"] = filter_field(
            "Таблица", [(name, name) for name in tables])
