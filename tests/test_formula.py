import unittest

from formulaguard.formula import (
    FormulaSyntaxError,
    Number,
    formula_fingerprint,
    normalized_formula,
    parse_formula,
    render,
    small_edit_candidates,
    small_edit_candidates_with_kinds,
    translate_formula,
)


class FormulaTests(unittest.TestCase):
    def test_relative_formula_fingerprint_is_copy_invariant(self):
        self.assertEqual(
            formula_fingerprint("=B5*C5", "D5"),
            formula_fingerprint("=B9*C9", "D9"),
        )

    def test_translate_formula_preserves_absolute_references(self):
        translated = translate_formula("=D5*(1+$B$2)", "E5", "E8")
        self.assertEqual(translated, "=D8*(1+$B$2)")

    def test_parser_accepts_supported_aggregate_and_if(self):
        self.assertIsNotNone(parse_formula("=IF(SUM(A1:A3)>5,AVERAGE(A1:A3),0)"))

    def test_render_preserves_numeric_source_text(self):
        literals = (
            "0.1234567",
            "0.100000000000000005",
            "1.2300E+02",
            ".5",
            "1.",
            "1e-7",
            "9007199254740993",
        )
        for literal in literals:
            with self.subTest(literal=literal):
                self.assertEqual(render(parse_formula("=" + literal)), literal)

        self.assertEqual(
            render(parse_formula("=A1+0.1234567+1.2300")),
            "((A1+0.1234567)+1.2300)",
        )

    def test_programmatic_number_render_is_float_round_trip_safe(self):
        for value in (0.1, 0.1234567, 1e-300, 987654.32109):
            with self.subTest(value=value):
                self.assertEqual(float(render(Number(value))), value)

    def test_number_source_text_does_not_change_ast_identity(self):
        left = Number(1.0, source_text="1")
        right = Number(1.0, source_text="1.00")

        self.assertEqual(left, right)
        self.assertEqual(hash(left), hash(right))

    def test_small_edit_candidates_cover_operator_and_reference_repairs(self):
        candidates = small_edit_candidates("=B6+C6")
        self.assertIn("=B6*C6", candidates)
        self.assertIn("=B5+C6", candidates)

    def test_small_edit_candidates_cover_range_function_and_absolute_repairs(self):
        candidates = dict(small_edit_candidates_with_kinds("=SUM(B$2:B6)"))
        self.assertIn("=MAX(B$2:B6)", candidates)
        self.assertIn("=SUM(B$2:B7)", candidates)
        self.assertIn("=SUM(B2:B6)", candidates)
        self.assertIn("range_boundary", candidates["=SUM(B$2:B7)"])
        self.assertIn("absolute_reference", candidates["=SUM(B2:B6)"])

    def test_normalized_formula_treats_optional_simple_sheet_quotes_as_equal(self):
        self.assertEqual(
            normalized_formula("=Detail!B7+'Other Sheet'!C2"),
            normalized_formula("='Detail'!B7+'Other Sheet'!C2"),
        )

    def test_small_edit_candidates_can_restore_absolute_copy_offset(self):
        candidates = dict(small_edit_candidates_with_kinds("=A1*(1+Params!B6)"))
        self.assertIn("=A1*(1+'Params'!$B$5)", candidates)
        self.assertIn("absolute_reference", candidates["=A1*(1+'Params'!$B$5)"])
        self.assertIn("reference_shift", candidates["=A1*(1+'Params'!$B$5)"])

    def test_parser_rejects_unsupported_text_literal(self):
        with self.assertRaises(FormulaSyntaxError):
            parse_formula('=IF(A1>0,"yes","no")')


if __name__ == "__main__":
    unittest.main()
