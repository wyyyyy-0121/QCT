import ast
import inspect
import unittest
from unittest import mock

import formulaguard.v5_structural_guard as guard
from formulaguard.api import localize
from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel


def closing_model(*, header_row: int = 1, wrong_rows: tuple[int, ...] = (4,)):
    """Build a small labelled-by-header model without exposing error labels."""
    cells = {}
    formulas = {}
    first_data_row = header_row + 1
    headers = {
        "A": "Opening",
        "B": "Shipped",
        "C": "Closing",
        "D": "Balance Check",
    }
    for column, value in headers.items():
        cells[("Ops", f"{column}{header_row}")] = value
    for row in range(first_data_row, first_data_row + 5):
        cells[("Ops", f"A{row}")] = 100 + row
        cells[("Ops", f"B{row}")] = 10
        closing = f"=A{row}+B{row}" if row in wrong_rows else f"=A{row}-B{row}"
        formulas[("Ops", f"C{row}")] = closing
        formulas[("Ops", f"D{row}")] = f"=C{row}-(A{row}-B{row})"
    return WorkbookModel.from_cells(cells, formulas)


def long_closing_model(*, wrong_rows: tuple[int, ...]):
    cells = {
        ("Ops", "A1"): "Opening",
        ("Ops", "B1"): "Shipped",
        ("Ops", "C1"): "Closing",
        ("Ops", "D1"): "Balance Check",
    }
    formulas = {}
    for row in range(2, 14):
        cells[("Ops", f"A{row}")] = 100 + row
        cells[("Ops", f"B{row}")] = 10
        formulas[("Ops", f"C{row}")] = (
            f"=A{row}+B{row}" if row in wrong_rows else f"=A{row}-B{row}"
        )
        formulas[("Ops", f"D{row}")] = f"=C{row}-(A{row}-B{row})"
    return WorkbookModel.from_cells(cells, formulas)


