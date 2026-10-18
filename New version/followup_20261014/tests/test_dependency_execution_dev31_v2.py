"""Boolean boundary is explicit and does not contaminate numeric dependencies."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from dependency_execution_dev31_v2 import Executor
from formulaguard.workbook import WorkbookModel


class ConservativeAggregateTests(unittest.TestCase):
    def test_boolean_reference_and_range_in_each_aggregate_are_unsupported(self):
        for name in ['SUM', 'MIN', 'MAX']:
            for formula in [f'={name}(A1)', f'={name}(A1:A2)']:
                values = {('S', 'A1'): True, ('S', 'A2'): 2}
                e = Executor(WorkbookModel(values, {('S', 'B1'): formula}), values)
                self.assertEqual(e.execute(('S', 'B1'))['reason'], 'aggregate_boolean_coercion_unverified')

    def test_boolean_formula_result_is_also_detected(self):
        e = Executor(WorkbookModel({}, {('S', 'A1'): '=2>1', ('S', 'B1'): '=SUM(A1)'}), {})
        self.assertEqual(e.execute(('S', 'B1'))['reason'], 'aggregate_boolean_coercion_unverified')

    def test_numeric_text_and_blank_inputs_preserve_supported_semantics(self):
        values = {('S', 'A1'): 2, ('S', 'A2'): '100', ('S', 'A3'): None}
        e = Executor(WorkbookModel(values, {('S', 'B1'): '=SUM(A1:A3)'}), values)
        self.assertEqual(e.execute(('S', 'B1'))['value']['value'], 2)

    def test_payment_results_and_lazy_if_preserved(self):
        e = Executor(WorkbookModel({}, {('S', 'A1'): '=PPMT(0,1,12,1200)',
                                       ('S', 'A2'): '=IF(1,12,1/0)'}), {})
        self.assertEqual(e.execute(('S', 'A1'))['value']['value'], -100)
        self.assertEqual(e.execute(('S', 'A2'))['value']['value'], 12)


if __name__ == '__main__':
    unittest.main()
