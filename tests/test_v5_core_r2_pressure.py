from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


pressure = load_script("r2_pressure_runner", "scripts/run_v5_core_r2_pressure.py")
audit = load_script("r2_pressure_audit", "scripts/audit_v5_core_r2_pressure.py")
predictions = load_script("r2_confirmation_predictions", "scripts/run_v5_core_r2_predictions.py")
scoring = load_script("r2_confirmation_scoring", "scripts/score_v5_core_r2_confirmation.py")
packing = load_script(
    "r2_confirmation_packing", "scripts/prepare_v5_core_r2_confirmation_pack.py",
)
completion = load_script(
    "r2_completion_audit", "scripts/audit_v5_core_r2_completion.py",
)
performance = load_script(
    "r2_performance", "scripts/run_v5_core_r2_performance.py",
)


class R2PressureProtocolTests(unittest.TestCase):
    def test_inventory_include_flag_excludes_unavailable_events(self):
        rows = [
            {"instance_id": "included", "include": "1", "workbook": "workbooks/01.xlsx"},
            {"instance_id": "label", "include": "0", "workbook": ""},
            {"instance_id": "unavailable", "include": "0", "workbook": ""},
        ]
        selected, excluded = pressure.evaluation_events(rows)
        self.assertEqual([row["instance_id"] for row in selected], ["included"])
        self.assertEqual(excluded, 2)

    def test_inventory_without_include_flag_retains_every_event(self):
        rows = [{"instance_id": "historical", "workbook": "workbooks/01.xlsx"}]
        selected, excluded = pressure.evaluation_events(rows)
        self.assertEqual(selected, rows)
        self.assertEqual(excluded, 0)

    def test_source_parser_normalizes_quotes_dollars_and_case(self):
        self.assertEqual(
            pressure.parse_sources("'Sheet One'!$a$1;Sheet2!b3"),
            {("Sheet One", "A1"), ("Sheet2", "B3")},
        )

    def _pressure_payload(self, events: int, *, r2_mrr: float = 0.51) -> dict:
        metrics = {
            "v4": {"events": events, "top5": 0.50, "mrr": 0.50},
            "r2_source": {"events": events, "top5": 0.55, "mrr": r2_mrr},
            "r2_full": {"events": events, "top5": 0.55, "mrr": r2_mrr},
        }
        return {
            "protocol": "v5_core_r2_revealed_retrospective_pressure_v1",
            "retrospective_only": True,
            "not_for_model_selection": True,
            "events": events,
            "input_events": 36 if events == 30 else events,
            "excluded_inventory_events": 6 if events == 30 else 0,
            "git_commit": f"commit-{events}",
            "runner_source_sha256": f"runner-{events}",
            "model_source_sha256": "same-model",
            "events_sha256": f"events-{events}",
            "summary": metrics,
            "paired_full_vs_source": {
                "improved_events": 0, "harmed_events": 0,
                "unchanged_events": events, "harmed_rate": 0.0, "mean_rank_gain": 0.0,
            },
            "quality_checks": {
                "unique_instance_ids": True,
                "all_workbooks_present": True,
                "complete_rankings": True,
                "raw_rows": events * 3,
            },
        }

    def _run_audit(self, *, enron_mrr: float = 0.51) -> dict:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            historical_path = root / "historical.json"
            enron_path = root / "enron.json"
            development_path = root / "development.json"
            output_path = root / "audit.json"
            historical_path.write_text(json.dumps(self._pressure_payload(100)), encoding="utf-8")
            enron_path.write_text(json.dumps(self._pressure_payload(30, r2_mrr=enron_mrr)), encoding="utf-8")
            development_path.write_text(json.dumps({
                "error_metrics": {"r2_source": {"macro_top5": 0.95, "weakest_top5": 0.80}},
                "gates": {"hard_gate_passed": False, "failed_gates": ["legacy_breadth_gate"]},
            }), encoding="utf-8")
            arguments = [
                "audit_v5_core_r2_pressure.py",
                "--historical-100", str(historical_path),
                "--enron", str(enron_path),
                "--development-audit", str(development_path),
                "--output", str(output_path),
            ]
            with patch.object(sys, "argv", arguments):
                audit.main()
            return json.loads(output_path.read_text(encoding="utf-8"))

    def test_audit_preserves_original_failure_but_can_allow_confirmation(self):
        receipt = self._run_audit()
        self.assertFalse(receipt["original_preregistered_development_gate_passed"])
        self.assertEqual(receipt["original_failed_gates_preserved"], ["legacy_breadth_gate"])
        self.assertTrue(receipt["pressure_safety_passed"])
        self.assertTrue(receipt["eligible_for_new_independent_confirmation"])
        self.assertFalse(receipt["runner_source_hashes_equal"])
        self.assertEqual(
            receipt["cohort_execution_provenance"]["enron"]["excluded_inventory_events"],
            6,
        )
        self.assertIn("pre-adapter runner", receipt["runner_difference_disclosure"])

    def test_audit_rejects_real_corpus_mrr_regression(self):
        receipt = self._run_audit(enron_mrr=0.40)
        self.assertFalse(receipt["pressure_safety_passed"])
        self.assertFalse(receipt["eligible_for_new_independent_confirmation"])
        self.assertFalse(receipt["gates"]["enron_r2_full_mrr_not_below_v4_by_more_than_0_01"])

    def test_confirmation_public_manifest_rejects_label_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.csv"
            path.write_text(
                "instance_id,workbook,source_cell\ncase_1,workbooks/one.xlsx,S!A1\n",
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                predictions.read_manifest(path)

    def test_confirmation_unsupported_formula_remains_in_complete_ranking(self):
        values = predictions.append_unsupported([], (("Sheet", "A1"),), method="r2_full")
        self.assertEqual(len(values), 1)
        self.assertEqual(values[0].cell_label, "Sheet!A1")
        self.assertEqual(values[0].evidence["diagnostic_status"], "unsupported_coverage")

    def test_confirmation_cell_normalization_handles_multi_source_events(self):
        self.assertEqual(
            scoring.parse_sources("'Sheet One'!$a$1;Sheet2!b3"),
            {"Sheet One!A1", "Sheet2!B3"},
        )

    def test_confirmation_bootstrap_is_deterministic(self):
        def row(method: str, value: float, stratum: str) -> dict:
            return {"method": method, "mrr": value, "top5": int(value >= 1),
                    "analysis_stratum": stratum}

        events = {
            "one": {"r2_full": row("r2_full", 1.0, "a"), "v4": row("v4", 0.5, "a")},
            "two": {"r2_full": row("r2_full", 0.5, "b"), "v4": row("v4", 0.25, "b")},
        }
        first = scoring.bootstrap_comparison(events, "r2_full", "v4", iterations=100)
        second = scoring.bootstrap_comparison(events, "r2_full", "v4", iterations=100)
        self.assertEqual(first, second)
        self.assertGreater(first["mrr_ci95"][0], 0)

    def test_third_party_packager_rejects_nonportable_and_escaping_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workbook = root / "case.xlsx"
            workbook.write_bytes(b"placeholder")
            self.assertEqual(packing.safe_file(root, "case.xlsx"), workbook.resolve())
            with self.assertRaises(ValueError):
                packing.safe_file(root, r"workbooks\case.xlsx")
            with self.assertRaises(ValueError):
                packing.safe_file(root, "../case.xlsx")

    def test_third_party_packager_normalizes_formula_spelling(self):
        self.assertEqual(
            packing.canonical_formula(" =sum( 'Data'!A1 : A2 ) "),
            "=SUM(DATA!A1:A2)",
        )

    def test_completion_audit_requires_exact_development_failure_receipt(self):
        value = {
            "protocol": "v5_core_r2_retrospective_audit_v2",
            "development_only": True,
            "independent_evidence": False,
            "errors": 480,
            "clean": 360,
            "workers": 24,
            "gates": {
                "hard_gate_passed": False,
                "failed_gates": ["improvement_spans_at_least_four_error_types"],
            },
        }
        self.assertTrue(completion.valid_development_receipt(value))
        value["independent_evidence"] = True
        self.assertFalse(completion.valid_development_receipt(value))

    def test_completion_audit_distinguishes_pressure_receipt_from_scores(self):
        value = {
            "protocol": "v5_core_r2_r1_pressure_safety_decision_v1",
            "development_only": True,
            "independent_evidence": False,
            "gates": {},
            "pressure_safety_passed": True,
            "eligible_for_new_independent_confirmation": True,
        }
        self.assertTrue(completion.valid_pressure_receipt(value))
        value["independent_evidence"] = True
        self.assertFalse(completion.valid_pressure_receipt(value))

    def test_r2_performance_sizes_and_percentile_are_deterministic(self):
        self.assertEqual(performance.parse_sizes("100,500,100"), (100, 500))
        self.assertEqual(performance.percentile95([1.0, 2.0, 3.0]), 3.0)
        with self.assertRaises(ValueError):
            performance.parse_sizes("0")


if __name__ == "__main__":
    unittest.main()
