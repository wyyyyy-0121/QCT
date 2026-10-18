from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from formulaguard.workbook import WorkbookModel
from candidate_features_dev16 import Context,choose

class CandidateFeatureTests(unittest.TestCase):
    def model(self,s='S',row=5,col='F'):
        forms={(s,col+str(row)):'=A'+str(row)+'+B'+str(row)}
        return WorkbookModel({(s,'A1'):'Price',(s,col+'1'):'Net cost'},forms)

    def test_vector_ignores_workbook_source_and_cell_identity(self):
        a=self.model('First');b=self.model('Renamed')
        fa=Context(a,[]).features('First','F5','=A5-B5',{'paper'},{})
        fb=Context(b,[]).features('Renamed','F5','=A5-B5',{'paper'},{})
        self.assertEqual(fa,fb)
        self.assertFalse(any(w in name for name in fa for w in ['path','case_id','cell_address','family','scenario']))

    def test_feature_does_not_use_formula_cache_values(self):
        a=self.model();b=self.model()
        a.cells['S','F5']=123
        self.assertEqual(Context(a,[]).features('S','F5','=A5-B5',{'paper'},{}),
                         Context(b,[]).features('S','F5','=A5-B5',{'paper'},{}))

    def test_neighbors_match_relative_translations_and_keep_axes(self):
        m=self.model()
        m.formulas['S','F4']='=A4-B4';m.formulas['S','F6']='=A6+B6'
        f=Context(m,[]).features('S','F5','=A5-B5',{'dev9'},{})
        self.assertEqual(f['column_support_candidate'],1)
        self.assertEqual(f['column_support_observed'],1)
        self.assertEqual(f['row_peers'],0)

    def test_selection_threshold_margin_and_eligibility(self):
        cs=[{'id':'a','cell':'S!A1','formula':'=1','eligible':True},
            {'id':'b','cell':'S!A1','formula':'=2','eligible':True}]
        self.assertIsNone(choose(cs,[.89,.1]))
        self.assertIsNone(choose(cs,[.95,.93]))
        self.assertEqual(choose(cs,[.96,.7])['candidate_id'],'a')
        cs[0]['eligible']=False
        self.assertIsNone(choose(cs,[.99,.7]))

    def test_hidden_text_not_a_feature(self):
        m=self.model();m.cells['S','B5']='exception';m.cell_visibility['S','B5']=False
        f=Context(m,[]).features('S','F5','=A5-B5',{'paper'},{})
        self.assertEqual(f['text_exception'],0)

if __name__=='__main__':unittest.main()
