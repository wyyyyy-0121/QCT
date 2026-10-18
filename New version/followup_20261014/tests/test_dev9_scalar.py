"""Invariants and counterexamples for the coefficient-majority experiment."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev9 import arithmetic, scalar_difference, extend


def fixture(forms):
    cells = {}
    formulas = {}
    for sheet, formula in forms.items():
        cells.update({(sheet, 'A1'): 'Units', (sheet, 'B1'): 'Price',
                      (sheet, 'C1'): 'Expense', (sheet, 'D1'): 'Output',
                      (sheet, 'A2'): 12, (sheet, 'B2'): 8, (sheet, 'C2'): 3})
        formulas[sheet, 'D2'] = formula
    model = WorkbookModel.from_cells(cells, formulas)
    base = {'rows': [{'cell': s+'!'+a, 'status': 'review', 'suggested_formula': None}
                     for s, a in formulas], 'limitations': []}
    return model, base


def run(forms, change=None):
    model, base = fixture(forms)
    if change:
        change(model, base)
    before, prior = dict(model.formulas), deepcopy(base)
    result = extend(model, base, list(forms))
    assert model.formulas == before and base == prior
    return {r['cell']: r for r in result['rows']}


class ScalarTests(unittest.TestCase):
    def test_exactly_one_positive_scalar_edit(self):
        for a, b in [('=A2*B2*0.85-C2', '=A2*B2-C2'),
                     ('=0.85*A2*B2-C2', '=A2*B2-C2'),
                     ('=A2/1.1-C2', '=A2-C2'),
                     ('=A2*0.85-C2', '=A2*0.9-C2')]:
            self.assertTrue(scalar_difference(arithmetic(a), arithmetic(b)), (a, b))

    def test_offsets_signs_references_and_multiple_edits_rejected(self):
        for a, b in [('=A2*B2-C2', '=A2*B2+C2'),
                     ('=A2*B2-C2', '=A3*B2-C2'),
                     ('=A2*B2-C2+3', '=A2*B2-C2+4'),
                     ('=A2*(1-B2)', '=A2*(0.8-B2)'),
                     ('=A2*0.8-C2*0.5', '=A2*0.9-C2*0.6'),
                     ('=A2*0-C2', '=A2-C2'),
                     ('=A2*1-C2', '=A2-C2')]:
            self.assertFalse(scalar_difference(arithmetic(a), arithmetic(b)), (a, b))

    def test_functions_ranges_and_explicit_sheets_rejected(self):
        for value in ['=SUM(A2:B2)', '=A!A2*0.85', '=A2^2']:
            with self.assertRaises(ValueError):
                arithmetic(value)

    def test_majority_can_recover_but_does_not_establish_intent(self):
        forms = dict(A='=A2*B2*0.85-C2', B='=A2*B2-C2', C='=A2*B2-C2')
        result = run(forms)
        self.assertEqual(result['A!D2']['suggested_formula'], '=A2*B2-C2')
        self.assertFalse(result['A!D2']['selection_evidence'][0]['independent_business_proof'])

    def test_tie_and_single_support_rejected(self):
        self.assertNotEqual(run(dict(A='=A2*0.85', B='=A2'))['A!D2']['status'], 'propose')
        forms = dict(A='=A2*0.85', B='=A2', C='=A2*0.85', D='=A2*0.85', E='=A2')
        self.assertNotEqual(run(forms)['A!D2']['status'], 'propose')

    def test_header_and_policy_guards(self):
        forms = dict(A='=A2*0.85', B='=A2', C='=A2')
        def header(model, _):
            model.cells['B', 'A1'] = 'Different meaning'
        self.assertNotEqual(run(forms, header)['A!D2']['status'], 'propose')
        def policy(model, _):
            model.cells['A', 'F1'] = 'Notes: Local exception applies.'
        self.assertNotEqual(run(forms, policy)['A!D2']['status'], 'propose')
        def peer_policy(model, _):
            model.cells['B', 'F1'] = 'Notes: Local exception applies.'
        self.assertNotEqual(run(forms, peer_policy)['A!D2']['status'], 'propose')

    def test_existing_proposals_and_inputs_preserved_exactly(self):
        forms = dict(A='=A2*0.85', B='=A2', C='=A2')
        def proposal(_, base):
            base['rows'][0].update(status='propose', suggested_formula='=A2*0.9', reason='prior')
        result = run(forms, proposal)
        self.assertEqual(result['A!D2'], {'cell':'A!D2', 'status':'propose',
                                        'suggested_formula':'=A2*0.9', 'reason':'prior'})

    def test_common_corruption_is_not_recovered_by_votes(self):
        forms = {s:'=A2*0.85' for s in 'ABCDE'}
        self.assertTrue(all(r['status'] != 'propose' for r in run(forms).values()))


if __name__ == '__main__':
    unittest.main()
