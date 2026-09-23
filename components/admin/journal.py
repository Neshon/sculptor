"""Раздел «Журнал и изображения»: история правок, картинки, заявки на рендер.

Всё здесь смотрят, а не правят: историю — потому что запись, которую можно
отредактировать, перестаёт быть свидетельством; картинки и заявки —
потому что их источник, STEP-модель, в базе не хранится.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from ..db import distinct_values
from ..models import ComponentChange, FootprintImage, StepRenderJob
from ..refs import component_titles
from ..registry import table_title


class ComponentTableFilter(admin.SimpleListFilter):
    """Фильтр по таблице — названиями групп, а не именами таблиц в базе.

    В списке только те таблицы, что встречаются в журнале: пустые варианты
    фильтра — шум, а таблиц 27.
    """

    title = "Таблица компонента"
    parameter_name = "component_table"

    def lookups(self, request, model_admin):
        tables = distinct_values(model_admin.get_queryset(request),
                                 "component_table")
        return sorted(((table, table_title(table)) for table in tables),
                      key=lambda pair: pair[1])

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(component_table=self.value())
        return queryset


@admin.register(ComponentChange)
class ComponentChangeAdmin(admin.ModelAdmin):
    """История правок — только для чтения.

    Править историю через админку нельзя: запись, которую можно
    отредактировать, перестаёт быть свидетельством. Удалять — можно, иначе
    от старых записей не избавиться, когда их станет слишком много.
    """

    list_display = ("created", "author", "action", "table", "component",
                    "fields_count", "source")
    list_filter = ("action", "source", ComponentTableFilter)
    search_fields = ("author", "component_table")
    date_hierarchy = "created"
    ordering = ("-created",)

    def view_on_site(self, obj):
        # на сайте запись показана по-человечески: было и стало рядом,
        # а здесь поле changes — сырой JSON
        return reverse("components:change", args=[obj.pk])

    def get_changelist_instance(self, request):
        """Названия компонентов для страницы — пачкой, до отрисовки.

        Спрашивать их из колонки значило бы запрос на строку, по разным
        таблицам. Здесь — один на таблицу, для той полусотни записей, что
        попала на страницу.
        """
        changelist = super().get_changelist_instance(request)
        changelist.result_list = list(changelist.result_list)
        titles = component_titles(
            (change.component_table, change.component_id)
            for change in changelist.result_list)
        for change in changelist.result_list:
            key = (change.component_table, change.component_id)
            if key in titles:
                change.component_title = titles[key]
        return changelist

    @admin.display(description="Таблица", ordering="component_table")
    def table(self, obj):
        return table_title(obj.component_table)

    @admin.display(description="Компонент", ordering="component_id")
    def component(self, obj):
        if not hasattr(obj, "component_title"):
            # проверить не удалось — показываем то, что записано
            return f"#{obj.component_id}"
        if obj.component_title is None:
            return f"#{obj.component_id} · удалён"
        return format_html('<a href="{}">{}</a> #{}', obj.component_url,
                           obj.component_title, obj.component_id)

    @admin.display(description="Полей")
    def fields_count(self, obj):
        return obj.fields_count

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(FootprintImage)
class FootprintImageAdmin(admin.ModelAdmin):
    """Картинки посадочных мест — посмотреть и удалить.

    Заводят их загрузкой STEP-модели — из карточки компонента или командой
    render_step_images: картинка получается из файла, который мы не храним,
    поэтому выбрать её здесь с диска нечем. Удаление оставлено: убрать
    неудачный рендер у посадочного места, которого больше нет ни у одного
    компонента, иначе негде.
    """

    list_display = ("footprint", "source_name", "author", "created")
    search_fields = ("footprint", "source_name", "author")
    date_hierarchy = "created"
    ordering = ("footprint",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def delete_queryset(self, request, queryset):
        """Пакетное удаление — через модель, чтобы ушли и файлы.

        Django удаляет пачку одним запросом, минуя ``delete()`` модели, и
        картинки остались бы на диске навсегда.
        """
        for image in queryset:
            image.delete()


@admin.register(StepRenderJob)
class StepRenderJobAdmin(admin.ModelAdmin):
    """Заявки на рендер — только смотреть.

    Здесь видно, что происходит с фоновым рендером: что стоит в очереди,
    что не отрисовалось и почему. Править заявку незачем — повторить
    рендер проще новой загрузкой модели.
    """

    list_display = ("created", "footprint", "status", "source_name",
                    "author", "finished")
    list_filter = ("status",)
    search_fields = ("footprint", "source_name", "author")
    date_hierarchy = "created"
    ordering = ("-created",)
    readonly_fields = [field.name for field in StepRenderJob._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
