import copy
import unittest

from formulaguard.model_discovery import audit_workbook
from formulaguard.peer_repair_responsibility import (
    probe_repair_responsibility,
    validate_responsibility_output,
)
from formulaguard.workbook import WorkbookModel


def responsibility_model(*, downstream: bool = True) -> WorkbookModel:
    cells = {("Sheet", f"A{row}"): row for row in range(1, 8)}
    cells.update({("Sheet", f"B{row}"): row + 1 for row in range(1, 8)})
    formulas = {
        ("Sheet", f"C{row}"): f"=A{row}+B{row}"
        for row in range(1, 8)
    }
    formulas[("Sheet", "C4")] = "=A4-B4"
    if downstream:
        formulas[("Sheet", "D4")] = "=C4*2"
    return WorkbookModel.from_cells(cells, formulas)


def v4_ranking(*, downstream: bool = True) -> list[str]:
    ranking = [
        "Sheet!C1",
        "Sheet!C2",
        "Sheet!C3",
        "Sheet!C5",
        "Sheet!C6",
        "Sheet!C4",
        "Sheet!C7",
    ]
    if downstream:
        ranking.append("Sheet!D4")
    return ranking


class PeerRepairResponsibilityTests(unittest.TestCase):
    def test_exact_repair_changes_visible_sink_and_passes(self):
        model = responsibility_model()
        original_formulas = dict(model.formulas)

        result = probe_repair_responsibility(
            model,
            v4_ranking(),
            audit_workbook(model),
        )

        responsibility = result["responsibility"]
        self.assertTrue(result["responsibility_evaluated"])
        self.assertGreater(responsibility["exact_repair_delta"], 0.0)
        self.assertEqual(responsibility["changed_reachable_visible_sink_count"], 1)
        self.assertTrue(responsibility["key_output_changed"])
        self.assertEqual(responsibility["new_evaluation_error_count"], 0)
        self.assertTrue(responsibility["responsibility_pass"])
        self.assertEqual(validate_responsibility_output(result), [])
        self.assertEqual(model.formulas, original_formulas)

    def test_local_repair_without_downstream_sink_abstains(self):
        model = responsibility_model(downstream=False)

        result = probe_repair_responsibility(
            model,
            v4_ranking(downstream=False),
            audit_workbook(model),
        )

        responsibility = result["responsibility"]
        self.assertGreater(responsibility["exact_repair_delta"], 0.0)
        self.assertEqual(responsibility["reachable_visible_sink_count"], 0)
        self.assertFalse(responsibility["responsibility_pass"])

    def test_peer_top1_inside_v4_top5_is_not_evaluated(self):
        model = responsibility_model()
        ranking = v4_ranking()
        ranking.remove("Sheet!C4")
        ranking.insert(0, "Sheet!C4")

        result = probe_repair_responsibility(model, ranking, audit_workbook(model))

        self.assertFalse(result["candidate_selected"])
        self.assertFalse(result["responsibility_evaluated"])
        self.assertIsNone(result["responsibility"])
        self.assertEqual(validate_responsibility_output(result), [])

    def test_validator_recomputes_fixed_action_rule(self):
        model = responsibility_model()
        result = probe_repair_responsibility(
            model,
            v4_ranking(),
            audit_workbook(model),
        )
        tampered = copy.deepcopy(result)
        tampered["responsibility"]["responsibility_pass"] = False

        self.assertIn(
            "responsibility pass flag differs from the fixed rule",
            validate_responsibility_output(tampered),
        )

    def test_validator_rejects_content_leaks(self):
        model = responsibility_model()
        result = probe_repair_responsibility(
            model,
            v4_ranking(),
            audit_workbook(model),
        )
        formula_leak = copy.deepcopy(result)
        formula_leak["responsibility"]["formula"] = "=A4+B4"
        cell_leak = copy.deepcopy(result)
        cell_leak["candidate_address"] = "Sheet!C4"

        self.assertTrue(validate_responsibility_output(formula_leak))
        self.assertTrue(validate_responsibility_output(cell_leak))


if __name__ == "__main__":
    unittest.main()
