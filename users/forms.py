"""Формы раздела пользователей."""

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

from components.filter_forms import filter_field

from .models import AccessEvent
from .roles import ROLES


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


class UserCreateForm(UserCreationForm):
    """Новый сотрудник: учётная запись, сведения о нём и роли проекта.

    Основа — штатная форма Django: она проверяет логин без учёта регистра
    («Ivanov» и «ivanov» — один человек), сверяет два ввода пароля и гоняет
    пароль через AUTH_PASSWORD_VALIDATORS. Свои проверки здесь были бы
    копией этих и рано или поздно от них отстали бы.

    Фамилия и имя обязательны: журналы показывают сотрудника по имени, и
    запись с одним логином там читалась бы как безымянная. Суперпользователя
    и доступ к админке здесь не выдают — как и на странице ролей, это
    делается в админке, осознанно.
    """

    roles = forms.MultipleChoiceField(
        label="Роли", required=False, widget=forms.CheckboxSelectMultiple,
        choices=[(name, name) for name in ROLES],
        help_text="Можно не отмечать: сотрудник без ролей только смотрит.")

    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username", "last_name", "first_name", "email",
                  "department", "position")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ("last_name", "first_name"):
            self.fields[name].required = True
        # «Имя пользователя» у Django рядом с полем «Имя» читалось как оно
        # же; на сайте это везде логин
        self.fields["username"].label = "Логин"
        # браузер не должен подставлять сюда свой сохранённый пароль: это
        # пароль нового сотрудника, а не администратора
        for name in ("password1", "password2"):
            self.fields[name].widget.attrs["autocomplete"] = "new-password"
        self.fields["username"].widget.attrs["autocomplete"] = "off"

    def role_rows(self):
        """``[(роль, описание, отмечена ли)]`` — для галочек в шаблоне."""
        chosen = set(self["roles"].value() or [])
        return [(name, description, name in chosen)
                for name, description in ROLES.items()]
