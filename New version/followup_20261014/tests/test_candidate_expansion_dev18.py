from pathlib import Path
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from candidate_expansion_dev18 import extend, reference_features, extra_features
from formulaguard.workbook import WorkbookModel
from run_candidate_learning_dev18 import weights

class ExpansionTests(unittest.TestCase):
    def test_common_error_no_correct_peer_can_get_operator_hypothesis(self):
        pool,meta=extend('=SUM(A1:A3)*2',{'=SUM(B1:B3)*2':{'paper'}})
        self.assertIn('=SUM(A1:A3)',pool)
        self.assertFalse(meta['search_truncated'])
        self.assertEqual(pool['=SUM(B1:B3)*2'],{'paper'})

    def test_operator_and_reference_offsets_are_not_business_decisions(self):
        pool,_=extend('=A2+B2',{})
        self.assertTrue({'=A2-B2','=A2*B2','=A2+B3'} <= set(pool))
        self.assertTrue(all(x=={'single_edit'} for x in pool.values()))

    def test_old_ast_duplicate_preserved(self):
        p,_=extend('=A2+B2',{'=(A2-B2)':{'paper'}})
        self.assertIn('=(A2-B2)',p)
        self.assertNotIn('=A2-B2',p)

    def test_unsupported_named_formula_not_silently_converted(self):
        p,meta=extend('=SpecialRate*A2',{})
        self.assertEqual(meta['status'],'unsupported')
        self.assertFalse(p)

    def test_relative_features_translation_and_sheet_rename_invariant(self):
        a=WorkbookModel({('First','A2'):17,('First','B2'):'note'}, {('First','F2'):'=A2+B2'})
        b=WorkbookModel({('Second','D5'):99,('Second','E5'):'changed'}, {('Second','I5'):'=D5+E5'})
        self.assertEqual(extra_features(a,'First','F2','=A2+B2','=A2-B2',{'single_edit'}),
                         extra_features(b,'Second','I5','=D5+E5','=D5-E5',{'single_edit'}))

    def test_formula_inventory_takes_priority_over_absent_or_numeric_cache(self):
        m=WorkbookModel({('S','A2'):123},{('S','A2'):'=1',('S','F2'):'=A2'})
        f=reference_features(m,'S','F2','=SUM(A2:B2)+F2')
        self.assertEqual(f['formula'],2)
        self.assertEqual(f['blank'],1)
        self.assertEqual(f['self_ref'],1)
        self.assertEqual(f['range_count'],1)

    def test_range_budget_is_reported(self):
        f=reference_features(WorkbookModel({},{}),'S','B1','=SUM(A1:A10000)')
        self.assertEqual(f['ref_occurrences'],256)
        self.assertEqual(f['range_truncated'],1)

    def test_source_weights_do_not_depend_on_candidate_multiplicity(self):
        rows=[{'source':'a','family':'x','case':'a1'} for _ in range(7)]
        rows += [{'source':'b','family':'y','case':'b1'}, {'source':'b','family':'z','case':'b2'}]
        w=weights(rows)
        self.assertAlmostEqual(sum(w[:7]),sum(w[7:]))
        self.assertAlmostEqual(w[7],w[8])

    def test_unknown_and_clean_equivalent_labels_are_not_positive_repairs(self):
        from prepare_candidate_labels_dev18 import label
        truth={'expected_formulas':{'S!A1':'=1'},'errors':[]}
        self.assertEqual(label({'cell':'S!A1','formula':'=1'},truth,lambda *a:True),0)
        self.assertIsNone(label({'cell':'S!B1','formula':'=1'},truth,lambda *a:True))

    def test_wrong_fold_and_oracle_reads_fail_in_separate_process(self):
        script="""
from run_candidate_learning_dev18 import training_protection,DATA
active,accesses,allowed,reads=training_protection()
for p in [DATA/'training_labels/wrong.json.gz',DATA/'case_labels/wrong.json.gz',DATA/'heldout_truth.json.gz']:
    try:p.read_bytes()
    except PermissionError:pass
    else:raise AssertionError(p)
active[0]=False
"""
        result=subprocess.run([sys.executable,'-c',"import sys;sys.path[:0]=['scripts','baseline/source/HybridGuard_V5_handoff_20260904/src'];"+script],
                              cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
