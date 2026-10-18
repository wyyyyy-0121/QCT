from pathlib import Path
import subprocess
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from nested_calibration_dev25 import top_rows,fit_calibrator,select,validate_folds


class CalibrationTests(unittest.TestCase):
    def test_two_excluded_origins_must_really_be_absent(self):
        from itertools import combinations
        import copy
        names=list('abcde');groups={x:{'origin_group':x} for x in names}
        pairs=[dict(id=str(n),excluded_origins=list(p),train_cases=[s for s in names if s not in p],test_cases=list(p))
            for n,p in enumerate(combinations(names,2))]
        outer=[dict(origin=s,test_cases=[s],train_cases=[x for x in names if x!=s],
            inner_pairs=[p['id'] for p in pairs if s in p['excluded_origins']]) for s in names]
        index=dict(origins=names,case_groups=groups,pairs=pairs,outer=outer);validate_folds(index)
        bad=copy.deepcopy(index);bad['pairs'][0]['train_cases'].append('a')
        with self.assertRaises(AssertionError):validate_folds(bad)
        bad=copy.deepcopy(index);bad['outer'][0]['inner_pairs']=bad['outer'][1]['inner_pairs']
        with self.assertRaises(AssertionError):validate_folds(bad)

    def test_top_without_raw_threshold_but_margin_and_units_preserved(self):
        candidates=[dict(id='a',cell='S!A1',formula='=1',eligible=True),dict(id='b',cell='S!A1',formula='=2',eligible=True),
            dict(id='c',cell='S!B1',formula='=3',eligible=True),dict(id='d',cell='S!C1',formula='=4',eligible=False)]
        rows=top_rows(dict(candidates=candidates),[.70,.55,.99,1.],np.asarray([[0],[0],[1],[0]]),['unit_new_incompatible'])
        self.assertEqual(len(rows),2);self.assertIsNone(rows[0]['gate_reason']);self.assertEqual(rows[0]['raw_probability'],.70)
        self.assertEqual(rows[1]['gate_reason'],'unit_incompatible')

    def test_tie_abstains_and_no_promotion(self):
        c=[dict(id=key,cell='S!A1',formula=formula,eligible=True) for key,formula in [('a','=2'),('b','=1')]]
        rows=top_rows(dict(candidates=c),[.8,.8],np.zeros((2,1)),['unit_new_incompatible'])
        self.assertEqual(rows[0]['candidate_id'],'b');self.assertEqual(rows[0]['gate_reason'],'raw_margin')

    def test_nonfinite_raw_is_rejected(self):
        c=[dict(id='a',cell='S!A1',formula='=1',eligible=True)]
        with self.assertRaises(ValueError):top_rows(dict(candidates=c),[np.nan],np.zeros((1,1)),['unit_new_incompatible'])

    def training(self):
        return [dict(case=s+str(n),family='f',source=s,raw_probability=p,label=y) for s in ['a','b'] for n,(p,y) in enumerate([(.1,0),(.3,1),(.5,0),(.8,1)])]

    def test_weighted_isotonic_known_pool_and_no_extrapolation(self):
        model,summary=fit_calibrator(self.training())
        self.assertEqual(summary['status'],'fitted')
        np.testing.assert_allclose(model.predict([.1,.3,.5,.8]),[0,.5,.5,1])
        self.assertTrue(np.isnan(model.predict([.01,.9])).all())
        self.assertEqual(summary['source_weight_sums']['a'],summary['source_weight_sums']['b'])

    def test_unknown_not_accepted_and_insufficient_evidence_abstains(self):
        rows=self.training()
        with self.assertRaises(ValueError):fit_calibrator(rows+[dict(rows[0],label=None)])
        model,summary=fit_calibrator([r for r in rows if r['source']=='a'])
        self.assertIsNone(model);self.assertIn('insufficient',summary['status'])
        model,_=fit_calibrator([dict(r,label=1) for r in rows]);self.assertIsNone(model)

    def test_calibration_can_release_low_raw_but_never_bypass_gates(self):
        model,_=fit_calibrator(self.training())
        top=[dict(cell='S!A1',candidate_id='a',suggested_formula='=1',raw_probability=.8,raw_runner_up_probability=.5,gate_reason=None)]
        selected,diagnostics=select(top,model);self.assertEqual(selected[0]['probability'],1.)
        for reason in ['unit_incompatible','raw_margin']:
            self.assertEqual(select([dict(top[0],gate_reason=reason)],model)[0],[])
        self.assertEqual(select([dict(top[0],raw_probability=.99)],model)[0],[])
        self.assertEqual(select(top,None)[0],[])

    def test_source_and_family_weights_not_formula_count_weights(self):
        rows=self.training();rows += [dict(rows[0],case='a0') for _ in range(20)]
        _,summary=fit_calibrator(rows)
        self.assertAlmostEqual(summary['source_weight_sums']['a'],summary['source_weight_sums']['b'])


class IsolationTests(unittest.TestCase):
    def isolated(self,body):
        result=subprocess.run([sys.executable,'-c',"import sys\nsys.path.insert(0,'scripts')\nimport run_nested_calibration_dev25 as m\n"+body],cwd=ROOT,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_preflight_denies_nested_and_old_label_hashes(self):
        self.isolated("""
active=m.protect_preflight()
for p in [m.LABELS/'training_labels/pair.json.gz',m.BASE/'heldout_truth.json.gz',m.BASE/'case_labels/x.json.gz']:
    try:m.sha(p)
    except PermissionError:pass
    else:raise AssertionError(str(p))
m.verify_features()
active[0]=False
""")

    def test_wrong_fold_author_and_old_outer_reads_denied(self):
        self.isolated("""
import tempfile
from pathlib import Path
with tempfile.TemporaryDirectory() as tmp:
    path=Path(tmp)/'training_labels';path.mkdir();current=path/'one.json';other=path/'two.json'
    current.write_text('{}');other.write_text('{}')
    active,accesses,allowed,reads=m.protection();allowed[0]=str(current.resolve())
    assert current.read_text()=='{}'
    for p in [other,m.UPSTREAM/'score.json',m.UPSTREAM/'predictions/test.json',m.UPSTREAM/'probabilities/test.npz',m.LABELS/'author_case_options/test.json']:
        try:p.read_bytes()
        except PermissionError:pass
        else:raise AssertionError(str(p))
    active[0]=False
""")


if __name__=='__main__':unittest.main()
