"""Дубли: ключи сравнения, правила проверки, ссылки на совпавшие."""

from unittest import mock

from django.test import SimpleTestCase

from ..duplicates import (
    CHECKS,
    DEFAULT_CHECK,
    MATCH_RULES,
    _key,
    _rule_filter,
    spelling_groups,
)
from ..matching import usable
from ..registry import get_category


class DuplicateKeyTests(SimpleTestCase):
    """Ключи, по которым записи считаются дублями."""

    def setUp(self):
        self.MAIN = get_category("resistor")
        self.REPLACEMENT = get_category("resistorreplacement")

    def test_default_check_is_known(self):
        self.assertIn(DEFAULT_CHECK, CHECKS)

    def test_vendor_key_is_the_part_number_alone(self):
        # производитель в ключ не входит: артикул опознаёт деталь сам, а
        # разнобой в написании вендора («LITE-ON», «Lite-On») прятал бы
        # дубли вместо того, чтобы их показывать
        self.assertEqual(_key("vendor", {"vendor_pn": "PN-1"}, self.MAIN),
                         "pn-1")

    def test_vendor_key_ignores_the_vendor_field(self):
        one = _key("vendor", {"vendor_pn": "PN-1", "vendor": "Yageo"},
                   self.MAIN)
        other = _key("vendor", {"vendor_pn": "PN-1", "vendor": "YAGEO"},
                     self.MAIN)
        self.assertEqual(one, other)

    def test_placeholders_do_not_make_a_key(self):
        self.assertIsNone(_key("gbt", {"gbt_pn": "---"}, self.MAIN))
        self.assertIsNone(_key("vendor", {"vendor_pn": "?"}, self.MAIN))

    def test_oy_id_key_is_scoped_to_the_table(self):
        key = _key("oy_id", {"oy_id": "ID_R_000221"}, self.MAIN)
        self.assertEqual(key, "RESISTOR · id_r_000221")

    def test_replacement_tables_are_excluded_from_oy_id_check(self):
        # у аналогов общий OY ID — это норма, а не дубль
        self.assertIsNone(_key("oy_id", {"oy_id": "ID_R_000221"},
                               self.REPLACEMENT))



class DuplicateCheckRulesTests(SimpleTestCase):
    """Правила проверки «нет ли уже такого компонента» при заведении."""

    def rules_for(self, **values):
        """Какие правила сработают на этих значениях (запросов не делает)."""
        cleaned = {name: usable(values.get(name))
                   for _, fields in MATCH_RULES for name in fields}
        return [label for label, fields in MATCH_RULES
                if _rule_filter(fields, cleaned) is not None]

    def test_rules_are_the_ones_asked_for(self):
        self.assertEqual([label for label, _ in MATCH_RULES],
                         ["Vendor PN", "GBT PN"])

    def test_both_rules_fire_when_everything_is_filled(self):
        self.assertEqual(
            self.rules_for(vendor_pn="GRM188", vendor="Murata", gbt_pn="GBT-1"),
            ["Vendor PN", "GBT PN"])

    def test_vendor_pn_alone_is_enough(self):
        # артикул опознаёт деталь сам; производитель в ключ не входит —
        # разнобой в его написании прятал бы дубли, а не показывал
        self.assertEqual(self.rules_for(vendor_pn="GRM188"), ["Vendor PN"])

    def test_vendor_alone_does_not_trigger_a_search(self):
        # по одному производителю нашлась бы вся его номенклатура
        self.assertEqual(self.rules_for(vendor="Murata"), [])

    def test_gbt_alone_is_enough(self):
        self.assertEqual(self.rules_for(gbt_pn="GBT-1"), ["GBT PN"])

    def test_placeholders_do_not_trigger_a_search(self):
        # иначе нашлось бы всё, у чего поле тоже не заполнено
        for blank in ("---", "?", "n/a", ""):
            with self.subTest(blank=blank):
                self.assertEqual(
                    self.rules_for(vendor_pn=blank, vendor=blank, gbt_pn=blank),
                    [])

    def test_partial_placeholder_disables_only_its_rule(self):
        # заглушка в одном поле выключает только своё правило, второе
        # работает: правила однополевые, и общего у них ничего нет
        self.assertEqual(
            self.rules_for(vendor_pn="---", gbt_pn="GBT-1"), ["GBT PN"])
        self.assertEqual(
            self.rules_for(vendor_pn="GRM188", gbt_pn="---"), ["Vendor PN"])

    def test_vendor_placeholder_no_longer_disables_the_search(self):
        # раньше «---» в Vendor выключал главную проверку целиком: пара
        # считалась неполной, и дубль по артикулу проходил незамеченным
        self.assertEqual(
            self.rules_for(vendor_pn="GRM188", vendor="---"), ["Vendor PN"])



class DuplicateMatchesTests(SimpleTestCase):
    """Ссылки на записи, с которыми совпал дубль, — только на живые."""

    def test_links_only_existing_records(self):
        from ..change_views import duplicate_matches

        alive = mock.Mock()
        alive.get_absolute_url.return_value = "/connector/421/"

        def lookup(table, pk):
            return None, (alive if pk == 421 else None)

        items = [{"table": "CONNECTOR", "id": 421, "title": "WIQ0150009"},
                 {"table": "CONNECTOR", "id": 7, "title": "GONE"}]
        matches = duplicate_matches(items, lookup)
        self.assertEqual([m["url"] for m in matches], ["/connector/421/", ""])
        # сама справка о совпадении не теряется
        self.assertEqual(matches[1]["title"], "GONE")

    def test_empty(self):
        from ..change_views import duplicate_matches
        self.assertEqual(duplicate_matches(None), [])


class SpellingGroupTests(SimpleTestCase):
    """Проверка «артикул записан по-разному» — на готовом наборе написаний."""

    def test_separators_and_case(self):
        groups = spelling_groups({"2n7002k-7", "2n7002k7"})
        self.assertEqual(groups, {"2n7002k-7": "2N7002K7",
                                  "2n7002k7": "2N7002K7"})

    def test_suffix_joins_its_base(self):
        groups = spelling_groups({"mmbt3904", "mmbt3904-7-f", "mmbt3904-7"})
        self.assertEqual(set(groups.values()), {"MMBT3904"})
        self.assertEqual(len(groups), 3)

    def test_glued_suffix_is_another_part(self):
        # «BAV99W» — другой корпус: без разделителя суффиксом не считается
        self.assertEqual(spelling_groups({"bav99", "bav99w"}), {})

    def test_lonely_spelling_is_not_reported(self):
        # у суффикса нет основы в библиотеке — сравнивать не с чем
        self.assertEqual(spelling_groups({"2n7002ktb_r1", "bav99"}), {})

    def test_domestic_values_are_not_glued(self):
        # на живой базе так склеивались 5,1 кОм и 51 кОм, 1,1 Ом и 1,1 кОм
        self.assertEqual(spelling_groups({
            "р1-12-0,062-5,1 ком±1%-к шкаб.434110.021 ту",
            "р1-12-0,062-51 ком±1%-к шкаб.434110.021 ту",
            "р1-12-0,063-1,1 ом±5%«а» шкаб.434110.024 ту",
            "р1-12-0,063-1,1 ком±5%«а» шкаб.434110.024 ту",
        }), {})

    def test_check_is_offered(self):
        self.assertIn("spelling", CHECKS)
