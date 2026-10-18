"""Regression tests for names/text/complex syntax that regex profiles missed."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev11 import qualify, syntax_evidence


def proposal(original, candidate):
    model = WorkbookModel.from_cells({}, {('Sheet', 'C2'): original})
    prior = {'rows': [{'cell': 'Sheet!C2', 'status': 'propose',
                      'suggested_formula': candidate, 'candidate_formula': candidate,
                      'reason': 'column_supported_nonconstant_anomaly'}]}
    before = deepcopy(prior)
    actual = dict(model.formulas)
    result = qualify(model, prior)
    assert prior == before and model.formulas == actual
    return result['rows'][0]


class CompleteASTGateTests(unittest.TestCase):
    def test_arithmetic_and_absolute_reference_proposals_preserved(self):
        for original, candidate in [('=A2*B2+C2', '=A2*B2-C2'),
                                    ('=B1+E228', '=$B$1+E228'),
                                    ('=A2*0.85-B2', '=A2-B2')]:
            row = proposal(original, candidate)
            self.assertEqual(row['status'], 'propose')
            self.assertEqual(row['suggested_formula'], candidate)
            self.assertFalse(row['complete_ast_gate']['business_authority_from_parsing'])

    def test_supported_functions_and_quoted_sheet_references(self):
        for formula in ['=SUM(A1:B3)', '=IF(A1>0,MAX(B1:B3),0)',
                        '=AVERAGE(A1:A3)', '=COUNT(A1:B9)',
                        "='Owner''s Plan'!A2+Sheet2!$B$3"]:
            self.assertTrue(syntax_evidence(formula)['supported'], formula)

    def test_names_and_named_checks_cannot_be_replaced_by_majority_units(self):
        for name in ['Check_balance_sheet', 'Check_master', 'Arbitrary_new_name']:
            row = proposal('=' + name, '=Currency & "000"')
            self.assertEqual(row['status'], 'review')
            self.assertIsNone(row['suggested_formula'])
            self.assertIsNone(row['candidate_formula'])
            self.assertEqual(row['suppressed_proposal']['formula'], '=Currency & "000"')

    def test_literal_units_are_protected_without_a_name_dictionary(self):
        for unit in ['/MW', '/MWh', '/kg', '/student']:
            row = proposal('=A1 & "' + unit + '"', '=A1 & ""')
            self.assertEqual(row['status'], 'review')

    def test_unsupported_original_and_candidate_each_block_proposal(self):
        for original, candidate in [('=Named_cost', '=A1'), ('=A1', '=Named_cost'),
                                    ('=A1', '="USD"'), ('="USD"', '=A1'),
                                    ('=TODAY()', '=A1'), ('=A1', '=XLOOKUP(A1,B1,C1)')]:
            self.assertEqual(proposal(original, candidate)['status'], 'review')

    def test_structured_external_arrays_and_invalid_arity_abstain(self):
        for formula in ['=Table1[Cost]', '=[Other.xlsx]Sheet1!A1', '=SUM({1,2})',
                        '=IF(A1)', '=MAX()', '=A1#', '=LET(x,1,x)', '=TRUE']:
            self.assertFalse(syntax_evidence(formula)['supported'], formula)

    def test_grid_and_parser_resource_limits(self):
        for formula in ['=XFE1', '=A1048577', '=A1+' + '1+' * 5000 + '1',
                        '=' + '(' * 1200 + 'A1' + ')' * 1200]:
            self.assertFalse(syntax_evidence(formula)['supported'], formula)

    def test_review_and_abstention_remain_in_output(self):
        model = WorkbookModel.from_cells({}, {('Sheet', 'A1'): '=Named_range'})
        prior = {'rows': [{'cell': 'Sheet!A1', 'status': 'review', 'suggested_formula': None}]}
        self.assertEqual(qualify(model, prior)['rows'], prior['rows'])


if __name__ == '__main__':
    unittest.main()
