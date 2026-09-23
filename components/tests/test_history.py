"""Журнал изменений: разница «было — стало», фильтры, изображения."""

from django.http import QueryDict
from django.test import SimpleTestCase

from ..filter_forms import ChangeFilterForm
from ..history import author_logins, diff, log_queryset, snapshot


class HistoryDiffTests(SimpleTestCase):
    """История правок: что считается изменением, а что нет.

    Модель здесь поддельная — сравнение работает с любым объектом, у
    которого есть ``_meta.fields``, и настоящая таблица компонентов для
    проверки не нужна.
    """

    class Field:
        def __init__(self, name, verbose):
            self.name, self.verbose_name = name, verbose

    class Fake:
        def __init__(self, **values):
            for field in HistoryDiffTests.FIELDS:
                setattr(self, field.name, values.get(field.name))

    FIELDS = [Field("id", "id"), Field("vendor_pn", "Vendor PN"),
              Field("value", "Value"), Field("created", "Created"),
              Field("notice", "Notice")]

    def setUp(self):
        meta = type("Meta", (), {"fields": self.FIELDS})()
        self.Fake._meta = meta

    def changed(self, before, after):
        return {item["field"]: (item["old"], item["new"])
                for item in diff(snapshot(before), snapshot(after), self.Fake)}

    def test_changed_field_is_recorded_with_both_values(self):
        result = self.changed(self.Fake(vendor_pn="WR06"),
                              self.Fake(vendor_pn="WR06X"))
        self.assertEqual(result, {"vendor_pn": ("WR06", "WR06X")})

    def test_untouched_fields_are_not_recorded(self):
        result = self.changed(self.Fake(vendor_pn="WR06", value="10k"),
                              self.Fake(vendor_pn="WR06X", value="10k"))
        self.assertNotIn("value", result)

    def test_empty_becoming_placeholder_is_not_a_change(self):
        # при сохранении пустые поля превращаются в «---»: для человека
        # ничего не изменилось, и в историю это попадать не должно
        result = self.changed(self.Fake(value=""), self.Fake(value="---"))
        self.assertEqual(result, {})

    def test_placeholder_replaced_by_value_is_a_change(self):
        result = self.changed(self.Fake(value="?"), self.Fake(value="4.7k"))
        self.assertEqual(result, {"value": ("", "4.7k")})

    def test_id_and_created_are_never_recorded(self):
        self.assertNotIn("id", snapshot(self.Fake()))
        self.assertNotIn("created", snapshot(self.Fake()))

    def test_creation_shows_filled_fields_as_new(self):
        result = {item["field"]: (item["old"], item["new"])
                  for item in diff({}, snapshot(self.Fake(vendor_pn="NEW-PN")),
                                   self.Fake)}
        self.assertEqual(result, {"vendor_pn": ("", "NEW-PN")})

    def test_fields_keep_model_order(self):
        before = self.Fake(notice="a", vendor_pn="b", value="c")
        after = self.Fake(notice="A", vendor_pn="B", value="C")
        names = [item["field"]
                 for item in diff(snapshot(before), snapshot(after), self.Fake)]
        self.assertEqual(names, ["vendor_pn", "value", "notice"])

    def test_label_comes_from_the_model(self):
        changed = diff(snapshot(self.Fake(vendor_pn="A")),
                       snapshot(self.Fake(vendor_pn="B")), self.Fake)
        self.assertEqual(changed[0]["label"], "Vendor PN")



class AuthorFilterTests(SimpleTestCase):
    """Список сотрудников в фильтре журнала — по одному разу каждый.

    Запрос строится, но не выполняется: проверяется его форма, а не данные.
    Этого достаточно — ошибка была именно в форме запроса.
    """

    def test_duplicates_are_removed_by_the_database(self):
        self.assertTrue(author_logins().query.distinct)

    def test_default_ordering_does_not_leak_into_the_query(self):
        # Ровно эта утечка и давала сотрудника столько раз, сколько правок
        # он сделал: поля сортировки журнала попадали в запрос рядом с
        # автором, и строки с разным временем правки становились разными
        query = author_logins().query
        self.assertFalse(query.default_ordering)
        self.assertEqual(query.order_by, ())

    def test_only_the_login_is_selected(self):
        self.assertEqual(author_logins().query.values_select, ("author",))



