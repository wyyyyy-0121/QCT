import unittest

from formulaguard.counterfactual_candidates import (
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
        self.assertEqual(limited, full[:7])
        self.assertEqual(len(limited), 7)
        normalized = [normalized_formula(item.formula) for item in full]
        self.assertEqual(len(normalized), len(set(normalized)))
        self.assertNotIn(normalized_formula("=A2+B2*1.5"), normalized)

    def test_offsets_preserve_absolute_markers_and_never_cross_a1_boundary(self):
        candidates = generate_formula_candidates("=$A$1", "$C$4", budget=100)
        formulas = {candidate.formula for candidate in candidates}

        self.assertEqual(formulas, {"=$A$2", "=$B$1"})
        self.assertTrue(
            all(candidate.edit_kind == REFERENCE_OFFSET for candidate in candidates)
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
            ["=0.123456", "=0.123458"],
        )

    def test_zero_budget_and_invalid_source_return_no_candidates(self):
        self.assertEqual(generate_formula_candidates("=A1+1", "B1", budget=0), [])
        self.assertEqual(generate_formula_candidates('=UNSUPPORTED("x")', "B1"), [])
        with self.assertRaisesRegex(ValueError, "non-negative"):
            generate_formula_candidates("=A1+1", "B1", budget=-1)
        with self.assertRaisesRegex(TypeError, "integer"):
            generate_formula_candidates("=A1+1", "B1", budget=True)


class WorkbookCandidateTests(unittest.TestCase):
    def test_workbook_filter_rejects_unknown_and_self_references(self):
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

        # B1 -> B2 is unknown, B1 -> C1 is self-referential, and B1 -> A1 is valid.
        self.assertEqual(reference_candidates, ["=(A1+1)"])
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

    def test_range_boundaries_require_every_referenced_cell_to_exist(self):
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

        self.assertEqual(
            range_formulas,
            {"=SUM(A1:A2)", "=SUM(A1:A4)", "=SUM(A2:A3)"},
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
        self.assertEqual(limited, full[:6])
        self.assertEqual(limited, sorted(limited, key=candidate_sort_key))


if __name__ == "__main__":
    unittest.main()
