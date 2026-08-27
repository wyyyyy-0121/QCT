import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path

from formulaguard.formula import normalized_formula
from scripts import run_v5_core_predictions, run_v5_core_stage
from scripts import audit_v5_core_public_inputs
from scripts.score_v5_core_predictions import hash_file, verify_prediction_completion
from scripts.build_v5_core_dataset import (
    PROFILE_COUNTS,
    build_case,
    clean_cases,
    enumerate_cases,
)


class V5CoreProtocolTests(unittest.TestCase):
    def test_preregistered_internal_counts_are_exact(self):
        for profile in ("smoke", "pilot", "development", "redteam", "validation", "third_party"):
            self.assertEqual(len(enumerate_cases(profile)), PROFILE_COUNTS[profile])
        self.assertEqual(len(clean_cases()), 360)

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


if __name__ == "__main__":
    unittest.main()
