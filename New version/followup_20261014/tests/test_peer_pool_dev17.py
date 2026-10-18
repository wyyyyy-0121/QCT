from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from formulaguard.workbook import WorkbookModel
from peer_pool_dev17 import candidates
class PeerPoolTests(unittest.TestCase):
    def test_two_independent_axes_kept_without_picking_one(self):
        forms={('S','F5'):'=A5+B5',('S','E5'):'=Z5',('S','G5'):'=AB5',
               ('S','F4'):'=A4-B4',('S','F6'):'=A6-B6'}
        m=WorkbookModel({},forms)
        c=candidates(m,'S','F5')
        self.assertEqual(set(c),{'=AA5','=A5-B5'})
        self.assertEqual({e['axis'] for v in c.values() for e in v},{'row','column'})
    def test_one_peer_and_hidden_peer_not_sufficient(self):
        m=WorkbookModel({},{('S','F5'):'=A5+B5',('S','F4'):'=A4-B4',('S','F6'):'=A6-B6'})
        m.cell_visibility['S','F6']=False
        self.assertFalse(candidates(m,'S','F5'))
    def test_clean_peer_pattern_produces_no_change(self):
        m=WorkbookModel({},{('S',f'F{r}'):f'=A{r}-B{r}' for r in range(2,8)})
        self.assertFalse(candidates(m,'S','F5'))
if __name__=='__main__':unittest.main()
