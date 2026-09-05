import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/score_static_fifth_public_revisions.py"
SPEC = importlib.util.spec_from_file_location(
    "score_static_fifth_public_revisions", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
scorer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(scorer)


class StaticFifthPublicRevisionScoringTests(unittest.TestCase):
    def test_ranking_metric_uses_best_changed_formula(self):
        ranking = [
            {"rank": rank, "cell": f"Sheet1!A{rank}"}
            for rank in range(1, 9)
        ]

        metric = scorer.ranking_metric(
            ranking,
            ("Sheet1!A7", "Sheet1!A3"),
        )

        self.assertEqual(metric["rank"], 3)
        self.assertEqual(metric["top1"], 0)
        self.assertEqual(metric["top5"], 1)
        self.assertEqual(metric["mrr"], 1 / 3)
        self.assertEqual(metric["formula_cells_top5"], 1)

    def test_all_frozen_gates_are_required(self):
        gates = scorer.evaluate_gates(
            integrity_passed=True,
            revision_events=4,
            formula_changes=8,
            inventory_parity=True,
            net_top5_rescues=1,
            candidate_top5=0.5,
            v4_top5=0.25,
            top5_losses=0,
            per_revision_regressions=0,
            candidate_mrr=0.3,
            v4_mrr=0.2,
            protected_data_inputs=(),
        )

        self.assertTrue(gates["all_gates_passed"])
        self.assertEqual(gates["failed_gates"], [])

        failed = scorer.evaluate_gates(
            integrity_passed=True,
            revision_events=4,
            formula_changes=8,
            inventory_parity=True,
            net_top5_rescues=0,
            candidate_top5=0.25,
            v4_top5=0.25,
            top5_losses=0,
            per_revision_regressions=0,
            candidate_mrr=0.2,
            v4_mrr=0.2,
            protected_data_inputs=(),
        )
        self.assertFalse(failed["g4_strict_top5_improvement"])
        self.assertFalse(failed["all_gates_passed"])

    def test_any_per_revision_rank_regression_fails(self):
        gates = scorer.evaluate_gates(
            integrity_passed=True,
            revision_events=4,
            formula_changes=8,
            inventory_parity=True,
            net_top5_rescues=1,
            candidate_top5=0.5,
            v4_top5=0.25,
            top5_losses=0,
            per_revision_regressions=1,
            candidate_mrr=0.3,
            v4_mrr=0.2,
            protected_data_inputs=(),
        )

        self.assertFalse(gates["g5_zero_losses_and_regressions"])
        self.assertFalse(gates["all_gates_passed"])


if __name__ == "__main__":
    unittest.main()
