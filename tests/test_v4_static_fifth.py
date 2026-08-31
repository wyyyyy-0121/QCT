import unittest
from types import SimpleNamespace
from unittest.mock import patch

from formulaguard.localize import LocalizationResult
from formulaguard.v4_static_fifth import (
    MODEL_VERSION,
    static_fifth_decision,
    v4_static_fifth_scores,
)


def result(index: int) -> LocalizationResult:
    return LocalizationResult(
        cell=("S", f"A{index}"),
        score=10.0 - index,
        candidate_formula=f"={index}",
        evidence={"model_version": "v4-dev-r1"},
    )


class V4StaticFifthTests(unittest.TestCase):
    def test_decision_preserves_top4_and_complete_v4_tail(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        static = ["S!A7", "S!A2", "S!A6", "S!A1", "S!A3", "S!A4", "S!A5"]
        decision = static_fifth_decision(v4, static)
        self.assertEqual(decision.ranking[:4], tuple(v4[:4]))
        self.assertEqual(decision.ranking[4], "S!A7")
        self.assertEqual(decision.ranking[5:], ("S!A5", "S!A6"))
        self.assertEqual(decision.displaced_v4_fifth, "S!A5")
        self.assertTrue(decision.changed)

    def test_decision_is_unchanged_when_static_selects_v4_fifth(self):
        v4 = [f"S!A{i}" for i in range(1, 7)]
        static = ["S!A2", "S!A5", "S!A1", "S!A3", "S!A4", "S!A6"]
        decision = static_fifth_decision(v4, static)
        self.assertEqual(list(decision.ranking), v4)
        self.assertFalse(decision.changed)
        self.assertIsNone(decision.displaced_v4_fifth)

    def test_decision_rejects_inventory_mismatch_and_duplicates(self):
        with self.assertRaises(ValueError):
            static_fifth_decision(["S!A1"], ["S!A2"])
        with self.assertRaises(ValueError):
            static_fifth_decision(["S!A1", "S!A1"], ["S!A1", "S!A2"])

    @patch("formulaguard.v4_static_fifth.diagnose_v5_psl")
    @patch("formulaguard.v4_static_fifth.v4_scores")
    def test_runtime_scores_expose_complete_exploratory_ranking(self, mock_v4, mock_static):
        v4 = [result(index) for index in range(1, 7)]
        static = [v4[index - 1] for index in (6, 2, 1, 3, 4, 5)]
        mock_v4.return_value = v4
        mock_static.return_value = SimpleNamespace(ranking=static)
        ranking = v4_static_fifth_scores(SimpleNamespace())
        self.assertEqual([row.cell_label for row in ranking], [
            "S!A1", "S!A2", "S!A3", "S!A4", "S!A6", "S!A5",
        ])
        self.assertEqual(ranking[4].evidence["model_version"], MODEL_VERSION)
        self.assertTrue(ranking[4].evidence["selected_static_fifth"])
        self.assertEqual(ranking[4].candidate_formula, "=6")
        self.assertGreater(ranking[0].score, ranking[-1].score)


if __name__ == "__main__":
    unittest.main()
