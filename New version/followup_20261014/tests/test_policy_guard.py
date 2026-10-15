from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev3 import policy_notes, review_guard


class PolicyGuardTests(unittest.TestCase):
    def test_visible_policy_routes_only_relevant_sheet_to_review(self):
        model = WorkbookModel.from_cells(
            {('A', 'H1'): 'Business policy', ('A', 'H2'): 'Shipping is absorbed by seller.'},
            {('A', 'F2'): '=1', ('B', 'F2'): '=1'})
        pred = {'rows': [{'cell': s + '!F2', 'status': 'propose', 'suggested_formula': '=2'}
                         for s in ['A', 'B']]}
        got = review_guard(model, pred)
        self.assertEqual([r['status'] for r in got['rows']], ['review', 'propose'])
        self.assertIsNone(got['rows'][0]['suggested_formula'])
        self.assertEqual(pred['rows'][0]['status'], 'propose')

    def test_numeric_assumption_table_is_not_policy_prose(self):
        model = WorkbookModel.from_cells({('A', 'A1'): 'Assumptions', ('A', 'A2'): .2}, {})
        self.assertEqual(policy_notes(model), {})

    def test_inline_chinese_note_supported(self):
        model = WorkbookModel.from_cells({('A', 'C7'): '业务规则：此行免运费'}, {})
        self.assertIn('A', policy_notes(model))

    def test_formula_text_does_not_act_as_a_policy(self):
        model = WorkbookModel.from_cells({('A', 'A1'): 'Notes'}, {('A', 'A2'): '="waived"'})
        self.assertEqual(policy_notes(model), {})


if __name__ == '__main__':
    unittest.main()
