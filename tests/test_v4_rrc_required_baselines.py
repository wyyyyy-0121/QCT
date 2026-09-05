import unittest

from scripts.run_v4_rrc_required_baselines import localization_rows, score


class V4RRCRequiredBaselineTests(unittest.TestCase):
    def test_localization_rows_preserve_complete_frozen_order(self):
        rows = [
            {
                "cell": "Sheet!A1",
                "rank": 1,
                "score": 2.0,
                "candidate_formula": "=1",
                "evidence": {"final_rank": 1},
            },
            {
                "cell": "Sheet!A2",
                "rank": 2,
                "score": 1.0,
                "candidate_formula": None,
                "evidence": {"final_rank": 2},
            },
        ]
        results = localization_rows(rows)
        self.assertEqual([row.cell_label for row in results], ["Sheet!A1", "Sheet!A2"])
        self.assertEqual(results[0].candidate_formula, "=1")

    def test_scoring_keeps_v42_native_budget_distinct_from_top5(self):
        events = [{
            "event_id": "e1",
            "unit_id": "u1",
            "structure_group": "g1",
            "cohort": "enron",
            "case_kind": "error",
            "source_formula_cells": ["S!A6"],
            "metrics": {"v4": {"rank": 6}},
        }]
        predictions = {"u1": {
            "v4_2_review_b": {
                "review_cells": [f"S!A{i}" for i in range(1, 7)],
                "review_cost": 6,
                "additional_action": 1,
            },
            "v5_psl_static_anchor": {
                "ranking": [f"S!A{i}" for i in range(6, 0, -1)],
            },
        }}
        summary, _ = score(events, predictions)
        self.assertEqual(summary["v4_top5"], 0.0)
        self.assertEqual(summary["v4_2_review_b"]["native_review_hit"], 1.0)
        self.assertEqual(summary["v4_2_review_b"]["mean_review_cost_per_event"], 6.0)
        self.assertEqual(summary["v5_psl_static_anchor"]["top5"], 1.0)


if __name__ == "__main__":
    unittest.main()
