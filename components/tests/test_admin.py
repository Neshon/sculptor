"""Админка: форма компонента, разделы, журнал, конструктор списков."""

import re
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

from ..registry import CATEGORIES, get_category


class ComponentAdminFormTests(SimpleTestCase):
    """Админка правит компоненты той же формой, что и сайт."""

    def model_admin(self, slug):
        from django.contrib import admin
        return admin.site._registry[get_category(slug).model]

    def test_admin_uses_site_form(self):
        from ..forms import ComponentForm
        for category in CATEGORIES.values():
            with self.subTest(table=category.table):
                form = self.model_admin(category.slug).form
                self.assertTrue(issubclass(form, ComponentForm))
                # по имени таблицы форма находит выпадающие списки
                self.assertEqual(form.option_table, category.table)

    def test_oy_id_editable_service_fields_not(self):
        fields = self.model_admin("resistor").form.base_fields
        self.assertIn("oy_id", fields)
        for name in ("id", "author", "created"):
            self.assertNotIn(name, fields)

    def test_site_form_still_has_no_oy_id(self):
        # поле возвращено только админке: на сайте OY ID назначается сам
        from ..forms import build_form_class
        category = get_category("resistor")
        form = build_form_class(category.model, category.table,
                                category.hidden_fields)
        self.assertNotIn("oy_id", form.base_fields)

    def test_hidden_fields_stay_hidden(self):
        self.assertNotIn("allegro_pcb_footprint",
                         self.model_admin("pcb").form.base_fields)

    def test_service_fields_readonly_on_change(self):
        model_admin = self.model_admin("resistor")
        obj = get_category("resistor").model()
        self.assertEqual(model_admin.get_readonly_fields(None, obj),
                         ("id", "author", "created"))
        self.assertEqual(model_admin.get_readonly_fields(None, None), ())

    def test_new_component_gets_next_oy_id(self):
        request = mock.Mock(GET={})
        with mock.patch("components.admin.components.next_oy_id",
                        return_value="ID_R_001500"):
            initial = self.model_admin("resistor").get_changeform_initial_data(
                request)
        self.assertEqual(initial["oy_id"], "ID_R_001500")

    def test_replacement_gets_no_oy_id(self):
        # у замены OY ID — номер основного компонента, а не следующий
        request = mock.Mock(GET={})
        with mock.patch("components.admin.components.next_oy_id") as numbering:
            initial = self.model_admin(
                "resistorreplacement").get_changeform_initial_data(request)
        numbering.assert_not_called()
        self.assertNotIn("oy_id", initial)



class BoardsWarningTests(SimpleTestCase):
    """Предупреждение при удалении из админки компонента, стоящего на платах."""

    def test_boards_named_by_number(self):
        # у платы нет oy_pn — раньше здесь падало с AttributeError
        from boards.models import Board

        from ..admin.components import boards_warning
        boards = [{"board": Board(base_pn="HSBP-4L01")},
                  {"board": Board(base_pn="HSRB-OCP02")}]
        text = boards_warning(boards, 5)
        self.assertIn("(5 строк): HSBP-4L01, HSRB-OCP02.", text)

    def test_long_list_cut(self):
        from boards.models import Board

        from ..admin.components import MAX_BOARDS_IN_WARNING, boards_warning
        boards = [{"board": Board(base_pn=f"B{i}")}
                  for i in range(MAX_BOARDS_IN_WARNING + 2)]
        text = boards_warning(boards, 12)
        self.assertIn(" и другие.", text)
        self.assertNotIn(f"B{MAX_BOARDS_IN_WARNING}", text)



