"""Indexed comparison must preserve the frozen algebra's answers and refusals."""
from pathlib import Path
import sys
import unittest

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from relation_algebra_dev30 import equivalent, UnknownRelation
from relation_algebra_dev32 import Comparator
from formulaguard.workbook import WorkbookModel
import tempfile


class IndexedAlgebraTests(unittest.TestCase):
    def setUp(self):
        book = openpyxl.Workbook(); sheet = book.active; sheet.title = 'Data'
        for cell, value in {'A1': 4, 'A2': 2, 'A3': 'text', 'A4': True,
                            'B1': '=A1+A2', 'B2': 0}.items():
            sheet[cell] = value
        book.create_sheet("O'Brien")['A1'] = 3
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'input.xlsx'; book.save(path)
            self.model = WorkbookModel.from_xlsx(path)
        self.index = Comparator(self.model)

    def compare(self, a, b):
        try:
            expected = equivalent(a, b, 'Data', self.model)
        except UnknownRelation as exc:
            with self.assertRaisesRegex(UnknownRelation, '^' + str(exc) + '$'):
                self.index.equivalent(a, b, 'Data')
        else:
            self.assertEqual(self.index.equivalent(a, b, 'Data'), expected)

    def test_polynomial_identity_and_inequality(self):
        for n in range(-4, 5):
            self.compare(f'=(A1+{n})*(A2-1)', f'=A1*A2-A1+{n}*A2-{n}')
            self.compare(f'=A1+A2+{n}', '=SUM(A1:A2)')

    def test_cross_sheet_casefold_quotes_and_missing(self):
        self.compare("='O''Brien'!A1+DATA!A2", "=Data!A2+'O''Brien'!A1")
        self.compare('=Missing!A1', '=A1')

    def test_typed_blanks_and_function_rejections(self):
        for a, b in [('=SUM(A1:A4)', '=A1+A2'), ('=A5+A1', '=A1'),
                     ('=A3', '=A3'), ('=A4', '=1'), ('=SQRT(A1)', '=2'),
                     ('=A1/B2', '=A1/B2'), ('=A1/2', '=0.5*A1')]:
            self.compare(a, b)

    def test_sheet_index_does_not_change_model(self):
        before = dict(self.model.cells), dict(self.model.formulas)
        self.index.equivalent('=A1+A2', '=SUM(A1:A2)', 'Data')
        self.assertEqual(before, (self.model.cells, self.model.formulas))


if __name__ == '__main__':
    unittest.main()
