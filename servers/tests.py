"""Тесты раздела серверов.

Как и в остальных разделах, без базы (``SimpleTestCase``): проверяется
логика обхода и то, какие запросы строятся, а не данные.

    python manage.py test servers
"""

from unittest import mock

from django.contrib import admin
from django.test import SimpleTestCase

from . import tree
from .models import BomLine, Item


class ExplodeQueryTests(SimpleTestCase):
    """Рекурсивный разворот состава: типы количества в обеих частях."""

    def test_quantity_types_match(self):
        # numeric(12, 3) в первой части и numeric во второй — PostgreSQL
        # такую рекурсию не принимал, «Дерево» и «Сводка» падали с 500
        self.assertIn("e.quantity::numeric AS total", tree.EXPLODE)
        self.assertIn("round(t.total * e.quantity, 3)", tree.EXPLODE)


class SummaryTests(SimpleTestCase):
    """Сводка складывает только листья и спрашивает базу один раз."""

    def row(self, child, quantity, oy_pn="R1"):
        return {"child": child, "oy_pn": oy_pn, "gct_pn": "",
                "description": "", "unit": "шт", "quantity": quantity}

    def test_nodes_skipped_leaves_summed(self):
        board = Item(pk=1, oy_pn="BOARD", board_id=5)
        assembly = Item(pk=2, oy_pn="ASM")
        leaf = Item(pk=3, oy_pn="SCREW")
        rows = [self.row(assembly, 1, "ASM"), self.row(board, 2, "BOARD"),
                self.row(leaf, 4, "SCREW"), self.row(leaf, 6, "SCREW"),
                self.row(None, 3, "C1")]
        with mock.patch.object(tree, "explode", return_value=rows), \
                mock.patch.object(tree, "_with_lines",
                                  return_value={2}) as with_lines:
            summary = tree.summary(99)

        # один вопрос к базе на всю сводку, а не по строке
        with_lines.assert_called_once_with({1, 2, 3})
        self.assertEqual({(e["oy_pn"], e["quantity"]) for e in summary},
                         {("SCREW", 10), ("C1", 3)})


class ItemListTests(SimpleTestCase):
    """Список позиций со счётчиком строк листается в определённом порядке."""

    def test_counted_list_is_ordered(self):
        # без ORDER BY Paginator предупреждал: позиция могла попасть на две
        # страницы, а другая — ни на одну
        queryset = Item.objects.with_counts()
        self.assertTrue(queryset.ordered)
        self.assertEqual(queryset.query.order_by, ("kind", "oy_pn"))


class BomLineAdminTests(SimpleTestCase):
    def test_related_items_read_with_rows(self):
        # родитель — колонка списка, child нужен label; иначе по запросу
        # на строку
        self.assertEqual(admin.site._registry[BomLine].list_select_related,
                         ("parent", "child"))
