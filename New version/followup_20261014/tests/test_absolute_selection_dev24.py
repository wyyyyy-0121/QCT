from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from absolute_selection_dev24 import KEEP,options,select,infer
from absolute_matrix_dev24 import build_matrix
from certified_preferences_dev22 import certified_pairs


def alternative(key,label,kind='candidate'):
    return dict(case='c',cell='S!A1',id=key,label=label,kind=kind)


def candidate(key='a',formula='=A2+A3',eligible=True):
    return dict(id=key,formula=formula,cell='S!A1',eligible=eligible)


class SelectionTests(unittest.TestCase):
    def test_tristate_sampling_and_keep_are_shared_with_pairs(self):
        states=[alternative(KEEP,1,'keep'),alternative('good',1),alternative('unknown',None)]
        states += [alternative(f'n{n:03}',0) for n in reversed(range(40))]
        selected=options(states)
        self.assertEqual(len(selected),34)
        self.assertNotIn('unknown',[r['id'] for r in selected])
        self.assertEqual([r['id'] for r in selected if r['label']==0],[f'n{n:03}' for n in range(32)])
        self.assertEqual(certified_pairs(states)[0],certified_pairs(selected)[0])

    def test_known_wrong_keep_bypasses_candidate_cap(self):
        states=[alternative(KEEP,0,'keep'),alternative('good',1)] + [alternative(f'n{n:03}',0) for n in range(35)]
        self.assertEqual(len(options(states)),34)
        self.assertIn(KEEP,[r['id'] for r in options(states)])

    def test_unknown_keep_never_assumed_negative(self):
        states=[alternative(KEEP,None,'keep'),alternative('good',1)]
        self.assertEqual([r['id'] for r in options(states)],['good'])
        self.assertEqual(certified_pairs(states)[0],[])

    def test_same_score_and_insufficient_keep_advantage_abstain(self):
        for keep in [.99,.96,.94]:
            self.assertEqual(select([candidate()],[.98],{'S!A1':keep}),[])
        self.assertEqual(len(select([candidate()],[.98],{'S!A1':.90})),1)

    def test_threshold_and_candidate_margin_still_apply(self):
        self.assertEqual(select([candidate()],[.89],{'S!A1':.1}),[])
        cs=[candidate(),candidate('b','=A2-A3')]
        self.assertEqual(select(cs,[.98,.95],{'S!A1':.1}),[])
        self.assertEqual(select(cs,[.98,.90],{'S!A1':.1})[0]['candidate_id'],'a')

    def test_ineligible_top_not_used_as_suggestion_or_runner(self):
        cs=[candidate(eligible=False),candidate('b','=A2-A3')]
        self.assertEqual(select(cs,[.99,.95],{'S!A1':.1})[0]['candidate_id'],'b')

    def test_unit_rejection_does_not_promote_second_candidate(self):
        class Model:
            classes_=np.asarray([0,1])
            def predict_proba(self,x):return np.column_stack([1-x[:,0],x[:,0]])
        cs=[candidate(),candidate('b','=A2-A3')]
        payload=dict(candidates=cs,baseline=[])
        scores,keep,pred=infer(Model(),payload,np.asarray([[.99,1],[.91,0]],dtype=np.float32),
            np.asarray([[.1,0]],dtype=np.float32),np.asarray([0,0]),['unit_new_incompatible'])
        self.assertEqual(len(pred['learned_unfiltered']),1)
        self.assertEqual(pred['learned_only'],[])

    def test_nonfinite_rejected(self):
        with self.assertRaises(ValueError):select([candidate()],[np.nan],{'S!A1':.1})
        with self.assertRaises(ValueError):select([candidate()],[.99],{'S!A1':np.nan})

    def test_absolute_matrix_preserves_float32_and_keep_mapping(self):
        x=np.asarray([[1/3,2],[3,4]],dtype=np.float32);k=np.asarray([[5,6]],dtype=np.float32)
        payload=dict(candidates=[candidate(),candidate('b')])
        rows=[alternative(KEEP,0,'keep'),alternative('b',1)]
        with tempfile.TemporaryDirectory() as tmp:
            matrix,digest=build_matrix(Path(tmp)/'matrix.npy',rows,2,{'c':{}},lambda _: (payload,x,k,np.asarray([0,0])))
            np.testing.assert_array_equal(matrix,np.asarray([[5,6],[3,4]],dtype=np.float64))
            self.assertFalse(matrix.flags.writeable)
            self.assertEqual(len(digest),64)

    def test_invalid_state_and_duplicate_keep_rejected(self):
        for states in [[alternative(KEEP,2,'keep')],[alternative(KEEP,1,'keep'),alternative(KEEP,0,'keep')]]:
            with self.assertRaises(ValueError):options(states)


class IsolationTests(unittest.TestCase):
    def isolated(self,body):
        result=subprocess.run([sys.executable,'-c',"import sys\nsys.path.insert(0,'scripts')\nimport run_absolute_selection_dev24 as m\n"+body],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_preflight_denies_all_label_bodies_including_hash_access(self):
        self.isolated("""
active=m.protect_preflight()
for folder in ['author_case_states','author_case_pairs','author_case_options','training_labels','case_labels']:
    try:m.sha(m.LABELS/folder/'test.json.gz')
    except PermissionError:pass
    else:raise AssertionError(folder)
m.verify_features()
active[0]=False
""")

    def test_current_fold_only_and_author_options_forbidden(self):
        self.isolated("""
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    folder=Path(tmp)/'training_labels';folder.mkdir()
    current=folder/'current.json';other=folder/'other.json'
    current.write_text('{}');other.write_text('{}')
    active,accesses,allowed,reads=m.protect_training()
    allowed[0]=str(current.resolve())
    assert current.read_text()=='{}'
    for p in [other,m.LABELS/'author_case_options/test.json',m.BASE/'heldout_truth.json.gz']:
        try:p.read_bytes()
        except PermissionError:pass
        else:raise AssertionError(str(p))
    assert reads=={str(current.resolve())}
    active[0]=False
""")


if __name__=='__main__':unittest.main()