class AdminFieldsetsTests(SimpleTestCase):
    """Форма компонента в админке разложена по тем же секциям, что на сайте."""

    def fieldsets(self, slug, obj=True):
        from django.contrib import admin
        category = get_category(slug)
        model_admin = admin.site._registry[category.model]
        return model_admin.get_fieldsets(
            None, category.model() if obj else None)

    def titles(self, fieldsets):
        return [title for title, _ in fieldsets]

    def test_sections_like_site(self):
        from ..admin.components import DUPLICATE_TITLE, SERVICE_TITLE
        self.assertEqual(self.titles(self.fieldsets("resistor")),
                         [SERVICE_TITLE, "Основные сведения",
                          "Электрические параметры", "Физические параметры",
                          DUPLICATE_TITLE])

    def test_service_first_only_on_change(self):
        from ..admin.components import SERVICE_TITLE
        first = self.fieldsets("resistor")[0]
        self.assertEqual(first, (SERVICE_TITLE,
                                 {"fields": ["id", "author", "created"]}))
        self.assertNotIn(SERVICE_TITLE,
                         self.titles(self.fieldsets("resistor", obj=False)))

    def test_every_field_shown_once(self):
        # форма Django требует, чтобы каждое поле стояло ровно в одной секции
        from django.contrib import admin
        for category in CATEGORIES.values():
            with self.subTest(table=category.table):
                model_admin = admin.site._registry[category.model]
                shown = [name for _, options in self.fieldsets(category.slug)
                         for name in options["fields"]]
                expected = (list(model_admin.form.base_fields)
                            + list(model_admin.get_readonly_fields(
                                None, category.model())))
                self.assertEqual(sorted(shown), sorted(expected))

    def test_oy_id_in_main_section(self):
        main = dict(self.fieldsets("resistor"))["Основные сведения"]["fields"]
        self.assertEqual(main[main.index("oy_pn") + 1], "oy_id")

    def test_site_sections_unchanged(self):
        # раскладку вынесли в field_sections — сайт должен видеть то же
        from ..forms import build_form_class, group_fields
        category = get_category("resistor")
        # справочник выпадающих списков живёт в базе — здесь он не нужен
        with mock.patch("components.forms.table_options", return_value={}):
            form = build_form_class(category.model, category.table,
                                    category.hidden_fields)()
        sections = group_fields(form)
        self.assertEqual([title for title, _ in sections],
                         ["Основные сведения", "Электрические параметры",
                          "Физические параметры"])
        names = [f.name for _, fields in sections for f in fields]
        self.assertNotIn("confirm_duplicate", names)
        self.assertNotIn("oy_id", names)



class AdminAppListTests(SimpleTestCase):
    """Служебные модели — своими разделами, и только на главной админки."""

    MODELS = ("Resistor", "StepRenderJob", "OptionField", "ComponentChange",
              "FootprintImage")

    def app_list(self, app_label, models=MODELS):
        from django.contrib.admin import AdminSite

        from ..admin_site import ComponentsAdminSite

        apps = [{"name": "Справочник компонентов", "app_label": "components",
                 "app_url": "/admin/components/",
                 "models": [{"object_name": name} for name in models]}]
        with mock.patch.object(AdminSite, "get_app_list", return_value=apps):
            result = ComponentsAdminSite().get_app_list(None, app_label)
        return {app["name"]: [m["object_name"] for m in app["models"]]
                for app in result}

    def test_index_gets_own_sections(self):
        self.assertEqual(self.app_list(None), {
            "Справочник компонентов": ["Resistor"],
            # порядок — как в SECTIONS, а не как пришло от Django
            "Журнал и изображения": ["ComponentChange", "FootprintImage",
                                     "StepRenderJob"],
            "Конструктор выпадающих списков": ["OptionField"],
        })

    def test_section_without_visible_models_is_skipped(self):
        # у пользователя без прав на журнал раздела нет вовсе, а не пустой
        sections = self.app_list(None, models=("Resistor", "OptionField"))
        self.assertNotIn("Журнал и изображения", sections)

    def test_app_page_has_single_section(self):
        # второй раздел с тем же app_label склеивался в крошке с первым
        self.assertEqual(list(self.app_list("components")),
                         ["Справочник компонентов"])



