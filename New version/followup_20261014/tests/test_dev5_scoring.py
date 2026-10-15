"""Test the actual dev5 runner's scoring entry point before freezing it."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_selector_dev5 import metrics


class Dev5ScoringTests(unittest.TestCase):
    def test_review_remains_in_coverage_denominator_and_harms_count_in_precision(self):
        observed = {'A!F2':'=B2+C2','A!F3':'=B3+C3','A!F4':'=B4-C4'}
        truth = {'expected_formulas':{'A!F2':'=B2-C2','A!F3':'=B3-C3','A!F4':'=B4-C4'},
                 'errors':['A!F2','A!F3']}
        prediction = {'rows':[
            {'cell':'A!F2','status':'propose','suggested_formula':'=B2-C2'},
            {'cell':'A!F3','status':'review','suggested_formula':'=B3-C3'},
            {'cell':'A!F4','status':'propose','suggested_formula':'=B4+C4'}]}
        got = metrics(prediction,truth,observed)
        self.assertEqual((got['proposals'],got['correct'],got['wrong'],got['harmful_correct_cells']),(2,1,1,1))
        self.assertEqual((got['precision'],got['coverage']),(.5,.5))

    def test_zero_proposals_have_undefined_precision_and_zero_error_coverage(self):
        got = metrics({'rows':[{'cell':'A!F2','status':'abstain','suggested_formula':None}]},
            {'expected_formulas':{'A!F2':'=B2-C2'},'errors':['A!F2']},{'A!F2':'=B2+C2'})
        self.assertIsNone(got['precision']); self.assertEqual(got['coverage'],0)


if __name__ == '__main__':
    unittest.main()
