import unittest

from horizontal_candidates_m3 import generate, candidate_is_safe


class HorizontalCandidateTests(unittest.TestCase):
    def test_row_copy_and_absolute_cross_sheet_reference(self):
        pool = generate({'S!B2': "=T!B1*$A$1", 'S!C2': '=C1*9',
                         'S!D2': "=T!D1*$A$1"})['candidate_pool']
        self.assertIn("='T'!C1*$A$1", [r['formula'] for r in pool['S!C2']])

    def test_low_support_and_unchanged_do_not_generate(self):
        self.assertNotIn('S!C2', generate({'S!B2': '=B1*2', 'S!C2': '=C1*3'})['candidate_pool'])
        self.assertNotIn('S!C2', generate({'S!B2': '=B1*2', 'S!C2': '=C1*2',
                                         'S!D2': '=D1*2'})['candidate_pool'])

    def test_self_reference_and_unsupported_names_reject(self):
        for formula in ('=C2', '=SUM(A1:D3)', '=Rate*C1', '=Table1[Value]'):
            self.assertFalse(candidate_is_safe(formula, ('S', 'C2')))

    def test_legal_exception_gets_candidates_but_no_repair(self):
        result = generate({'S!B2': '=B1*0.2', 'S!C2': '=C1*0.1', 'S!D2': '=D1*0.2'})
        self.assertTrue(result['candidate_pool']['S!C2'])
        self.assertFalse(result['automatic_edit_applied'])
        self.assertEqual(result['selected_repairs'], [])


if __name__ == '__main__':
    unittest.main()
