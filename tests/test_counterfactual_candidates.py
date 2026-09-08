import unittest

from formulaguard.counterfactual_candidates import (
    FUNCTION_REPLACEMENT,
    NUMERIC_CONSTANT,
    OPERATOR_REPLACEMENT,
    RANGE_BOUNDARY,
    REFERENCE_OFFSET,
    candidate_sort_key,
    generate_counterfactual_candidates,
    generate_formula_candidates,
)
from formulaguard.formula import normalized_formula, parse_formula
from formulaguard.workbook import WorkbookModel


class FormulaCandidateTests(unittest.TestCase):
    def test_ast_candidates_cover_each_constrained_single_edit(self):
        candidates = generate_formula_candidates(
            "=A1*SUM(B1:B3)+10",
            "C4",
            budget=100,
        )
        by_formula = {candidate.formula: candidate for candidate in candidates}

        expected = {
            "=((A1+SUM(B1:B3))+10)": OPERATOR_REPLACEMENT,
            "=((A1*AVERAGE(B1:B3))+10)": FUNCTION_REPLACEMENT,
            "=((A2*SUM(B1:B3))+10)": REFERENCE_OFFSET,
            "=((A1*SUM(B1:B4))+10)": RANGE_BOUNDARY,
            "=((A1*SUM(B1:B3))+9)": NUMERIC_CONSTANT,
        }
        for formula, edit_kind in expected.items():
            self.assertIn(formula, by_formula)
            candidate = by_formula[formula]
            self.assertEqual(candidate.edit_kind, edit_kind)
            self.assertEqual(candidate.witness.target, "C4")
            self.assertTrue(candidate.witness.path.startswith("root"))
            self.assertNotEqual(candidate.witness.before, candidate.witness.after)
            self.assertIsNotNone(parse_formula(candidate.formula))

    def test_candidates_are_deterministic_sorted_deduplicated_and_budgeted(self):
        full = generate_formula_candidates("=A2+B2*1.5", "C2", budget=100)
        repeated = generate_formula_candidates("=A2+B2*1.5", "C2", budget=100)
        limited = generate_formula_candidates("=A2+B2*1.5", "C2", budget=7)

        self.assertEqual(full, repeated)
        self.assertEqual(full, sorted(full, key=candidate_sort_key))
        self.assertEqual(len(limited), 7)
        self.assertEqual(limited, sorted(limited, key=candidate_sort_key))
        self.assertTrue(
            {OPERATOR_REPLACEMENT, REFERENCE_OFFSET, NUMERIC_CONSTANT}.issubset(
                {candidate.edit_kind for candidate in limited}
            )
        )
        normalized = [normalized_formula(item.formula) for item in full]
        self.assertEqual(len(normalized), len(set(normalized)))
        self.assertNotIn(normalized_formula("=A2+B2*1.5"), normalized)

    def test_budget_is_stratified_across_edit_kinds_and_ast_sites(self):
        candidates = generate_formula_candidates(
            "=SUM(A1:A2)+B1+C1+D1+E1+F1+G1+H1+I1+J1+1",
            "K1",
            budget=32,
        )

        self.assertEqual(len(candidates), 32)
        self.assertEqual(
            {candidate.edit_kind for candidate in candidates},
            {
                OPERATOR_REPLACEMENT,
                FUNCTION_REPLACEMENT,
                REFERENCE_OFFSET,
                RANGE_BOUNDARY,
                NUMERIC_CONSTANT,
            },
        )
        operator_sites = {
            candidate.witness.path
            for candidate in candidates
            if candidate.edit_kind == OPERATOR_REPLACEMENT
        }
        self.assertGreater(len(operator_sites), 1)

    def test_offsets_preserve_absolute_markers_and_never_cross_a1_boundary(self):
        candidates = generate_formula_candidates("=$A$1", "$C$4", budget=100)
        formulas = {candidate.formula for candidate in candidates}

        self.assertEqual(formulas, {"=$A$2", "=$B$1"})
        self.assertTrue(
            all(candidate.edit_kind == REFERENCE_OFFSET for candidate in candidates)
        )

        upper_bound = generate_formula_candidates("=$XFD$1", "A1", budget=100)
        self.assertEqual(
            {candidate.formula for candidate in upper_bound},
            {"=$XFC$1", "=$XFD$2"},
        )

    def test_function_replacements_are_limited_to_aggregate_family(self):
        aggregate = generate_formula_candidates("=MIN(A1:A3)", "B1", budget=100)
        functions = {
            candidate.formula
            for candidate in aggregate
            if candidate.edit_kind == FUNCTION_REPLACEMENT
        }
        self.assertEqual(
            functions,
            {
                "=AVERAGE(A1:A3)",
                "=COUNT(A1:A3)",
                "=MAX(A1:A3)",
                "=SUM(A1:A3)",
            },
        )

        conditional = generate_formula_candidates("=IF(A1>0,A1,0)", "B1", budget=100)
        self.assertFalse(
            any(
                candidate.edit_kind == FUNCTION_REPLACEMENT
                for candidate in conditional
            )
        )

    def test_decimal_constant_uses_its_smallest_rendered_decimal_place(self):
        candidates = generate_formula_candidates("=0.25", "A1", budget=100)
        self.assertEqual(
            [candidate.formula for candidate in candidates],
            ["=0.24", "=0.26"],
        )
        self.assertEqual(
            [candidate.witness.delta for candidate in candidates],
            [-0.01, 0.01],
        )

        rounded = generate_formula_candidates("=0.1234567", "A1", budget=100)
        self.assertEqual(
            [candidate.formula for candidate in rounded],
            ["=0.1234566", "=0.1234568"],
        )

    def test_non_numeric_edit_preserves_untouched_high_precision_constant(self):
        candidates = generate_formula_candidates(
            "=0.1234567*A1+987654.32109",
            "B2",
            budget=100,
        )
        non_numeric = [
            candidate
            for candidate in candidates
            if candidate.edit_kind != NUMERIC_CONSTANT
        ]

        self.assertTrue(non_numeric)
        self.assertTrue(
            all(
                "0.1234567" in candidate.formula
                and "987654.32109" in candidate.formula
                for candidate in non_numeric
            )
        )
        self.assertIn(
            "=((0.1234567*A2)+987654.32109)",
            {candidate.formula for candidate in non_numeric},
        )

    def test_numeric_edit_preserves_the_other_numeric_literal(self):
        candidates = generate_formula_candidates(
            "=0.1234567+987654.32109",
            "B1",
            budget=100,
        )
        left_edits = [
            candidate
            for candidate in candidates
            if candidate.edit_kind == NUMERIC_CONSTANT
            and candidate.witness.path == "root.left"
        ]

        self.assertEqual(len(left_edits), 2)
        self.assertTrue(
            all("987654.32109" in candidate.formula for candidate in left_edits)
        )

    def test_zero_budget_and_invalid_source_return_no_candidates(self):
        self.assertEqual(generate_formula_candidates("=A1+1", "B1", budget=0), [])
        self.assertEqual(generate_formula_candidates('=UNSUPPORTED("x")', "B1"), [])
        with self.assertRaisesRegex(ValueError, "non-negative"):
            generate_formula_candidates("=A1+1", "B1", budget=-1)
        with self.assertRaisesRegex(TypeError, "integer"):
            generate_formula_candidates("=A1+1", "B1", budget=True)


