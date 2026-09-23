"""Импорт ссылок на задачи трекера."""

from io import BytesIO
from unittest import mock

from django.test import SimpleTestCase

from .. import links as links_module
from ..links import (
    LinkFileError,
    build_suggest_index,
    candidates,
    match,
    read_rows,
    suggest,
)


class LinkCandidateTests(SimpleTestCase):
    """Из названия задачи достаются возможные артикулы — без догадок о формате."""

    def test_longest_piece_comes_first(self):
        # длинный кусок надёжнее короткого: сначала пробуем его
        found = candidates("Создание резистора WR06X472 JTL")
        self.assertEqual(found[0], "Создание резистора WR06X472 JTL")
        self.assertIn("WR06X472 JTL", found)
        self.assertIn("WR06X472", found)

    def test_non_breaking_space_is_handled(self):
        # выгрузка трекера ставит его сплошь и рядом
        self.assertIn("MMBT3904-7-F",
                      candidates("Создание транзистора\u00a0MMBT3904-7-F"))

    def test_glued_prefix_is_split(self):
        # «ИндуктивностьWPN4020H3R3MT» — пробел потерян при вводе
        self.assertIn("WPN4020H3R3MT", candidates("ИндуктивностьWPN4020H3R3MT"))

    def test_russian_words_are_not_candidates(self):
        # в артикулах есть латиница или цифры; «Отсутствует» — это описание
        self.assertEqual(candidates("Создание соединителя Отсутствует"), [])

    def test_placeholder_task_gives_nothing(self):
        self.assertEqual(candidates("Создание соединителя ---"), [])
        self.assertEqual(candidates("Создание винта -"), [])

    def test_empty_input(self):
        self.assertEqual(candidates(""), [])
        self.assertEqual(candidates(None), [])



class LinkMatchTests(SimpleTestCase):
    """Сопоставление идёт по базе: побеждает самый длинный найденный артикул."""

    def index(self, vendor=(), gbt=()):
        def side(pns):
            return {pn.lower(): {"pn": pn, "targets": [("RESISTOR", i)]}
                    for i, pn in enumerate(pns, 1)}
        return side(vendor), side(gbt)

    def test_plain_part_number(self):
        targets, piece, rule = match("Создание транзистора MMBT3904-7-F",
                                     self.index(vendor=["MMBT3904-7-F"]))
        self.assertEqual(piece, "MMBT3904-7-F")
        self.assertEqual(rule, "Vendor PN")
        self.assertEqual(targets, [("RESISTOR", 1)])

    def test_multi_word_part_number_wins_over_its_prefix(self):
        # если в базе есть «WR06X472 JTL», берём его целиком, а не «WR06X472»
        index = self.index(vendor=["WR06X472 JTL", "WR06X472"])
        _, piece, _ = match("Создание резистора WR06X472 JTL", index)
        self.assertEqual(piece, "WR06X472 JTL")

    def test_falls_back_to_shorter_piece(self):
        index = self.index(vendor=["WR06X472"])
        _, piece, _ = match("Создание резистора WR06X472 JTL", index)
        self.assertEqual(piece, "WR06X472")

    def test_case_is_ignored(self):
        _, piece, _ = match("Создание диода bav99-7-f",
                            self.index(vendor=["BAV99-7-F"]))
        self.assertEqual(piece, "bav99-7-f")

    def test_gbt_is_the_fallback_rule(self):
        targets, piece, rule = match("Создание резистора GBT-123",
                                     self.index(gbt=["GBT-123"]))
        self.assertEqual(rule, "GBT PN")
        self.assertEqual(piece, "GBT-123")

    def test_vendor_wins_over_gbt(self):
        index = self.index(vendor=["X1"], gbt=["X1"])
        _, _, rule = match("Резистор X1", index)
        self.assertEqual(rule, "Vendor PN")

    def test_one_task_can_hit_several_records(self):
        # один артикул может стоять и в основной таблице, и в заменах
        index = ({"x1": {"pn": "X1",
                         "targets": [("RESISTOR", 1), ("z_RESISTOR", 7)]}}, {})
        targets, _, _ = match("Резистор X1", index)
        self.assertEqual(len(targets), 2)

    def test_nothing_found(self):
        targets, piece, rule = match("Создание резистора WR06X472",
                                     self.index(vendor=["ДРУГОЕ1"]))
        self.assertEqual((targets, piece, rule), ([], "", ""))



