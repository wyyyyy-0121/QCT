import unittest
from types import SimpleNamespace
from unittest.mock import patch

from formulaguard.localize import LocalizationResult
from formulaguard.v4_static_allocator import (
    MODEL_VERSION,
    static_allocation_decision,
    v4_static_allocator_scores,
)


def result(index: int) -> LocalizationResult:
    return LocalizationResult(
        cell=("S", f"A{index}"),
        score=10.0 - index,
        candidate_formula=f"={index}",
        evidence={"model_version": "v4-dev-r1"},
    )


class V4StaticAllocatorTests(unittest.TestCase):
    def test_unsupported_state_allocates_two_static_slots(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        static = ["S!A7", "S!A2", "S!A6", "S!A1", "S!A3", "S!A4", "S!A5"]
        decision = static_allocation_decision(v4, static, static_state="unsupported")
        self.assertEqual(decision.v4_prefix, 3)
        self.assertEqual(decision.top5, ("S!A1", "S!A2", "S!A3", "S!A7", "S!A6"))
        self.assertEqual(decision.ranking[5:], ("S!A4", "S!A5"))
        self.assertEqual(decision.displaced_v4_cells, ("S!A4", "S!A5"))

    def test_review_state_preserves_four_v4_cells(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        static = ["S!A7", "S!A2", "S!A6", "S!A1", "S!A3", "S!A4", "S!A5"]
        decision = static_allocation_decision(v4, static, static_state="review")
        self.assertEqual(decision.v4_prefix, 4)
        self.assertEqual(decision.top5, ("S!A1", "S!A2", "S!A3", "S!A4", "S!A7"))

    def test_small_inventory_is_not_reordered(self):
        v4 = [f"S!A{i}" for i in range(1, 6)]
        decision = static_allocation_decision(
            v4, list(reversed(v4)), static_state="unsupported",
        )
        self.assertEqual(list(decision.ranking), v4)
        self.assertFalse(decision.changed)

    def test_inventory_mismatch_and_duplicates_are_rejected(self):
        with self.assertRaises(ValueError):
            static_allocation_decision(["S!A1"], ["S!A2"], static_state="review")
        with self.assertRaises(ValueError):
            static_allocation_decision(
                ["S!A1", "S!A1"], ["S!A1", "S!A2"], static_state="review",
            )

    @patch("formulaguard.v4_static_allocator.diagnose_v5_psl")
    @patch("formulaguard.v4_static_allocator.v4_scores")
    def test_runtime_uses_static_coverage_state(self, mock_v4, mock_static):
        v4 = [result(index) for index in range(1, 8)]
        static = [v4[index - 1] for index in (7, 2, 6, 1, 3, 4, 5)]
        mock_v4.return_value = v4
        mock_static.return_value = SimpleNamespace(state="unsupported", ranking=static)
        ranking = v4_static_allocator_scores(SimpleNamespace())
        self.assertEqual(
            [row.cell_label for row in ranking],
            ["S!A1", "S!A2", "S!A3", "S!A7", "S!A6", "S!A4", "S!A5"],
        )
        self.assertEqual(ranking[3].evidence["model_version"], MODEL_VERSION)
        self.assertEqual(ranking[3].evidence["selected_static_slot"], 4)
        self.assertEqual(ranking[0].evidence["v4_prefix_quota"], 3)


if __name__ == "__main__":
    unittest.main()
