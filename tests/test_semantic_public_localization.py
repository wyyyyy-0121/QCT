import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import score_semantic_public_localization as public_localization
from scripts.score_semantic_public_localization import (
    _validate_selective_receipt,
    action_cells,
    group_bootstrap_interval,
    paired_summary,
    semantic_ranking,
)


class SemanticPublicLocalizationTests(unittest.TestCase):
    def selective_receipt(self):
        return {
            "protocol": "formulaguard_semantic_compatibility_selective_v1",
            "complete": True,
            "calibration_passed": True,
            "internal_test_evaluated": True,
            "calibration": {"threshold": 3.0},
            "internal_test": {"threshold": 3.0},
            "selected_model_sha256": "model",
            "target_receipt_sha256": "target",
            "vocabulary_sha256": "vocabulary",
            "training_receipt_sha256": "training",
            "protected_data_inputs": [],
            "fault_label_inputs": [],
            "v4_rank_inputs": [],
            "threshold_selection": "maximum_calibration_coverage_passing_all_fixed_gates",
        }

    def semantic_complete(self):
        return {
            "selected_model_sha256": "model",
            "target_receipt_sha256": "target",
            "vocabulary_sha256": "vocabulary",
            "training_receipt_sha256": "training",
        }

    def test_semantic_ranking_uses_signed_confidence_and_retains_inventory(self):
        v4 = ["S!A1", "S!A2", "S!A3", "S!A4"]
        scores = [
            {
                "cell": "S!A1",
                "v4_rank": 1,
                "semantic_anomaly_margin": 0.9,
                "semantic_anomaly_confidence": -0.2,
            },
            {
                "cell": "S!A3",
                "v4_rank": 3,
                "semantic_anomaly_margin": 0.1,
                "semantic_anomaly_confidence": 0.8,
            },
            {
                "cell": "S!A2",
                "v4_rank": 2,
                "semantic_anomaly_margin": 0.2,
                "semantic_anomaly_confidence": 0.8,
            },
        ]
        self.assertEqual(
            semantic_ranking(v4, scores),
            ["S!A2", "S!A3", "S!A1", "S!A4"],
        )
        self.assertEqual(
            semantic_ranking(
                v4,
                scores,
                score_field="semantic_anomaly_margin",
            ),
            ["S!A1", "S!A2", "S!A3", "S!A4"],
        )

    def test_actions_require_alternative_win_frozen_threshold_and_budget(self):
        scores = [
            {
                "cell": f"S!A{rank}",
                "v4_rank": rank,
                "semantic_prefers_alternative": prefers,
                "semantic_decision_margin": margin,
            }
            for rank, prefers, margin in (
                (1, False, 9.0),
                (2, True, 2.9),
                (3, True, 3.0),
                (4, True, 4.0),
            )
        ]
        self.assertEqual(action_cells(scores, 3.0, budget=1), ["S!A4"])
        self.assertEqual(action_cells(scores, 3.0, budget=5), ["S!A4", "S!A3"])

    def test_group_bootstrap_is_reproducible(self):
        first = group_bootstrap_interval([0.1, 0.2, 0.3], samples=200, seed=7)
        second = group_bootstrap_interval([0.1, 0.2, 0.3], samples=200, seed=7)
        self.assertEqual(first, second)
        self.assertGreater(first[0], 0.0)

    def test_selective_threshold_receipt_rejects_identity_change(self):
        with tempfile.TemporaryDirectory(dir=public_localization.ROOT) as temporary:
            path = Path(temporary) / "receipt.json"
            payload = self.selective_receipt()
            path.write_text(json.dumps(payload), encoding="ascii")
            _receipt, threshold = _validate_selective_receipt(
                path,
                self.semantic_complete(),
            )
            self.assertEqual(threshold, 3.0)
            payload["selected_model_sha256"] = "changed"
            path.write_text(json.dumps(payload), encoding="ascii")
            with self.assertRaisesRegex(ValueError, "score contract"):
                _validate_selective_receipt(path, self.semantic_complete())

    def test_invalid_prediction_receipt_is_rejected_before_labels_load(self):
        with tempfile.TemporaryDirectory(dir=public_localization.ROOT) as temporary:
            root = Path(temporary)
            profiles = root / "profiles.csv"
            profiles.write_text("unit_id\n", encoding="ascii")
            with (
                mock.patch.object(public_localization, "require_clean_tracked_worktree"),
                mock.patch.object(public_localization, "read_profiles", return_value=[]),
                mock.patch.object(
                    public_localization,
                    "_validate_v4_run",
                    side_effect=ValueError("invalid prediction receipt"),
                ),
                mock.patch.object(public_localization, "load_revealed_events") as labels,
                self.assertRaisesRegex(ValueError, "invalid prediction receipt"),
            ):
                public_localization.score(
                    profiles_path=profiles,
                    v4_dir=root / "v4",
                    semantic_dir=root / "semantic",
                    selective_receipt_path=root / "selective.json",
                    output=root / "output",
                )
            labels.assert_not_called()

    def test_paired_summary_resamples_structure_group_deltas(self):
        rows = []
        for group, baseline, semantic in (
            ("g1", 0.0, 1.0),
            ("g2", 1.0, 1.0),
        ):
            rows.append({
                "case_kind": "error",
                "structure_group": group,
                "metrics": {
                    "v4": {"top5": baseline},
                    "semantic_confidence": {"top5": semantic},
                },
            })
        summary = paired_summary(rows, "top5")
        self.assertEqual(summary["structure_macro_difference"], 0.5)
        self.assertEqual(summary["improved_events"], 1)
        self.assertEqual(summary["worse_events"], 0)

    def test_script_runs_directly_outside_repository(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "scripts/score_semantic_public_localization.py"
        )
        completed = subprocess.run(
            (sys.executable, str(script), "--help"),
            cwd="/tmp",
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--semantic", completed.stdout)


if __name__ == "__main__":
    unittest.main()
