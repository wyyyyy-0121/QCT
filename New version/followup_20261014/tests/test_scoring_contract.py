"""Verify harmful clean-cell proposals and refusals cannot inflate objective metrics."""
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from score_selector_dev1_propose_only import final_proposals
spec = importlib.util.spec_from_file_location('paper_score', ROOT/'baseline/scripts/score.py')
scorer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scorer)


class ContractTests(unittest.TestCase):
    def test_review_candidate_does_not_count_as_repair(self):
        prediction = {'rows': [
            {'cell':'S!A1','status':'propose','suggested_formula':'=2','candidate_formula':'=2'},
            {'cell':'S!A2','status':'review','candidate_formula':'=4','suggested_formula':None},
            {'cell':'S!A3','status':'propose','suggested_formula':'=7'},
        ]}
        truth = {'expected_formulas':{'S!A1':'=2','S!A2':'=4','S!A3':'=6'},
                 'errors':{'S!A1':'=2','S!A2':'=4'}}
        got = scorer.evaluate(final_proposals(prediction),
            {'S!A1':'=1','S!A2':'=3','S!A3':'=6'}, truth)
        self.assertEqual(got['proposals'], 2)
        self.assertEqual(got['exact_repairs'], 1)
        self.assertEqual(got['proposal_precision'], .5)
        self.assertEqual(got['repair_coverage'], .5)
        self.assertEqual(got['harmful_correct_cells'], 1)
        self.assertEqual(prediction['rows'][1]['candidate_formula'], '=4')

    def test_no_action_is_not_a_perfect_precision_score(self):
        for status in ['review','abstain','unsupported']:
            got = scorer.evaluate(final_proposals({'rows':[{
                'cell':'S!A1','status':status,'candidate_formula':'=2'}]}),
                {'S!A1':'=1'}, {'expected_formulas':{'S!A1':'=2'}, 'errors':{'S!A1':'=2'}})
            self.assertIsNone(got['proposal_precision'])
            self.assertEqual(got['repair_coverage'], 0)


if __name__=='__main__':
    unittest.main()