class LinkFileTests(SimpleTestCase):
    """Чтение CSV со ссылками: колонки по заголовку, кодировка угадывается."""

    def upload(self, text, encoding="utf-8-sig"):
        """Имитирует файл, пришедший из формы, — байтами."""
        return BytesIO(text.encode(encoding))

    GOOD = ("Ключ,Задача\n"
            "https://tracker/OYLIB-1,Создание транзистора MMBT3904-7-F\n"
            "https://tracker/OYLIB-2,Создание резистора WR06X472\n")

    def test_rows_are_read(self):
        rows = read_rows(self.upload(self.GOOD))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["url"], "https://tracker/OYLIB-1")
        self.assertEqual(rows[0]["title"],
                         "Создание транзистора MMBT3904-7-F")

    def test_windows_encoding_is_understood(self):
        # выгрузку часто пересохраняют в Excel под Windows
        rows = read_rows(self.upload(self.GOOD, encoding="cp1251"))
        self.assertEqual(len(rows), 2)
        self.assertIn("транзистора", rows[0]["title"])

    def test_column_order_does_not_matter(self):
        text = ("Задача,Ключ\n"
                "Создание диода BAV99-7-F,https://tracker/OYLIB-3\n")
        rows = read_rows(self.upload(text))
        self.assertEqual(rows[0]["url"], "https://tracker/OYLIB-3")

    def test_rows_without_url_or_title_are_skipped(self):
        text = ("Ключ,Задача\n"
                "https://tracker/OYLIB-1,Создание диода BAV99-7-F\n"
                ",Создание диода без ссылки\n"
                "https://tracker/OYLIB-9,\n")
        self.assertEqual(len(read_rows(self.upload(text))), 1)

    def test_missing_columns_are_reported(self):
        with self.assertRaises(LinkFileError) as caught:
            read_rows(self.upload("a,b\n1,2\n"))
        self.assertIn("Ключ", str(caught.exception))

    def test_empty_file(self):
        with self.assertRaises(LinkFileError):
            read_rows(self.upload(""))

    def test_header_without_rows(self):
        with self.assertRaises(LinkFileError):
            read_rows(self.upload("Ключ,Задача\n"))



class SuggestTests(SimpleTestCase):
    """Предположения для ненайденных: артикул тот же, записан иначе."""

    def buckets(self, *pns):
        """Подготовленные структуры подбора по «библиотеке» из этих артикулов."""
        index = ({pn.lower(): {"pn": pn, "targets": [("TRANSISTOR", i)]}
                  for i, pn in enumerate(pns, 1)}, {})
        return build_suggest_index(index)

    def test_extra_suffix_in_the_task(self):
        # «2N7002KTB_R1» в задаче против «2N7002KTB» в библиотеке
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB"))
        self.assertEqual(hints[0]["pn"], "2N7002KTB")
        self.assertEqual(hints[0]["reason"], "в задаче лишний суффикс")

    def test_different_separators(self):
        hints = suggest("Создание транзистора MMBT3904 7 F",
                        self.buckets("MMBT3904-7-F"))
        self.assertEqual(hints[0]["pn"], "MMBT3904-7-F")
        self.assertEqual(hints[0]["reason"],
                         "запись отличается только разделителями")

    def test_library_part_number_is_longer(self):
        hints = suggest("Создание микросхемы LM5066IPMHE",
                        self.buckets("LM5066IPMHE/NOPB"))
        self.assertEqual(hints[0]["pn"], "LM5066IPMHE/NOPB")

    def test_original_spelling_is_kept(self):
        # подсказка показывает артикул так, как он в базе, а не ключом
        hints = suggest("Создание диода bav99-7-f", self.buckets("BAV99-7-F"))
        self.assertEqual(hints[0]["pn"], "BAV99-7-F")

    def test_nothing_similar(self):
        self.assertEqual(suggest("Создание соединителя ZZZZ99999",
                                 self.buckets("2N7002KTB")), [])

    def test_most_likely_comes_first(self):
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB", "2N7002KT", "2N7002"))
        self.assertEqual(hints[0]["pn"], "2N7002KTB")

    def test_limit_is_respected(self):
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB", "2N7002KT", "2N7002K",
                                     "2N7002"),
                        limit=2)
        self.assertLessEqual(len(hints), 2)

    def test_task_without_a_part_number(self):
        self.assertEqual(suggest("Создание винта -", self.buckets("2N7002KTB")),
                         [])

    def test_typo_is_still_caught(self):
        # последний символ другой — точных правил не хватит, работает
        # нестрогое сравнение
        hints = suggest("Создание диода BAV99-7-X", self.buckets("BAV99-7-F"))
        self.assertTrue(hints)
        self.assertEqual(hints[0]["pn"], "BAV99-7-F")

    def test_suggestion_links_to_the_card(self):
        hints = suggest("Создание транзистора 2N7002KTB_R1",
                        self.buckets("2N7002KTB"))
        self.assertTrue(hints[0]["url"].endswith("/1/"))

    def test_suggestion_carries_what_the_button_needs(self):
        # кнопка «Добавить» шлёт таблицу и ключ — без них ссылку не завести
        hint = suggest("Создание транзистора 2N7002KTB_R1",
                       self.buckets("2N7002KTB"))[0]
        self.assertEqual(hint["table"], "TRANSISTOR")
        self.assertEqual(hint["pk"], 1)



