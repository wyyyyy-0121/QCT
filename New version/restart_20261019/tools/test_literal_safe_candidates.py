import unittest

from trace_paper_candidates import ROOT  # Add the frozen package to sys.path.
import formulaguard.formula as native
import formulaguard.v5_structural_guard as fg
from literal_safe_candidates import wrap_transforms, literal_safe_paper


class LiteralTransformTests(unittest.TestCase):
    def setUp(self):
        _, self.safe = wrap_transforms(native)

    def test_reference_text_and_escaped_quotes_survive_copy(self):
        formula = '=IF(A1=0,"A1+B1 / SUM ""New York""",$B$1+B1)'
        copied = self.safe['translate_formula'](formula, 'C1', 'C2')
        self.assertEqual(copied, '=IF(A2=0,"A1+B1 / SUM ""New York""",$B$1+B2)')

    def test_all_candidates_preserve_literals_and_quoted_sheet_names(self):
        formula = '=IF(A1=0,"A1+B1 / SUM",\'A+B SUM\'!B1)'
        candidates = self.safe['small_edit_candidates_with_kinds'](formula)
        self.assertTrue(candidates)
        for formula, _ in candidates:
            self.assertIn('"A1+B1 / SUM"', formula)
            self.assertIn("'A+B SUM'!", formula)

    def test_normalization_preserves_string_case_spaces_and_separate_values(self):
        value = self.safe['normalized_formula']('=IF(A1=0,"New York","newyork")')
        self.assertIn('"New York"', value)
        self.assertIn('"newyork"', value)

    def test_without_quotes_every_transform_is_identical(self):
        for formula in ('=A1+B2*$C$3', '=SUM(A1:B4)', '=IF(A1>0,B1,C1)', '=A1*10%'):
            self.assertEqual(native.translate_formula(formula, 'D2', 'F3'),
                             self.safe['translate_formula'](formula, 'D2', 'F3'))
            self.assertEqual(native.small_edit_candidates_with_kinds(formula),
                             self.safe['small_edit_candidates_with_kinds'](formula))
            self.assertEqual(native.normalized_formula(formula), self.safe['normalized_formula'](formula))

    def test_patches_restore_after_failure(self):
        before = fg.translate_formula
        with self.assertRaises(RuntimeError):
            with literal_safe_paper():
                self.assertIsNot(fg.translate_formula, before)
                raise RuntimeError('test')
        self.assertIs(fg.translate_formula, before)


if __name__ == '__main__':
    unittest.main()
