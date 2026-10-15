"""Checks for the explicitly bounded common-peer contract experiment."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev6 import augment, contract_formula


HEADERS = ['Period', 'Opening inventory [units]', 'Receipts [units]',
           'Issues [units]', 'Write-offs [units]', 'Closing inventory [units]']


def fixture(formulas, headers=HEADERS):
    cells = {}; forms = {}
    for sheet, formula in formulas.items():
        cells.update({(sheet, f'{col}1'): text for col, text in zip('ABCDEF', headers)})
        cells.update({(sheet, 'B2'): 100, (sheet, 'C2'): 20,
                      (sheet, 'D2'): 5, (sheet, 'E2'): 1})
        forms[sheet, 'F2'] = formula
    model = WorkbookModel.from_cells(cells, forms)
    prior = {'rows': [{'cell': s+'!'+a, 'status': 'review', 'suggested_formula': None}
                      for s, a in model.formulas]}
    return model, prior


def rows(pred):
    return {row['cell']: row for row in pred['rows']}


class Dev6ContractTests(unittest.TestCase):
    def test_common_peer_corruption_uses_exact_contract(self):
        model, prior = fixture({s: '=B2+C2+D2-E2' for s in 'ABCDE'})
        result = rows(augment(model, prior, list('ABCDE')))
        for sheet in 'ABCDE':
            self.assertEqual(result[sheet+'!F2']['status'], 'propose')
            self.assertEqual(result[sheet+'!F2']['suggested_formula'], '=B2+C2-D2-E2')
            self.assertEqual(result[sheet+'!F2']['reason'],
                             'explicit_contract_recovers_common_peer_corruption')

    def test_mixed_peers_are_left_to_dev5(self):
        forms = {s: '=B2+C2+D2-E2' for s in 'ABCD'}
        forms['E'] = '=B2+C2-D2-E2'
        model, prior = fixture(forms)
        result = rows(augment(model, prior, list(forms)))
        self.assertEqual(result['A!F2']['status'], 'propose')
        self.assertEqual(result['A!F2']['reason'], 'peer_candidate_resolves_opposite_sign')

    def test_unknown_output_and_unit_headers_do_not_activate_contract(self):
        model, prior = fixture({s: '=B2+C2+D2-E2' for s in 'ABCDE'},
                               HEADERS[:-1] + ['Result [different unit system]'])
        result = rows(augment(model, prior, list('ABCDE')))
        self.assertTrue(all(row['status'] != 'propose' for row in result.values()))

    def test_contract_templates_cover_registered_formulas(self):
        roles = {2: ('opening loan [usd]', 1), 3: ('interest [usd]', 1),
                 4: ('payment [usd]', -1)}
        self.assertEqual(contract_formula('closing loan [usd]', roles, 2), '=B2+C2-D2')

    def test_temperature_scale_role_is_completed_for_contract(self):
        headers = ['Sample', 'Temperature [C]', 'Scale [F/C]', 'Offset [F]',
                   'Sensor correction [F]', 'Temperature [F]']
        model, prior = fixture({s: '=B2*C2-D2+E2' for s in 'ABCDE'}, headers)
        result = rows(augment(model, prior, list('ABCDE')))
        for sheet in 'ABCDE':
            self.assertEqual(result[sheet+'!F2']['status'], 'propose')
            self.assertEqual(result[sheet+'!F2']['suggested_formula'], '=B2*C2+D2+E2')


if __name__ == '__main__':
    unittest.main()
