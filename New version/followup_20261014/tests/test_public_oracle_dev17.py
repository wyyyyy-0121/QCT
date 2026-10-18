from pathlib import Path
import sys
import unittest
import sympy
from openpyxl import Workbook
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from product_sum_oracle_dev17 import equivalent,symbolic,witness
class PublicOracleTests(unittest.TestCase):
    def setUp(self):
        self.w=Workbook();self.s=self.w.active;self.s.title='S'
        for a,v in [('A1',3),('A2',4),('A3',' '),('B1',2),('B2',8)]:self.s[a]=v
    def test_sum_ignores_blank_and_text_but_not_numeric_inputs(self):
        self.assertTrue(equivalent('=SUM(A1:A4)','=A1+A2','S',self.w))
        self.assertFalse(equivalent('=SUM(A1:A4)','=A1','S',self.w))
        self.assertTrue(equivalent('=SUM(A1,A2)','=A2+A1','S',self.w))
    def test_scalar_text_rejected(self):
        with self.assertRaises(ValueError):symbolic('=A1+A3','S',self.w)
    def test_sum_arithmetic_and_parentheses(self):
        self.assertTrue(equivalent('=SUM(A1:A2)*(B1+B2)','=A1*B1+A1*B2+A2*B1+A2*B2','S',self.w))
        self.assertTrue(equivalent('=-SUM(A1,A2-B1)','=B1-A1-A2','S',self.w))
    def test_formula_precedents_remain_independent(self):
        self.s['B3']='=A1+A2'
        self.assertFalse(equivalent('=B3','=A1+A2','S',self.w))
    def test_exact_large_literals_and_witness(self):
        self.assertFalse(equivalent('=A1*9007199254740992','=A1*9007199254740993','S',self.w))
        w=witness('=A1-A2','=A1+A2','S',self.w)
        self.assertNotEqual(w['observed'],w['expected'])
if __name__=='__main__':unittest.main()