class V5StructuralGuardTests(unittest.TestCase):
    def test_public_ranker_is_independent_of_v4_and_has_complete_ranking(self):
        tree = ast.parse(inspect.getsource(guard.v5_structural_guard_scores))
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("v4_scores", called_names)

        model = closing_model()
        results = guard.v5_structural_guard_scores(model)
        self.assertEqual({row.cell for row in results}, set(model.formula_cells))
        self.assertEqual(len(results), len(model.formula_cells))
        self.assertEqual(len({row.cell for row in results}), len(results))

    def test_header_role_search_and_closing_sign_semantics(self):
        model = closing_model(header_row=12, wrong_rows=(16,))
        wrong = ("Ops", "C16")
        self.assertEqual(guard._header_row(model, wrong), 12)
        self.assertEqual(guard._header(model, wrong), "closing")
        self.assertGreaterEqual(
            guard._role_penalty(model, wrong, model.formulas[wrong]),
            0.90,
        )
        correct_formula = "=A16-B16"
        self.assertEqual(guard._role_penalty(model, wrong, correct_formula), 0.0)

        derived = WorkbookModel.from_cells(
            {
                ("Customers", "C1"): "Seats",
                ("Customers", "F1"): "MRR",
                ("Customers", "J1"): "MRR per Seat",
                ("Customers", "C2"): 4,
                ("Customers", "F2"): 80,
            },
            {("Customers", "J2"): "=IF(C2=0,0,F2/C2)"},
        )
        self.assertEqual(
            guard._role_penalty(derived, ("Customers", "J2"), derived.formulas[("Customers", "J2")]),
            0.0,
        )

    def test_downstream_balance_check_is_attributed_to_source_cell(self):
        model = closing_model()
        wrong = ("Ops", "C4")
        result = next(
            row for row in guard.v5_structural_guard_scores(model) if row.cell == wrong
        )
        self.assertGreater(result.evidence["affected_constraint_count"], 0)
        self.assertGreater(result.evidence["downstream_constraint_residual"], 0.0)
        self.assertEqual(result.candidate_formula, "=A4-B4")

    def test_candidate_repair_is_explanatory_and_does_not_mutate_source(self):
        model = closing_model()
        original = dict(model.formulas)
        results = localize(model, "formulaguard_v5_structural_guard")
        self.assertEqual(model.formulas, original)
        wrong = next(row for row in results if row.cell == ("Ops", "C4"))
        self.assertEqual(
            normalized_formula(wrong.candidate_formula or ""),
            normalized_formula("=A4-B4"),
        )
        self.assertFalse(wrong.evidence["automatic_edit_applied"])

    def test_fixed_five_point_sampling_is_deterministic(self):
        cells = tuple(("Sheet", f"A{row}") for row in range(1, 21))
        self.assertEqual(
            guard._representative_cells(cells),
            (cells[0], cells[4], cells[9], cells[14], cells[19]),
        )
        self.assertEqual(guard._representative_cells(cells[:4]), cells[:4])

    def test_coherent_group_boundaries_are_discovered_without_labels(self):
        model = long_closing_model(wrong_rows=tuple(range(5, 10)))
        hypotheses = guard._group_hypotheses(model)
        group = next(item for item in hypotheses if item.run.cells[0] == ("Ops", "C5"))
        self.assertEqual(group.run.cells[-1], ("Ops", "C9"))
        self.assertEqual(group.trigger, "flanking_consensus")
        self.assertEqual(group.representatives, group.run.cells)

        original = dict(model.formulas)
        results = guard.v5_structural_guard_scores(model)
        repaired = [row for row in results if row.evidence.get("group_state") == "accepted"]
        self.assertEqual({row.cell for row in repaired}, set(group.run.cells))
        self.assertTrue(all(row.candidate_formula == f"=A{row.cell[1][1:]}-B{row.cell[1][1:]}" for row in repaired))
        self.assertEqual(model.formulas, original)

    def test_systematic_column_uses_semantics_and_propagates_exact_template(self):
        model = long_closing_model(wrong_rows=tuple(range(2, 14)))
        results = guard.v5_structural_guard_scores(model)
        repaired = [row for row in results if row.evidence.get("group_state") == "accepted"]
        self.assertEqual(len(repaired), 12)
        self.assertTrue(all(row.evidence["group_trigger"] == "semantic_column" for row in repaired))
        for row in repaired:
            number = row.cell[1][1:]
            self.assertEqual(row.candidate_formula, f"=A{number}-B{number}")

    def test_equivalent_plus_zero_group_abstains(self):
        cells = {
            ("Sheet", "A1"): "Approved",
            ("Sheet", "B1"): "Spent",
            ("Sheet", "C1"): "Variance",
        }
        formulas = {}
        for row in range(2, 14):
            cells[("Sheet", f"A{row}")] = 100
            cells[("Sheet", f"B{row}")] = 30
            formulas[("Sheet", f"C{row}")] = (
                f"=A{row}-B{row}+0" if 5 <= row <= 9 else f"=A{row}-B{row}"
            )
        model = WorkbookModel.from_cells(cells, formulas)
        results = guard.v5_structural_guard_scores(model)
        group = [row for row in results if row.evidence.get("group_id")]
        self.assertEqual({row.evidence["group_reason"] for row in group}, {"no_behavioral_change"})
        self.assertTrue(all(row.candidate_formula is None for row in group))

    def test_constant_and_missing_formulas_do_not_create_repairs(self):
        cells = {("Sheet", "C1"): "Variance"}
        formulas = {("Sheet", f"C{row}"): "=0" for row in range(2, 10)}
        model = WorkbookModel.from_cells(cells, formulas)
        results = guard.v5_structural_guard_scores(model)
        self.assertTrue(all(row.candidate_formula is None for row in results))
        self.assertEqual(
            {row.evidence.get("group_reason") for row in results},
            {"representative_candidate_missing"},
        )

        missing = long_closing_model(wrong_rows=tuple(range(2, 14)))
        del missing.formulas[("Ops", "C7")]
        ranked = guard.v5_structural_guard_scores(missing)
        self.assertNotIn(("Ops", "C7"), {row.cell for row in ranked})

    def test_vertical_aggregate_formula_is_not_group_eligible(self):
        cells = {("Sheet", "A1"): 1, ("Sheet", "B1"): "Total"}
        formulas = {}
        for row in range(2, 9):
            cells[("Sheet", f"A{row}")] = row
            formulas[("Sheet", f"B{row}")] = f"=SUM(A1:A{row})"
        model = WorkbookModel.from_cells(cells, formulas)
        self.assertFalse(guard._group_hypotheses(model))

    def test_representative_template_disagreement_abstains(self):
        model = long_closing_model(wrong_rows=tuple(range(2, 14)))

        def inconsistent(formula):
            row = int(formula.split("A", 1)[1].split("+", 1)[0])
            operator = "-" if row < 8 else "*"
            return [(formula.replace("+", operator), ("operator",))]

        with mock.patch.object(guard, "small_edit_candidates_with_kinds", side_effect=inconsistent):
            results = guard.v5_structural_guard_scores(model)
        grouped = [row for row in results if row.evidence.get("group_id")]
        self.assertEqual({row.evidence["group_reason"] for row in grouped}, {"template_disagreement"})
        self.assertTrue(all(row.evidence["group_state"] == "abstained" for row in grouped))

    def test_invalid_group_references_are_rejected(self):
        model = long_closing_model(wrong_rows=tuple(range(2, 14)))

        def invalid_reference(formula):
            row = formula.split("A", 1)[1].split("+", 1)[0]
            return [(f"=Z{row}-B{row}", ("reference_shift",))]

        with mock.patch.object(
            guard,
            "small_edit_candidates_with_kinds",
            side_effect=invalid_reference,
        ):
            results = guard.v5_structural_guard_scores(model)
        grouped = [row for row in results if row.evidence.get("group_id")]
        self.assertEqual({row.evidence["group_reason"] for row in grouped}, {"invalid_reference"})
        self.assertTrue(all(row.candidate_formula is None for row in grouped))


if __name__ == "__main__":
    unittest.main()