class WorkbookCandidateTests(unittest.TestCase):
    def test_workbook_filter_keeps_blank_cells_but_rejects_self_references(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2, ("S", "B1"): 3},
            {("S", "C1"): "=B1+1"},
        )
        candidates = generate_counterfactual_candidates(model, ("S", "C1"), budget=100)
        reference_candidates = [
            candidate.formula
            for candidate in candidates
            if candidate.edit_kind == REFERENCE_OFFSET
        ]

        # B2 is an unstored but legal blank cell; C1 is self-referential.
        self.assertEqual(reference_candidates, ["=(B2+1)", "=(A1+1)"])
        self.assertTrue(
            all(
                normalized_formula(candidate.formula)
                != normalized_formula(model.formulas[("S", "C1")])
                for candidate in candidates
            )
        )

    def test_workbook_filter_rejects_indirect_cycles(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2, ("S", "B1"): 3},
            {
                ("S", "C1"): "=B1",
                ("S", "B2"): "=C1*2",
            },
        )
        candidates = generate_counterfactual_candidates(model, ("S", "C1"), budget=100)

        # B1 -> B2 would create C1 -> B2 -> C1; B1 -> C1 is a direct cycle.
        self.assertEqual(
            [candidate.formula for candidate in candidates],
            ["=A1"],
        )

    def test_range_boundaries_may_expand_into_legal_blank_cells(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {("S", "C5"): "=SUM(A1:A3)"},
        )
        candidates = generate_counterfactual_candidates(model, ("S", "C5"), budget=100)
        range_formulas = {
            candidate.formula
            for candidate in candidates
            if candidate.edit_kind == RANGE_BOUNDARY
        }

        self.assertTrue(
            {"=SUM(A1:A2)", "=SUM(A1:A4)", "=SUM(A2:A3)"}.issubset(range_formulas)
        )
        self.assertIn("=SUM(A1:B3)", range_formulas)

    def test_workbook_filter_rejects_references_to_unknown_sheets(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2},
            {("S", "C1"): "=Ghost!A1"},
        )

        self.assertEqual(
            generate_counterfactual_candidates(model, ("S", "C1"), budget=100),
            [],
        )

    def test_workbook_budget_is_applied_after_validity_filtering(self):
        model = WorkbookModel.from_cells(
            {
                ("S", "A1"): 1,
                ("S", "A2"): 2,
                ("S", "B1"): 3,
                ("S", "B2"): 4,
            },
            {("S", "C1"): "=A1+B1+1"},
        )
        full = generate_counterfactual_candidates(model, ("S", "C1"), budget=100)
        limited = generate_counterfactual_candidates(model, ("S", "C1"), budget=6)

        self.assertGreater(len(full), 6)
        self.assertEqual(limited, sorted(limited, key=candidate_sort_key))
        self.assertTrue(
            {OPERATOR_REPLACEMENT, REFERENCE_OFFSET, NUMERIC_CONSTANT}.issubset(
                {candidate.edit_kind for candidate in limited}
            )
        )


if __name__ == "__main__":
    unittest.main()
