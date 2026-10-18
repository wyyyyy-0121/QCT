from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from unit_evidence_dev1 import UnitEvidence, parse_unit, UnknownUnit


def checker(headers, extra=None, forms=None):
    cells = {('S', col+'1'): value for col, value in headers.items()}
    cells.update({('S', col+'2'): 2 for col in headers})
    cells.update(extra or {})
    return UnitEvidence(WorkbookModel.from_cells(cells, forms or {('S', 'F2'): '=B2'}))


class UnitEvidenceTests(unittest.TestCase):
    def test_product_and_quotient_cancel_units(self):
        unit = checker({'B': 'Mass [kg]', 'C': 'Price [usd/kg]', 'F': 'Revenue [usd]'})
        self.assertEqual(unit.check('=B2*C2', 'S', 'F2')['status'], 'compatible')
        self.assertEqual(unit.check('=B2/C2', 'S', 'F2')['status'], 'incompatible')

    def test_sign_and_coefficient_are_not_determined_by_units(self):
        unit = checker({'B': 'Opening [usd]', 'C': 'Fee [usd]', 'F': 'Closing [usd]'})
        for formula in ['=B2+C2', '=B2-C2', '=B2*0.85-C2']:
            result = unit.check(formula, 'S', 'F2')
            self.assertEqual(result['status'], 'compatible')
            self.assertFalse(result['repair_authority'])

    def test_unknown_header_is_not_dimensionless_or_inherited(self):
        unit = checker({'B': 'Weight', 'F': 'Total [kg]'})
        self.assertEqual(unit.check('=B2', 'S', 'F2')['status'], 'unknown')
        unit = checker({'B': 'Weight [kg]', 'F': 'Total [kg]'},
                       {('S', 'B3'): 'New region', ('S', 'B4'): 5, ('S', 'F4'): 2})
        self.assertEqual(unit.check('=B4', 'S', 'F4')['status'], 'unknown')

    def test_units_and_scales_are_not_silently_converted(self):
        unit = checker({'B': 'Length [m]', 'C': 'Length [cm]', 'F': 'Length [m]'})
        self.assertEqual(unit.check('=B2+C2', 'S', 'F2')['status'], 'incompatible')
        unit = checker({'B': 'Temp [c]', 'C': 'Scale [f/c]', 'D': 'Offset [f]', 'F': 'Temp [f]'})
        self.assertEqual(unit.check('=B2*C2+D2', 'S', 'F2')['status'], 'compatible')
        self.assertEqual(unit.check('=B2*C2-D2', 'S', 'F2')['status'], 'compatible')

    def test_zero_does_not_authorize_nonzero_dimensionless_addition(self):
        unit = checker({'B': 'Mass [kg]', 'F': 'Mass [kg]'})
        self.assertEqual(unit.check('=B2+0', 'S', 'F2')['status'], 'compatible')
        self.assertEqual(unit.check('=B2+1', 'S', 'F2')['status'], 'incompatible')

    def test_cross_sheet_absolute_reference_and_aggregation(self):
        unit = checker({'F': 'Total [kg]'},
                       {('Other', 'B1'): 'Mass [kg]', ('Other', 'B2'): 1, ('Other', 'B3'): 3})
        self.assertEqual(unit.check("=SUM('Other'!$B$2:$B$3)", 'S', 'F2')['status'], 'compatible')

    def test_unknown_functions_and_absent_precedents_remain_unknown(self):
        unit = checker({'B': 'Mass [kg]', 'F': 'Mass [kg]'})
        for formula in ['=IF(1,B2,B2)', '=B999', '=SUM(B2:B400)']:
            self.assertEqual(unit.check(formula, 'S', 'F2')['status'], 'unknown')

    def test_explicit_exponents_and_ambiguous_units(self):
        self.assertEqual(parse_unit('m/s^2'), (('m', 1), ('s', -2)))
        with self.assertRaises(UnknownUnit):
            parse_unit('kg/m/s')
        with self.assertRaises(UnknownUnit):
            parse_unit('kg m')


if __name__ == '__main__':
    unittest.main()
