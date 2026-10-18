from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from prepare_certified_labels_dev22 import case_alternatives,KEEP


class CertifiedLabelTests(unittest.TestCase):
    def test_clean_zero_repair_label_is_not_a_wrong_formula_certificate(self):
        t={'expected_formulas':{'S!A1':'=B1+C1'},'errors':[]}
        p={'case':'test','candidates':[{'id':'equivalent','cell':'S!A1','formula':'=C1+B1'}]}
        a=case_alternatives(p,t,{'equivalent':0})
        self.assertEqual(a[0]['label'],1)
        self.assertEqual(a[0]['id'],KEEP)
        self.assertIsNone(a[1]['label'])

    def test_error_keeps_inherited_accepted_repair_labels_and_explicit_bad_keep(self):
        t={'expected_formulas':{'S!A1':'=B1+C1'},'errors':['S!A1']}
        p={'case':'test','candidates':[{'id':str(n),'cell':'S!A1','formula':f'={n}'} for n in range(3)]}
        a=case_alternatives(p,t,{'0':0,'1':1,'2':None})
        self.assertEqual([r['label'] for r in a],[0,0,1,None])

    def test_unknown_scope_does_not_infer_keep_correctness_from_candidate_absence(self):
        t={'expected_formulas':{},'errors':[]}
        p={'case':'test','candidates':[{'id':'x','cell':'S!A1','formula':'=1'}]}
        a=case_alternatives(p,t,{'x':None})
        self.assertEqual([r['label'] for r in a],[None,None])


if __name__=='__main__':unittest.main()
