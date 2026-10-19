import unittest

from diagnose_paper_syntax import classify


class SyntaxDiagnosisTests(unittest.TestCase):
    def test_string_percent_is_not_a_percent_operator(self):
        result = classify('=IF(A1="10%",1,0)')
        self.assertEqual(result['primary'], 'text_literal')
        self.assertNotIn('percent_operator', result['features'])

    def test_parse_success_does_not_hide_unsupported_execution_function(self):
        result = classify('=ROUND(A1,2)')
        self.assertEqual(result, dict(status='parsed', unsupported_functions=['ROUND']))

    def test_error_and_logical_literals_stay_separate(self):
        self.assertEqual(classify('=SUM(#REF!)')['primary'], 'error_literal')
        self.assertEqual(classify('=IF(TRUE,1,0)')['primary'], 'logical_literal')

    def test_standard_numeric_formula_stays_supported(self):
        self.assertEqual(classify('=IF(A1>0,SUM(B1:B3),0)'),
                         dict(status='parsed', unsupported_functions=[]))


if __name__ == '__main__':
    unittest.main()
