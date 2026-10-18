"""Semantic comparisons, uncached inventory, observable blockers and known limits."""
from pathlib import Path
import sys
import tempfile
import unittest

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from formulaguard.workbook import WorkbookModel
from visible_relations_dev30 import predict
from relation_algebra_dev30 import equivalent, UnknownRelation


class VisibleRelationsTests(unittest.TestCase):
    def model(self, values, hidden=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'sample.xlsx'; book = openpyxl.Workbook(); sheet = book.active; sheet.title = 'S'
            for address, value in values.items():
                sheet[address] = value
            if hidden:
                sheet.row_dimensions[hidden].hidden = True
            book.save(path)
            return WorkbookModel.from_xlsx(path)

    def cash(self, formula='=B2+B3', **extra):
        return self.model({'A2': 'Total Cash Inflows', 'B2': 100, 'A3': 'Total Cash Outflows', 'B3': 30,
                           'A4': 'Net Cash Flow:', 'B4': formula, **extra})

    def test_cash_identity_and_whitespace_binding_without_fixed_addresses(self):
        m = self.model({'H11': ' Total   Cash Inflows: ', 'N11': 100, 'H17': 'TOTAL CASH OUTFLOWS', 'N17': 30,
                        'H25': 'Net Cash Flow', 'N25': '=N11+N17'})
        p = predict(m); self.assertEqual(p['suggestions'][0]['suggested_formula'], '=N11-N17')
        self.assertFalse(p['author_intent_proven'])

    def test_clean_algebraic_forms_are_not_unnecessary_suggestions(self):
        for formula in ['=+B2-B3', '=SUM(B2,-B3)', '=(B2-B3)*1', '=B2+(-1)*B3']:
            with self.subTest(formula=formula):
                self.assertEqual(predict(self.cash(formula))['suggestions'], [])

    def test_visible_exception_conflicting_instruction_and_duplicates_abstain(self):
        for extra in [{'A8': 'Exception: a one-off adjustment applies.'},
                      {'A8': 'Net Cash Flow equals Total Cash Inflows plus Total Cash Outflows.'},
                      {'A8': 'Total Cash Inflows', 'B8': 50}]:
            with self.subTest(extra=extra):
                self.assertEqual(predict(self.cash(**extra))['suggestions'], [])

    def test_hidden_role_and_output_abstain(self):
        values = {'A2': 'Total Cash Inflows', 'B2': 100, 'A3': 'Total Cash Outflows', 'B3': 30,
                  'A4': 'Net Cash Flow', 'B4': '=B2+B3'}
        for row in [2, 4]:
            self.assertEqual(predict(self.model(values, hidden=row))['suggestions'], [])

    def test_percentage_sum_and_signed_annual_cost(self):
        m = self.model({'B2': 'Base Annual Development Cost:', 'E2': -100,
                        'B4': 'Rewrite Costs (% of Base)', 'E4': .1,
                        'B6': 'Maintenance Costs (% of Base)', 'E6': .2,
                        'D8': 'Yearly % Base:', 'E8': '=SUM(E4:E6)',
                        'D9': 'Yearly Cost', 'E9': '=E8+E2'})
        p = predict(m)
        self.assertEqual([(r['cell'], r['suggested_formula']) for r in p['suggestions']], [('S!E9', '=E8*E2')])
        self.assertTrue(equivalent('=SUM(E4:E6)', '=SUM(E4,E6)', 'S', m))

    def test_opening_rollforward_requires_matching_units(self):
        values = {'B8': 'Opening Balance', 'C8': 'kGBP', 'F8': '=F11',
                  'B11': 'Closing Balance', 'C11': 'kGBP', 'E11': 30, 'F11': 40}
        self.assertEqual(predict(self.model(values))['suggestions'][0]['suggested_formula'], '=E11')
        values['C11'] = 'GBP'
        self.assertEqual(predict(self.model(values))['suggestions'], [])

    def test_unmarked_exception_remains_a_harmful_hypothesis(self):
        p = predict(self.cash('=(B2-B3)+10'))
        self.assertEqual(p['suggestions'][0]['suggested_formula'], '=B2-B3')
        self.assertFalse(p['suggestions'][0]['evidence']['author_intent_proven'])

    def test_algebra_keeps_uncached_formula_dependency_and_rejects_unknown(self):
        m = self.cash('=B2-B3', B2='=SUM(C2:D2)', C2=40, D2=60)
        self.assertTrue(equivalent('=B2-B3', '=SUM(B2,-B3)', 'S', m))
        self.assertFalse(equivalent('=B2-B3', '=-B3', 'S', m))
        with self.assertRaises(UnknownRelation):
            equivalent('=IF(B2>0,B2,0)', '=B2', 'S', m)


if __name__ == '__main__':
    unittest.main()
