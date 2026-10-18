from pathlib import Path
from fractions import Fraction
import sys
import unittest
from openpyxl import Workbook
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from tristate_relations_dev23 import NumericRelations, BUDGETS


class TriStateRelationsTests(unittest.TestCase):
    def setUp(self):
        self.w = Workbook(); self.s = self.w.active; self.s.title = 'Main'
        self.s['A1'] = 4; self.s['B1'] = 7; self.s['C1'] = 3
        self.oracle = NumericRelations(self.w)

    def label(self, a, b, **kwargs): return self.oracle.certify(a, b, 'Main', **kwargs)

    def test_exact_algebra_and_fraction_literals(self):
        for a, b in [('=A1+B1', '=B1+A1'), ('=A1*(B1+C1)', '=A1*B1+A1*C1'),
                     ('=A1/10', '=0.1*A1'), ('=1E-2*A1', '=A1/100'), ('=--A1', '=A1')]:
            self.assertEqual(self.label(a, b)['label'], 1, (a, b))

    def test_wrong_formula_needs_exact_recomputable_witness(self):
        result = self.label('=A1-B1', '=A1+B1')
        self.assertEqual(result['label'], 0)
        inputs = {key: Fraction(value) for key, value in result['witness']['inputs'].items()}
        self.assertEqual(Fraction(result['witness']['candidate']), inputs['Main!A1']-inputs['Main!B1'])
        self.assertEqual(Fraction(result['witness']['expected']), inputs['Main!A1']+inputs['Main!B1'])

    def test_dependency_expansion_prevents_impossible_independent_assignments(self):
        self.s['D1'] = '=2*A1'; self.s['E1'] = '=D1+B1'
        self.assertEqual(self.label('=D1', '=2*A1')['label'], 1)
        self.assertEqual(self.label('=E1', '=2*A1+B1')['label'], 1)
        self.assertNotIn('Main!D1', self.label('=D1', '=A1')['witness']['inputs'])

    def test_expected_dependencies_override_injected_formulas(self):
        self.s['D1'] = '=A1*7'
        oracle = NumericRelations(self.w, {'Main!D1': '=A1*2'})
        self.assertEqual(oracle.certify('=D1', '=A1*2', 'Main')['label'], 1)

    def test_sum_range_text_blank_and_cross_sheet_escaping(self):
        self.s['D1'] = 'notes'
        self.assertEqual(self.label('=SUM(A1:E1)', '=A1+B1+C1')['label'], 1)
        other = self.w.create_sheet("Bob's Data"); other['A1'] = 5
        oracle = NumericRelations(self.w)
        self.assertEqual(oracle.certify("='Bob''s Data'!$A$1", "='Bob''s Data'!A1", 'Main')['label'], 1)
        self.assertEqual(self.label('=E1+A1', '=A1')['label'], 1)

    def test_unknown_is_not_negative_or_positive_even_for_identical_text(self):
        for value in ['=IF(A1>0,A1,B1)', '=A1/B1', '=A1^2', '=Named', '="text"',
                      '=A1&"x"', '=A1=1', '=SUM(A1,,B1)', '=SUM(A1)B1', '=A1+']:
            self.assertIsNone(self.label(value, value)['label'], value)
        self.assertIsNone(self.label('=A1+B1', '=A1+B1', in_scope=False)['label'])

    def test_dates_booleans_errors_and_bad_sheet_stay_unknown(self):
        from datetime import datetime
        for value in [True, '#DIV/0!', datetime(2026, 1, 1)]:
            self.s['D1'] = value; oracle = NumericRelations(self.w)
            self.assertIsNone(oracle.certify('=D1+A1', '=A1', 'Main')['label'])
        self.assertIsNone(self.label('=Missing!A1', '=A1')['label'])

    def test_self_cycles_indirect_cycles_and_target_reference_are_unknown(self):
        self.s['D1'] = '=E1'; self.s['E1'] = '=D1'
        self.assertIsNone(self.label('=D1', '=A1')['label'])
        self.assertIsNone(self.label('=A1', '=1', target='Main!A1')['label'])

    def test_variable_divisor_cancellation_does_not_erase_undefinedness(self):
        self.assertIsNone(self.label('=A1/A1', '=1')['label'])
        self.assertIsNone(self.label('=1/0', '=1')['label'])
        self.assertEqual(self.label('=A1/(1+1)', '=A1*0.5')['label'], 1)

    def test_budget_failures_and_range_scalar_are_unknown(self):
        for value in ['=SUM(A1:A300)', '=A1:B1', '=XFE1', '=A1048577', '='+'1+'*600+'1',
                      '='+'A1*'*9+'A1', '='+'9'*65, '=1e99999999999999999']:
            self.assertIsNone(self.label(value, '=A1')['label'], value[:60])

    def test_cache_cannot_bypass_depth_or_cycle_budgets(self):
        for row in range(1, 25): self.s[f'F{row}'] = f'=F{row+1}'
        self.s['F25'] = 9
        first = self.label('=F1', '=A1')
        self.label('=F20', '=A1')
        self.assertEqual(self.label('=F1', '=A1'), first)
        self.assertIsNone(first['label'])

    def test_sum_argument_boundaries_and_precedence(self):
        self.assertEqual(self.label('=SUM(A1+B1,C1*2)', '=A1+B1+2*C1')['label'], 1)
        self.assertEqual(self.label('=A1-B1-C1', '=A1-(B1+C1)')['label'], 1)
        self.assertEqual(self.label('=A1/-2', '=-A1/2')['label'], 1)


if __name__ == '__main__': unittest.main()
