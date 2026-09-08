import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_external_results import random_event_expectation
from scripts.audit_benchmark_independence import classify_coupling
from scripts.audit_external_manifest import manifest_sources
from scripts.audit_v4_development import build_audit
from scripts.freeze_v4_model import verify_model_source_hashes
from scripts.merge_v5_development_results import _key_audit
from scripts.prepare_enron_manifest import expand_fault_spec
from scripts.run_external_evaluation import METHODS, parse_methods
from scripts.run_v4_blind_predictions import validate_label_free_columns
from scripts.score_v4_blind_predictions import score_rankings, verify_prediction_lock
from scripts.verify_v5_prerequisites import verify as verify_v5_prerequisites


class AuthenticityAuditTests(unittest.TestCase):
    def test_v5_prerequisites_preserve_frozen_v4_and_locked_references(self):
        repository = Path(__file__).resolve().parents[1]
        payload = verify_v5_prerequisites(
            repository, repository / "research" / "V5_REFERENCE_RECEIPT.json"
        )
        self.assertTrue(payload["passed"])
        self.assertEqual(payload["mismatches"], [])

    def test_v5_merge_key_audit_requires_one_row_per_event_method(self):
        rows = [
            {"instance_id": "a", "method": "graph"},
            {"instance_id": "a", "method": "pattern"},
            {"instance_id": "b", "method": "graph"},
        ]
        instances, errors = _key_audit(rows, ("graph", "pattern"))
        self.assertEqual(instances, {"a", "b"})
        self.assertTrue(any("missing keys" in error for error in errors))

    def test_v5_merge_preserves_reference_rows_byte_for_field(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            reference = root / "reference.csv"
            v5 = root / "v5.csv"
            output = root / "combined.csv"
            reference_methods = (
                "graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4"
            )
            with reference.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["instance_id", "method", "rank"])
                writer.writeheader()
                for index, method in enumerate(reference_methods, 1):
                    writer.writerow({"instance_id": "case", "method": method, "rank": index})
            with v5.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=["instance_id", "method", "rank", "joint_confirmed"]
                )
                writer.writeheader()
                writer.writerow({
                    "instance_id": "case", "method": "formulaguard_v5",
                    "rank": 1, "joint_confirmed": 1,
                })
            completed = subprocess.run(
                [
                    sys.executable,
                    str(repository / "scripts" / "merge_v5_development_results.py"),
                    "--reference", str(reference), "--v5", str(v5), "--output", str(output),
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            with output.open("r", encoding="utf-8-sig", newline="") as handle:
                merged = list(csv.DictReader(handle))
            for index, method in enumerate(reference_methods, 1):
                row = next(item for item in merged if item["method"] == method)
                self.assertEqual(row["rank"], str(index))
                self.assertEqual(row["joint_confirmed"], "")
            self.assertEqual(len(merged), 6)

    def test_v5_audit_accepts_only_a_complete_gate_passing_matrix(self):
        repository = Path(__file__).resolve().parents[1]
        methods = (
            "graph", "pattern", "formulaguard", "formulaguard_v3",
            "formulaguard_v4", "formulaguard_v5",
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)

            def write_matrix(path, count, synthetic=False):
                fields = [
                    "instance_id", "method", "rank", "top1", "top3", "top5",
                    "mrr", "exam", "error_type", "diagnostic_status",
                    "v4_diagnostic_status", "v4_final_rank", "pattern_elite",
                    "joint_eligible", "joint_gate_active", "joint_candidate_count",
                    "supported_source_formula_count",
                ]
                with path.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fields)
                    writer.writeheader()
                    for index in range(count):
                        for method in methods:
                            row = {
                                "instance_id": f"event_{index:02d}", "method": method,
                                "rank": 1, "top1": 1, "top3": 1, "top5": 1,
                                "mrr": 1, "exam": 0.01,
                                "error_type": f"type_{index % 6}" if synthetic else "natural",
                                "supported_source_formula_count": 1,
                            }
                            if method == "formulaguard_v4":
                                row.update({
                                    "rank": 6, "top1": 0, "top3": 0, "top5": 0,
                                    "mrr": 1 / 6, "exam": 0.06,
                                })
                            if method == "formulaguard_v5":
                                row.update({
                                    "diagnostic_status": "joint_confirmed",
                                    "v4_diagnostic_status": "strong_counterfactual",
                                    "v4_final_rank": 6, "pattern_elite": 1,
                                    "joint_eligible": 1, "joint_gate_active": 1,
                                    "joint_candidate_count": 1,
                                })
                                if index == 0:
                                    row.update({
                                        "supported_source_formula_count": 2,
                                        "v4_final_rank": 17,
                                    })
                            writer.writerow(row)

            synthetic = root / "synthetic.csv"
            enron = root / "enron.csv"
            write_matrix(synthetic, 18, synthetic=True)
            write_matrix(enron, 30)
            synthetic_reference = root / "synthetic_reference.csv"
            enron_reference = root / "enron_reference.csv"
            for source, target in ((synthetic, synthetic_reference), (enron, enron_reference)):
                with source.open("r", encoding="utf-8-sig", newline="") as handle:
                    rows = [row for row in csv.DictReader(handle) if row["method"] != "formulaguard_v5"]
                with target.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                    writer.writeheader()
                    writer.writerows(rows)
            clean = root / "clean.json"
            clean.write_text(json.dumps({"clean_workbooks": 48, "alarm_rate": 0.0}), encoding="utf-8")
            prerequisite = root / "prerequisite.json"
            prerequisite.write_text(json.dumps({"passed": True}), encoding="utf-8")
            output = root / "audit.json"
            completed = subprocess.run(
                [
                    sys.executable, str(repository / "scripts" / "audit_v5_development.py"),
                    "--synthetic-raw", str(synthetic),
                    "--synthetic-reference", str(synthetic_reference),
                    "--enron-raw", str(enron),
                    "--enron-reference", str(enron_reference),
                    "--clean-summary", str(clean),
                    "--prerequisite-audit", str(prerequisite),
                    "--output", str(output),
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertTrue(payload["freeze_permitted"])
            self.assertTrue(all(payload["gates"].values()))
            self.assertEqual(
                len(payload["v5_embedded_v4_rank_noncomparable_multi_source_events"]),
                2,
            )

    def test_mirrored_mutation_operator_classification(self):
        self.assertTrue(classify_coupling("M3_operator", {"operator"}))
        self.assertTrue(classify_coupling("M2_range_boundary", {"range_boundary_end_row"}))
        self.assertFalse(classify_coupling("M3_operator", {"reference_shift"}))
        self.assertFalse(classify_coupling("unknown", {"operator"}))

    def test_external_evaluation_includes_frozen_v3_and_keeps_v2_reference(self):
        self.assertIn("formulaguard_v3", METHODS)
        self.assertIn("formulaguard_v4", METHODS)
        self.assertIn("formulaguard", METHODS)
        self.assertNotIn("sfl_oracle", METHODS)

    def test_external_method_subset_is_ordered_validated_and_deduplicated(self):
        self.assertEqual(
            parse_methods("graph,formulaguard_v4,graph"),
            ["graph", "formulaguard_v4"],
        )
        with self.assertRaises(ValueError):
            parse_methods("graph,not_a_method")

    def test_v4_development_audit_rejects_weak_promotion(self):
        rows = []
        for method in ("graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4"):
            row = {
                "instance_id": "event-1", "method": method, "rank": "1",
                "diagnostic_status": "", "promotion_cap": "0",
                "null_control_count": "0", "candidate_delta": "0",
                "intervention_responsibility_gain": "0", "intervention_selected": "1",
                "candidate_count": "1",
            }
            rows.append(row)
        v4 = next(row for row in rows if row["method"] == "formulaguard_v4")
        v4.update({
            "diagnostic_status": "pattern_only", "promotion_cap": "10",
            "candidate_delta": "0.00001", "intervention_responsibility_gain": "9",
        })
        audit = build_audit(rows, expected_events=1)
        self.assertFalse(audit["gates"]["promotion_rules_respected"])
        self.assertFalse(audit["development_decision_ready"])

    def test_blind_manifest_rejects_label_columns(self):
        validate_label_free_columns(["instance_id", "workbook"])
        with self.assertRaises(ValueError):
            validate_label_free_columns(["instance_id", "workbook", "source_cell"])

    def test_blind_prediction_scheduler_writes_locked_parallel_ranking(self):
        repository = Path(__file__).resolve().parents[1]
        workbook = repository / "data" / "propagationbench_smoke" / "mutants" / "budget_v0_M1_deep.xlsx"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.csv"
            output = root / "locked"
            manifest.write_text(
                f"instance_id,workbook\ncase-1,{workbook}\n", encoding="utf-8-sig"
            )
            completed = subprocess.run(
                [
                    sys.executable,
                    str(repository / "scripts" / "run_v4_blind_predictions.py"),
                    "--manifest", str(manifest),
                    "--config", str(repository / "research" / "frozen_config_v4.json"),
                    "--output", str(output),
                    "--methods", "graph,pattern",
                    "--workers", "2",
                ],
                cwd=repository, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            lock = json.loads((output / "prediction_lock.json").read_text(encoding="utf-8"))
            metadata = json.loads(
                (output / lock["metadata_file"]).read_text(encoding="utf-8")
            )
            self.assertEqual(metadata["worker_processes"], 2)
            self.assertEqual(metadata["scheduler_unit"], "one_label_free_workbook_method_ranking")
            verify_prediction_lock(output / "prediction_lock.json")

    def test_blind_scoring_uses_locked_full_ranking(self):
        rankings = [
            {"instance_id": "case-1", "method": "graph", "rank": "1", "formula_count": "3", "cell": "S!A1"},
            {"instance_id": "case-1", "method": "graph", "rank": "2", "formula_count": "3", "cell": "S!A2"},
            {"instance_id": "case-1", "method": "graph", "rank": "3", "formula_count": "3", "cell": "S!A3"},
        ]
        scored, summary = score_rankings(rankings, [{"instance_id": "case-1", "source_cell": "S!A2"}])
        self.assertEqual(scored[0]["rank"], 2)
        self.assertEqual(scored[0]["top1"], 0)
        self.assertEqual(scored[0]["top3"], 1)
        self.assertEqual(summary[0]["mrr"], 0.5)

    def test_prediction_lock_detects_changed_rankings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rankings = root / "blind_rankings.csv"
            metadata = root / "metadata.json"
            rankings.write_text("rank\n1\n", encoding="utf-8")
            metadata.write_text("{}", encoding="utf-8")
            from scripts.run_external_evaluation import sha256_file
            lock = root / "prediction_lock.json"
            lock.write_text(json.dumps({
                "rankings_file": rankings.name,
                "rankings_sha256": sha256_file(rankings),
                "metadata_file": metadata.name,
                "metadata_sha256": sha256_file(metadata),
            }), encoding="utf-8")
            verify_prediction_lock(lock)
            rankings.write_text("rank\n2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_prediction_lock(lock)

    def test_frozen_model_source_verification_detects_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "model.py"
            source.write_text("before", encoding="utf-8")
            from scripts.run_external_evaluation import sha256_file
            metadata = {"source_sha256": {"model.py": sha256_file(source)}}
            verify_model_source_hashes(metadata, root)
            source.write_text("after", encoding="utf-8")
            with self.assertRaises(ValueError):
                verify_model_source_hashes(metadata, root)

    def test_enron_overview_range_expansion_is_event_level(self):
        self.assertEqual(expand_fault_spec("F28:G28"), {"F28", "G28"})
        self.assertEqual(expand_fault_spec("G33; I34"), {"G33", "I34"})
        self.assertIsNone(expand_fault_spec("C10:E14; etc."))

    def test_external_manifest_preserves_multi_cell_event(self):
        sources = manifest_sources({
            "source_cells": "Sheet1!F28;Sheet1!G28",
            "source_cell": "",
        })
        self.assertEqual(sources, {("Sheet1", "F28"), ("Sheet1", "G28")})

    def test_exact_random_expectation_handles_multi_cell_events(self):
        single = random_event_expectation(10, 1)
        multiple = random_event_expectation(10, 2)
        self.assertAlmostEqual(single["top1"], 0.1)
        self.assertAlmostEqual(single["exam"], 0.55)
        self.assertGreater(multiple["top5"], single["top5"])
        self.assertGreater(multiple["mrr"], single["mrr"])


if __name__ == "__main__":
    unittest.main()
