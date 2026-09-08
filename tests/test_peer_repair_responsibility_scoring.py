import unittest
from unittest import mock

from scripts.score_peer_repair_responsibility import build_prediction, summarize


def v4_payload():
    return {
        "workbook_sha256": "a" * 64,
        "ranking": [{"cell": f"Sheet!A{rank}"} for rank in range(1, 8)],
    }


def responsibility_payload(*, passed: bool):
    return {
        "probe": {
            "candidate_selected": True,
            "candidate_v4_rank": 6,
            "responsibility_evaluated": True,
            "responsibility": {
                "responsibility_pass": passed,
                "positive_exact_repair_delta": True,
                "changed_reachable_visible_sink": passed,
                "no_new_evaluation_errors": True,
            },
        },
    }


class PeerRepairResponsibilityScoringTests(unittest.TestCase):
    def test_pass_moves_candidate_to_fifth(self):
        prediction = build_prediction(
            "observed-workbook:test",
            v4_payload(),
            responsibility_payload(passed=True),
        )

        self.assertEqual(
            prediction["top5"],
            ["Sheet!A1", "Sheet!A2", "Sheet!A3", "Sheet!A4", "Sheet!A6"],
        )
        self.assertTrue(prediction["changed"])
        self.assertEqual(prediction["probe_state"], "responsibility_pass")

    def test_fail_preserves_v4_ranking(self):
        prediction = build_prediction(
            "observed-workbook:test",
            v4_payload(),
            responsibility_payload(passed=False),
        )

        self.assertEqual(prediction["ranking"], [f"Sheet!A{rank}" for rank in range(1, 8)])
        self.assertFalse(prediction["changed"])
        self.assertEqual(prediction["forced_peer_top1_ranking"][4], "Sheet!A6")

    def test_summary_uses_the_frozen_public_gates(self):
        rows = []
        for fold in range(5):
            rows.append({
                "event_id": f"error-{fold}",
                "unit_id": f"unit-{fold}",
                "case_kind": "error",
                "cohort": "enron",
                "structure_group": f"group-{fold}",
                "fold": fold,
                "probe_state": "responsibility_pass",
                "responsibility_pass": True,
                "acted": True,
                "v4_top5": 0,
                "model_top5": 1,
                "v4_mrr": 0.1,
                "model_mrr": 0.2,
                "residual_delta": 1,
                "forced_peer_top1_residual_delta": 1,
            })
        rows.append({
            "event_id": "control",
            "unit_id": "control-unit",
            "case_kind": "control",
            "cohort": "control",
            "structure_group": "control-group",
            "fold": 0,
            "probe_state": "no_candidate",
            "responsibility_pass": False,
            "acted": False,
            "v4_top5": 0,
            "model_top5": 0,
            "v4_mrr": 0.0,
            "model_mrr": 0.0,
            "residual_delta": 0,
            "forced_peer_top1_residual_delta": 0,
        })

        with (
            mock.patch("scripts.score_peer_repair_responsibility.EXPECTED_EVENTS", 6),
            mock.patch("scripts.score_peer_repair_responsibility.EXPECTED_ERRORS", 5),
            mock.patch("scripts.score_peer_repair_responsibility.EXPECTED_CONTROLS", 1),
        ):
            result = summarize(rows)

        self.assertTrue(result["all_public_gates_passed"])
        self.assertTrue(all(result["public_gates"].values()))


if __name__ == "__main__":
    unittest.main()
