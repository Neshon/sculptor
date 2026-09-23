"""Таблицы компонентов в админке — та же форма и та же история, что на сайте."""

from django.contrib import admin, messages

from boards.usage import usage_summary

from ..editing import save_component, stored_snapshot
from ..forms import CONFIRM_FIELD, build_form_class, field_sections
from ..history import ADMIN, record_deletion
from ..mixins import SEARCH_FIELDS, field_names
from ..numbering import next_oy_id
from ..registry import CATEGORIES

MAX_BOARDS_IN_WARNING = 10
LIST_FILTERS = ("group", "subgroup", "vendor", "status")

# Поля, которых нет в форме сайта: их заполняет база или сохранение. В
# админке они видны при правке, но не правятся — автор это тот, кто завёл
# запись, и переписать его значило бы подделать историю.
SERVICE_FIELDS = ("id", "author", "created")

# Что админка, в отличие от сайта, даёт править (см. build_form_class)
ADMIN_EDITABLE = ("oy_id",)


def admin_form_class(category):
    """Форма компонента для админки — та же, что на сайте.

    Раньше админка строила обычную форму Django по модели, и правка через
    неё обходила всё, что делает форма сайта: пустые поля ложились в базу
    NULL вместо «---» (его ждут сторонний софт и сопоставление аналогов),
    не проверялись артикулы на чужие алфавиты, обязательные поля и дубли,
    а поля из конструктора выпадающих списков оставались свободным текстом.
    """
    return build_form_class(category.model, category.table,
                            category.hidden_fields, ADMIN_EDITABLE)


SERVICE_TITLE = "Служебное"
DUPLICATE_TITLE = "Похожий компонент"
DUPLICATE_HINT = ("Отметьте, если при сохранении нашёлся компонент с тем же "
                  "Vendor PN или GBT PN, а это другая деталь.")


def admin_fieldsets(names, readonly=()):
    """Секции формы компонента в админке — те же, что на сайте.

    Служебные поля идут первыми: при правке они отвечают на вопрос «что за
    запись передо мной», а в конце длинной формы их никто не видел. Галочка
    подтверждения дубля — последней, отдельно от параметров: нужна она,
    только когда форма нашла совпадение, и сообщение об этом стоит наверху.
    """
    service = [n for n in SERVICE_FIELDS if n in readonly]
    params = [n for n in names if n != CONFIRM_FIELD and n not in service]

    fieldsets = []
    if service:
        fieldsets.append((SERVICE_TITLE, {"fields": service}))
    fieldsets += [(title, {"fields": picked})
                  for title, picked in field_sections(params)]
    if CONFIRM_FIELD in names:
        fieldsets.append((DUPLICATE_TITLE, {"fields": [CONFIRM_FIELD],
                                            "description": DUPLICATE_HINT}))
    return fieldsets


def boards_warning(boards, rows):
    """Текст предупреждения «компонент стоит на платах».

    Плату называет её номер — ``base_pn``. Раньше здесь стояло ``oy_pn``,
    которого у платы нет (он у ревизии), и удаление через админку
    компонента, стоящего хоть на одной плате, падало с ошибкой 500 — ровно
    в том случае, ради которого предупреждение и писалось.
    """
    names = ", ".join(str(entry["board"])
                      for entry in boards[:MAX_BOARDS_IN_WARNING])
    return (f"Компонент стоит в составах плат ({rows} строк): {names}"
            + (" и другие." if len(boards) > MAX_BOARDS_IN_WARNING else ".")
            + " Строки останутся, но потеряют связь с библиотекой.")


