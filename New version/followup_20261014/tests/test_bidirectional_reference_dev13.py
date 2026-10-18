from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from openpyxl.formula.translate import Translator
from bidirectional_reference_dev13 import candidates, reference_difference, supported_ast


class BidirectionalReferenceTests(unittest.TestCase):
    def grid(self):
        return {('Outputs', f'{col}{row}'):
                Translator("='Inputs'!A1+'Inputs'!$Z$1", origin='J10').translate_formula(f'{col}{row}')
                for col in 'JKLMNO' for row in range(10, 16)}

    def test_clean_grid_has_no_candidates(self):
        self.assertFalse(any(candidates(self.grid()).values()))

    def test_single_reference_error_supported_in_two_axes(self):
        grid = self.grid()
        expected = grid[('Outputs', 'L12')]
        grid[('Outputs', 'L12')] = "='Inputs'!D3+'Inputs'!$Z$1"
        before = dict(grid)
        self.assertEqual(candidates(grid)['both']['Outputs!L12']['formula'], expected)
        self.assertEqual(grid, before)

    def test_coefficient_and_operator_changes_are_not_reference_edits(self):
        grid = self.grid()
        for formula in ["='Inputs'!C3-'Inputs'!$Z$1", "='Inputs'!C3+'Inputs'!$Z$1+2"]:
            grid[('Outputs', 'L12')] = formula
            self.assertNotIn('Outputs!L12', candidates(grid)['both'])

    def test_two_axes_can_expose_same_unmarked_legal_exception(self):
        # Deliberately documents the information boundary; not a safety claim.
        grid = self.grid()
        grid[('Outputs', 'L12')] = "='Inputs'!D3+'Inputs'!$Z$1"
        evidence = candidates(grid)['both']['Outputs!L12']
        self.assertFalse(evidence['business_correctness_proven'])

    def test_single_axis_ablation_is_distinct(self):
        grid = {k:v for k,v in self.grid().items() if k[1].startswith('L')}
        grid[('Outputs', 'L12')] = "='Inputs'!D3+'Inputs'!$Z$1"
        result = candidates(grid)
        self.assertIn('Outputs!L12', result['column_only'])
        self.assertNotIn('Outputs!L12', result['both'])

    def test_peer_directly_dependent_on_target_rejected(self):
        grid = self.grid()
        grid[('Outputs', 'L12')] = "='Inputs'!D3+'Inputs'!$Z$1"
        grid[('Outputs', 'L11')] = '=L12'
        self.assertNotIn('Outputs!L12', candidates(grid)['both'])

    def test_large_integer_constants_not_aliased_by_float(self):
        a = supported_ast('=A1+9007199254740992')
        b = supported_ast('=A2+9007199254740993')
        self.assertIsNone(reference_difference(a,b))

    def test_sheet_or_absolute_mode_change_rejected(self):
        a = supported_ast("='A'!B2")
        for text in ["='B'!B3", "='A'!$B3", "='A'!C3"]:
            self.assertIsNone(reference_difference(a,supported_ast(text)))


if __name__ == '__main__':
    unittest.main()
