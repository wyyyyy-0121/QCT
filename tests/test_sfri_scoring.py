import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/score_sfri_predictions.py"
SPEC = importlib.util.spec_from_file_location("score_sfri_predictions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
scorer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorer)


class SfriScoringTests(unittest.TestCase):
    def test_adapter_preserves_top_four_and_moves_candidate_to_fifth(self):
        ranking = tuple(f"Sheet1!A{row}" for row in range(1, 9))

        adapted = scorer.adapt_v4_ranking(ranking, "Sheet1!A8")

        self.assertEqual(adapted[:5], (*ranking[:4], "Sheet1!A8"))
        self.assertEqual(adapted[5:], ranking[4:7])
        self.assertEqual(set(adapted), set(ranking))

    def test_adapter_is_identity_for_existing_top_five(self):
        ranking = tuple(f"Sheet1!A{row}" for row in range(1, 9))

        self.assertEqual(
            scorer.adapt_v4_ranking(ranking, "Sheet1!A3"),
            ranking,
        )
        self.assertEqual(scorer.adapt_v4_ranking(ranking, None), ranking)

    def test_ranking_metric_uses_best_labeled_source(self):
        metric = scorer.ranking_metric(
            ("Sheet1!A1", "Sheet1!A2", "Sheet1!A3"),
            ("Sheet1!A3", "Sheet1!A2"),
        )

        self.assertEqual(metric["rank"], 2)
        self.assertEqual(metric["top1"], 0)
        self.assertEqual(metric["top5"], 1)
        self.assertEqual(metric["mrr"], 0.5)

    def test_two_rescue_gate_is_not_relaxed_after_scoring(self):
        gates = scorer.evaluate_gates(
            candidate_workbooks=8,
            candidate_structure_clusters=2,
            certificate_precision=1.0,
            false_control_workbooks=0,
            formula_accuracy=1.0,
            net_top5_rescues=1,
            newly_hit_structure_clusters=1,
            top5_losses=0,
            cohort_top5_losses={"enron": 0, "public:test": 0},
            enron_top5_delta=0.0,
            enron_mrr_delta=0.0,
            public_control_action_rate=0.0,
            integrity_passed=True,
        )

        self.assertFalse(gates["g4_net_top5_rescues"])
        self.assertFalse(gates["all_gates_passed"])
        self.assertEqual(gates["failed_gates"], ["g4_net_top5_rescues"])

    def test_formula_gate_requires_evaluable_correct_formulas(self):
        gates = scorer.evaluate_gates(
            candidate_workbooks=8,
            candidate_structure_clusters=2,
            certificate_precision=1.0,
            false_control_workbooks=0,
            formula_accuracy=None,
            net_top5_rescues=2,
            newly_hit_structure_clusters=1,
            top5_losses=0,
            cohort_top5_losses={"enron": 0},
            enron_top5_delta=0.0,
            enron_mrr_delta=0.0,
            public_control_action_rate=0.0,
            integrity_passed=True,
        )

        self.assertFalse(gates["g3_candidate_formula_accuracy"])
        self.assertFalse(gates["all_gates_passed"])


if __name__ == "__main__":
    unittest.main()
