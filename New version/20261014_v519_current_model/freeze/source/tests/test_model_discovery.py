import unittest

from formulaguard.model_discovery import audit_workbook, validate_label_free_output
from formulaguard.workbook import WorkbookModel


def operator_error_model():
    cells = {
        ("Sheet", "A1"): 2,
        ("Sheet", "B1"): 3,
        ("Sheet", "A2"): 4,
        ("Sheet", "B2"): 5,
        ("Sheet", "A3"): 6,
        ("Sheet", "B3"): 7,
    }
    formulas = {
        ("Sheet", "C1"): "=A1+B1",
        ("Sheet", "C2"): "=A2-B2",
        ("Sheet", "C3"): "=A3+B3",
    }
    return WorkbookModel.from_cells(cells, formulas)


class ModelDiscoveryTests(unittest.TestCase):
    def test_operator_change_gets_multi_view_evidence(self):
        result = audit_workbook(operator_error_model())
        row = next(item for item in result["records"] if item["cell"] == "Sheet!C2")
        self.assertEqual(row["status"], "evidence_supported")
        self.assertEqual(row["alternative_support"], 2)
        self.assertIn("=A2+B2", [item["formula"] for item in row["repair_hypotheses"]])
        self.assertEqual(result["rankings"]["combined"][0], "Sheet!C2")

    def test_unrelated_horizontal_role_is_not_a_peer(self):
        model = WorkbookModel.from_cells(
            {("Sheet", "A1"): 2, ("Sheet", "B1"): 3, ("Sheet", "A2"): 4, ("Sheet", "B2"): 5},
            {
                ("Sheet", "C1"): "=A1+B1",
                ("Sheet", "C2"): "=A2+B2",
                ("Sheet", "D1"): "=C1*2",
                ("Sheet", "D2"): "=C2*2",
            },
        )
        result = audit_workbook(model)
        records = {item["cell"]: item for item in result["records"]}
        self.assertNotEqual(records["Sheet!C1"]["status"], "evidence_supported")
        self.assertNotEqual(records["Sheet!D1"]["status"], "evidence_supported")
        self.assertEqual(records["Sheet!C1"]["alternative_support"], 0)

    def test_competing_alternatives_are_ambiguous(self):
        cells = {("Sheet", f"A{row}"): row for row in range(1, 6)}
        cells.update({("Sheet", f"B{row}"): row + 1 for row in range(1, 6)})
        formulas = {
            ("Sheet", "C1"): "=A1+B1",
            ("Sheet", "C2"): "=A2+B2",
            ("Sheet", "C3"): "=A3*B3",
            ("Sheet", "C4"): "=A4-B4",
            ("Sheet", "C5"): "=A5-B5",
        }
        result = audit_workbook(WorkbookModel.from_cells(cells, formulas))
        row = next(item for item in result["records"] if item["cell"] == "Sheet!C3")
        self.assertEqual(row["status"], "ambiguous")
        self.assertEqual(row["alternative_support"], 2)
        self.assertEqual(row["second_alternative_support"], 2)

    def test_unsupported_formula_remains_in_complete_ranking(self):
        model = WorkbookModel.from_cells(
            {("Sheet", "A1"): 1},
            {("Sheet", "B1"): "=XLOOKUP(A1,A:A,B:B)"},
        )
        result = audit_workbook(model)
        row = result["records"][0]
        self.assertFalse(row["parseable"])
        self.assertEqual(row["status"], "unsupported")
        self.assertEqual(result["rankings"]["combined"], ["Sheet!B1"])

    def test_output_is_deterministic_and_label_free(self):
        model = operator_error_model()
        first = audit_workbook(model)
        second = audit_workbook(model)
        self.assertEqual(first, second)
        self.assertEqual(validate_label_free_output(first), [])
        for row in first["records"]:
            for field in (
                "correct_formula", "source_cell", "source_cells", "error_type", "case_kind",
            ):
                self.assertNotIn(field, row)

    def test_review_budget_deduplicates_contiguous_region(self):
        model = WorkbookModel.from_cells(
            {("Sheet", f"A{row}"): row for row in range(1, 8)},
            {("Sheet", f"B{row}"): f"=A{row}*2" for row in range(1, 8)},
        )
        result = audit_workbook(model)
        review = result["review_cells"]["combined"]
        self.assertLessEqual(len(review), 5)
        self.assertEqual(len(review), len(set(review)))


if __name__ == "__main__":
    unittest.main()
