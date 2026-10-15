"""Auxiliary contract integrity tests; no final/generalization claim."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from contract_mode_dev1 import apply_contract, validate_contract

BINDING = 'a' * 64


def fixture():
    cells = {('A', 'B1'): 'Opening inventory [units]', ('A', 'C1'): 'Receipts [units]',
             ('A', 'D1'): 'Issues [units]', ('A', 'E1'): 'Write-offs [units]',
             ('A', 'F1'): 'Closing inventory [units]',
             ('A', 'B2'): 100, ('A', 'C2'): 20, ('A', 'D2'): 5, ('A', 'E2'): 1,
             ('A', 'C3'): 10, ('A', 'D3'): 4, ('A', 'E3'): 2,
             ('A', 'C4'): 9, ('A', 'D4'): 3, ('A', 'E4'): 0}
    forms = {('A', 'F2'): '=B2+C2+D2-E2', ('A', 'B3'): '=F2',
             ('A', 'F3'): '=B3+C3+D3-E3', ('A', 'B4'): '=F3',
             ('A', 'F4'): '=B4+C4-D4-E4', ('A', 'F5'): '=SUM(F2:F4)'}
    model = WorkbookModel.from_cells(cells, forms)
    return model, {'rows': [{'cell': s+'!'+a, 'status': 'abstain', 'suggested_formula': None}
                           for s, a in model.formulas]}


def contract():
    return {'schema_version': 1, 'mode': 'author_supplied_contract',
            'author': 'Development fixture author (not an independently verified author)',
            'source_uri': 'development-fixture:inventory', 'provenance_status': 'development_authored',
            'workbook_sha256': BINDING, 'sheet_scopes': {'A': {
                'header_row': 1, 'data_rows': [2, 4], 'output_column': 'F',
                'output_header': 'Closing inventory [units]',
                'roles': {'opening': {'header': 'Opening inventory [units]'},
                          'receipts': {'header': 'Receipts [units]'},
                          'issues': {'header': 'Issues [units]'},
                          'writeoffs': {'header': 'Write-offs [units]'}},
                'formula_template': '={opening}+{receipts}-{issues}-{writeoffs}'}}}


def run(model, prior, value=None):
    return {r['cell']: r for r in apply_contract(model, prior, value or contract(), BINDING)['rows']}


class ContractModeTests(unittest.TestCase):
    def test_repairs_only_output_column_inside_explicit_region(self):
        model, prior = fixture(); before = deepcopy((model.cells, model.formulas, prior))
        rows = run(model, prior)
        self.assertEqual({k for k, v in rows.items() if v['status'] == 'propose'}, {'A!F2', 'A!F3'})
        self.assertEqual(rows['A!F2']['suggested_formula'], '=B2+C2-D2-E2')
        self.assertEqual(rows['A!B3'], prior['rows'][1])
        self.assertEqual(rows['A!F5']['status'], 'abstain')
        self.assertEqual((model.cells, model.formulas, prior), before)

    def test_matching_contract_cancels_wrong_upstream_change(self):
        model, prior = fixture()
        prior['rows'][4].update(status='propose', suggested_formula='=B4+C4+D4-E4')
        row = run(model, prior)['A!F4']
        self.assertEqual(row['status'], 'abstain'); self.assertIsNone(row['suggested_formula'])

    def test_row_rule_preserves_exception_and_repairs_other_row(self):
        model, prior = fixture(); value = contract()
        value['sheet_scopes']['A']['row_rules'] = [{'row': 2, 'formula_template': '={opening}+{receipts}+{issues}-{writeoffs}'}]
        prior['rows'][0].update(status='propose', suggested_formula='=B2+C2-D2-E2')
        rows = run(model, prior, value)
        self.assertEqual(rows['A!F2']['status'], 'abstain')
        self.assertEqual(rows['A!F3']['status'], 'propose')

    def test_explicit_exclusion_clears_upstream_proposal(self):
        model, prior = fixture(); value = contract()
        value['sheet_scopes']['A']['excluded_rows'] = [2]
        prior['rows'][0].update(status='propose', suggested_formula='=B2+C2-D2-E2')
        row = run(model, prior, value)['A!F2']
        self.assertEqual(row['status'], 'review'); self.assertIsNone(row['suggested_formula'])

    def test_scope_requires_explicit_bounds_and_column(self):
        for key in ('header_row', 'data_rows', 'output_column'):
            with self.subTest(key=key):
                value = contract(); del value['sheet_scopes']['A'][key]
                with self.assertRaises(ValueError): validate_contract(value)

    def test_incorrect_binding_and_incomplete_predictions_rejected(self):
        model, prior = fixture()
        with self.assertRaisesRegex(ValueError, 'hash_mismatch'):
            apply_contract(model, prior, contract(), 'b' * 64)
        prior['rows'].pop()
        with self.assertRaisesRegex(ValueError, 'exactly_once'):
            apply_contract(model, prior, contract(), BINDING)

    def test_duplicate_prediction_rejected(self):
        model, prior = fixture(); prior['rows'].append(deepcopy(prior['rows'][0]))
        with self.assertRaises(ValueError): apply_contract(model, prior, contract(), BINDING)

    def test_duplicate_or_conflicting_row_rules_rejected(self):
        for number in (2, 99, True):
            value = contract(); rule = {'row': number, 'formula_template': '={opening}+{receipts}+{issues}-{writeoffs}'}
            value['sheet_scopes']['A']['row_rules'] = [rule, deepcopy(rule)]
            with self.assertRaises(ValueError): validate_contract(value)
        value = contract(); value['sheet_scopes']['A']['row_rules'] = [rule | {'row': 2}]
        value['sheet_scopes']['A']['excluded_rows'] = [2]
        with self.assertRaises(ValueError): validate_contract(value)

    def test_missing_or_duplicate_unit_header_reviews_output(self):
        for replacement in ('Closing inventory [kg]', 'Receipts [kg]'):
            model, prior = fixture()
            addr = 'F1' if replacement.startswith('Closing') else 'C1'
            model.cells['A', addr] = replacement
            self.assertEqual(run(model, prior)['A!F2']['status'], 'review')
        model, prior = fixture(); model.cells['A', 'G1'] = 'Closing inventory [units]'
        self.assertEqual(run(model, prior)['A!F2']['status'], 'review')

    def test_raw_reference_unknown_role_and_function_rejected(self):
        for template in ('={opening}+A99', '={unknown}', '=SUM({opening})', '={opening}^2', '=42'):
            with self.subTest(template=template):
                value = contract(); value['sheet_scopes']['A']['formula_template'] = template
                with self.assertRaises(ValueError): validate_contract(value)

    def test_missing_numeric_input_and_target_error_review(self):
        for value in (None, True, 'not measured'):
            model, prior = fixture(); model.cells['A', 'C2'] = value
            self.assertEqual(run(model, prior)['A!F2']['status'], 'review')
        model, prior = fixture(); value = contract()
        value['sheet_scopes']['A']['formula_template'] = '={opening}/({issues}-{issues})'
        self.assertEqual(run(model, prior, value)['A!F2']['status'], 'review')

    def test_unrelated_execution_error_does_not_authorize_or_block_target(self):
        model, prior = fixture(); model.formulas['Other', 'Z1'] = '=1/0'
        prior['rows'].append({'cell': 'Other!Z1', 'status': 'abstain'})
        rows = run(model, prior)
        self.assertEqual(rows['A!F2']['status'], 'propose')
        self.assertEqual(rows['Other!Z1']['status'], 'abstain')

    def test_missing_provenance_and_boolean_scope_rejected(self):
        for field in ('author', 'source_uri', 'workbook_sha256', 'provenance_status'):
            value = contract(); value.pop(field)
            with self.assertRaises(ValueError): validate_contract(value)
        value = contract(); value['sheet_scopes']['A']['data_rows'] = [True, 4]
        with self.assertRaises(ValueError): validate_contract(value)

    def test_declared_formula_can_omit_a_waived_role(self):
        model, prior = fixture(); value = contract()
        value['sheet_scopes']['A']['formula_template'] = '={opening}+{receipts}-{issues}'
        self.assertEqual(run(model, prior, value)['A!F2']['suggested_formula'], '=B2+C2-D2')

    def test_negative_values_do_not_control_role_binding(self):
        model, prior = fixture(); model.cells['A', 'C2'] = -20
        self.assertEqual(run(model, prior)['A!F2']['suggested_formula'], '=B2+C2-D2-E2')

    def test_wrong_declared_contract_is_not_automatically_verified(self):
        model, prior = fixture(); value = contract()
        value['sheet_scopes']['A']['formula_template'] = '={opening}-{receipts}-{issues}-{writeoffs}'
        result = apply_contract(model, prior, value, BINDING)
        self.assertFalse(result['main_acceptance_eligible'])
        self.assertTrue(all(not row.get('contract_provenance', {}).get('author_identity_verified', False)
                            for row in result['rows']))
        self.assertEqual(result['rows'][0]['suggested_formula'], '=B2-C2-D2-E2')


if __name__ == '__main__':
    unittest.main()
