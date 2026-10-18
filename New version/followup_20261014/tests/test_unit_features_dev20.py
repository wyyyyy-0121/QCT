from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from formulaguard.workbook import WorkbookModel
from unit_features_dev20 import VisibleUnits, written_unit
from unit_evidence_dev1 import UnknownUnit

class UnitFeaturesTests(unittest.TestCase):
    def model(self, cells, formulas=None):
        return WorkbookModel.from_cells({('S',a):v for a,v in cells.items()},
                                        formulas or {('S','J45'):'=J42+J44'})

    def test_currency_sum_and_product_from_row_units(self):
        u=VisibleUnits(self.model({'C42':'£m','C44':'£m','C45':'£m','J42':2,'J44':3}))
        self.assertEqual(u.check('=J42+J44','S','J45')['status'],'compatible')
        self.assertEqual(u.check('=J42*J44','S','J45')['status'],'incompatible')
        self.assertFalse(u.check('=J42-J44','S','J45')['repair_authority'])
        self.assertEqual(u.check('=J42*0.5-J44','S','J45')['status'],'compatible')

    def test_header_product_division_and_unknown(self):
        u=VisibleUnits(self.model({'B1':'Mass [kg]','C1':'Price [usd/kg]',
            'F1':'Revenue [usd]','B2':2,'C2':3}, {('S','F2'):'=B2*C2'}))
        self.assertEqual(u.check('=B2*C2','S','F2')['status'],'compatible')
        self.assertEqual(u.check('=B2/C2','S','F2')['status'],'incompatible')
        self.assertEqual(u.check('=IF(1,B2,B2)','S','F2')['status'],'unknown')
        self.assertEqual(u.check('=B999','S','F2')['status'],'unknown')

    def test_conflicts_and_scales_are_not_compatible(self):
        u=VisibleUnits(self.model({'J41':'Cost [usd]','C42':'£m','J42':2}))
        self.assertEqual(u.check('=J42','S','J45')['status'],'unknown')
        u=VisibleUnits(self.model({'C42':'£','C44':'£m','C45':'£m','J42':2,'J44':3}))
        self.assertEqual(u.check('=J42+J44','S','J45')['status'],'incompatible')
        self.assertNotEqual(written_unit('m'),written_unit('cm'))

    def test_unknown_words_are_not_units(self):
        for word in ['cost','Total','ratio','units','£million']:
            with self.assertRaises(UnknownUnit):written_unit(word)
        u=VisibleUnits(self.model({'C42':'cost','C44':'cost','C45':'cost','J42':2,'J44':3}))
        f=u.features('S','J45','=J42+J44','=J42*J44')
        self.assertEqual(f['unit_new_unknown'],1)
        self.assertEqual(f['unit_new_compatible'],0)

    def test_hidden_unit_and_precedent_never_supply_evidence(self):
        m=self.model({'C42':'£m','C44':'£m','C45':'£m','J42':2,'J44':3})
        visible=m.is_visible
        m.is_visible=lambda k: k!=('S','C44') and visible(k)
        self.assertEqual(VisibleUnits(m).check('=J42*J44','S','J45')['status'],'unknown')
        m.is_visible=lambda k: k!=('S','J44') and visible(k)
        self.assertEqual(VisibleUnits(m).check('=J42*J44','S','J45')['status'],'unknown')

    def test_cross_sheet_and_explicit_unknown_conflict(self):
        m=self.model({'F1':'Amount [usd]'}, {('S','F2'):"='Other'!B2"})
        m.cells.update({('Other','B1'):'Amount [usd]',('Other','B2'):2})
        self.assertEqual(VisibleUnits(m).check("='Other'!$B$2",'S','F2')['status'],'compatible')
        u=VisibleUnits(self.model({'J41':'Price [kg m]','C42':'£m','J42':2}))
        with self.assertRaises(UnknownUnit):u.declared('S','J42')
        with self.assertRaises(UnknownUnit):u.declared('S','J42')

if __name__=='__main__':unittest.main()
