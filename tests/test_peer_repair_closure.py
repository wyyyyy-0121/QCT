import copy
import unittest

from formulaguard.model_discovery import audit_workbook
from formulaguard.peer_repair_closure import (
    probe_repair_closure,
    select_peer_candidate,
    validate_probe_output,
)
from formulaguard.workbook import WorkbookModel


def operator_error_model() -> WorkbookModel:
    cells = {("Sheet", f"A{row}"): row for row in range(1, 8)}
    cells.update({("Sheet", f"B{row}"): row + 1 for row in range(1, 8)})
    formulas = {
        ("Sheet", f"C{row}"): f"=A{row}+B{row}"
        for row in range(1, 8)
    }
    formulas[("Sheet", "C4")] = "=A4-B4"
    return WorkbookModel(
        cells,
        formulas,
        source="in-memory",
        cell_visibility={("Sheet", "C4"): False},
        number_formats={("Sheet", "C4"): "0.00"},
        sheet_visibility={"Sheet": True},
    )


def v4_with_error_sixth() -> list[str]:
    return [
        "Sheet!C1",
        "Sheet!C2",
        "Sheet!C3",
        "Sheet!C5",
        "Sheet!C6",
        "Sheet!C4",
        "Sheet!C7",
    ]


class PeerRepairClosureTests(unittest.TestCase):
    def test_probe_closes_operator_error_without_mutating_workbook(self):
        model = operator_error_model()
        original_formulas = dict(model.formulas)
        source_audit = audit_workbook(model)

        result = probe_repair_closure(model, v4_with_error_sixth(), source_audit)

        self.assertTrue(result["candidate_selected"])
        self.assertTrue(result["repair_executed"])
        self.assertEqual(result["candidate_v4_rank"], 6)
        closure = result["closure"]
        self.assertTrue(closure["candidate"]["anomaly_disappeared"])
        self.assertTrue(closure["candidate"]["peer_priority_decreased"])
        self.assertTrue(closure["candidate"]["local_consistency_recovered"])
        self.assertEqual(closure["global"]["other_new_actionable_count"], 0)
        self.assertTrue(closure["round_trip_reversible"])
        self.assertTrue(closure["repair_closes_without_new_anomaly"])
        self.assertEqual(validate_probe_output(result), [])
        self.assertEqual(model.formulas, original_formulas)
        self.assertFalse(model.cell_visibility[("Sheet", "C4")])
        self.assertEqual(model.number_formats[("Sheet", "C4")], "0.00")

    def test_peer_top1_inside_v4_top5_abstains(self):
        model = operator_error_model()
        source_audit = audit_workbook(model)
        ranking = [
            "Sheet!C4",
            "Sheet!C1",
            "Sheet!C2",
            "Sheet!C3",
            "Sheet!C5",
            "Sheet!C6",
            "Sheet!C7",
        ]

        candidate, reason = select_peer_candidate(ranking, source_audit)
        result = probe_repair_closure(model, ranking, source_audit)

        self.assertIsNone(candidate)
        self.assertEqual(reason, "peer_top1_already_in_v4_top5")
        self.assertFalse(result["candidate_selected"])
        self.assertFalse(result["repair_executed"])
        self.assertIsNone(result["closure"])
        self.assertEqual(validate_probe_output(result), [])

    def test_output_validator_rejects_formula_cell_and_label_leaks(self):
        model = operator_error_model()
        result = probe_repair_closure(
            model,
            v4_with_error_sixth(),
            audit_workbook(model),
        )
        formula_leak = copy.deepcopy(result)
        formula_leak["closure"]["formula"] = "=A4+B4"
        cell_leak = copy.deepcopy(result)
        cell_leak["candidate_address"] = "Sheet!C4"
        label_leak = copy.deepcopy(result)
        label_leak["event_id"] = "error-1"

        self.assertTrue(validate_probe_output(formula_leak))
        self.assertTrue(validate_probe_output(cell_leak))
        self.assertTrue(validate_probe_output(label_leak))

    def test_source_audit_hash_must_remain_valid(self):
        model = operator_error_model()
        source_audit = audit_workbook(model)
        source_audit["review_cells"]["peer"].reverse()

        with self.assertRaisesRegex(ValueError, "source peer audit is invalid"):
            probe_repair_closure(model, v4_with_error_sixth(), source_audit)

    def test_candidate_inventory_is_fixed_to_v4(self):
        model = operator_error_model()
        source_audit = audit_workbook(model)
        ranking = v4_with_error_sixth()[:-1]

        with self.assertRaisesRegex(ValueError, "differs from the V4 formula inventory"):
            select_peer_candidate(ranking, source_audit)


if __name__ == "__main__":
    unittest.main()
