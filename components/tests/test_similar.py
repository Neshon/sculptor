"""Подбор похожего артикула: общие правила ссылок, BOM и отчёта о дублях."""

from django.test import SimpleTestCase

from .. import similar


def prepared(*pns):
    """Подготовленная «библиотека» из этих артикулов, без базы."""
    index = {pn.lower(): {"pn": pn, "targets": [("TRANSISTOR", i)]}
             for i, pn in enumerate(pns, 1)}
    return similar.prepare([index])


class SimilarTests(SimpleTestCase):

    def reasons(self, pn, library):
        return {entry["pn"]: reason for _, entry, _, reason
                in similar.similar(pn, library)}

    def test_same_spelling_is_named_as_such(self):
        # строка BOM не связалась из-за производителя, а артикул тот же:
        # подсказка должна сказать это прямо, а не «разделители»
        self.assertEqual(self.reasons("bav99-7-f", prepared("BAV99-7-F")),
                         {"BAV99-7-F": similar.SAME})

    def test_separators_only(self):
        self.assertEqual(self.reasons("BAV99 7 F", prepared("BAV99-7-F")),
                         {"BAV99-7-F": similar.SEPARATORS})

    def test_exact_rules_hide_fuzzy_noise(self):
        # точное правило сработало — похожие строки сверх него не нужны
        found = self.reasons("2N7002KTB_R1",
                             prepared("2N7002KTB", "2N7003KTB"))
        self.assertEqual(found, {"2N7002KTB": similar.EXTRA_SUFFIX})

    def test_decimal_comma_is_not_a_separator(self):
        # «5,1 кОм» и «51 кОм» — разные резисторы, а не одна запись
        self.assertNotEqual(similar.core("Р1-12-0,062-5,1 кОм±1%-К"),
                            similar.core("Р1-12-0,062-51 кОм±1%-К"))

    def test_cyrillic_is_part_of_the_value(self):
        # «1,1 Ом» и «1,1 кОм» — различаются только кириллицей
        self.assertNotEqual(similar.core("Р1-12-0,063-1,1 Ом±5%"),
                            similar.core("Р1-12-0,063-1,1 кОм±5%"))

    def test_usual_separators(self):
        self.assertEqual(similar.core("2n7002ktb_r1"), "2N7002KTBR1")
        self.assertEqual(similar.core("LM5066IPMHE/NOPB"), "LM5066IPMHENOPB")
        self.assertEqual(similar.core("MMBT3904 – 7 – F"), "MMBT39047F")

    def test_short_part_numbers_are_not_compared(self):
        # у трёх знаков три четверти совпадения найдутся с чем угодно
        self.assertEqual(similar.similar("R1", prepared("R10K")), [])

    def test_letter_typo_is_similar(self):
        found = similar.similar("BAV99-7-X", prepared("BAV99-7-F"))
        self.assertEqual([reason for *_, reason in found], [similar.FUZZY])

    def test_gbt_numbers_are_not_compared_loosely(self):
        # внутренние номера похожи друг на друга по построению
        index = ({}, {"10cm0-4k1004-54r": {"pn": "10CM0-4K1004-54R",
                                             "targets": [("CAPACITOR", 1)]}})
        self.assertEqual(similar.similar("10CM0-4M1004-54R",
                                         similar.prepare(index)), [])

    def test_exact_rules_can_be_the_only_ones(self):
        self.assertEqual(similar.similar("BAV99-7-X", prepared("BAV99-7-F"),
                                         fuzzy=False), [])


class BaseSpellingTests(SimpleTestCase):

    def test_suffixes_after_separators(self):
        self.assertEqual(similar.base_spellings("MMBT3904-7-F"),
                         ["MMBT3904-7", "MMBT3904"])

    def test_glued_suffix_is_not_cut(self):
        # «BAV99W» — другой корпус, а не «BAV99» с суффиксом
        self.assertEqual(similar.base_spellings("BAV99W"), [])

    def test_trailing_separator_cuts_nothing(self):
        self.assertEqual(similar.base_spellings("BAV99-"), [])

    def test_too_short_base_is_dropped(self):
        self.assertEqual(similar.base_spellings("R1-0402"), [])
