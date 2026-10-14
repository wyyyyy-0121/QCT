from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.audit_counterfactual_behavior_input_only as audit_module
from formulaguard.counterfactual_candidates import REFERENCE_OFFSET
from formulaguard.workbook import WorkbookModel
from scripts.audit_counterfactual_behavior_input_only import (
    BEHAVIOR_CONFIG,
    DRFV_MANIFEST_SHA256,
    EXPECTED_GROUP_SPLITS,
    EXPECTED_GROUPS,
    EXPECTED_WORKBOOK_SPLITS,
    EXPECTED_WORKBOOKS,
    INTAKE_MANIFEST_SHA256,
    ORACLE_CONFIG,
    REPAIR_POOL_CONFIG,
    _oracle_target_summary,
    audit_source,
    expected_edit_kind,
    load_group_sources,
    public_gates,
    require_clean_audit_sources,
    select_injection,
    selection_funnel,
    sha256_file,
    summarize,
    write_json_atomic,
)
from scripts.build_v6_dataset import write_xlsx


class CounterfactualBehaviorAuditTests(unittest.TestCase):
    def _fixture_manifests(self, root: Path) -> tuple[Path, Path, Path, dict[str, int], dict[str, int]]:
        input_root = root / "public_inputs"
        input_root.mkdir()
        specifications = [
            ("train-group", "train", 3),
            ("calibration-group", "calibration", 1),
            ("test-group", "internal_test", 1),
        ]
        intake_rows: list[dict[str, object]] = []
        corpus_rows: list[dict[str, object]] = []
        for group_index, (group, split, copies) in enumerate(specifications):
            for copy_index in range(copies):
                task = f"task-{group_index}-{copy_index}"
                task_dir = input_root / task
                task_dir.mkdir()
                workbook = task_dir / f"1_{task}_input.xlsx"
                write_xlsx(
                    workbook,
                    [("Sheet", {"A1": 10 * group_index + copy_index + 1}, {"B1": "=A1+1"})],
                )
                digest = hashlib.sha256(workbook.read_bytes()).hexdigest()
                workbook_id = f"spreadsheetbench-v1:{task}:{workbook.name}"
                relative_path = f"{task}/{workbook.name}"
                intake_rows.append(
                    {
                        "workbook_id": workbook_id,
                        "task_id": task,
                        "relative_path": relative_path,
                        "bytes": workbook.stat().st_size,
                        "sha256": digest,
                    }
                )
                corpus_rows.append(
                    {
                        "workbook_id": workbook_id,
                        "workbook_sha256": digest,
                        "status": "eligible",
                        "byte_representative": True,
                        "excluded_known_overlap_component": False,
                        "template_group_id": group,
                        "split": split,
                    }
                )
        intake = root / "input_manifest.json"
        corpus = root / "corpus_manifest.json"
        intake.write_text(
            json.dumps(
                {
                    "protocol": "formulaguard_drfv_spreadsheetbench_v1_intake_v1",
                    "archive_sha256": "fixture",
                    "workbooks": intake_rows,
                }
            ),
            encoding="ascii",
        )
        corpus.write_text(
            json.dumps(
                {
                    "protocol": "formulaguard_drfv_corpus_build_v1",
                    "workbooks": corpus_rows,
                }
            ),
            encoding="ascii",
        )
        return (
            corpus,
            intake,
            input_root,
            {"train": 3, "calibration": 1, "internal_test": 1},
            {"train": 1, "calibration": 1, "internal_test": 1},
        )

    def _load_fixture(self, root: Path):
        corpus, intake, input_root, workbook_splits, group_splits = self._fixture_manifests(root)
        return load_group_sources(
            corpus,
            intake,
            input_root,
            expected_corpus_sha256=sha256_file(corpus),
            expected_intake_sha256=sha256_file(intake),
            expected_workbooks=5,
            expected_groups=3,
            expected_workbook_splits=workbook_splits,
            expected_group_splits=group_splits,
        )

    def test_frozen_contract_constants_are_explicit(self):
        self.assertEqual(len(DRFV_MANIFEST_SHA256), 64)
        self.assertEqual(len(INTAKE_MANIFEST_SHA256), 64)
        self.assertEqual(EXPECTED_WORKBOOKS, 607)
        self.assertEqual(EXPECTED_GROUPS, 219)
        self.assertEqual(EXPECTED_WORKBOOK_SPLITS, {"train": 421, "calibration": 95, "internal_test": 91})
        self.assertEqual(EXPECTED_GROUP_SPLITS, {"train": 153, "calibration": 33, "internal_test": 33})
        self.assertEqual(BEHAVIOR_CONFIG.min_peers, 3)
        self.assertEqual(BEHAVIOR_CONFIG.response_config.max_inputs, 8)
        self.assertEqual(BEHAVIOR_CONFIG.response_config.max_downstream, 0)
        self.assertEqual(ORACLE_CONFIG.max_input_cells, 32)
        self.assertEqual(REPAIR_POOL_CONFIG.ast_budget, 24)
        self.assertEqual(REPAIR_POOL_CONFIG.peer_budget, 8)
        self.assertEqual(REPAIR_POOL_CONFIG.peer_radius, 8)
        self.assertEqual(REPAIR_POOL_CONFIG.minimum_peer_votes, 2)

    def test_manifest_selection_is_deterministic_and_one_per_group(self):
        with tempfile.TemporaryDirectory() as directory:
            first = self._load_fixture(Path(directory))
            corpus = Path(directory) / "corpus_manifest.json"
            intake = Path(directory) / "input_manifest.json"
            second = load_group_sources(
                corpus,
                intake,
                Path(directory) / "public_inputs",
                expected_corpus_sha256=sha256_file(corpus),
                expected_intake_sha256=sha256_file(intake),
                expected_workbooks=5,
                expected_groups=3,
                expected_workbook_splits={"train": 3, "calibration": 1, "internal_test": 1},
                expected_group_splits={"train": 1, "calibration": 1, "internal_test": 1},
            )
            self.assertEqual(first, second)
            self.assertEqual(len(first), 3)
            self.assertEqual(len({row["structure_group"] for row in first}), 3)

    def test_any_fault_answer_v4_or_protected_field_is_rejected(self):
        forbidden = (
            "fault_label",
            "answer_position",
            "v4_rank",
            "protected_data",
            "label",
            "ground_truth",
            "correct_formula",
        )
        for field in forbidden:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                corpus, intake, input_root, workbook_splits, group_splits = self._fixture_manifests(root)
                payload = json.loads(corpus.read_text(encoding="ascii"))
                payload[field] = []
                corpus.write_text(json.dumps(payload), encoding="ascii")
                with self.assertRaisesRegex(ValueError, "forbidden label/protected field"):
                    load_group_sources(
                        corpus,
                        intake,
                        input_root,
                        expected_corpus_sha256=sha256_file(corpus),
                        expected_intake_sha256=sha256_file(intake),
                        expected_workbooks=5,
                        expected_groups=3,
                        expected_workbook_splits=workbook_splits,
                        expected_group_splits=group_splits,
                    )

    def test_symlinked_input_workbook_is_rejected_before_hashing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            corpus, intake, input_root, workbook_splits, group_splits = self._fixture_manifests(root)
            intake_payload = json.loads(intake.read_text(encoding="ascii"))
            first = input_root / intake_payload["workbooks"][0]["relative_path"]
            second = input_root / intake_payload["workbooks"][1]["relative_path"]
            first.unlink()
            first.symlink_to(second)
            with self.assertRaisesRegex(ValueError, "symlink component"):
                load_group_sources(
                    corpus,
                    intake,
                    input_root,
                    expected_corpus_sha256=sha256_file(corpus),
                    expected_intake_sha256=sha256_file(intake),
                    expected_workbooks=5,
                    expected_groups=3,
                    expected_workbook_splits=workbook_splits,
                    expected_group_splits=group_splits,
                )

    def test_unexpected_worker_exception_aborts_instead_of_becoming_a_record(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self._load_fixture(Path(directory))[0]
            tampered = dict(source)
            tampered["source_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "attestation"):
                audit_source(tampered)
            with mock.patch.object(
                WorkbookModel,
                "from_xlsx",
                side_effect=RuntimeError("programming defect"),
            ), self.assertRaisesRegex(RuntimeError, "programming defect"):
                audit_source(source)
            with mock.patch.object(
                WorkbookModel,
                "from_xlsx",
                side_effect=OSError("bad input"),
            ):
                row = audit_source(source)
            self.assertEqual(row["status"], "rejected")
            self.assertEqual(row["rejection_reason"], "workbook_load_error")

    def test_full_run_requires_every_audit_source_to_be_clean_and_tracked(self):
        dirty = mock.Mock(stdout="?? scripts/audit_counterfactual_behavior_input_only.py\n")
        with mock.patch.object(
            audit_module.subprocess, "run", return_value=dirty
        ), self.assertRaisesRegex(ValueError, "clean tracked audit source"):
            require_clean_audit_sources()
        clean = mock.Mock(stdout="")
        with mock.patch.object(audit_module.subprocess, "run", return_value=clean):
            require_clean_audit_sources()

    def test_target_and_injected_candidate_are_hash_deterministic(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {("S", f"B{row}"): f"=A{row}*2" for row in range(1, 5)},
        )
        first = select_injection(model, "a" * 64, REFERENCE_OFFSET)
        second = select_injection(model, "a" * 64, REFERENCE_OFFSET)
        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertEqual(first[2].edit_kind, REFERENCE_OFFSET)
        self.assertEqual(expected_edit_kind("fixed-group"), expected_edit_kind("fixed-group"))
        with mock.patch.object(
            audit_module,
            "_target_behavior",
            side_effect=AssertionError("selection consulted behavior"),
        ):
            self.assertEqual(
                select_injection(model, "a" * 64, REFERENCE_OFFSET),
                first,
            )

    def test_summary_counts_and_all_pre_run_gates(self):
        records = []
        for index in range(80):
            behavior_hit = index < 56
            formula_hit = index < 48
            records.append(
                {
                    "status": "evaluated",
                    "expected_edit_kind": (
                        "operator_replacement",
                        "reference_offset",
                        "range_boundary",
                        "numeric_constant",
                    )[index % 4],
                    "behavior_pair_eligible": True,
                    "behavior_ranking_evaluable": True,
                    "reverse_original_available": True,
                    "reverse_original_sources": (
                        ["ast_edit", "peer_translation"]
                        if index < 40
                        else ["ast_edit"]
                    ),
                    "original_behavior_outlier": index < 8,
                    "mutant_pairwise_score_increase": index < 56,
                    "mutant_behavior_outlier": index < 48,
                    "behavior_exact_top1": behavior_hit,
                    "formula_baseline_exact_top1": formula_hit,
                    "behavior_only_win": behavior_hit and not formula_hit,
                    "formula_only_win": formula_hit and not behavior_hit,
                }
            )
        summary = summarize(records, 80)
        self.assertEqual(summary["eligible_groups"], 80)
        self.assertEqual(summary["clean_behavior_outlier_rate"], 0.1)
        self.assertEqual(summary["mutant_pairwise_score_increase_rate"], 0.7)
        self.assertEqual(summary["mutant_behavior_outlier_rate"], 0.6)
        self.assertEqual(summary["behavior_exact_top1_rate"], 0.7)
        self.assertEqual(summary["formula_baseline_exact_top1_rate"], 0.6)
        self.assertEqual(
            summary["reverse_original_source_counts"],
            {"ast_edit": 80, "peer_translation": 40},
        )
        self.assertTrue(all(public_gates(summary).values()))
        funnel = selection_funnel(records, 80)
        self.assertEqual(funnel["structure_groups"], 80)
        self.assertEqual(funnel["mechanisms_evaluated"], 80)

    def test_top1_comparison_uses_only_the_common_eligible_set(self):
        eligible = {
            "status": "evaluated",
            "expected_edit_kind": "reference_offset",
            "behavior_pair_eligible": True,
            "behavior_ranking_evaluable": True,
            "reverse_original_available": True,
            "original_behavior_outlier": False,
            "mutant_pairwise_score_increase": True,
            "mutant_behavior_outlier": True,
            "behavior_exact_top1": True,
            "formula_baseline_exact_top1": False,
            "behavior_only_win": True,
            "formula_only_win": False,
        }
        behavior_abstained = {
            **eligible,
            "behavior_pair_eligible": False,
            "behavior_ranking_evaluable": False,
            "behavior_exact_top1": False,
            "formula_baseline_exact_top1": True,
            "behavior_only_win": False,
            "formula_only_win": True,
        }
        summary = summarize([eligible, behavior_abstained], 2)
        self.assertEqual(summary["reverse_original_available_groups"], 2)
        self.assertEqual(summary["top1_comparison_groups"], 1)
        self.assertEqual(summary["behavior_exact_top1_rate"], 1.0)
        self.assertEqual(summary["formula_baseline_exact_top1_rate"], 0.0)
        self.assertEqual(summary["behavior_only_wins"], 1)
        self.assertEqual(summary["formula_only_wins"], 0)

    def test_oracle_is_invoked_without_exporting_witness_values(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2, ("S", "A2"): 3, ("S", "A3"): 5},
            {("S", "D1"): "=SUM(A1:A3)"},
        )
        summary = _oracle_target_summary(model, ("S", "D1"), "=SUM(A1:A3)")
        self.assertEqual(
            set(summary),
            {
                "status",
                "applicable_relations",
                "relation_holds_count",
                "ambiguity_count",
                "violation_count",
            },
        )
        self.assertGreaterEqual(summary["relation_holds_count"], 1)
        self.assertNotIn("=SUM", json.dumps(summary))

    def test_atomic_writer_rejects_formula_text(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "audit.json"
            with self.assertRaisesRegex(ValueError, "formula text"):
                write_json_atomic(output, {"formula": "=A1+1"})
            self.assertFalse(output.exists())
            write_json_atomic(output, {"target_id": "target:abc", "score": 0.5})
            self.assertEqual(json.loads(output.read_text(encoding="ascii"))["score"], 0.5)


if __name__ == "__main__":
    unittest.main()
