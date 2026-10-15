"""Behavioral checks, not evidence of unseen-domain generalization."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev5 import augment, header_index, policy_scopes, semantic_check, semantic_roles

HEADERS = ['Period', 'Opening inventory [units]', 'Receipts [units]',
           'Issues [units]', 'Write-offs [units]', 'Closing inventory [units]']


def fixture(formulas=None, headers=HEADERS):
    cells = {}; forms = {}
    formulas = formulas or {'A': '=B2+C2+D2-E2', 'B': '=B2+C2-D2-E2'}
    for sheet, formula in formulas.items():
        cells.update({(sheet, f'{col}1'): text for col, text in zip('ABCDEF', headers)})
        cells.update({(sheet, 'B2'): 100, (sheet, 'C2'): 20,
                      (sheet, 'D2'): 5, (sheet, 'E2'): 1})
        forms[sheet, 'F2'] = formula
    model = WorkbookModel.from_cells(cells, forms)
    prior = {'rows': [{'cell': s+'!'+a, 'status': 'abstain', 'suggested_formula': None}
                      for s, a in model.formulas]}
    return model, prior


def by_cell(pred):
    return {row['cell']: row for row in pred['rows']}


class Dev5SelectionTests(unittest.TestCase):
    def test_minority_candidate_repairs_four_copied_errors_without_harming_peer(self):
        forms = {s: '=B2+C2+D2-E2' for s in 'ABCD'}
        forms['E'] = '=B2+C2-D2-E2'
        model, prior = fixture(forms)
        before_cells, before_forms, before_prior = deepcopy(model.cells), deepcopy(model.formulas), deepcopy(prior)
        result = by_cell(augment(model, prior, list(forms)))
        for sheet in 'ABCD':
            self.assertEqual(result[sheet+'!F2']['status'], 'propose')
            self.assertEqual(result[sheet+'!F2']['suggested_formula'], forms['E'])
        self.assertEqual(result['E!F2']['status'], 'abstain')
        self.assertEqual((model.cells, model.formulas, prior), (before_cells, before_forms, before_prior))

    def test_observed_formula_precedents_are_resolved_then_held_constant(self):
        model = WorkbookModel.from_cells({('A','B2'):100, ('A','C2'):.1, ('A','E2'):20},
                {('A','D2'):'=B2*C2', ('A','F2'):'=B2+D2-E2'})
        values, errors = model.evaluate(); self.assertFalse(errors)
        roles = {2:('opening', 1), 4:('interest', 1), 5:('payment', -1)}
        check = semantic_check('=B2+D2-E2','A','F2',roles,values)
        self.assertTrue(check['available'])
        self.assertEqual(check['opposite_roles'], [])
        self.assertEqual(check['missing_roles'], [])
        # Local partial wrt B is 1; recomputing D would incorrectly yield 1.1.
        self.assertAlmostEqual(check['checks'][0]['partial_effect'],1)
        bad = semantic_check('=B2+D2+E2','A','F2',roles,values)
        self.assertEqual(bad['opposite_roles'], ['payment'])

    def test_negative_temperature_does_not_reverse_derivative(self):
        values = {('A','B2'):-15,('A','C2'):1.8,('A','D2'):32,('A','E2'):.5}
        roles = {2:('celsius',1), 4:('offset',1), 5:('correction',1)}
        self.assertEqual(semantic_check('=B2*C2+D2+E2','A','F2',roles,values)['opposite_roles'],[])
        self.assertEqual(semantic_check('=B2*C2-D2+E2','A','F2',roles,values)['opposite_roles'],['offset'])

    def test_missing_terms_and_coefficient_only_changes_are_not_authorized(self):
        for formula in ['=B2+C2-D2', '=0.5*B2+C2-D2-E2', '=B2+C2+D2']:
            with self.subTest(formula=formula):
                model, prior = fixture({'A':formula, 'B':'=B2+C2-D2-E2'})
                prior['rows'][0].update(status='propose',suggested_formula='=B2+C2-D2-E2')
                row = by_cell(augment(model,prior,['A','B']))['A!F2']
                self.assertNotEqual(row['status'],'propose')

    def test_no_correct_peer_and_multiple_valid_peers_require_abstention(self):
        for forms in [
            {'A':'=B2+C2+D2-E2','B':'=B2+C2+D2-E2'},
            {'A':'=B2+C2+D2-E2','B':'=B2+C2-D2-E2','C':'=C2+B2-D2-E2'}]:
            model, prior = fixture(forms)
            self.assertNotEqual(by_cell(augment(model,prior,list(forms)))['A!F2']['status'],'propose')

    def test_unknown_header_retains_upstream_and_summary_region_is_preserved(self):
        model, prior = fixture(headers=HEADERS[:-1]+['Unknown output'])
        result = augment(model,prior,['A','B'])
        self.assertEqual(result['rows'][0]['status'],'abstain')
        model, prior = fixture({'A':'=SUM(B2:E2)','B':'=B2+C2-D2-E2'})
        self.assertNotEqual(by_cell(augment(model,prior,['A','B']))['A!F2']['status'],'propose')
        model.cells['A','F1']='USD cents'
        roles, _ = semantic_roles(header_index(model),'A','F2')
        self.assertFalse(roles)

    def test_dependency_absolute_reference_and_constants_cannot_be_changed(self):
        for candidate in ['=B2+C2-D2-$E$2','=B2+C2-D2-E2+1','=B2+C2-D2-E3']:
            model, prior = fixture({'A':'=B2+C2+D2-E2','B':candidate})
            self.assertNotEqual(by_cell(augment(model,prior,['A','B']))['A!F2']['status'],'propose')

    def test_row_policy_does_not_block_unrelated_error(self):
        model, prior = fixture()
        model.cells['A','H1']='Business policy'; model.cells['A','H2']='Row 3: payment deferred.'
        model.formulas['A','F3']='=B3+C3-D3'
        prior['rows'].append({'cell':'A!F3','status':'abstain','suggested_formula':None})
        result = by_cell(augment(model,prior,['A','B']))
        self.assertEqual(result['A!F2']['status'],'propose')
        self.assertEqual(result['A!F3']['status'],'review')

    def test_opaque_global_multirow_and_invalid_policy_scopes_review_sheet(self):
        for text in ['Row 999: payment deferred.', 'Row 2: all payments deferred.',
                     'Rows 2-3: payment deferred.', 'Row 2: payment deferred. Other rules apply.',
                     'Row 2: apply the following policy.', 'Use contract terms.',
                     'Row 2: payment reduced by 50%.']:
            with self.subTest(text=text):
                model, prior = fixture()
                model.cells['A','H1']='Business policy'; model.cells['A','H2']=text
                self.assertTrue(policy_scopes(model)['A']['opaque'])
                self.assertEqual(by_cell(augment(model,prior,['A','B']))['A!F2']['status'],'review')

    def test_second_policy_line_and_conflicting_row_notes_are_not_ignored(self):
        for text in ['All payments have reversed meaning.', 'Row 2: do the opposite.']:
            model, prior = fixture()
            model.cells['A','H1']='Business policy';model.cells['A','H2']='Row 2: payment deferred.'
            model.cells['A','H3']=text
            self.assertTrue(policy_scopes(model)['A']['opaque'])
            self.assertEqual(by_cell(augment(model,prior,['A','B']))['A!F2']['status'],'review')


if __name__ == '__main__':
    unittest.main()
