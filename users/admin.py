"""Пользователи в админке — тем же видом, что стандартные, плюс сведения о сотруднике.

``UserAdmin`` из Django подходит почти без изменений: модель унаследована
от ``AbstractUser``. Свои поля (отдел, должность) идут
отдельным блоком «Сотрудник» — сразу после личных данных.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import AccessEvent, User

EMPLOYEE_FIELDS = ("department", "position")


def _with_employee_block(fieldsets):
    """Стандартные блоки UserAdmin и «Сотрудник» после личных данных."""
    blocks = list(fieldsets)
    blocks.insert(2, ("Сотрудник", {"fields": EMPLOYEE_FIELDS}))
    return tuple(blocks)


@admin.register(User)
class SculptorUserAdmin(UserAdmin):
    list_display = ("username", "last_name", "first_name", "department",
                    "position", "is_staff", "is_active", "last_login")
    list_filter = ("is_staff", "is_superuser", "is_active", "groups",
                   "department")
    search_fields = UserAdmin.search_fields + EMPLOYEE_FIELDS
    fieldsets = _with_employee_block(UserAdmin.fieldsets)


@admin.register(AccessEvent)
class AccessEventAdmin(admin.ModelAdmin):
    """Журнал доступа — только смотреть.

    Запись, которую можно поправить, перестаёт быть свидетельством. На
    сайте тот же журнал — страница «Журнал доступа» у администратора.
    """

    list_display = ("created", "kind", "username", "detail", "actor", "ip")
    list_filter = ("kind",)
    search_fields = ("username", "actor", "ip", "detail")
    date_hierarchy = "created"
    readonly_fields = [field.name for field in AccessEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
