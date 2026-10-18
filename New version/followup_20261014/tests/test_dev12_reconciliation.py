"""Controlled declarations, invalid evidence and numeric counterexamples."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev12 import apply


def fixture(original='=B2+C2', control=12, declaration=True, **kwargs):
    cells = {('S', 'B2'): 17, ('S', 'C2'): 5, ('S', 'G2'): control}
    if declaration:
        cells['S', 'H2'] = ('Reconciliation: target=F2; expression=F2-G2; '
                            'expected=0; tolerance=0.000001.')
    cells.update(kwargs.pop('cells', {}))
    formulas = {('S', 'F2'): original, **kwargs.pop('formulas', {})}
    model = WorkbookModel.from_cells(cells, formulas, **kwargs)
    prior = {'rows': [{'cell': s+'!'+a, 'status': 'review', 'suggested_formula': None,
                       'reason': 'upstream_review'} for s, a in formulas]}
    return model, prior


class ReconciliationTests(unittest.TestCase):
    def output(self, model, prior):
        saved = deepcopy((model.cells, model.formulas, prior))
        result = apply(model, prior)
        self.assertEqual((model.cells, model.formulas, prior), saved)
        return next(r for r in result['rows'] if r['cell'] == 'S!F2')

    def test_unique_arithmetic_candidate(self):
        row = self.output(*fixture())
        self.assertEqual((row['status'], row['suggested_formula']), ('propose', '=B2-C2'))
        self.assertFalse(row['reconciliation']['control_provenance_verified'])
        self.assertFalse(row['reconciliation']['formula_identity_proven_by_numeric_agreement'])

    def test_absent_declaration_preserves_every_prior_row(self):
        model, prior = fixture(declaration=False)
        self.assertEqual(apply(model, prior)['rows'], prior['rows'])

    def test_clean_or_legitimate_exception_is_preserved(self):
        for formula, control in [('=B2-C2', 12), ('=B2+C2', 22)]:
            model, prior = fixture(formula, control)
            prior['rows'][0].update(status='propose', suggested_formula='=B2*C2')
            self.assertEqual(self.output(model, prior)['status'], 'abstain')

    def test_numeric_collision_is_ambiguous(self):
        row = self.output(*fixture(control=2, cells={('S', 'B2'): 4, ('S', 'C2'): 2}))
        self.assertEqual(row['reason'], 'ambiguous_declared_checks')
        self.assertGreaterEqual(len(row['reconciliation']['satisfying_candidates']), 2)

    def test_wrong_control_can_uniquely_select_wrong_formula(self):
        row = self.output(*fixture(control=85))
        self.assertEqual((row['status'], row['suggested_formula']), ('propose', '=B2*C2'))
        # Intentionally demonstrates a failure: reference answer is B2-C2.
        self.assertFalse(row['reconciliation']['control_provenance_verified'])

    def test_no_candidate_remains_review(self):
        self.assertEqual(self.output(*fixture(control=123456))['reason'],
                         'no_candidate_satisfies_declared_checks')

    def test_control_depending_directly_or_indirectly_on_target(self):
        for formulas in [{('S', 'G2'): '=F2'},
                         {('S', 'G2'): '=J2', ('S', 'J2'): '=F2'}]:
            self.assertEqual(self.output(*fixture(formulas=formulas))['reason'],
                             'control depends on target')

    def test_shared_inputs_reject_derived_control(self):
        self.assertEqual(self.output(*fixture(formulas={('S', 'G2'): '=B2-C2'}))['reason'],
                         'control_and_output_share_precedents')

    def test_missing_input_is_not_zero(self):
        model, prior = fixture()
        del model.cells['S', 'B2']
        self.assertEqual(self.output(model, prior)['reason'], 'missing control or precedent')

    def test_indirect_shared_inputs_reject_derived_control(self):
        row = self.output(*fixture(formulas={('S', 'B2'): '=J2+1',
                                            ('S', 'G2'): '=J2-4'},
                                   cells={('S', 'J2'): 16}))
        self.assertEqual(row['reason'], 'control_and_output_share_precedents')

    def test_hidden_control_rejected(self):
        row = self.output(*fixture(cell_visibility={('S', 'G2'): False}))
        self.assertEqual(row['reason'], 'hidden control or precedent')

    def test_cycle_is_rejected_by_evaluation(self):
        row = self.output(*fixture(formulas={('S', 'G2'): '=J2', ('S', 'J2'): '=G2'}))
        self.assertEqual(row['status'], 'review')
        self.assertEqual(row['reason'], 'formula evaluation failed')

    def test_unsupported_formula_rejected(self):
        self.assertEqual(self.output(*fixture('=NamedValue'))['reason'], 'unsupported_original')

    def test_contradictory_declarations_reject_every_candidate(self):
        model, prior = fixture(cells={('S', 'J2'): 13, ('S', 'H3'):
            'Reconciliation: target=F2; expression=F2-J2; expected=0; tolerance=0.000001.'})
        self.assertEqual(self.output(model, prior)['reason'], 'no_candidate_satisfies_declared_checks')

    def test_incomplete_and_unscoped_declarations_block(self):
        for text in ['Reconciliation: target=F2; expression=F2-G2;', 'Reconciliation: check this']:
            row = self.output(*fixture(cells={('S', 'H2'): text}))
            self.assertEqual(row['reason'], 'invalid_or_unscoped_declaration')

    def test_reserved_probe_cannot_overwrite_real_cell(self):
        row = self.output(*fixture(cells={('S', 'XFD1048576'): 9}))
        self.assertEqual(row['reason'], 'reserved evaluator address is occupied')

    def test_truncated_inventory_is_not_a_unique_solution(self):
        with patch('selector_dev12.generate', return_value={'status': 'supported',
                   'candidates': [], 'search_truncated': True}):
            self.assertEqual(self.output(*fixture())['reason'], 'incomplete_candidate_search')

    def test_nonnumeric_and_nonfinite_control(self):
        for value in [True, '12', float('inf')]:
            row = self.output(*fixture(control=value))
            self.assertEqual(row['reason'], 'control or result is not finite numeric')


if __name__ == '__main__':
    unittest.main()
