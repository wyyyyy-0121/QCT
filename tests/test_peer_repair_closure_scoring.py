import unittest
from unittest import mock

from scripts.score_peer_repair_closure import (
    _bootstrap_delta,
    build_prediction,
    summarize,
)


def v4_payload():
    return {
        "workbook_sha256": "a" * 64,
        "ranking": [
            {"cell": f"Sheet!A{rank}"}
            for rank in range(1, 8)
        ],
    }


def closure_payload(*, passed: bool):
    return {
        "probe": {
            "candidate_selected": True,
            "candidate_v4_rank": 6,
            "repair_executed": True,
            "closure": {
                "candidate": {"status_before": "unsupported"},
                "repair_closes_without_new_anomaly": passed,
            },
        },
    }


class PeerRepairClosureScoringTests(unittest.TestCase):
    def test_closure_pass_moves_only_candidate_to_fifth(self):
        prediction = build_prediction(
            "observed-workbook:test",
            v4_payload(),
            closure_payload(passed=True),
        )

        self.assertEqual(
            prediction["top5"],
            ["Sheet!A1", "Sheet!A2", "Sheet!A3", "Sheet!A4", "Sheet!A6"],
        )
        self.assertEqual(prediction["ranking"][5], "Sheet!A5")
        self.assertTrue(prediction["changed"])
        self.assertEqual(prediction["probe_state"], "closure_pass")
        self.assertEqual(prediction["label_inputs"], [])

    def test_closure_fail_preserves_v4_but_keeps_forced_diagnostic(self):
        prediction = build_prediction(
            "observed-workbook:test",
            v4_payload(),
            closure_payload(passed=False),
        )

        self.assertEqual(
            prediction["ranking"],
            [f"Sheet!A{rank}" for rank in range(1, 8)],
        )
        self.assertEqual(prediction["forced_peer_top1_ranking"][4], "Sheet!A6")
        self.assertFalse(prediction["changed"])
        self.assertEqual(prediction["probe_state"], "closure_fail")

    def test_selected_candidate_must_be_outside_v4_top5(self):
        payload = closure_payload(passed=True)
        payload["probe"]["candidate_v4_rank"] = 5

        with self.assertRaisesRegex(ValueError, "candidate rank is invalid"):
            build_prediction("observed-workbook:test", v4_payload(), payload)

    def test_bootstrap_is_structure_group_deterministic(self):
        rows = [
            {"structure_group": "g1", "v4_top5": 0, "model_top5": 1},
            {"structure_group": "g1", "v4_top5": 1, "model_top5": 1},
            {"structure_group": "g2", "v4_top5": 0, "model_top5": 0},
        ]

        first = _bootstrap_delta(rows)
        second = _bootstrap_delta(rows)

        self.assertEqual(first, second)
        self.assertEqual(first["groups"], 2)
        self.assertEqual(first["mean_delta_pp"], 25.0)

    def test_summary_applies_all_fixed_public_gates(self):
        rows = []
        for fold in range(5):
            rows.append({
                "event_id": f"error-{fold}",
                "unit_id": f"unit-{fold}",
                "case_kind": "error",
                "cohort": "enron",
                "structure_group": f"group-{fold}",
                "fold": fold,
                "probe_state": "closure_pass",
                "status_before": "unsupported",
                "closure_pass": True,
                "acted": True,
                "v4_top5": 0,
                "model_top5": 1,
                "v4_mrr": 0.1,
                "model_mrr": 0.2,
                "residual_delta": 1,
                "forced_peer_top1_residual_delta": 1,
            })
        rows.append({
            "event_id": "control-1",
            "unit_id": "control-unit",
            "case_kind": "control",
            "cohort": "control",
            "structure_group": "control-group",
            "fold": 0,
            "probe_state": "no_candidate",
            "status_before": None,
            "closure_pass": False,
            "acted": False,
            "v4_top5": 0,
            "model_top5": 0,
            "v4_mrr": 0.0,
            "model_mrr": 0.0,
            "residual_delta": 0,
            "forced_peer_top1_residual_delta": 0,
        })

        with (
            mock.patch("scripts.score_peer_repair_closure.EXPECTED_EVENTS", 6),
            mock.patch("scripts.score_peer_repair_closure.EXPECTED_ERRORS", 5),
            mock.patch("scripts.score_peer_repair_closure.EXPECTED_CONTROLS", 1),
        ):
            result = summarize(rows)

        self.assertTrue(result["all_public_gates_passed"])
        self.assertTrue(all(result["public_gates"].values()))
        self.assertEqual(result["overall"]["positive_residual_action_precision"], 1.0)
        self.assertEqual(result["controls"]["workbook_action_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
