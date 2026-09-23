"""Раздел «Конструктор выпадающих списков»: столбцы и их значения.

Как устроен сам справочник и почему так — в components.options и
docs/components.md, раздел «Конструктор выпадающих списков». Здесь —
только то, как его правят в админке.
"""

from django import forms
from django.contrib import admin, messages
from django.db.models import Count
from django.urls import reverse
from django.utils.html import format_html

from ..cache import drop_options
from ..models import OptionField, OptionValue
from ..options import (
    field_choices,
    overlapping,
    parse_values,
    source_categories,
    table_choices,
    tables_without,
    values_in_data,
)
from ..registry import MAIN_CATEGORIES, counterpart, table_title
from ..templatetags.components_extras import plural

VALUE_FORMS = "значение,значения,значений"

# Сколько значений ещё правится прямо на странице столбца. Каждое значение —
# пять полей формы, а Django принимает не больше 1000 полей за раз
# (DATA_UPLOAD_MAX_NUMBER_FIELDS): у футпринтов разъёмов — почти пятьсот
# значений, и сохранение такой страницы падало с ошибкой 400, даже если
# поменяли одну галочку. Длинный список правится отдельной страницей, по
# сотне строк.
VALUES_INLINE_LIMIT = 100

VALUE_MAX_LENGTH = OptionValue._meta.get_field("value").max_length


def _value_count(option_field):
    """Число значений: из счётчика запроса, а без него — у базы.

    Страница столбца берёт запись через get_queryset админки, и счётчик
    там уже есть; отдельный COUNT нужен только записи, пришедшей иначе.
    """
    counted = getattr(option_field, "values_total", None)
    return counted if counted is not None else option_field.values.count()


class TablesGridWidget(forms.CheckboxSelectMultiple):
    """Таблицы сеткой: строка — группа, колонки — рабочая таблица и замены.

    Двадцать семь галочек одной колонкой читались плохо, а списки почти
    всегда заводятся парой «таблица + её замены» — подгруппы у них общие.
    В сетке пара стоит в одной строке, щелчок по названию группы отмечает
    обе; кнопки сверху отмечают все рабочие или все замены.

    Без скрипта это обычные галочки: кнопки остаются скрытыми.
    """

    template_name = "components/widgets/option_tables.html"

    class Media:
        js = ("components/option-tables.js",)

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["rows"] = table_rows()
        context["widget"]["chosen"] = set(context["widget"]["value"] or ())
        return context


def table_rows():
    """Строки сетки: ``{title, main, replacement}``; у PCB замен нет."""
    rows = []
    for category in MAIN_CATEGORIES:
        pair = counterpart(category)
        rows.append({"title": category.title, "main": category.table,
                     "replacement": pair.table if pair else ""})
    return rows


