"""Форма компонента: образец, формат полей, обязательные, скрытые."""

from unittest import mock

from django import forms
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from ..forms import (
    ARTICLE_FIELDS,
    FIELD_VALIDATORS,
    NOT_COPIED,
    REQUIRED_FIELDS,
    REQUIRED_MESSAGE,
    URL_FIELDS,
    URL_VALIDATOR,
    sample_initial,
)
from ..registry import get_category


class SampleInitialTests(SimpleTestCase):
    """«Добавить по образцу»: что переносится в новую форму, а что нет."""

    # поддельная модель: в ней должно быть каждое поле из NOT_COPIED —
    # иначе «не перенеслось» и «в модели такого нет» неразличимы, и
    # добавленное в список поле тест молча пропустит
    FIELDS = ("id", "vendor_pn", "vendor", "oy_pn", "oy_id", "gbt_pn",
              "tracker_url", "group", "package", "value", "datasheet",
              "author", "created", "notice")

    class Field:
        def __init__(self, name):
            self.name = name

    class Fake:
        def __init__(self, **values):
            for name in SampleInitialTests.FIELDS:
                setattr(self, name, values.get(name, f"<{name}>"))

    def setUp(self):
        self.Fake._meta = type("Meta", (), {
            "fields": [self.Field(name) for name in self.FIELDS]})()

    def test_identity_fields_are_not_copied(self):
        # скопировать их значило бы завести дубль, а образец нужен ровно
        # для обратного — для похожей, но другой детали
        initial = sample_initial(self.Fake())
        for name in ("vendor_pn", "vendor", "gbt_pn", "oy_id", "tracker_url"):
            self.assertNotIn(name, initial)

    def test_datasheet_is_not_copied(self):
        # документация у каждого артикула своя: перенесённая ссылка вела бы
        # не на тот файл, а такую ошибку заметить труднее, чем пустое поле
        self.assertNotIn("datasheet", sample_initial(self.Fake()))

    def test_service_fields_are_not_copied(self):
        initial = sample_initial(self.Fake())
        for name in ("id", "author", "created"):
            self.assertNotIn(name, initial)

    def test_parameters_are_copied(self):
        initial = sample_initial(self.Fake(group="CAPACITOR", value="10n"))
        self.assertEqual(initial["group"], "CAPACITOR")
        self.assertEqual(initial["value"], "10n")

    def test_every_excluded_field_exists_in_the_fake(self):
        # страховка для теста ниже: сравнивать состав можно, только если
        # поддельная модель знает все поля, которые не переносятся
        self.assertEqual(set(NOT_COPIED) - set(self.FIELDS), set())

    def test_nothing_else_is_dropped(self):
        initial = sample_initial(self.Fake())
        skipped = set(self.FIELDS) - set(initial)
        self.assertEqual(skipped, set(NOT_COPIED))



class FieldFormatTests(SimpleTestCase):
    """Проверки формата полей формы компонента."""

    def check(self, name, value):
        FIELD_VALIDATORS[name](value)

    def test_ordinary_part_numbers_pass(self):
        for value in ("GRM155R61A104KA01D", "ID_V_000006", "L02U5V0NA-4C",
                      "12345678"):
            with self.subTest(value=value):
                self.check("gbt_pn", value)

    def test_cyrillic_lookalike_is_rejected(self):
        # «С» кириллическая: на вид не отличить, но поиск её не найдёт, и
        # на месте этой записи заведут вторую
        with self.assertRaises(ValidationError):
            self.check("oy_pn", "С0805")

    def test_placeholders_pass_untouched(self):
        # в большинстве записей тут «---», и требовать исправить поле,
        # которого человек не трогал, неправильно
        for blank in ("---", "?", "", "n/a"):
            with self.subTest(blank=blank):
                self.check("oy_id", blank)

    def test_every_article_field_is_checked(self):
        for name in ARTICLE_FIELDS:
            self.assertIn(name, FIELD_VALIDATORS)

    def test_allegro_rules_are_still_stricter(self):
        # у посадочного места набор уже: скобки и пробелы там не нужны
        with self.assertRaises(ValidationError):
            self.check("allegro_pcb_footprint", "CAP (0.1 uF)")



class TrackerUrlTests(SimpleTestCase):
    """Ссылка на задачу в трекере — адрес, и проверяется как адрес."""

    def test_full_address_passes(self):
        URL_VALIDATOR("https://tracker.yandex.ru/OYLIB-113")

    def test_bare_number_is_rejected(self):
        with self.assertRaises(ValidationError):
            URL_VALIDATOR("OYLIB-113")

    def test_placeholder_passes(self):
        URL_VALIDATOR("---")

    def test_the_field_is_the_tracker_one(self):
        self.assertEqual(URL_FIELDS, ("tracker_url",))



class RequiredMessageTests(SimpleTestCase):
    """Сообщение об обязательном поле не называет само поле.

    Подпись стоит рядом с полем, а в сводке ошибок её подставляет шаблон.
    Если бы текст повторял её сам, в сводке выходило бы «Description:
    заполните «Description»».
    """

    def test_message_does_not_repeat_the_label(self):
        for name in ("Description", "Vendor PN", "«"):
            self.assertNotIn(name, REQUIRED_MESSAGE.replace("«---»", ""))

    def test_message_covers_both_cases(self):
        # пустое поле и заглушка для того, кто потом ищет компонент, —
        # одно и то же, и текст у них общий
        self.assertIn("---", REQUIRED_MESSAGE)

    def test_required_fields_are_the_identifying_ones(self):
        self.assertEqual(REQUIRED_FIELDS, ("vendor_pn", "description"))



class HiddenFieldsTests(SimpleTestCase):
    """Поле, которого у группы по смыслу нет, убрано из формы, но не из базы."""

    def form_class(self, slug):
        from ..forms import build_form_class
        category = get_category(slug)
        return build_form_class(category.model, category.table,
                                category.hidden_fields)

    def test_pcb_form_has_no_footprint(self):
        self.assertNotIn("allegro_pcb_footprint",
                         self.form_class("pcb").base_fields)
        # схемный символ у платы есть — убирается только посадочное место
        self.assertIn("allegro_schematic_part",
                      self.form_class("pcb").base_fields)

    def test_other_groups_keep_footprint(self):
        self.assertIn("allegro_pcb_footprint",
                      self.form_class("capacitor").base_fields)

    def test_new_record_gets_placeholder(self):
        from ..forms import BLANK_VALUE, ComponentForm
        form_class = self.form_class("pcb")
        obj = get_category("pcb").model()
        # проверка формы ходит в базу за справочником и дублями, поэтому
        # родительский save подменён: проверяется только то, что добавляет
        # ComponentForm
        with mock.patch.object(forms.ModelForm, "save", return_value=obj):
            saved = ComponentForm.save(form_class.__new__(form_class),
                                       commit=False)
        self.assertEqual(saved.allegro_pcb_footprint, BLANK_VALUE)