class ComponentAdmin(admin.ModelAdmin):
    list_per_page = 50
    save_on_top = True
    show_full_result_count = False
    date_hierarchy = "created"
    # категория реестра; подставляется в _register
    category = None

    def delete_view(self, request, object_id, extra_context=None):
        """Предупреждает, если компонент стоит на платах.

        Django показывает только каскад по своим связям, а связь строк BOM
        внешним ключом не является — про неё он не знает.
        """
        obj = self.get_object(request, object_id)
        if obj is not None:
            boards, rows = usage_summary(obj, self.model._meta.db_table)
            if boards:
                messages.warning(request, boards_warning(boards, rows))
        return super().delete_view(request, object_id, extra_context)

    def get_readonly_fields(self, request, obj=None):
        # у новой записи служебные поля ещё пустые — показывать нечего
        if obj is None:
            return ()
        names = field_names(type(obj))
        return tuple(name for name in SERVICE_FIELDS if name in names)

    def get_fieldsets(self, request, obj=None):
        return admin_fieldsets(self.form.base_fields,
                               self.get_readonly_fields(request, obj))

    def get_changeform_initial_data(self, request):
        """OY ID новой записи — следующий по нумерации, как на сайте.

        Это подсказка, поле остаётся редактируемым. Замене номер не
        подбирается: он должен совпадать с номером основного компонента, а
        какого — админка не знает, и выданный по нумерации был бы ошибкой,
        которую легко не заметить.
        """
        initial = super().get_changeform_initial_data(request)
        category = self.category
        if (category is not None and not category.replacement
                and "oy_id" in category.field_names):
            initial.setdefault("oy_id", next_oy_id(category) or "")
        return initial

    def save_model(self, request, obj, form, change):
        """Сохраняет тем же путём, что и сайт, — с той же историей.

        Через админку правят не реже, чем через сайт, и без этого история в
        карточке была бы с дырами — а история с дырами хуже её отсутствия:
        по ней делают вывод, что запись не трогали. Автор, запись в журнал и
        след подтверждённого дубля — в save_component, одном на оба пути.

        Снимок «до» берётся из базы, а не с объекта: форма уже перенесла на
        него присланные значения.
        """
        before = stored_snapshot(self.model, obj.pk) if change else {}
        save_component(obj, self.model._meta.db_table, request.user, before,
                       getattr(form, "confirmed_duplicates", ()),
                       source=ADMIN)

    def delete_model(self, request, obj):
        """Удаление через админку тоже попадает в историю.

        Запись делается до удаления: после него не останется ни значений,
        ни ключа. Увидеть её можно в разделе «История изменений» — карточки
        у удалённого компонента больше нет.
        """
        record_deletion(obj, self.model._meta.db_table, request.user,
                        source=ADMIN)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """То же для массового удаления из списка.

        Django не зовёт delete_model для каждой записи — иначе групповое
        удаление проходило бы мимо истории целиком, а это как раз тот
        случай, когда позже спрашивают, куда делись полсотни строк.
        """
        table = self.model._meta.db_table
        for obj in queryset:
            record_deletion(obj, table, request.user, source=ADMIN)
        super().delete_queryset(request, queryset)


class ReadOnlyComponentAdmin(ComponentAdmin):
    """Для таблиц, помеченных в реестре read_only: смотреть можно, менять — нет."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


def _admin_options(category):
    """Настройки ModelAdmin, выведенные из реестра и полей модели."""
    names = category.field_names
    has_id = "id" in names
    columns = (["id"] if has_id else []) + list(category.columns)

    options = {
        "category": category,
        "form": admin_form_class(category),
        "list_display": tuple(columns) or ("__str__",),
        "list_filter": tuple(f for f in LIST_FILTERS if f in names),
        "search_fields": tuple(f for f in SEARCH_FIELDS if f in names),
    }
    if has_id:
        options["list_display_links"] = ("id",)
        options["ordering"] = ("-id",)
    elif category.columns:
        options["list_display_links"] = (category.columns[0],)
    if "created" not in names:
        options["date_hierarchy"] = None
    return options


def _register(category):
    base = ReadOnlyComponentAdmin if category.read_only else ComponentAdmin
    admin_class = type(f"{category.model.__name__}Admin", (base,),
                       _admin_options(category))
    admin.site.register(category.model, admin_class)


for _category in CATEGORIES.values():
    _register(_category)
