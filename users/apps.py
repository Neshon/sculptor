from django.apps import AppConfig


class UsersConfig(AppConfig):
    # AutoField, как у стандартного пользователя Django: модель встаёт на
    # его существующую таблицу, и ключ там — обычный integer. С BigAutoField
    # Django решил бы, что колонку надо расширить, и завёл бы миграцию
    default_auto_field = "django.db.models.AutoField"
    name = "users"
    verbose_name = "Пользователи"

    def ready(self):
        """Журнал доступа ведут сигналы — см. users/access.py, почему так."""
        from django.contrib.auth.signals import (
            user_logged_in,
            user_logged_out,
            user_login_failed,
        )
        from django.db.models.signals import m2m_changed

        from . import access
        from .models import User

        user_logged_in.connect(access.on_login, dispatch_uid="access-login")
        user_login_failed.connect(access.on_login_failed,
                                  dispatch_uid="access-login-failed")
        user_logged_out.connect(access.on_logout, dispatch_uid="access-logout")
        m2m_changed.connect(access.on_groups_changed,
                            sender=User.groups.through,
                            dispatch_uid="access-groups")
