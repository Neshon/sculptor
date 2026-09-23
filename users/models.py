"""Пользователь системы — своя модель вместо стандартной.

Сейчас она ничем не отличается от стандартной ``django.contrib.auth``: те же
поля, тот же вход по логину. Смысл в том, чтобы место для перемен было
заранее. Добавить отдел, должность или другое поле — одна
миграция. А заменить модель пользователя, когда на неё уже ссылаются группы,
права и журнал админки, — переезд таблиц (см. ``sql/move_user_to_users.sql``
и раздел о нём в ``docs/schema-history.md``). Этот переезд сделан один раз,
чтобы следующим изменениям он был не нужен.

Правила для всего проекта:

* на пользователя ссылаются только через ``settings.AUTH_USER_MODEL`` во
  внешних ключах и ``get_user_model()`` в коде — прямой импорт класса
  привязал бы код к конкретной модели;
* в журнале изменений автор хранится логином, а не ссылкой: логин не
  меняется, а удалённый сотрудник не должен стирать историю.
"""

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    # Сведения о сотруднике. Заполняет администратор; сам сотрудник видит их
    # в профиле. Необязательные: учётные записи заводились и до них, и
    # требовать заполнения задним числом незачем.
    department = models.CharField(max_length=150, blank=True, default="",
                                  verbose_name="Отдел")
    position = models.CharField(max_length=150, blank=True, default="",
                                verbose_name="Должность")

    class Meta(AbstractUser.Meta):
        # Таблица — users_user, как положено модели этого приложения. На
        # существующей базе она получена переименованием auth_user, а не
        # созданием заново: пользователи, пароли, группы и права остаются
        # на месте
        db_table = "users_user"
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"

    def __str__(self):
        return self.get_full_name() or self.username


class AccessEvent(models.Model):
    """Запись журнала доступа: входы, выходы, неудачные попытки, смена ролей.

    Как и в журнале изменений компонентов, сотрудник хранится логином, а не
    ссылкой: удалённая учётная запись не должна стирать следы, а неудачную
    попытку входа делают как раз под логином, которого может и не быть.

    Роль меняет не сам сотрудник, поэтому у события два логина: ``username``
    — чья роль, ``actor`` — кто поменял. У входа и выхода они совпадают, и
    ``actor`` пуст.
    """

    LOGIN = "login"
    LOGIN_FAILED = "login_failed"
    LOGOUT = "logout"
    ROLE_ADDED = "role_added"
    ROLE_REMOVED = "role_removed"
    KINDS = [
        (LOGIN, "Вход"),
        (LOGIN_FAILED, "Неудачный вход"),
        (LOGOUT, "Выход"),
        (ROLE_ADDED, "Роль выдана"),
        (ROLE_REMOVED, "Роль снята"),
    ]

    # цвет чипа в списке — тем же набором, что у журнала изменений
    CHIP_CLASSES = {LOGIN: "chip--added", LOGIN_FAILED: "chip--gone",
                    LOGOUT: "", ROLE_ADDED: "chip--edited",
                    ROLE_REMOVED: "chip--dup"}

    created = models.DateTimeField(auto_now_add=True, db_index=True,
                                   verbose_name="Когда")
    kind = models.CharField(max_length=16, choices=KINDS,
                            verbose_name="Событие")
    username = models.CharField(max_length=150, verbose_name="Сотрудник")
    actor = models.CharField(max_length=150, blank=True, default="",
                             verbose_name="Кто изменил")
    detail = models.CharField(max_length=255, blank=True, default="",
                              verbose_name="Подробности",
                              help_text="Роль — для выдачи и снятия роли")
    ip = models.GenericIPAddressField(null=True, blank=True,
                                      verbose_name="Адрес")
    user_agent = models.CharField(max_length=255, blank=True, default="",
                                  verbose_name="Браузер")

    class Meta:
        db_table = "users_access_event"
        ordering = ("-created", "-id")
        verbose_name = "событие доступа"
        verbose_name_plural = "Журнал доступа"
        indexes = [models.Index(fields=["username", "-created"],
                                name="access_event_user_idx")]

    def __str__(self):
        return f"{self.get_kind_display()} · {self.username}"

    @property
    def chip_class(self):
        return self.CHIP_CLASSES.get(self.kind, "")