class ChangeLogFilterTests(SimpleTestCase):
    """Фильтры журнала — несколько значений сразу, как у компонентов.

    Запрос строится, но не выполняется: проверяется, какие условия в него
    попали. ``?action=created|deleted`` должен стать «добавлен или удалён»,
    а не пустым ответом, как было, пока фильтр принимал одно значение.
    """

    @staticmethod
    def conditions(query):
        where = log_queryset(QueryDict(query)).query.where
        return {(node.lhs.target.name, node.lookup_name): node.rhs
                for node in where.children}

    def test_values_joined_by_bar(self):
        found = self.conditions("action=created|deleted&table=Resistor")
        self.assertEqual(found[("action", "in")], ["created", "deleted"])
        self.assertEqual(found[("component_table", "in")], ["Resistor"])

    def test_repeated_parameter_is_understood_too(self):
        # так отправит браузер сам, если скрипт выпадающих списков не
        # загрузился и форму отдал обычный <select multiple>
        found = self.conditions("author=ivanov&author=petrov")
        self.assertEqual(found[("author", "in")], ["ivanov", "petrov"])

    def test_unknown_action_is_dropped_not_matched(self):
        found = self.conditions("action=created|nonsense")
        self.assertEqual(found[("action", "in")], ["created"])
        self.assertEqual(self.conditions("action=nonsense"), {})

    def test_empty_and_foreign_params_narrow_nothing(self):
        self.assertEqual(self.conditions("action=&table=|&since=вчера&x=1"),
                         {})

    def test_form_marks_every_chosen_value(self):
        # по ссылке с «|» форма должна отметить оба значения — иначе
        # галочки в списке разошлись бы с тем, что отобрано
        form = ChangeFilterForm(
            QueryDict("action=created|deleted"),
            actions=[("created", "Добавлен"), ("deleted", "Удалён")],
            authors=[], tables=["Resistor"])
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["action"], ["created", "deleted"])

    def test_filters_look_like_component_filters(self):
        form = ChangeFilterForm(actions=[], authors=[], tables=[])
        for name in ("action", "author", "table"):
            attrs = form.fields[name].widget.attrs
            self.assertTrue(form.fields[name].widget.allow_multiple_selected)
            self.assertEqual(attrs.get("data-autosubmit"), "1")
            self.assertTrue(attrs.get("data-title"))



class ImageChangeTests(SimpleTestCase):
    """Действия с картинкой посадочного места — в журнале изменений."""

    def test_record_reads_like_a_field_change(self):
        # один элемент в формате правки полей: запись журнала показывает
        # его обычной таблицей «было — стало», без отдельной разметки
        from ..history import image_changes

        changes = image_changes("SOT-23", old="a.step", new="b.step")
        self.assertEqual(len(changes), 1)
        self.assertEqual(set(changes[0]), {"field", "label", "old", "new"})
        self.assertEqual((changes[0]["old"], changes[0]["new"]),
                         ("a.step", "b.step"))

    def test_footprint_is_named_in_the_record(self):
        # картинка общая для всех компонентов с этим местом — по записи
        # должно быть видно, что поменялось не только здесь
        from ..history import image_changes

        self.assertIn("SOT-23", image_changes("SOT-23")[0]["label"])

    def test_deletion_has_an_empty_after(self):
        from ..history import image_changes

        self.assertEqual(image_changes("SOT-23", old="a.step")[0]["new"], "")

    def test_event_is_known_to_the_journal(self):
        # фильтр журнала строится из ACTIONS: новое событие появляется в
        # нём само, если оно там есть
        from ..models import ComponentChange

        self.assertIn(ComponentChange.IMAGE, dict(ComponentChange.ACTIONS))
        self.assertEqual(ComponentChange(action="image").short_action,
                         "изображение")
        self.assertEqual(ComponentChange(action="image").chip_class,
                         "chip--image")

    def test_batch_upload_writes_nothing(self):
        # у пакетной загрузки нет компонента, из которого загружали, —
        # записи в журнал нет, а не запись «ничья»
        from ..history import record_image

        self.assertIsNone(record_image("", None, "robot", "SOT-23"))

    def test_background_author_is_a_login(self):
        # рендер идёт в фоне, и к моменту записи есть только логин строкой
        from ..history import _username

        self.assertEqual(_username("ivanov"), "ivanov")
