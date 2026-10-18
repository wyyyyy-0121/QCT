"""Guard token edits and demonstrate that legitimate lag is indistinguishable."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from record_candidates_dev29 import generate


class RecordCandidatesTests(unittest.TestCase):
    def call(self, formula):
        inputs = {('S', col + str(row)): col + str(row) for col in 'ABCD' for row in range(1, 4)}
        return generate(formula, 'S', 'E2', inputs, sheet_names=['S', 'Other'])

    def test_only_reference_row_changes_quoted_fake_refs_untouched(self):
        f = '=CONCATENATE("C3 says ""yes""",A2,B2,$C3,D2)'
        r = self.call(f)
        self.assertEqual(r['candidate_formula'], '=CONCATENATE("C3 says ""yes""",A2,B2,$C2,D2)')
        self.assertEqual(r['status'], 'candidate_for_review')
        self.assertFalse(r['automatic_repair_allowed'])

    def test_sheet_qualifier_case_and_absolute_column_preserved(self):
        r = self.call("=A2&B2&'s'!$C3&D2")
        self.assertEqual(r['candidate_formula'], "=A2&B2&'s'!$C2&D2")

    def test_repetition_not_distinct_column_support(self):
        self.assertEqual(self.call('=A2&A2&C3&D2')['status'], 'abstain')

    def test_absolute_cross_sheet_and_multiple_dissent_rejected(self):
        for f in ['=A2&B2&C$3&D2', '=A2&B2&Other!C3&D2', '=A2&B2&C3&D3']:
            with self.subTest(formula=f):
                self.assertEqual(self.call(f)['status'], 'abstain')

    def test_unsupported_syntax_and_uncomputed_dependency_retained(self):
        self.assertEqual(self.call('=SUM(A2,B2,C3,D2)')['status'], 'unsupported')
        r = generate('=A2&B2&C3&D2', 'S', 'E2', {}, formula_cells=[('S', 'A2')])
        self.assertEqual(r['reason'], 'formula_dependency_not_computed')

    def test_legal_lead_still_generates_a_harmful_candidate(self):
        # The same visible formula can intentionally use next-row C. There
        # is no intent input to this generator; such a candidate cannot be
        # promoted to a suggestion by the generator's own structural score.
        r = self.call('=A2&B2&C3&D2')
        self.assertEqual(r['candidate_formula'], '=A2&B2&C2&D2')
        self.assertFalse(r['business_authority'])


if __name__ == '__main__':
    unittest.main()