class OptionFieldForm(forms.ModelForm):
    """Столбец, таблицы и новые значения списка."""

    field = forms.ChoiceField(
        label="Столбец",
        help_text="Один столбец можно завести несколько раз — с разными "
                  "наборами таблиц")
    tables = forms.MultipleChoiceField(
        required=False,
        label="Таблицы",
        help_text="Ничего не отмечено — список работает во всех таблицах",
        widget=TablesGridWidget,
    )
    # Подпись и подсказка — здесь, а не в модели: там они уходят в
    # миграции. Раньше подсказка обещала «как столбец называть в
    # интерфейсе», но сайт это поле не показывает нигде: оно служит только
    # тому, чтобы отличать в админке списки одного столбца
    # («subgroup_RESISTOR»). Показывать его на сайте значило бы вывести эти
    # служебные имена в формы.
    label = forms.CharField(
        required=False,
        max_length=OptionField._meta.get_field("label").max_length,
        label="Название в админке",
        help_text="Чтобы отличать списки одного столбца, например "
                  "«Подгруппы резисторов». На сайте не показывается")
    new_values = forms.CharField(
        required=False,
        label="Новые значения",
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="По одному в строке. Пустые строки, повторы и уже "
                  "заведённые значения пропускаются")
    collect_values = forms.BooleanField(
        required=False,
        label="Добавить значения из данных",
        help_text="Соберёт всё, что уже записано в этом столбце в отмеченных "
                  "таблицах (ничего не отмечено — во всех, где он есть). "
                  "То же делает команда load_options")

    class Meta:
        model = OptionField
        fields = ("field", "label", "tables", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["field"].choices = (
            [("", "—")] + field_choices(self.instance.field))
        self.fields["tables"].choices = table_choices()
        if self.instance.pk:
            self.initial["tables"] = self.instance.tables or []

    def clean_tables(self):
        return list(self.cleaned_data["tables"])

    def clean_new_values(self):
        values = parse_values(self.cleaned_data.get("new_values"))
        too_long = [value for value in values
                    if len(value) > VALUE_MAX_LENGTH]
        if too_long:
            raise forms.ValidationError(
                f"Длиннее {VALUE_MAX_LENGTH} символов: "
                + "; ".join(value[:40] + "…" for value in too_long))
        return values

    def clean(self):
        cleaned = super().clean()
        field = cleaned.get("field")
        tables = cleaned.get("tables") or []
        if not field:
            return cleaned

        missing = tables_without(field, tables)
        if missing:
            self.add_error("tables", (
                f"В таблицах {', '.join(table_title(t) for t in missing)} "
                f"нет колонки {field}: список там не появится. Снимите их."))

        # отключённый список ни с кем не сливается — проверять нечего
        if cleaned.get("is_active"):
            others = (OptionField.objects.filter(field=field, is_active=True)
                      .exclude(pk=self.instance.pk))
            for other, common in overlapping(
                    tables, [(other, other.tables) for other in others]):
                where = (", ".join(f"«{table_title(t)}»" for t in common)
                         if common else "всех таблиц")
                url = reverse("admin:components_optionfield_change",
                              args=[other.pk])
                self.add_error(None, format_html(
                    "У столбца {} уже есть список для {}: "
                    '<a href="{}">{}</a>. Значения двух списков сливались бы '
                    "молча — добавьте их в тот список или снимите общие "
                    "таблицы.", field, where, url, other))
        return cleaned


class OptionValueInline(admin.TabularInline):
    """Значения столбца правятся прямо на его странице — пока их немного."""

    model = OptionValue
    fields = ("value", "is_active")
    # без заготовок: новые значения вписываются списком в «Новые значения»,
    # а строка по одной — ссылкой под таблицей
    extra = 0
    # Ссылку под таблицей Django собирает как «Добавить еще один
    # {verbose_name}» — со словом среднего рода выходило «еще один
    # Значение». Слово мужского рода читается правильно
    verbose_name = "вариант"
    verbose_name_plural = "Значения выпадающего списка"


@admin.register(OptionField)
class OptionFieldAdmin(admin.ModelAdmin):
    form = OptionFieldForm
    inlines = [OptionValueInline]
    # Без __str__ в первой колонке: без названия он повторяет имя столбца,
    # и строки одного столбца с разными таблицами выглядели одинаково —
    # тринадцать «allegro_pcb_footprint allegro_pcb_footprint» подряд.
    # Различает их набор таблиц, поэтому он идёт сразу за столбцом.
    list_display = ("field", "table_list", "title", "value_count", "is_active")
    list_display_links = ("field",)
    list_filter = ("is_active", "field")
    search_fields = ("field", "label", "values__value")
    save_on_top = True
    readonly_fields = ("values_link",)

    def get_fieldsets(self, request, obj=None):
        # у нового столбца смотреть ещё нечего — только вписать значения
        values = (("new_values", "collect_values", "values_link") if obj
                  else ("new_values", "collect_values"))
        return (
            (None, {
                "fields": ("field", "label", "is_active"),
                "description": "Пока список активен, поле показывается "
                               "выпадающим списком в формах и в фильтрах "
                               "над таблицей.",
            }),
            ("Где работает", {"fields": ("tables",)}),
            ("Значения", {"fields": values}),
        )

    def get_inlines(self, request, obj):
        if obj is not None and _value_count(obj) > VALUES_INLINE_LIMIT:
            return []
        return self.inlines

    def get_queryset(self, request):
        # Число значений — счётчиком в запросе. Раньше ради него читались
        # все значения всех списков (больше тысячи строк), чтобы посчитать
        # их в питоне. distinct — на случай поиска по значениям: он
        # добавляет join к той же таблице
        return super().get_queryset(request).annotate(
            values_total=Count("values", distinct=True))

    def save_related(self, request, form, formsets, change):
        """Значения из «Новые значения» — после того, как столбец сохранён.

        Одним запросом, а не по записи: список вставляют и на сотни строк.
        ``bulk_create`` не шлёт ``post_save``, поэтому кэш справочника
        сбрасывается здесь — иначе новые значения появились бы в формах
        только через срок жизни кэша.
        """
        super().save_related(request, form, formsets, change)
        option_field = form.instance
        values = list(form.cleaned_data.get("new_values") or [])

        collected = []
        if form.cleaned_data.get("collect_values"):
            collected = self._collect(request, option_field)
            values += [value for value in collected if value not in values]
        if not values:
            return

        existing = set(option_field.values.values_list("value", flat=True))
        fresh = [value for value in values if value not in existing]
        OptionValue.objects.bulk_create(
            [OptionValue(option_field=option_field, value=value)
             for value in fresh],
            ignore_conflicts=True)
        drop_options()

        skipped = len(values) - len(fresh)
        messages.info(
            request,
            f"Добавлено: {plural(len(fresh), VALUE_FORMS)}"
            + (f", уже были в списке: {skipped}" if skipped else "")
            + (f" (в данных найдено: {len(collected)})"
               if form.cleaned_data.get("collect_values") else "")
            + ".")

    def _collect(self, request, option_field):
        """Значения столбца из таблиц компонентов — как в load_options."""
        categories = source_categories(option_field.field, option_field.tables)
        found, failed = values_in_data(categories, option_field.field)
        if failed:
            messages.warning(
                request,
                "Не прочитались таблицы "
                + ", ".join(table_title(table) for table in failed)
                + " — их значения не собраны.")
        return found

    @admin.display(description="Все значения")
    def values_link(self, obj):
        count = _value_count(obj)
        url = (reverse("admin:components_optionvalue_changelist")
               + f"?option_field__id__exact={obj.pk}")
        note = ("" if count <= VALUES_INLINE_LIMIT else
                " — список длинный, поэтому правится там: поиск, "
                "отключение и удаление")
        return format_html('<a href="{}">{} — открыть списком</a>{}',
                           url, plural(count, VALUE_FORMS), note)

    @admin.display(description="Название", ordering="label")
    def title(self, obj):
        return obj.label or "—"

    @admin.display(description="Значений", ordering="values_total")
    def value_count(self, obj):
        return obj.values_total

    @admin.display(description="Таблицы")
    def table_list(self, obj):
        # названиями групп, как в фильтре журнала: z_RESISTOR человеку
        # приходится расшифровывать
        return (", ".join(table_title(table) for table in obj.tables)
                if obj.tables else "все")


@admin.register(OptionValue)
class OptionValueAdmin(admin.ModelAdmin):
    """Значения одного списка — отдельной страницей, с поиском и по сотне.

    Открывается ссылкой со страницы столбца; в меню админки её нет —
    значения без своего столбца смысла не имеют. Новые значения здесь не
    заводятся: для этого на странице столбца есть «Новые значения».
    """

    list_display = ("value", "option_field", "is_active")
    list_display_links = ("value",)
    list_editable = ("is_active",)
    list_filter = ("is_active",)
    list_select_related = ("option_field",)
    search_fields = ("value",)
    list_per_page = 100
    ordering = ("value",)
    fields = ("option_field", "value", "is_active")
    readonly_fields = ("option_field",)
    actions = ("activate", "deactivate")

    def has_module_permission(self, request):
        return False

    def has_add_permission(self, request):
        return False

    def changelist_view(self, request, extra_context=None):
        option_field = self._option_field(request)
        if option_field is not None:
            extra_context = {"title": f"Значения: {option_field}",
                             **(extra_context or {})}
        return super().changelist_view(request, extra_context)

    @staticmethod
    def _option_field(request):
        pk = request.GET.get("option_field__id__exact", "")
        if not pk.isdigit():
            return None
        return OptionField.objects.filter(pk=pk).first()

    @admin.action(description="Включить выбранные значения")
    def activate(self, request, queryset):
        self._set_active(request, queryset, True)

    @admin.action(description="Отключить выбранные значения")
    def deactivate(self, request, queryset):
        self._set_active(request, queryset, False)

    def _set_active(self, request, queryset, active):
        # update() не шлёт post_save — кэш справочника сбрасываем сами
        changed = queryset.update(is_active=active)
        drop_options()
        messages.success(request, f"{'Включено' if active else 'Отключено'}: "
                                  f"{plural(changed, VALUE_FORMS)}.")
