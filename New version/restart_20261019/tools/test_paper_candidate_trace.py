"""Observation invariants and input-type classification."""
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

import openpyxl
from openpyxl.worksheet.formula import ArrayFormula

from trace_paper_candidates import observe_candidates, xml_inventory


class CandidateTraceTests(unittest.TestCase):
    def test_observer_preserves_return_identity_and_restores_functions(self):
        probes = []
        fg = SimpleNamespace(_candidate_probes=lambda *a, **kw: probes)
        sg = SimpleNamespace(translate_formula=lambda *a: '=A2',
                             _translate_is_safe=lambda *a: True)
        target = SimpleNamespace(cell_id='S!B2')
        selected = ('=A2', 'S!B1', 1.0)

        def repair(*args):
            formula = sg.translate_formula('=A1', 'B1', 'B2')
            sg._translate_is_safe(formula, target)
            return selected

        sg._candidate_repair = repair
        old = (fg._candidate_probes, sg._candidate_repair, sg.translate_formula, sg._translate_is_safe)
        with observe_candidates(fg, sg) as trace:
            self.assertIs(fg._candidate_probes(None, ('S', 'B2')), probes)
            self.assertIs(sg._candidate_repair(target), selected)
        self.assertEqual(old, (fg._candidate_probes, sg._candidate_repair, sg.translate_formula, sg._translate_is_safe))
        self.assertEqual(trace['sg']['S!B2']['candidates'], [dict(formula='=A2', calls=1, source='B1')])

    def test_restoration_after_failure(self):
        def fail(*args):
            raise ValueError('expected failure')
        fg = SimpleNamespace(_candidate_probes=fail)
        sg = SimpleNamespace(_candidate_repair=fail, translate_formula=fail, _translate_is_safe=fail)
        with self.assertRaises(ValueError):
            with observe_candidates(fg, sg):
                fg._candidate_probes(None, ('S', 'B2'))
        self.assertIs(fg._candidate_probes, fail)
        self.assertIs(sg._candidate_repair, fail)

    def test_xml_distinguishes_formula_array_constant_and_missing(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'input.xlsx'
            book = openpyxl.Workbook()
            sheet = book.active
            sheet['A1'], sheet['A2'], sheet['A3'] = 42, 'data', True
            sheet['B1'], sheet['B2'] = '=A1', ArrayFormula(ref='B2:B2', text='=A1*2')
            sheet['C1'] = '#REF!'
            book.save(path)
            types = xml_inventory(path)
        self.assertEqual({k: types['Sheet!' + k] for k in ['A1', 'A2', 'A3', 'B1', 'B2', 'C1']},
                         dict(A1='numeric', A2='text', A3='boolean', B1='formula_normal', B2='formula_array', C1='error'))
        self.assertNotIn('Sheet!D1', types)


if __name__ == '__main__':
    unittest.main()
