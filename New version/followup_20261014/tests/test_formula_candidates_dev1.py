from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formula_candidates_dev1 import generate, structural_key


class CandidateTests(unittest.TestCase):
    def keys(self, formula):
        result = generate(formula)
        self.assertFalse(result['selector_proposals'])
        return {c['structural_key'] for c in result['candidates']}

    def test_operator_edit_without_peer_or_header(self):
        self.assertIn(structural_key('=A1-B1'), self.keys('=A1+B1'))
        self.assertIn(structural_key('=A1*B1'), self.keys('=A1/B1'))

    def test_coefficient_deletion_not_a_repair_authorization(self):
        self.assertIn(structural_key('=A1*B1-C1'), self.keys('=A1*B1*0.85-C1'))
        self.assertIn(structural_key('=A1'), self.keys('=A1/0.85'))

    def test_references_preserve_absolute_flags_and_sheet(self):
        candidates = generate("='A!B''C'!$B$2+C2")['candidates']
        references = [c['formula'] for c in candidates if any(e['kind'] == 'reference_offset' for e in c['edits'])]
        self.assertTrue(any("'A!B''C'!$B$3" in f for f in references))
        self.assertTrue(all("'A!B''C'!$" in f for f in references))

    def test_boundaries_and_unsupported_formula_remain_visible(self):
        result = generate('=A1')
        self.assertFalse(any('A0' in c['formula'] for c in result['candidates']))
        self.assertEqual(generate('=SUM({1,2})')['status'], 'unsupported')
        self.assertEqual(generate('=A1&"x"')['status'], 'unsupported')

    def test_no_unchanged_or_duplicate_candidates(self):
        result = generate('=SUM(A1:A4)+B2*2')
        keys = [c['structural_key'] for c in result['candidates']]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertNotIn(structural_key('=SUM(A1:A4)+B2*2'), keys)
        self.assertFalse(result['search_truncated'])

    def test_does_not_claim_multi_edit_search(self):
        keys = self.keys('=A1+B1+C1')
        self.assertNotIn(structural_key('=A1-B1-C1'), keys)

    def test_ast_match_is_not_numeric_equivalence(self):
        self.assertEqual(structural_key('=(A1+B1)'), structural_key('=A1+B1'))
        self.assertNotEqual(structural_key('=A1+B1'), structural_key('=B1+A1'))


if __name__ == '__main__':
    unittest.main()
