from pathlib import Path
from copy import deepcopy
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'tests'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
import test_annotation_evidence_dev14 as fixtures
from annotation_evidence_dev15 import Notes,apply
from audit_annotation_dev14_v2 import equals
from formulaguard.workbook import WorkbookModel

class UncachedInventoryTests(unittest.TestCase):
    def test_uncached_and_cached_peers_produce_identical_decisions(self):
        m=fixtures.AnnotationEvidenceTests().model('=$D$1+F2*F3*$D$4')
        cached=WorkbookModel({**m.cells,**{k:12.3 for k in m.formulas}},m.formulas)
        uncached=WorkbookModel({k:v for k,v in m.cells.items() if k not in m.formulas},m.formulas)
        prior={'rows':[{'cell':s+'!'+a,'status':'abstain','suggested_formula':None} for s,a in m.formulas]}
        self.assertEqual(apply(cached,prior,deepcopy(prior)),apply(uncached,prior,deepcopy(prior)))
        self.assertEqual(apply(uncached,prior,prior)['note_only']['rows'][0]['status'],'propose')

    def test_formula_input_without_cached_cell_can_bind(self):
        m=fixtures.AnnotationEvidenceTests().model()
        m.cells.pop(('S','F2'))
        m.formulas['S','F2']='=0.6'
        expected,ev=Notes(m).evidence('S','F5')
        self.assertEqual(ev['bindings'][1]['value_cell'],'F2')

    def test_independent_token_oracle_accepts_grammar_and_distinguishes_errors(self):
        for a,b in [('=$A$1*B2','=B2*A1'),('=-(A1+2)*B2','=-A1*B2-2*B2'),
                    ('=1.1*A1','=A1*11/10'),('=A1+2*B2','=2*B2+A1')]:
            self.assertTrue(equals(a,b),(a,b))
        self.assertFalse(equals('=A1*B1','=A1+B1'))
        self.assertFalse(equals('=9007199254740992*A1','=9007199254740993*A1'))

if __name__=='__main__':unittest.main()
