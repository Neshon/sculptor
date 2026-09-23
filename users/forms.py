"""Формы раздела пользователей."""

from django import forms

from components.filter_forms import filter_field

from .models import AccessEvent


class AccessFilterForm(forms.Form):
    """Фильтры журнала доступа — теми же списками, что над компонентами.

    Вид и поведение у фильтров всех журналов должны совпадать, поэтому поле
    собирает общий filter_field. Сотрудники — те, что встречаются в журнале:
    неудачную попытку входа делают и под логином, которого нет.
    """

    def __init__(self, *args, usernames=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["kind"] = filter_field("Событие", AccessEvent.KINDS)
        self.fields["username"] = filter_field(
            "Сотрудник", [(name, name) for name in usernames])
