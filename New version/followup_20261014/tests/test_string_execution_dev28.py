"""Semantic boundaries: strings must never silently masquerade as formula refs."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from string_execution_dev28 import parse,execute,provenance,Unsupported
from typed_execution_adapter import ExcelError


class StringExecutionTests(unittest.TestCase):
    def test_escaped_quote_unicode_and_fake_reference(self):
        node=parse('=CONCATENATE("A100 says ""好""",A1,"🙂")')
        self.assertEqual(execute(node,'S',{('S','A1'):'x'}),'A100 says "好"x🙂')
        self.assertEqual([r['address'] for r in provenance(node,'S')],['A1'])

    def test_nested_ampersand_and_order(self):
        self.assertEqual(execute(parse('=("a"&CONCATENATE("b",(A1&"d")))&"e"'),'S',{('S','A1'):'c'}),'abcde')

    def test_quoted_sheet_escape_absolute_flags_casefold(self):
        node=parse("='O''Brien'!$A2&'O''Brien'!B$3")
        self.assertEqual(execute(node,'S', {("O'Brien",'A2'):'a',("O'Brien",'B3'):'b'}),'ab')
        refs=provenance(node,'S');self.assertTrue(refs[0]['column_absolute']);self.assertFalse(refs[0]['row_absolute'])
        self.assertTrue(refs[1]['row_absolute']);self.assertNotEqual(refs[0]['ast_path'],refs[1]['ast_path'])
        self.assertEqual(execute(parse('=sheet2!A1'),'S',{('Sheet2','A1'):'yes'}),'yes')

    def test_error_is_distinct_from_error_text_and_blank(self):
        self.assertEqual(execute(parse('=A1&"x"'),'S',{('S','A1'):ExcelError('#VALUE!')}),ExcelError('#VALUE!'))
        self.assertEqual(execute(parse('=A1&"x"'),'S',{('S','A1'):'#VALUE!'}),'#VALUE!x')
        self.assertEqual(execute(parse('=A1&"x"'),'S',{}),'x')

    def test_integer_boolean_and_restricted_numeric(self):
        self.assertEqual(execute(parse('=A1&B1&-12'),'S',{('S','A1'):True,('S','B1'):12.0}),'TRUE12-12')
        for value in [1.5,1e16,float('inf'),float('nan')]:
            with self.subTest(value=value),self.assertRaises((Unsupported,ValueError,OverflowError)):
                execute(parse('="n="&A1'),'S',{('S','A1'):value})

    def test_missing_sheet_not_empty_and_formula_dependency_not_cached(self):
        self.assertEqual(execute(parse('=Missing!A1'),'S',{}),ExcelError('#REF!'))
        with self.assertRaisesRegex(Unsupported,'formula_dependency'):
            execute(parse('=A1'),'S',{('S','A1'):'stale'},formula_cells=[('S','A1')])

    def test_full_consumption_and_grid(self):
        for f in ['=A1+1','=A1:A2','=A1 A2','=CONCAT(A1)','=IF(1,"a","b")','=NAME',
                  "='[book]Sheet'!A1",'=Sheet1:Sheet2!A1','=A1#','=A0','=XFE1','=A1048577',
                  '="unterminated','=CONCATENATE("a",)','=CONCATENATE()','=1.2','=TRUE']:
            with self.subTest(formula=f),self.assertRaises(Unsupported):parse(f)
        self.assertEqual(execute(parse('=$XFD$1048576'),'S',{}),0)
        self.assertEqual(execute(parse('=12'),'S',{}),12)

    def test_budgets_bound_nested_and_unicode_results(self):
        for f in ['="'+'a'*8192+'"','='+'('*66+'"a"'+')'*66,'='+'&'.join(['A1']*513)]:
            with self.assertRaises(Unsupported):parse(f)
        with self.assertRaisesRegex(Unsupported,'result_budget'):
            execute(parse('=A1&A1'),'S',{('S','A1'):'🙂'*8192})

    def test_repeated_ref_provenance_is_preserved(self):
        refs=provenance(parse('=A1&A1&"A1"'),'S')
        self.assertEqual(len(refs),2);self.assertLess(refs[0]['formula_offset'],refs[1]['formula_offset'])


if __name__=='__main__':unittest.main()
