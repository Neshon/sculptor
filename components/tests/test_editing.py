"""Заведение и правка компонента: четыре случая формы и одно сохранение."""

from unittest import mock

from django.test import SimpleTestCase

from ..editing import ComponentDraft, save_component
from ..history import ADMIN, SITE
from ..registry import get_category

RESISTOR = get_category("resistor")
REPLACEMENT = get_category("resistorreplacement")


class User:
    def get_username(self):
        return "ivanov"


def resistor(pk=None, **fields):
    return RESISTOR.model(pk=pk, **fields)


class SaveComponentTests(SimpleTestCase):
    """Одно сохранение на сайт и админку: автор, история, след дубля."""

    def save(self, obj, **kwargs):
        with mock.patch.object(type(obj), "save") as save, \
                mock.patch("components.editing.record") as record, \
                mock.patch("components.editing.record_duplicate") as duplicate:
            save_component(obj, "RESISTOR", User(), **kwargs)
        return save, record, duplicate

    def test_new_record_gets_author(self):
        obj = resistor()
        save, record, duplicate = self.save(obj)
        self.assertEqual(obj.author, "ivanov")
        save.assert_called_once()
        self.assertEqual(record.call_args.kwargs["source"], SITE)

    def test_editing_keeps_author(self):
        # автор — тот, кто завёл запись, а не последний правивший
        obj = resistor(pk=5, author="petrov")
        obj._state.adding = False
        self.save(obj, before={"vendor_pn": "R1"})
        self.assertEqual(obj.author, "petrov")

    def test_history_and_duplicate_from_admin(self):
        obj = resistor(pk=5)
        obj._state.adding = False
        matches = [{"obj": resistor(pk=7)}]
        _, record, duplicate = self.save(
            obj, before={"vendor_pn": "R1"}, confirmed=matches, source=ADMIN)
        self.assertEqual(record.call_args.args[3], {"vendor_pn": "R1"})
        self.assertEqual(record.call_args.kwargs["source"], ADMIN)
        self.assertEqual(duplicate.call_args.args[3], matches)
        self.assertEqual(duplicate.call_args.kwargs["source"], ADMIN)


class DraftTests(SimpleTestCase):
    """Четыре случая формы: правка, новый, по образцу, замена."""

    def draft(self, category=RESISTOR, obj=None, **kwargs):
        obj = obj if obj is not None else category.model()
        with mock.patch("components.editing.next_oy_id",
                        return_value="ID_R_001500"), \
                mock.patch("components.editing.defaults",
                           return_value={"group": "Resistor"}):
            draft = ComponentDraft(category, obj, **kwargs)
            draft.initial_values = draft.initial()
        return draft

    def test_new_component(self):
        draft = self.draft()
        self.assertTrue(draft.created)
        self.assertEqual(draft.before, {})
        self.assertEqual(draft.oy_id, "ID_R_001500")
        self.assertIn("Следующий свободный номер", draft.oy_id_hint)
        # Group определяется таблицей и заперта
        self.assertEqual(draft.locked, {"group": ("Resistor", "")})
        self.assertEqual(draft.initial_values["group"], "Resistor")

    def test_editing_keeps_own_values(self):
        obj = resistor(pk=5, oy_id="ID_R_000007", group="Resistor/RUS",
                       vendor_pn="R1")
        draft = self.draft(obj=obj)
        self.assertFalse(draft.created)
        self.assertEqual(draft.before["vendor_pn"], "R1")
        self.assertEqual(draft.oy_id, "ID_R_000007")
        # своя группа не подменяется общей
        self.assertEqual(draft.locked["group"][0], "Resistor/RUS")
        # у правки значения по умолчанию не подставляются
        self.assertNotIn("vendor_pn", draft.initial_values)

    def test_editing_placeholder_oy_id_stays_editable(self):
        draft = self.draft(obj=resistor(pk=5, oy_id="---"))
        self.assertIsNone(draft.oy_id)

    def test_by_sample(self):
        sample = resistor(pk=9, vendor_pn="R-OLD", value="10k",
                          tolerance="1%")
        draft = self.draft(sample=sample)
        self.assertEqual(draft.oy_id, "ID_R_001500")
        self.assertEqual(draft.initial_values["value"], "10k")
        # артикул образца не переносится — это была бы копия, а не соседняя деталь
        self.assertNotIn("vendor_pn", draft.initial_values)

    def test_replacement(self):
        source = resistor(pk=3, oy_id="ID_R_000003", vendor_pn="R-MAIN",
                          value="10k")
        draft = self.draft(category=REPLACEMENT, source=source)
        # OY ID — основного компонента, а не следующий по нумерации
        self.assertEqual(draft.oy_id, "ID_R_000003")
        self.assertIn("R-MAIN", draft.oy_id_hint)
        self.assertEqual(draft.initial_values["value"], "10k")
        self.assertNotIn("vendor_pn", draft.initial_values)

    def test_form_locks_group_before_validation(self):
        draft = self.draft()
        with mock.patch("components.forms.table_options", return_value={}), \
                mock.patch("components.editing.defaults",
                           return_value={"group": "Resistor"}):
            form = draft.build_form()
        self.assertTrue(form.fields["group"].disabled)
        self.assertIn("field--locked", form.fields["group"].widget.attrs["class"])

    def test_save_sets_oy_id_and_passes_history(self):
        draft = self.draft()
        obj = resistor()
        form = mock.Mock(confirmed_duplicates=["match"])
        form.save.return_value = obj
        with mock.patch("components.editing.save_component") as save:
            draft.save(form, User())
        self.assertEqual(obj.oy_id, "ID_R_001500")
        args = save.call_args.args
        self.assertEqual((args[0], args[1], args[3], args[4]),
                         (obj, "RESISTOR", {}, ["match"]))


class AdminSaveTests(SimpleTestCase):
    """Админка сохраняет тем же путём, что и сайт."""

    def test_admin_uses_save_component(self):
        from django.contrib import admin

        model_admin = admin.site._registry[RESISTOR.model]
        obj = resistor(pk=5)
        form = mock.Mock(confirmed_duplicates=["match"])
        request = mock.Mock(user=User())
        with mock.patch("components.admin.components.stored_snapshot",
                        return_value={"vendor_pn": "R1"}), \
                mock.patch("components.admin.components.save_component") as save:
            model_admin.save_model(request, obj, form, change=True)
        args, kwargs = save.call_args
        self.assertEqual(args[3], {"vendor_pn": "R1"})
        self.assertEqual(args[4], ["match"])
        self.assertEqual(kwargs["source"], ADMIN)
