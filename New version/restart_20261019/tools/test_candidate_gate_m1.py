"""Mechanism and counterexample tests, not a model-accuracy benchmark."""
from copy import deepcopy
import unittest

from candidate_gate_m1 import gate_row, filter_prediction


class BilateralGateTests(unittest.TestCase):
    def test_vertical_and_horizontal_copy_evidence(self):
        row = {'cell': 'S!B2', 'suggested_formula': '=A2*2'}
        self.assertEqual(gate_row(row, {'S!B1': '=A1*2', 'S!B2': '=A2*3',
                                       'S!B3': '=A3*2'}), (True, 'bilateral_support'))
        self.assertTrue(gate_row({'cell': 'S!C2', 'suggested_formula': '=C1'},
                               {'S!B2': '=B1', 'S!C2': '=C1*2', 'S!D2': '=D1'})[0])

    def test_boundary_and_competing_axes_reject(self):
        row = {'cell': 'S!B2', 'suggested_formula': '=B1'}
        self.assertEqual(gate_row(row, {'S!A2': '=A1', 'S!C2': '=C1',
                                       'S!B1': '=A1', 'S!B3': '=A3'})[1], 'axis_conflict')
        self.assertFalse(gate_row(row, {'S!B1': '=B0', 'S!B2': '=B1*2'})[0])

    def test_named_external_structured_and_self_references_reject(self):
        for formula in ('=Rate*A2', "='[Book.xlsx]S'!A2", '=SUM(Table1[Cost])',
                        '=SUM(S:T!A2)', '=B2+1', '=SUM(A1:C3)', '=1', '=#REF!'):
            with self.subTest(formula=formula):
                self.assertFalse(gate_row({'cell': 'S!B2', 'suggested_formula': formula}, {})[0])

    def test_unchanged_and_input_immutability(self):
        prediction = {'observed_formulas': {'S!B2': '=A2'}, 'paper': {'rows': [
            {'cell': 'S!B2', 'suggested_formula': '=A2'}]}}
        original = deepcopy(prediction)
        filtered = filter_prediction(prediction)
        self.assertEqual(prediction, original)
        self.assertIsNone(filtered['paper']['rows'][0]['suggested_formula'])

    def test_single_cell_business_exception_is_a_known_false_positive(self):
        # The middle row may legitimately have a different tax rate. Formula
        # copying alone cannot tell this workbook apart from a typo case.
        observed = {'S!B1': '=A1*0.2', 'S!B2': '=A2*0.1', 'S!B3': '=A3*0.2'}
        self.assertTrue(gate_row({'cell': 'S!B2', 'suggested_formula': '=A2*0.2'}, observed)[0])


if __name__ == '__main__':
    unittest.main()
