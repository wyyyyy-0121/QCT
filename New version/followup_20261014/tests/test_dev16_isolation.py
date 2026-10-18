from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_candidate_learning_dev16 import protection,DATA
from semantic_fingerprint_dev16 import fingerprint,typed
from formulaguard.workbook import WorkbookModel,SharedFormulaRegion

class IsolationTests(unittest.TestCase):
    def test_label_access_requires_exact_current_fold(self):
        active,allowed,accesses,reads=protection()
        try:
            current=DATA/'training_labels/family__0.json.gz'
            other=DATA/'training_labels/family__1.json.gz'
            allowed[0]=str(current.resolve())
            with self.assertRaises(PermissionError):other.read_bytes()
            with self.assertRaises(PermissionError):(DATA/'heldout_truth.json.gz').read_bytes()
        finally:active[0]=False

    def test_fingerprint_keeps_shared_metadata_and_ignores_source_path(self):
        m=WorkbookModel({('S','A1'):1},{('S','B1'):'=A1'},source='first')
        same=WorkbookModel({('S','A1'):1},{('S','B1'):'=A1'},source='second')
        self.assertEqual(fingerprint(m,[]),fingerprint(same,[]))
        same.cell_visibility['S','A1']=False
        self.assertNotEqual(fingerprint(m,[]),fingerprint(same,[]))
        region=SharedFormulaRegion('S','1',('S','B1'),'B1','B2','=A1',(('S','B1'),('S','B2')))
        self.assertEqual(typed(region)[0],'dataclass')

if __name__=='__main__':unittest.main()