class SkipExistingTests(SimpleTestCase):
    """Повторная загрузка не показывает то, что уже заведено.

    Тесты не ходят в базу: список уже заведённых ссылок подставляется
    вместо запроса, а проверяется само правило раскладки строк.
    """

    INDEX = ({"2n7002ktb": {"pn": "2N7002KTB",
                            "targets": [("TRANSISTOR", 1)]},
              "bav99-7-f": {"pn": "BAV99-7-F",
                            "targets": [("DIODE", 2)]}}, {})

    ROWS = [
        {"url": "https://t/1", "title": "Создание транзистора 2N7002KTB"},
        {"url": "https://t/2", "title": "Создание диода BAV99-7-F"},
        {"url": "https://t/3", "title": "Создание транзистора 2N7002KTB_R1"},
    ]

    def resolve(self, existing, rows=None, index=None):
        """Раскладка строк при заданном наборе уже существующих ссылок."""
        pairs = set(existing)
        urls = {url for url, _, _ in pairs}
        with mock.patch.object(links_module, "_existing_links",
                               return_value=(pairs, urls)):
            return links_module.resolve_rows(rows or self.ROWS,
                                             index or self.INDEX)

    def test_nothing_is_hidden_on_the_first_import(self):
        matched, unmatched, already = self.resolve([])
        self.assertEqual(len(matched), 2)
        self.assertEqual(len(unmatched), 1)
        self.assertEqual(already, [])

    def test_written_rows_disappear_on_reimport(self):
        matched, unmatched, already = self.resolve([
            ("https://t/1", "TRANSISTOR", 1), ("https://t/2", "DIODE", 2)])
        self.assertEqual(matched, [])
        self.assertEqual(len(already), 2)
        # осталась только та строка, с которой ещё нужно разобраться
        self.assertEqual([row["title"] for row in unmatched],
                         ["Создание транзистора 2N7002KTB_R1"])

    def test_suggestion_confirmed_by_hand_also_disappears(self):
        # кнопка «Добавить» рядом с предположением ставит ссылку на
        # компонент, чей артикул с задачей точно не совпал
        _, unmatched, already = self.resolve([
            ("https://t/3", "TRANSISTOR", 1)])
        self.assertEqual(unmatched, [])
        self.assertEqual(len(already), 1)

    def test_row_stays_until_every_record_is_linked(self):
        # один артикул может стоять в основной таблице и в заменах;
        # пока связана не каждая, работа не закончена
        index = ({"2n7002ktb": {"pn": "2N7002KTB",
                                "targets": [("TRANSISTOR", 1),
                                            ("z_TRANSISTOR", 9)]}}, {})
        matched, _, already = self.resolve(
            [("https://t/1", "TRANSISTOR", 1)], rows=[self.ROWS[0]],
            index=index)
        self.assertEqual(len(matched), 1)
        self.assertEqual(already, [])

    def test_skipping_can_be_turned_off(self):
        matched, unmatched, already = links_module.resolve_rows(
            self.ROWS, self.INDEX, skip_existing=False)
        self.assertEqual(already, [])
        self.assertEqual(len(matched) + len(unmatched), 3)
