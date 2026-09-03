import ast
import inspect
import unittest

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


if __name__ == "__main__":
    unittest.main()
