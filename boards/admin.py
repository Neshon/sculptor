"""Платы и составы в админке."""

from django.contrib import admin
from django.db.models import Count, OuterRef, Subquery
from django.db.models.functions import Coalesce

from .forms import BoardItemForm
from .linking import MATCH_LABELS, NO_MATCH_LABEL, match_label
from .models import Board, BoardItem, BoardRevision

# Что в строке состава правится руками — ровно то, что в форме на сайте.
# Артикулы и описание пришли из BOM-файла или карточки компонента, связь с
# библиотекой ставит выбор или relink_boards (docs/boards.md, «Компонент
# берётся из библиотеки, и только оттуда»).
ITEM_EDITABLE = tuple(BoardItemForm._meta.fields)

ITEM_FIELDSETS = (
    (None, {"fields": ("revision",) + ITEM_EDITABLE}),
    ("Компонент — из BOM-файла или библиотеки", {
        "fields": ("vendor_pn", "vendor", "country", "oy_id", "oy_pn",
                   "gbt_pn", "group", "subgroup", "description",
                   "description_gbt", "smt_tht", "row"),
    }),
    ("Связь с библиотекой", {
        # match — component_match подписью, а не кодом (BoardItemAdmin.match)
        "fields": ("component_table", "component_id", "match"),
    }),
)


def _count_items(**conditions):
    """Подзапрос «сколько строк состава у ревизии» с условием.

    Подзапросом, а не Count по join: три счётчика по одной связи через join
    перемножили бы строки друг на друга, и цифры вышли бы неверными.
    """
    rows = (BoardItem.objects.filter(revision=OuterRef("pk"), **conditions)
            .order_by().values("revision")
            .annotate(total=Count("pk")).values("total"))
    return Coalesce(Subquery(rows), 0)


# те же счётчики, что свойства BoardRevision.position_count и соседние
REVISION_COUNTS = {
    "positions_total": _count_items(kind=BoardItem.MAIN),
    "items_total": _count_items(),
    "unlinked_total": _count_items(component_id__isnull=True),
}


class MatchFilter(admin.SimpleListFilter):
    """«Как сопоставлено» — подписями правил, а не кодами gbt и vendor."""

    title = "Как сопоставлено"
    parameter_name = "component_match"
    # в адресе пустой параметр не отличить от отсутствующего, поэтому у
    # строк без связи своё значение
    NONE = "none"

    def lookups(self, request, model_admin):
        return [*MATCH_LABELS.items(), (self.NONE, NO_MATCH_LABEL)]

    def queryset(self, request, queryset):
        value = self.value()
        if value == self.NONE:
            return queryset.filter(component_match="")
        if value:
            return queryset.filter(component_match=value)
        return queryset


class BoardItemInline(admin.TabularInline):
    model = BoardItem
    fields = ("position", "kind", "vendor_pn", "vendor", "gbt_pn", "qty",
              "component_table", "component_id")
    readonly_fields = fields
    extra = 0
    can_delete = False
    show_change_link = True
    verbose_name_plural = "Состав · новые строки добавляются на сайте, из библиотеки"

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("base_pn", "name", "board_type", "revision_count",
                    "imported_at")
    search_fields = ("base_pn", "name")
    date_hierarchy = "imported_at"
    readonly_fields = ("imported_at", "imported_by")
    save_on_top = True

    def get_queryset(self, request):
        # число ревизий — одним запросом на страницу, как в списке на
        # сайте; без этого revision_count спрашивал базу по строке
        return super().get_queryset(request).with_counts()

    @admin.display(description="Ревизий", ordering="revisions_total")
    def revision_count(self, obj):
        return obj.revision_count


@admin.register(BoardRevision)
class BoardRevisionAdmin(admin.ModelAdmin):
    """Ревизии создаются импортом BOM, руками их не заводят."""

    list_display = ("board", "oy_pn", "board_rev", "bom_rev",
                    "position_count", "item_count", "unlinked_count",
                    "imported_at")
    list_filter = ("board",)
    search_fields = ("board__base_pn", "oy_pn", "gct_pcb", "gct_bom",
                     "decimal_pcba")
    date_hierarchy = "imported_at"
    inlines = [BoardItemInline]
    readonly_fields = ("board", "number", "oy_pn", "board_rev", "bom_rev",
                       "imported_at", "imported_by")

    def get_queryset(self, request):
        """Три счётчика состава — в том же запросе, что и сами ревизии.

        Свойства модели (position_count и др.) спрашивают базу каждое
        отдельно: на странице в 15 ревизий это было 45 лишних запросов, на
        сотне — триста. Здесь они считаются подзапросами одним заходом.
        """
        return super().get_queryset(request).annotate(**REVISION_COUNTS)

    @admin.display(description="Позиций", ordering="positions_total")
    def position_count(self, obj):
        return obj.positions_total

    @admin.display(description="Строк", ordering="items_total")
    def item_count(self, obj):
        return obj.items_total

    @admin.display(description="Без компонента", ordering="unlinked_total")
    def unlinked_count(self, obj):
        return obj.unlinked_total

    def has_add_permission(self, request):
        return False


@admin.register(BoardItem)
class BoardItemAdmin(admin.ModelAdmin):
    """Строки состава — с теми же правилами, что на сайте.

    Раньше здесь правилось всё подряд: артикулы, описание, пара «таблица +
    ключ». Это ровно то, что на сайте закрыто нарочно, — строка, которая
    ссылается на один компонент, а называется по-другому, и расхождение
    видно только при сверке с библиотекой. Поэтому форма та же
    (``BoardItemForm``), остальное только для чтения, а новых строк здесь не
    заводят: на сайте их берут из библиотеки, и поля переносятся из карточки.
    Удалять можно — как и на сайте.
    """

    form = BoardItemForm
    fieldsets = ITEM_FIELDSETS
    readonly_fields = tuple(
        name for _, options in ITEM_FIELDSETS for name in options["fields"]
        if name not in ITEM_EDITABLE)
    list_display = ("revision", "position", "kind", "vendor_pn", "vendor",
                    "gbt_pn", "qty", "component_table", "component_id")
    list_filter = ("kind", MatchFilter, "revision__board")
    search_fields = ("vendor_pn", "vendor", "gbt_pn", "oy_id", "oy_pn",
                     "description", "references")
    list_select_related = ("revision", "revision__board")
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    @admin.display(description="Как сопоставлено")
    def match(self, obj):
        return match_label(obj.component_match)

    def save_model(self, request, obj, form, change):
        # форма обещает «пусто — следующий свободный номер»; держим слово
        # тем же правилом, что на сайте
        if obj.position is None:
            obj.position = obj.revision.next_position(obj.kind)
        super().save_model(request, obj, form, change)


# Чек-листы в админке отдельной моделью больше не показываются: строки
# перестали быть записями и лежат полем ревизии. Разбирать расхождения
# теперь удобнее на самой странице чек-листов — там видно шаблон целиком,
# а не только заполненные строки.
