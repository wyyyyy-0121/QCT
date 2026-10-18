"""V2 conservatively rejects coercion without altering direct bool references."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from string_execution_dev28_v2 import execute, parse, Unsupported
from typed_execution_adapter import ExcelError


class ConservativeBooleanTests(unittest.TestCase):
    def test_both_boolean_values_are_explicitly_unsupported_in_text(self):
        for value in [True, False]:
            for formula in ['=A1&"x"', '=CONCATENATE("x",A1)',
                            '=CONCATENATE("outer",CONCATENATE(A1,"inner"))']:
                with self.subTest(value=value, formula=formula):
                    with self.assertRaisesRegex(Unsupported, 'boolean_text_coercion_unverified'):
                        execute(parse(formula), 'S', {('S', 'A1'): value})

    def test_direct_boolean_preserves_type(self):
        for value in [True, False]:
            actual = execute(parse('=(A1)'), 'S', {('S', 'A1'): value})
            self.assertIs(actual, value)

    def test_boolean_text_and_numbers_are_not_misclassified(self):
        self.assertEqual(execute(parse('=A1&B1&C1&D1'), 'S', {
            ('S', 'A1'): 'TRUE', ('S', 'B1'): 'FALSE', ('S', 'C1'): 1, ('S', 'D1'): 0}), 'TRUEFALSE10')

    def test_cross_sheet_casefold_and_error_types(self):
        with self.assertRaisesRegex(Unsupported, 'boolean_text_coercion_unverified'):
            execute(parse('="x"&other!A1'), 'S', {('Other', 'A1'): True}, sheet_names=iter(['S', 'Other']))
        self.assertEqual(execute(parse('=A1&"x"'), 'S', {('S', 'A1'): ExcelError('#VALUE!')}), ExcelError('#VALUE!'))
        with self.assertRaisesRegex(Unsupported, 'formula_dependency_not_computed'):
            execute(parse('=A1&"x"'), 'S', {}, formula_cells=iter([('S', 'A1')]))


if __name__ == '__main__':
    unittest.main()
