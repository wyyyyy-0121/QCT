from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from train_candidate_dev16 import fit,infer

class LearningProtocolTests(unittest.TestCase):
    def test_training_fixed_seed_reproduces_and_weights_equal_cases(self):
        records={str(i):{'features':[i%2,i/100]} for i in range(100)}
        labels=[{'id':str(i),'label':i%2,'case':'A' if i<80 else 'B','family':'one'} for i in range(100)]
        a,ma=fit(records,labels);b,mb=fit(records,labels)
        x=np.array([records[str(i)]['features'] for i in range(100)])
        np.testing.assert_array_equal(a.predict_proba(x),b.predict_proba(x))
        self.assertEqual(ma,mb)
        self.assertAlmostEqual(ma['sample_weight_sum'],100)
        self.assertAlmostEqual(ma['max_weight'],2.5)

    def test_no_candidates_preserves_base_and_abstains_learner(self):
        r=infer(None,{'candidates':[],'baseline':[{'cell':'S!A1','suggested_formula':'=1'}]})
        self.assertEqual(r['learned_only'],[])
        self.assertEqual(len(r['keep_base_plus_learned']),1)

    def test_one_class_training_does_not_fake_a_fitted_classifier(self):
        with self.assertRaises(ValueError):
            fit({'a':{'features':[0]}},[{'id':'a','label':0,'case':'one','family':'one'}])
if __name__=='__main__':unittest.main()
