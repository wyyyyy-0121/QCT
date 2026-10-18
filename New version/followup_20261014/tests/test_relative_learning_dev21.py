from pathlib import Path
import sys
import unittest
import tempfile
import json
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
import build_keep_features_dev21 as build
from relative_learning_dev21 import selected_rows,representation,preference,infer

class DirectionLearner:
    classes_=np.array([0,1])
    def predict_proba(self,x):
        z=np.clip(x[:,x.shape[1]//2]+0.2*x[:,0],-20,20)
        p=1/(1+np.exp(-z));return np.stack([1-p,p],axis=1)

class RelativeLearningTests(unittest.TestCase):
    def test_negative_cap_is_per_cell_and_deterministic(self):
        rows=[{'case':'c','cell':cell,'id':f'{cell}_{n:03}','label':int(n==99)}
              for cell in ['S!A1','S!B1'] for n in range(100)]
        selected=selected_rows(rows[::-1])
        self.assertEqual(selected,selected_rows(rows))
        self.assertEqual(len(selected),66)
        self.assertEqual(sum(r['label'] for r in selected),2)
        with self.assertRaises(AssertionError):selected_rows([dict(rows[0],label=None)])

    def test_representation_and_mirrored_class_weight(self):
        c=np.array([[3.,4.],[1.,8.]],dtype=np.float32);k=np.array([[1.,2.],[1.,2.]],dtype=np.float32)
        a=representation(c,k);b=representation(c,k,reverse=True)
        np.testing.assert_array_equal(a[:,:2],k)
        np.testing.assert_array_equal(a[:,2:],-b[:,2:])
        y=np.array([1,0]);w=np.array([.3,5.]);mirrored=np.concatenate([y,1-y]);weights=np.tile(w,2)
        self.assertEqual(weights[mirrored==0].sum(),weights[mirrored==1].sum())

    def test_zero_difference_and_reversed_difference(self):
        m=DirectionLearner();k=np.array([[2.,3.],[7.,9.]])
        np.testing.assert_array_equal(preference(m,k,k),[.5,.5])
        x=k+np.array([[4.,-1.],[-2.,3.]])
        np.testing.assert_allclose(preference(m,x,k),1-preference(m,2*k-x,k),atol=1e-15)
        self.assertEqual(len(preference(m,np.empty((0,2)),np.empty((0,2)))),0)

    def test_keep_feature_order_nonfinite_and_empty(self):
        candidates=[{'id':'a','cell':'S!A1'},{'id':'b','cell':'S!B1'}];item={'case':'c'}
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'features').mkdir();path=root/'features/c.npz'
            def write(c,values,cd=None):
                np.savez_compressed(path,k=values,order_digest=np.asarray(build.order_digest(c)),
                                    cell_digest=np.asarray(cd or build.digest_cells(sorted({v['cell'] for v in c}))))
            with patch.object(build,'DATA',root),patch.object(build,'names',return_value=['f']):
                write(candidates,np.ones((2,1),dtype=np.float32))
                cells,k=build.load(item,{'candidates':candidates});self.assertEqual(cells,['S!A1','S!B1'])
                with self.assertRaisesRegex(AssertionError,'candidate order'):build.load(item,{'candidates':candidates[::-1]})
                write(candidates,np.array([[np.nan],[1]],dtype=np.float32))
                with self.assertRaises(AssertionError):build.load(item,{'candidates':candidates})
                write(candidates,np.ones((2,1),dtype=np.float32),'wrong')
                with self.assertRaisesRegex(AssertionError,'target order'):build.load(item,{'candidates':candidates})
                write([],np.empty((0,1),dtype=np.float32))
                self.assertEqual(build.load(item,{'candidates':[]})[1].shape,(0,1))

    def test_selector_preserves_baseline_ast_margin_and_unit_gate(self):
        # Width=4, with the last 3 entries describing units. Comparator is zero.
        names=['unit_new_compatible','unit_new_incompatible','unit_new_unknown']
        c=[{'id':'a','cell':'S!A1','formula':'=2','eligible':True},
           {'id':'b','cell':'S!A1','formula':'=3','eligible':True},
           {'id':'c','cell':'S!B1','formula':'=4','eligible':False}]
        base=[{'cell':'S!A1','suggested_formula':'=9','status':'propose'}]
        k=np.zeros((2,4));pos=np.array([0,0,1]);x=np.array([[5,1,0,0],[0,1,0,0],[8,1,0,0]],dtype=np.float32)
        _,r=infer(DirectionLearner(),{'candidates':c,'baseline':base},x,k,pos,names)
        self.assertEqual(r['learned_only'][0]['candidate_id'],'a');self.assertEqual(r['keep_base_plus_learned'],base)
        x[0,-3:]=[0,1,0]
        _,r=infer(DirectionLearner(),{'candidates':c,'baseline':[]},x,k,pos,names)
        self.assertFalse(r['learned_only']);self.assertEqual(len(r['learned_unfiltered']),1)
        x[1,0]=4.9
        _,r=infer(DirectionLearner(),{'candidates':c,'baseline':[]},x,k,pos,names)
        self.assertFalse(r['learned_unfiltered'])

    def test_wrong_fold_and_heldout_labels_are_denied(self):
        from run_candidate_learning_dev18 import training_protection
        with tempfile.TemporaryDirectory() as t:
            root=Path(t)/'training_labels';root.mkdir();p=root/'fold.json';p.write_text('{}')
            active,accesses,allowed,reads=training_protection()
            try:
                with self.assertRaises(PermissionError):p.read_text()
                allowed[0]=str(p.resolve());self.assertEqual(p.read_text(),'{}')
                with self.assertRaises(PermissionError):(root/'other.json').read_text()
                with self.assertRaises(PermissionError):(Path(t)/'heldout_truth.json.gz').read_bytes()
            finally:active[0]=False
            self.assertEqual(reads,{str(p.resolve())})
if __name__=='__main__':unittest.main()
