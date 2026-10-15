"""Check semantic qualification and business exceptions on small new fixtures."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev2 import select, directional_check, header_roles


def fixture(mode, output_header='Net Profit'):
    cells={};formulas={}
    for sheet in ['A','B','C','D','E']:
        for address,value in {'A1':'Units','B1':'Unit Price','C1':'Unit Cost',
                              'D1':'Shipping','E1':'Discount Rate','F1':output_header}.items():
            cells[sheet,address]=value
        for row in range(2,32):
            for col,value in [('A',4),('B',20),('C',5),('D',2),('E',.1)]:cells[sheet,f'{col}{row}']=value
            formula=f'=A{row}*B{row}*(1-E{row})-A{row}*C{row}-D{row}'
            if sheet=='A' and mode=='cost_sign':formula=formula.replace(f'-A{row}*C{row}',f'+A{row}*C{row}')
            if sheet=='A' and mode=='legitimate':formula=formula.replace(f'-D{row}',f'-2*D{row}')
            formulas[sheet,f'F{row}']=formula
    model=WorkbookModel.from_cells(cells,formulas)
    rows=[{'cell':s+'!'+a} for s,a in formulas]
    return model,rows


class SelectionTests(unittest.TestCase):
    def test_whole_column_sign_error_uses_direction_not_only_majority(self):
        model,rows=fixture('cost_sign');before=dict(model.formulas)
        got=select(model,{'rows':rows},[],[],['A','B','C','D','E'])
        proposals=[r for r in got['rows'] if r['status']=='propose']
        self.assertEqual(len(proposals),30)
        self.assertTrue(all('-A' in r['suggested_formula'] for r in proposals))
        self.assertEqual(model.formulas,before)

    def test_legitimate_double_shipping_whole_column_is_preserved(self):
        model,rows=fixture('legitimate')
        got=select(model,{'rows':rows},[],[],['A','B','C','D','E'])
        self.assertFalse(any(r['status']=='propose' for r in got['rows']))

    def test_unknown_header_cannot_justify_replacing_uniform_column(self):
        model,rows=fixture('cost_sign','Custom Metric')
        got=select(model,{'rows':rows},[],[],['A','B','C','D','E'])
        self.assertFalse(any(r['status']=='propose' for r in got['rows']))

    def test_missing_expense_dependency_is_visible(self):
        model,_=fixture('clean');roles=header_roles(model,'A',6)
        got=directional_check(model,'=A2*B2*(1-E2)-A2*C2','A','F2',roles)
        self.assertEqual(got['violations'],['shipping'])


if __name__=='__main__':unittest.main()