class ComponentChangeAdminTests(SimpleTestCase):
    """Журнал в админке: группы названиями, компонент — ссылкой на карточку."""

    def model_admin(self):
        from django.contrib import admin

        from ..models import ComponentChange
        return admin.site._registry[ComponentChange]

    def change(self, **attrs):
        from ..models import ComponentChange
        change = ComponentChange(component_table="RESISTOR", component_id=7)
        for name, value in attrs.items():
            setattr(change, name, value)
        return change

    def test_table_title(self):
        from ..registry import table_title
        self.assertEqual(table_title("RESISTOR"), "Резисторы")
        self.assertEqual(table_title("z_RESISTOR"), "Резисторы (замены)")
        # таблицу могли переименовать — имя лучше прочерка
        self.assertEqual(table_title("OLD_TABLE"), "OLD_TABLE")

    def test_component_link(self):
        cell = self.model_admin().component(self.change(component_title="R1"))
        self.assertIn('href="/resistor/7/"', cell)
        self.assertIn(">R1</a> #7", cell)

    def test_deleted_component(self):
        cell = self.model_admin().component(self.change(component_title=None))
        self.assertEqual(cell, "#7 · удалён")

    def test_not_checked_is_not_called_deleted(self):
        # таблица не прочиталась — про удаление сказать нельзя
        self.assertEqual(self.model_admin().component(self.change()), "#7")

    def test_view_on_site_is_readable_change_page(self):
        change = self.change(pk=15)
        self.assertEqual(self.model_admin().view_on_site(change),
                         reverse("components:change", args=[15]))



class OptionFieldAdminTests(SimpleTestCase):
    """Строки одного столбца различимы по таблицам сразу за его именем."""

    def model_admin(self):
        from django.contrib import admin

        from ..models import OptionField
        return admin.site._registry[OptionField]

    def test_columns(self):
        model_admin = self.model_admin()
        self.assertEqual(model_admin.list_display[:2], ("field", "table_list"))
        self.assertIn("field", model_admin.list_filter)

    def test_values_counted_in_query(self):
        # раньше ради счётчика читались все значения всех списков
        queryset = self.model_admin().get_queryset(None)
        self.assertIn("values_total", queryset.query.annotations)
        self.assertFalse(queryset._prefetch_related_lookups)

    def test_tables_by_group_title(self):
        from ..models import OptionField
        field = OptionField(field="subgroup",
                            tables=["RESISTOR", "z_RESISTOR"])
        self.assertEqual(self.model_admin().table_list(field),
                         "Резисторы, Резисторы (замены)")
        self.assertEqual(self.model_admin().table_list(OptionField()), "все")

    def test_empty_label_is_dash(self):
        from ..models import OptionField
        self.assertEqual(self.model_admin().title(OptionField(field="x")), "—")

    def test_name_includes_tables(self):
        # тринадцать списков одного столбца различаются только таблицами
        from ..models import OptionField
        self.assertEqual(
            str(OptionField(field="subgroup", tables=["RESISTOR"])),
            "subgroup · Резисторы")
        self.assertEqual(str(OptionField(field="smt_tht", label="Монтаж")),
                         "Монтаж · все таблицы")

    def test_long_list_leaves_the_page(self):
        # почти пятьсот значений не помещались в лимит полей Django (1000)
        from ..admin.option_lists import VALUES_INLINE_LIMIT
        model_admin = self.model_admin()
        # счётчик приходит из get_queryset админки
        obj = mock.Mock(values_total=VALUES_INLINE_LIMIT + 1)
        self.assertEqual(model_admin.get_inlines(None, obj), [])
        obj = mock.Mock(values_total=VALUES_INLINE_LIMIT)
        self.assertEqual(model_admin.get_inlines(None, obj),
                         model_admin.inlines)
        # запись без счётчика — спрашиваем базу
        obj = mock.Mock(values_total=None)
        obj.values.count.return_value = VALUES_INLINE_LIMIT + 1
        self.assertEqual(model_admin.get_inlines(None, obj), [])
        self.assertEqual(model_admin.get_inlines(None, None),
                         model_admin.inlines)

    def test_inline_fits_upload_limit(self):
        # поля одной строки значения: id, ссылка на столбец, значение,
        # галочка, «удалить». Плюс форма столбца и служебные поля — с запасом
        from ..admin.option_lists import VALUES_INLINE_LIMIT
        limit = settings.DATA_UPLOAD_MAX_NUMBER_FIELDS
        self.assertLess(VALUES_INLINE_LIMIT * 5 + 100, limit)

    def test_value_list_page_fits_upload_limit(self):
        from django.contrib import admin

        from ..models import OptionValue
        value_admin = admin.site._registry[OptionValue]
        # на строку: id, галочка «активно» и галочка выбора для действия
        self.assertLess(value_admin.list_per_page * 3 + 50,
                        settings.DATA_UPLOAD_MAX_NUMBER_FIELDS)
        # в меню админки значений нет — только ссылкой со столбца
        self.assertFalse(value_admin.has_module_permission(None))
        self.assertFalse(value_admin.has_add_permission(None))



