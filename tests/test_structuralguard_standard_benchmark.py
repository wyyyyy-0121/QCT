import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel
from scripts.audit_structuralguard_standard_v2 import audit
from scripts.evaluate_structuralguard_standard_benchmark import (
    load_model_outputs,
    ranking_record,
)

ROOT = Path(__file__).resolve().parents[1]
V1 = ROOT / "data" / "structuralguard_standard_v1"
V2 = ROOT / "data" / "structuralguard_standard_v2"


class StructuralGuardStandardBenchmarkTests(unittest.TestCase):
    def test_v1_is_immutable_and_v2_answers_match_clean_formulas(self):
        self.assertEqual(
            hashlib.sha256((V1 / "SHA256SUMS.txt").read_bytes()).hexdigest(),
            "177d6840ff11783196b30765611f6e48924c760ec8cfa4d327fcf0008af7cff3",
        )
        labels = json.loads((V2 / "labels" / "answer_keys.json").read_text(encoding="utf-8"))
        clean = {
            case["scenario"]: WorkbookModel.from_xlsx(V2 / case["workbook"])
            for case in labels["cases"]
            if case["condition"] == "clean"
        }
        errors = 0
        for case in labels["cases"]:
            for error in case["errors"]:
                errors += 1
                cell = (error["sheet"], error["cell"])
                self.assertEqual(
                    normalized_formula(error["expected_formula"]),
                    normalized_formula(clean[case["scenario"]].formulas[cell]),
                )
        self.assertEqual(errors, 1068)

    def test_ranking_record_exposes_candidate_denominators_and_group_counts(self):
        cells = [("Sheet", "A1"), ("Sheet", "A2"), ("Sheet", "A3")]
        record = ranking_record(
            "test",
            {
                "case_id": "case",
                "condition": "singleton",
                "scenario": "unit",
                "workbook": "unit.xlsx",
                "sha256": "abc",
            },
            cells,
            cells,
            {
                cells[0]: "=B1+C1",
                cells[1]: "=B2*C2",
                cells[2]: "=B3+C3",
            },
            {cells[0], cells[1]},
            {cells[0]: "=B1+C1", cells[1]: "=B2+C2"},
            evidence_by_cell={
                cells[0]: {"group_id": "g1", "group_state": "accepted", "group_reason": "accepted"},
                cells[1]: {"group_id": "g2", "group_state": "abstained", "group_reason": "ambiguous_template"},
            },
        )
        self.assertEqual(record["candidate_count"], 3)
        self.assertEqual(record["candidate_truth_hits"], 2)
        self.assertAlmostEqual(record["candidate_location_precision"], 2 / 3)
        self.assertAlmostEqual(record["candidate_exact_precision"], 1 / 3)
        self.assertEqual(record["candidate_error_coverage"], 1.0)
        self.assertEqual(record["candidate_exact_coverage"], 0.5)
        self.assertEqual(record["candidate_error_abstention_rate"], 0.0)
        self.assertEqual(record["accepted_group_count"], 1)
        self.assertEqual(record["abstained_group_count"], 1)
        self.assertEqual(record["group_rejection_reasons"], {"ambiguous_template": 1})

    def test_method_filter_selects_only_current_v5_and_frozen_v4_r1(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Ops"
            sheet.append(["Opening", "Shipped", "Closing", "Balance Check"])
            for row in range(2, 8):
                sheet.append([100, 10, f"=A{row}-B{row}", f"=C{row}-(A{row}-B{row})"])
            workbook.save(root / "tiny.xlsx")
            outputs = load_model_outputs(
                {"workbook": "tiny.xlsx"},
                root,
                None,
                {"v5_structural_guard", "v4_r1"},
            )
        self.assertEqual({row[0] for row in outputs}, {"v5_structural_guard", "v4_r1"})
        self.assertNotIn("v4_1_pcg", {row[0] for row in outputs})

    def test_acceptance_audit_rejects_clean_candidates(self):
        strong = {
            "singleton": {
                "macro_average_precision": 1.0,
                "exact_repairs": 28,
                "candidate_exact_precision": 1.0,
                "candidate_exact_coverage": 1.0,
            },
            "clean": {"candidate_count": 0, "accepted_group_count": 0},
            "coherent_block": {
                "macro_average_precision": 1.0,
                "candidate_exact_coverage": 1.0,
                "candidate_exact_precision": 1.0,
            },
            "systematic_column": {
                "macro_average_precision": 1.0,
                "exact_repairs": 940,
                "candidate_exact_coverage": 1.0,
                "candidate_exact_precision": 1.0,
            },
        }
        payload = {
            "dataset_protocol": "structuralguard_standard_benchmark_v2",
            "requested_methods": ["v5_structural_guard", "v4_r1"],
            "summaries": [
                {
                    "method": "v5_structural_guard",
                    "status": "ok",
                    "completed_cases": 20,
                    "by_condition": strong,
                },
                {
                    "method": "v4_r1",
                    "status": "ok",
                    "completed_cases": 20,
                    "by_condition": strong,
                },
            ],
        }
        self.assertTrue(audit(payload)["gate_passed"])
        strong["clean"]["candidate_count"] = 1
        result = audit(payload)
        self.assertFalse(result["gate_passed"])
        self.assertFalse(result["checks"]["clean_has_zero_candidates"])


if __name__ == "__main__":
    unittest.main()
