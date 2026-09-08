from __future__ import annotations

import unittest

from scripts.run_v5_successor_diagnostic import (
    SUCCESSOR_POLICY_IDS,
    evaluate_successor_policies,
    policy_actions,
    summarize_policy,
)


def methods(statuses: list[tuple[str, int, str]]) -> dict[str, object]:
    ranking = [
        {
            "cell": f"Model!A{index}",
            "evidence": {
                "diagnostic_status": status,
                "candidate_support": support,
                "candidate_source": source,
            },
        }
        for index, (status, support, source) in enumerate(statuses, 1)
    ]
    return {
        "v4_r1": {
            "ranking": ranking,
            "action_cells": [row["cell"] for row in ranking[:5]],
        },
        "v4_2_review_b": {
            "action_cells": [row["cell"] for row in ranking[:5]] + ["Model!A6"],
        },
        "v5_psl_dev1": {"action_cells": ["Model!A2"]},
    }


class V5SuccessorDiagnosticTests(unittest.TestCase):
    def test_policy_actions_require_unique_fixed_evidence(self):
        payload = methods([
            ("pattern_only", 0, ""),
            ("strong_counterfactual", 2, "peer_translation,bounded_edit"),
            ("pattern_only", 0, ""),
            ("pattern_only", 0, ""),
            ("pattern_only", 0, ""),
            ("pattern_only", 0, ""),
        ])
        self.assertEqual(policy_actions(payload, "v4_top1_strong"), [])
        self.assertEqual(
            policy_actions(payload, "v4_unique_strong_top5"), ["Model!A2"],
        )
        self.assertEqual(
            policy_actions(payload, "v4_unique_peer_strong_top5"), ["Model!A2"],
        )

    def test_multiple_candidates_force_abstention(self):
        payload = methods([
            ("strong_counterfactual", 2, "peer_translation"),
            ("moderate_counterfactual", 1, "bounded_edit"),
            ("pattern_only", 0, ""),
            ("pattern_only", 0, ""),
            ("pattern_only", 0, ""),
        ])
        self.assertEqual(policy_actions(payload, "v4_unique_strong_top5"), ["Model!A1"])
        self.assertEqual(policy_actions(payload, "v4_unique_counterfactual_top5"), [])

    def test_policy_summary_separates_coverage_precision_and_efficiency(self):
        rows = [
            {"case_kind": "error", "actionable": 1, "action_hit": 1, "action_count": 1},
            {"case_kind": "error", "actionable": 1, "action_hit": 0, "action_count": 1},
            {"case_kind": "error", "actionable": 0, "action_hit": 0, "action_count": 0},
            {"case_kind": "control", "actionable": 0, "action_hit": 0, "action_count": 0},
        ]
        summary = summarize_policy(rows)
        self.assertAlmostEqual(summary["error_action_coverage"], 2 / 3)
        self.assertAlmostEqual(summary["error_source_hit_rate"], 1 / 3)
        self.assertEqual(summary["acted_error_case_precision"], 0.5)
        self.assertEqual(summary["review_efficiency_per_100_cells"], 50.0)

    def test_advancement_requires_every_gate_and_four_folds(self):
        baseline = {"review_efficiency_per_100_cells": 8.0}
        passing = {
            "error_source_hit_rate": 0.30,
            "acted_error_case_precision": 0.75,
            "control_actionable_rate": 0.15,
            "review_efficiency_per_100_cells": 8.0,
        }
        summaries = {"v4_fixed_top5": baseline}
        folds = {}
        for policy_id in SUCCESSOR_POLICY_IDS:
            summaries[policy_id] = dict(passing)
            folds[policy_id] = [
                {
                    "error_source_hit_rate": 0.20,
                    "acted_error_case_precision": 0.60,
                    "control_actionable_rate": 0.25,
                }
                for _ in range(4)
            ] + [{
                "error_source_hit_rate": 0.0,
                "acted_error_case_precision": 0.0,
                "control_actionable_rate": 0.0,
            }]
        decisions = evaluate_successor_policies(summaries, folds)
        self.assertTrue(all(
            row["eligible_for_new_architecture_preregistration"]
            for row in decisions.values()
        ))
        summaries[SUCCESSOR_POLICY_IDS[0]]["control_actionable_rate"] = 0.16
        decisions = evaluate_successor_policies(summaries, folds)
        self.assertFalse(
            decisions[SUCCESSOR_POLICY_IDS[0]][
                "eligible_for_new_architecture_preregistration"
            ]
        )


if __name__ == "__main__":
    unittest.main()
