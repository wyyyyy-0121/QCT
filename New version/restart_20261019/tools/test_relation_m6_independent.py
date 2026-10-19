from fractions import Fraction
import unittest

from score_relation_m6 import formula_value, rational_expression, branch_expression


class IndependentRelationChecks(unittest.TestCase):
    def test_fraction_points_distinguish_current_coincidence_from_identity(self):
        refs = {'B2': 'q', 'C2': 'd'}
        self.assertEqual(formula_value('=B2/C2', refs, 10, 1),
                         formula_value('=B2*(2-C2)', refs, 10, 1))
        self.assertEqual(formula_value('=B2/C2', refs, 10, Fraction(1, 2)), 20)
        self.assertEqual(formula_value('=B2*(2-C2)', refs, 10, Fraction(1, 2)), 15)

    def test_nested_if_arguments_and_commas_inside_text(self):
        formula = '=IF(A1="a,b",IF(A2=0,"x,y",B2),(B2/C2))'
        self.assertEqual(branch_expression(formula), '=(B2/C2)')

    def test_independent_arithmetic_rejects_calls_and_unknown_symbols(self):
        for expression in ('open("x")', 'q/x', 'q.__class__'):
            with self.assertRaises(ValueError):
                rational_expression(expression, dict(q=Fraction(10), d=Fraction(2)))


if __name__ == '__main__':
    unittest.main()
