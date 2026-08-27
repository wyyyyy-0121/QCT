import hashlib
import inspect
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from formulaguard.a1 import parse_address
from formulaguard.formula import formula_fingerprint, normalized_formula
from formulaguard.workbook import WorkbookModel
from scripts import freeze_v5_core, run_v5_core_predictions, run_v5_core_stage
from scripts import audit_v5_core_public_inputs
from scripts.score_v5_core_predictions import hash_file, verify_prediction_completion
from scripts.build_v5_core_dataset import (
    PROFILE_COUNTS,
    build_case,
    clean_cases,
    clean_control_partition,
    enumerate_cases,
    write_xlsx,
)


class V5CoreProtocolTests(unittest.TestCase):
    def test_preregistered_internal_counts_are_exact(self):
        for profile in ("smoke", "pilot", "development", "redteam", "validation", "third_party"):
            self.assertEqual(len(enumerate_cases(profile)), PROFILE_COUNTS[profile])
        self.assertEqual(len(clean_cases()), 360)

    def test_clean_calibration_and_locked_controls_are_balanced(self):
        cases = clean_cases()
        for limit, per_structure in ((24, 2), (48, 4), (240, 20)):
            self.assertEqual(Counter(case.ambiguity for case in cases[:limit]), Counter({
                structure: per_structure for structure in {case.ambiguity for case in cases}
            }))
        self.assertTrue(all(clean_control_partition(case) == "calibration" for case in cases[:240]))
        self.assertTrue(all(clean_control_partition(case) == "locked_control" for case in cases[240:]))
        self.assertEqual(set(Counter(case.ambiguity for case in cases[240:]).values()), {10})

    def test_labeled_formula_pairs_are_disjoint_across_splits(self):
        pairs = {}
        for profile in ("pilot", "development", "redteam", "validation", "third_party"):
            pairs[profile] = {
                (normalized_formula(build_case(case)[2]), normalized_formula(build_case(case)[3]))
                for case in enumerate_cases(profile)
            }
        profiles = list(pairs)
        for index, left in enumerate(profiles):
            for right in profiles[index + 1:]:
                self.assertFalse(pairs[left] & pairs[right], (left, right))

    def test_clean_structure_probes_are_real_and_pairwise_distinct(self):
        selected = {}
        for case in clean_cases():
            selected.setdefault(case.ambiguity, case)
        self.assertEqual(len(selected), 12)
        signatures = {}
        with tempfile.TemporaryDirectory() as directory:
            for structure, case in selected.items():
                path = Path(directory) / f"{structure}.xlsx"
                sheets, *_ = build_case(case, clean_only=True)
                write_xlsx(path, sheets)
                model = WorkbookModel.from_xlsx(path)
                _, errors = model.evaluate()
                self.assertFalse(errors, structure)
                probe = []
                for (sheet, address), formula in model.formulas.items():
                    parsed = parse_address(address)
                    if sheet == "Model" and 23 <= parsed.col <= 28:
                        probe.append((parsed.row, parsed.col, formula_fingerprint(formula, address)))
                self.assertTrue(probe, structure)
                min_row = min(item[0] for item in probe)
                min_col = min(item[1] for item in probe)
                normalized = sorted((row - min_row, col - min_col, fp) for row, col, fp in probe)
                signatures[structure] = hashlib.sha256(json.dumps(normalized).encode("utf-8")).hexdigest()
        self.assertEqual(len(set(signatures.values())), 12, signatures)

    def test_prediction_worker_source_cannot_read_labels(self):
        source = inspect.getsource(run_v5_core_predictions)
        self.assertNotIn("evaluation_labels", source)
        self.assertNotIn("correct_formula", source)
        self.assertNotIn("source_cell", source)

    def test_public_prediction_metadata_declares_empty_label_reads(self):
        source = inspect.getsource(run_v5_core_predictions.main)
        self.assertIn('"label_files_read": []', source)

    def test_locked_validation_uses_public_audit_before_scoring(self):
        public_source = inspect.getsource(audit_v5_core_public_inputs)
        self.assertNotIn("evaluation_labels", public_source)
        self.assertNotIn("correct_formula", public_source)
        stage_source = inspect.getsource(run_v5_core_stage.main)
        lock_branch, score_branch = stage_source.split(
            'if not (root / "prediction_lock.json").exists()', 1,
        )
        self.assertIn("audit_v5_core_public_inputs.py", lock_branch)
        self.assertNotIn("audit_v5_core_dataset.py", lock_branch.rsplit('if args.stage == "validation_lock":', 1)[1])
        self.assertIn("audit_v5_core_dataset.py", score_branch)
        self.assertIn("locked input changed", score_branch)

    def test_scorer_detects_post_completion_shard_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "shards").mkdir()
            metadata = root / "prediction_metadata.json"
            metadata.write_text(json.dumps({"label_files_read": []}), encoding="utf-8")
            shard = root / "shards/case.json"
            shard.write_text(json.dumps({"instance_id": "case"}), encoding="utf-8")
            digest = hashlib.sha256()
            digest.update(shard.name.encode("utf-8"))
            digest.update(bytes.fromhex(hash_file(shard)))
            (root / "prediction_complete.json").write_text(json.dumps({
                "instances": 1,
                "metadata_sha256": hash_file(metadata),
                "combined_shards_sha256": digest.hexdigest(),
            }), encoding="utf-8")
            verify_prediction_completion(root)
            shard.write_text(json.dumps({"instance_id": "changed"}), encoding="utf-8")
            with self.assertRaises(SystemExit):
                verify_prediction_completion(root)

    def test_freeze_receipt_locks_code_data_evidence_and_environment(self):
        source = inspect.getsource(freeze_v5_core.main)
        for required_field in (
            '"source_sha256"',
            '"historical_source_sha256"',
            '"data_manifest_sha256"',
            '"evidence_sha256"',
            '"environment"',
            '"post_validation_retuning_allowed": False',
        ):
            self.assertIn(required_field, source)
        self.assertIn('git("status", "--porcelain")', source)
        self.assertIn('selection.get("no_parameter_changes_after_this_receipt")', source)

    def test_freeze_manifest_keys_are_repository_relative_and_portable(self):
        self.assertEqual(
            freeze_v5_core.manifest_key(Path("results/v5_core_validation/summary.json")),
            "results/v5_core_validation/summary.json",
        )
        self.assertEqual(
            freeze_v5_core.manifest_key(
                Path("D:/code/QCT/results/v5_core_validation/summary.json")
            ),
            "results/v5_core_validation/summary.json",
        )


if __name__ == "__main__":
    unittest.main()
