"""Domain, provenance, cache rejection and independent amortization checks."""
from decimal import Decimal, localcontext
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'scripts'), str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from dependency_execution_dev31 import Executor, Budget, Unsupported, payment, principal_payment
from formulaguard.workbook import WorkbookModel
from typed_execution_adapter import ExcelError


class DependencyExecutionTests(unittest.TestCase):
    def engine(self, formulas, inputs=None, **kw):
        inputs = inputs or {}
        return Executor(WorkbookModel(inputs, {('S', a): f for a, f in formulas.items()}), inputs, **kw)

    def test_payments_against_decimal_discounted_cashflows_and_schedule(self):
        # Independent oracle: solve discounted cash-flow sum at high precision,
        # then evolve an amortization schedule period by period (no expm1).
        with localcontext() as context:
            context.prec = 70
            for rate in ['0', '.05', '-.02', '0.000000000001']:
                for when in [0, 1]:
                    for fv in ['0', '200']:
                        with self.subTest(rate=rate, when=when, fv=fv):
                            r, future, balance = Decimal(rate), Decimal(fv), Decimal(1000)
                            n, factor = 12, 1 + r
                            pmt = -(balance + future / factor ** n) / sum(
                                factor ** -(k - when) for k in range(1, n + 1))
                            self.assertAlmostEqual(payment(float(r), n, 1000, float(future), when), float(pmt), places=9)
                            for per in range(1, n + 1):
                                interest = 0 if when == 1 and per == 1 else -balance * r
                                principal = pmt - interest
                                self.assertAlmostEqual(principal_payment(float(r), per, n, 1000, float(future), when),
                                                       float(principal), places=9)
                                balance += principal
                            self.assertAlmostEqual(float(balance * (factor if when else 1)), -float(future), places=8)

    def test_financial_invalid_domains_are_explicit(self):
        for args in [(-1, 12, 100), (.1, 0, 100), (.1, 2.5, 100), (.1, 12, 100, 0, 2)]:
            with self.assertRaises(Unsupported):
                payment(*args)
        for per in [0, 13, 1.5]:
            with self.assertRaises(Unsupported):
                principal_payment(.05, per, 12, 100)

    def test_full_dependency_audit_and_lazy_if(self):
        e = self.engine({'B1': '=IF(A1=0,12,1/0)', 'B2': '=IF(A1=0,12,C1)', 'C1': '=1/0'}, {('S', 'A1'): 0})
        self.assertEqual(e.execute(('S', 'B1'))['value']['value'], 12)
        r = e.execute(('S', 'B2'))
        self.assertIn(('S', 'C1'), r['audit']['formula_cells'])
        self.assertNotIn(('S', 'C1'), r['accessed'])
        self.assertEqual(r['value']['value'], 12)

    def test_inactive_unsupported_and_circular_branches_rejected(self):
        for formula in ['=IF(1,12,SQRT(A1))', '=IF(1,12,B1)']:
            self.assertEqual(self.engine({'B1': formula}).execute(('S', 'B1'))['status'], 'unsupported')

    def test_index_horizontal_vertical_two_dimensional_and_blank(self):
        values = {('S', 'A1'): 10, ('S', 'B1'): 20, ('S', 'A2'): 30, ('S', 'B2'): 40}
        formulas = {'D1': '=INDEX(A1:B1,2)', 'D2': '=INDEX(A1:A2,2)', 'D3': '=INDEX(A1:B2,2,2)',
                    'D4': '=INDEX(A3:B3,1)', 'D5': '=INDEX(A1:B2,3,1)'}
        e = self.engine(formulas, values)
        self.assertEqual([e.execute(('S', 'D' + str(i)))['value']['value'] for i in range(1, 5)], [20, 30, 40, 0])
        self.assertEqual(e.execute(('S', 'D5'))['value']['error'], '#REF!')

    def test_index_selection_is_lazy_but_whole_range_is_audited(self):
        e = self.engine({'A1': '=1/0', 'B1': '=4', 'C1': '=INDEX(A1:B1,2)'})
        r = e.execute(('S', 'C1'))
        self.assertEqual(r['value']['value'], 4)
        self.assertIn(('S', 'A1'), r['audit']['cells'])
        self.assertNotIn(('S', 'A1'), r['accessed'])

    def test_index_noninteger_zero_and_missing_dimension_are_unsupported(self):
        for formula in ['=INDEX(A1:B2,1)', '=INDEX(A1:B1,1.5)', '=INDEX(A1:B1,0)']:
            r = self.engine({'D1': formula}).execute(('S', 'D1'))
            self.assertEqual(r['status'], 'unsupported', formula)

    def test_reference_aggregates_ignore_text_booleans_and_blanks(self):
        values = {('S', 'A1'): 7, ('S', 'A2'): '100', ('S', 'A3'): True}
        e = self.engine({'B1': '=SUM(A1:A4)', 'B2': '=MAX(A1:A4)', 'B3': '=MIN(A1:A4)',
                         'B4': '=SUM(A2,A3)', 'B5': '=SUM(A3=1)'}, values)
        for a in ['B1', 'B2', 'B3']:
            self.assertEqual(e.execute(('S', a))['value']['value'], 7)
        self.assertEqual(e.execute(('S', 'B4'))['value']['value'], 0)
        self.assertEqual(e.execute(('S', 'B5'))['status'], 'unsupported')

    def test_error_is_distinct_from_text_and_propagates(self):
        e = self.engine({'B1': '=SUM(A1:A2)', 'B2': '=A2+1', 'B3': '=IF(A1,1,2)'},
                        {('S', 'A1'): ExcelError('#N/A'), ('S', 'A2'): '#N/A'})
        self.assertEqual(e.execute(('S', 'B1'))['value']['error'], '#N/A')
        self.assertEqual(e.execute(('S', 'B2'))['reason'], 'text_numeric_coercion')
        self.assertEqual(e.execute(('S', 'B3'))['value']['error'], '#N/A')

    def test_small_nonzero_denominator_not_treated_as_zero(self):
        e = self.engine({'B1': '=1/0.00000000000001', 'B2': '=1/0', 'B3': '=(-1)^0.5'})
        self.assertEqual(e.execute(('S', 'B1'))['value']['value'], 1e14)
        self.assertEqual(e.execute(('S', 'B2'))['value']['error'], '#DIV/0!')
        self.assertEqual(e.execute(('S', 'B3'))['value']['error'], '#NUM!')

    def test_unknown_sheet_and_chained_power_never_guessed(self):
        for formula in ['=Other!A1', '=2^3^2', '="12"+1']:
            self.assertEqual(self.engine({'B1': formula}).execute(('S', 'B1'))['status'], 'unsupported')

    def test_sheet_name_case_and_cross_sheet_range(self):
        e = self.engine({'B1': '=s!A1', 'B2': '=SUM(S!A1:T!A1)'}, {('S', 'A1'): 5, ('T', 'A1'): 10})
        self.assertEqual(e.execute(('S', 'B1'))['value']['value'], 5)
        self.assertEqual(e.execute(('S', 'B2'))['reason'], 'cross_sheet_range')

    def test_all_budgets_fail_explicitly(self):
        samples = [(Budget(formula_chars=3), '=1+2', 'formula_length_budget'),
                   (Budget(formula_nodes=2), '=1+2', 'ast_budget'),
                   (Budget(ast_depth=0), '=1+2', 'ast_budget'),
                   (Budget(range_cells=2), '=SUM(A1:A3)', 'range_budget'),
                   (Budget(dependency_cells=1), '=A1+1', 'dependency_cell_budget'),
                   (Budget(dependency_nodes=1), '=1+2', 'dependency_node_budget'),
                   (Budget(execution_nodes=1), '=1+2', 'execution_node_budget')]
        for budget, formula, code in samples:
            self.assertEqual(self.engine({'B1': formula}, budget=budget).execute(('S', 'B1'))['reason'], code)
        e = self.engine({'B1': '=B2', 'B2': '=B3', 'B3': '=4'}, budget=Budget(dependency_depth=1))
        self.assertEqual(e.execute(('S', 'B1'))['reason'], 'dependency_depth_budget')

    def test_poisoned_formula_cache_is_never_input(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / 'input.xlsx'; book = openpyxl.Workbook(); book.active['A1'] = '=2+3'
            book.active['B1'] = '=A1*2'; book.save(p)
            with zipfile.ZipFile(p) as z:
                parts = {n: z.read(n) for n in z.namelist()}
            parts['xl/worksheets/sheet1.xml'] = parts['xl/worksheets/sheet1.xml'].replace(b'<v></v>', b'<v>99999</v>')
            with zipfile.ZipFile(p, 'w') as z:
                for n, v in parts.items(): z.writestr(n, v)
            e = Executor.from_xlsx(p)
            self.assertNotIn(('Sheet', 'A1'), e.inputs)
            self.assertEqual(e.execute(('Sheet', 'B1'))['value']['value'], 10)


if __name__ == '__main__':
    unittest.main()