class OptionFieldFormTests(SimpleTestCase):
    """Проверки конструктора: столбец, таблицы, новые значения."""

    def test_new_values_added_once_and_cache_dropped(self):
        from django.contrib import admin

        from ..models import OptionField, OptionValue
        model_admin = admin.site._registry[OptionField]
        option_field = OptionField(pk=5, field="smt_tht")
        values = mock.Mock()
        values.values_list.return_value = ["SMT"]
        form = mock.Mock(instance=option_field,
                         cleaned_data={"new_values": ["SMT", "THT"]})
        with mock.patch.object(OptionField, "values", values), \
                mock.patch("django.contrib.admin.ModelAdmin.save_related"), \
                mock.patch.object(OptionValue.objects, "bulk_create") as create, \
                mock.patch("components.admin.option_lists.drop_options") as drop, \
                mock.patch("components.admin.option_lists.messages") as messages:
            model_admin.save_related(None, form, [], True)
        created = create.call_args.args[0]
        # уже заведённое SMT не вставляется второй раз
        self.assertEqual([value.value for value in created], ["THT"])
        # bulk_create не шлёт post_save — кэш сбрасывается руками
        drop.assert_called_once()
        self.assertIn("1 значение, уже были в списке: 1",
                      messages.info.call_args.args[1])

    def save_with(self, cleaned, collected=(), failed=()):
        from django.contrib import admin

        from ..models import OptionField, OptionValue
        model_admin = admin.site._registry[OptionField]
        option_field = OptionField(pk=5, field="smt_tht", tables=["RESISTOR"])
        values = mock.Mock()
        values.values_list.return_value = ["SMT"]
        form = mock.Mock(instance=option_field, cleaned_data=cleaned)
        with mock.patch.object(OptionField, "values", values), \
                mock.patch("django.contrib.admin.ModelAdmin.save_related"), \
                mock.patch.object(OptionValue.objects, "bulk_create") as create, \
                mock.patch("components.admin.option_lists.drop_options"), \
                mock.patch("components.admin.option_lists.values_in_data",
                           return_value=(list(collected), list(failed))) as data, \
                mock.patch("components.admin.option_lists.messages") as messages:
            model_admin.save_related(None, form, [], True)
        created = ([v.value for v in create.call_args.args[0]]
                   if create.called else None)
        return created, data, messages

    def test_collect_from_data(self):
        created, data, messages = self.save_with(
            {"new_values": ["THT"], "collect_values": True},
            collected=["SMT", "THT", "Press-fit"])
        # собирается по таблицам списка и только по его столбцу
        categories, field = data.call_args.args
        self.assertEqual([c.table for c in categories], ["RESISTOR"])
        self.assertEqual(field, "smt_tht")
        # вписанное руками — первым, из данных — без повторов и без уже
        # заведённого SMT
        self.assertEqual(created, ["THT", "Press-fit"])
        self.assertIn("в данных найдено: 3", messages.info.call_args.args[1])

    def test_collect_reports_unread_tables(self):
        _, _, messages = self.save_with(
            {"new_values": [], "collect_values": True},
            collected=["THT"], failed=["RESISTOR"])
        self.assertIn("Резисторы", messages.warning.call_args.args[1])

    def test_nothing_to_add(self):
        created, data, messages = self.save_with(
            {"new_values": [], "collect_values": False})
        self.assertIsNone(created)
        data.assert_not_called()
        messages.info.assert_not_called()

    def test_label_is_admin_only(self):
        # на сайте поле не показывается — подпись не должна обещать иного
        from ..admin.option_lists import OptionFieldForm
        self.assertEqual(OptionFieldForm.base_fields["label"].label,
                         "Название в админке")

    def test_model_names(self):
        from ..models import OptionField
        self.assertEqual(OptionField._meta.verbose_name, "выпадающий список")
        self.assertEqual(OptionField._meta.verbose_name_plural,
                         "Выпадающие списки")

    def test_source_categories(self):
        from ..options import source_categories
        self.assertEqual(
            [c.table for c in source_categories(
                "allegro_pcb_footprint", ["CONNECTOR", "z_CONNECTOR"])],
            ["CONNECTOR"])
        everywhere = {c.table for c in source_categories("smt_tht")}
        self.assertEqual(everywhere, {c.table for c in CATEGORIES.values()
                                      if "smt_tht" in c.field_names})

    def test_parse_values(self):
        from ..options import parse_values
        self.assertEqual(parse_values("SMT\n  THT \n\nSMT\nsmt\n"),
                         ["SMT", "THT", "smt"])
        self.assertEqual(parse_values(None), [])

    def test_field_choices(self):
        from ..options import field_choices
        names = [name for name, _ in field_choices()]
        for name in ("smt_tht", "subgroup", "country",
                     "allegro_pcb_footprint", "vendor"):
            self.assertIn(name, names)
        # артикулы, служебное и длинный текст списком не бывают
        for name in ("vendor_pn", "oy_id", "id", "author", "created",
                     "description", "notice"):
            self.assertNotIn(name, names)
        self.assertIn(("smt_tht", "SMT_THT — smt_tht"), field_choices())

    def test_unknown_current_field_kept(self):
        from ..options import field_choices
        self.assertIn(("old_column", "old_column — old_column"),
                      field_choices("old_column"))

    def test_tables_without_column(self):
        from ..options import tables_without
        # полей Allegro в таблицах замен нет
        self.assertEqual(
            tables_without("allegro_pcb_footprint",
                           ["CONNECTOR", "z_CONNECTOR"]),
            ["z_CONNECTOR"])
        self.assertEqual(tables_without("smt_tht", ["RESISTOR"]), [])

    def test_overlapping(self):
        from ..options import overlapping
        others = [("общий", []), ("резисторы", ["RESISTOR", "z_RESISTOR"])]
        # своя запись поверх общей — задуманная схема, не пересечение
        self.assertEqual(overlapping(["CAPACITOR"], others), [])
        self.assertEqual(overlapping(["RESISTOR", "IC"], others),
                         [("резисторы", ["RESISTOR"])])
        # две общие — пересечение
        self.assertEqual(overlapping([], others), [("общий", [])])

    def test_table_rows_pair_replacements(self):
        from ..admin.option_lists import table_rows
        rows = {row["main"]: row for row in table_rows()}
        self.assertEqual(rows["RESISTOR"]["replacement"], "z_RESISTOR")
        self.assertEqual(rows["RESISTOR"]["title"], "Резисторы")
        # у печатных плат таблицы замен нет
        self.assertEqual(rows["PCB"]["replacement"], "")
        covered = {row["main"] for row in table_rows()} | {
            row["replacement"] for row in table_rows() if row["replacement"]}
        self.assertEqual(covered, {c.table for c in CATEGORIES.values()})

    def test_grid_marks_chosen_tables(self):
        from ..admin.option_lists import TablesGridWidget
        html = TablesGridWidget().render("tables", ["RESISTOR", "z_IC"])
        checked = re.findall(r'value="(\w+)"\s+data-kind="(\w+)" checked',
                             html)
        self.assertEqual(checked, [("z_IC", "replacement"),
                                   ("RESISTOR", "main")])
