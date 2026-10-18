import tempfile
from pathlib import Path
import unittest
import openpyxl

from spreadsheetbench2_scoring import exact_metrics, verify_prediction_lock, formula_differences


class ExactMetricTests(unittest.TestCase):
    def test_timeouts_preserve_coverage_denominator(self):
        result = exact_metrics(None, {'S!A1': '=1'}, terminal_status='timeout')
        self.assertEqual(result['confirmed_errors'], 1)
        self.assertEqual(result['correct_repair_coverage'], 0)
        self.assertIsNone(result['precision_all_suggestions'])

    def test_control_unknown_and_wrong_suggestions_all_count(self):
        prediction = {'observed_formulas': {'S!A1': '=0', 'S!A2': '=0', 'S!A3': '=0', 'S!A4': '=0'},
                      'paper': {'rows': [dict(cell=f'S!A{i}', suggested_formula=f'={i}') for i in range(1, 5)]}}
        result = exact_metrics(prediction, {'S!A1': '=1', 'S!A2': '=99', 'S!A5': '=5'}, unknown_cells={'S!A4'})
        self.assertEqual(result['all_suggestions'], 4)
        self.assertEqual(result['exact_correct'], 1)
        self.assertEqual(result['precision_all_suggestions'], .25)
        self.assertEqual(result['correct_repair_coverage'], 1/3)
        self.assertEqual(result['wrong_formula_on_errors'], 1)
        self.assertEqual(result['suggestions_on_unknown'], 1)

    def test_same_formula_is_not_a_modification(self):
        prediction = {'observed_formulas': {'S!A1': '=1'}, 'paper': {'rows': [
            dict(cell='S!A1', suggested_formula='=1'), dict(cell='S!A2', suggested_formula=None)]}}
        self.assertEqual(exact_metrics(prediction, {})['all_suggestions'], 0)

    def test_scoring_blocked_without_lock(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                verify_prediction_lock(Path(root))

    def test_formula_diff_is_separate_from_nonformula_changes(self):
        before, after = openpyxl.Workbook(), openpyxl.Workbook()
        for book in [before, after]:
            book.active.title = 'S'
        before.active['A1'], after.active['A1'] = '=1', '=2'
        before.active['B1'], after.active['B1'] = 3, 4
        before.active['C1'], after.active['C1'] = '=1', 1
        after.active['D1'] = '=5'
        result = formula_differences(before, after)
        self.assertEqual(set(result['formula_changes']), {'S!A1', 'S!C1', 'S!D1'})
        self.assertEqual(result['formula_changes']['S!A1']['kind'], 'formula_changed')
        self.assertEqual(result['formula_changes']['S!C1']['kind'], 'formula_removed')
        self.assertEqual(result['formula_changes']['S!D1']['kind'], 'formula_added')
        self.assertEqual(result['nonformula_value_change_count'], 2)


if __name__ == '__main__':
    unittest.main()
