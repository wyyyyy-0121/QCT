from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
import build_signed_features_dev19 as build
from run_signed_learning_dev19 import infer

class FakeLearner:
    classes_=np.array([0,1])
    def predict_proba(self,x):
        p=x[:,0]
        return np.stack([1-p,p],axis=1)

class SignedLearningTests(unittest.TestCase):
    def setup_data(self,root,candidates,x,digest):
        (root/'features').mkdir()
        (root/'feature_schema.json').write_text(json.dumps({'names':['feature']}))
        np.savez_compressed(root/'features/S__c.npz',x=x,order_digest=np.asarray(digest))

    def test_compressed_feature_order_mismatch_refused(self):
        c=[{'id':'a'},{'id':'b'}]
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_data(root,c,np.ones((2,1),dtype=np.float32),build.order_digest(c[::-1]))
            with patch.object(build,'DATA',root),self.assertRaisesRegex(AssertionError,'order mismatch'):
                build.load({'case':'S/c'},{'candidates':c})

    def test_empty_case_matrix_retains_width_and_float32(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_data(root,[],np.empty((0,1),dtype=np.float32),build.order_digest([]))
            with patch.object(build,'DATA',root):
                x=build.load({'case':'S/c'},{'candidates':[]})
            self.assertEqual(x.shape,(0,1));self.assertEqual(x.dtype,np.float32)

    def test_nonfinite_role_features_refused(self):
        c=[{'id':'a'}]
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);self.setup_data(root,c,np.array([[np.nan]],dtype=np.float32),build.order_digest(c))
            with patch.object(build,'DATA',root),self.assertRaises(AssertionError):
                build.load({'case':'S/c'},{'candidates':c})

    def test_selector_preserves_ast_visibility_margin_and_baseline(self):
        c=[{'id':'a','cell':'S!A1','formula':'=2','eligible':True},
           {'id':'b','cell':'S!A1','formula':'=3','eligible':True},
           {'id':'c','cell':'S!B1','formula':'=4','eligible':False}]
        base=[{'cell':'S!A1','suggested_formula':'=5','status':'propose'}]
        p,result=infer(FakeLearner(),{'candidates':c,'baseline':base},np.array([[.96],[.1],[.99]]))
        self.assertEqual(result['learned_only'][0]['candidate_id'],'a')
        self.assertEqual(result['keep_base_plus_learned'],base)
        self.assertEqual(result['dev11'],base)
        _,result=infer(FakeLearner(),{'candidates':c,'baseline':[]},np.array([[.96],[.94],[.99]]))
        self.assertFalse(result['learned_only'])

if __name__=='__main__':unittest.main()
