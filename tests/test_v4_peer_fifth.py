import unittest
from types import SimpleNamespace
from unittest.mock import patch

from formulaguard.localize import LocalizationResult
from formulaguard.v4_peer_fifth import (
    MODEL_VERSION,
    peer_fifth_decision,
    v4_peer_fifth_scores,
)


def result(index: int) -> LocalizationResult:
    return LocalizationResult(
        cell=("S", f"A{index}"),
        score=10.0 - index,
        candidate_formula=f"={index}",
        evidence={"model_version": "v4-dev-r1"},
    )


def audit() -> dict[str, object]:
    cells = [f"S!A{i}" for i in range(1, 8)]
    peer = ["S!A7", "S!A2", "S!A6", "S!A1", "S!A3", "S!A4", "S!A5"]
    return {
        "audit_sha256": "a" * 64,
        "rankings": {"peer": peer},
        "review_cells": {"peer": peer[:5]},
        "records": [
            {
                "cell": cell,
                "peer_disagreement": 0.5,
                "alternative_support": 2,
                "independent_support": 1,
            }
            for cell in cells
        ],
    }


class V4PeerFifthTests(unittest.TestCase):
    def test_first_peer_review_cell_replaces_only_v4_fifth(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        decision = peer_fifth_decision(v4, ["S!A7", "S!A6"])
        self.assertEqual(decision.top5, ("S!A1", "S!A2", "S!A3", "S!A4", "S!A7"))
        self.assertEqual(decision.ranking[5:], ("S!A5", "S!A6"))
        self.assertEqual(decision.displaced_v4_fifth, "S!A5")
        self.assertTrue(decision.changed)

    def test_first_peer_inside_v4_top5_does_not_fall_through(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        decision = peer_fifth_decision(v4, ["S!A2", "S!A7"])
        self.assertEqual(list(decision.ranking), v4)
        self.assertEqual(decision.proposed_peer, "S!A2")
        self.assertIsNone(decision.selected_peer)

    def test_short_inventory_and_empty_peer_set_are_unchanged(self):
        v4 = [f"S!A{i}" for i in range(1, 6)]
        self.assertFalse(peer_fifth_decision(v4, ["S!A5"]).changed)
        self.assertFalse(peer_fifth_decision(v4, []).changed)

    def test_invalid_peer_inventory_is_rejected(self):
        with self.assertRaises(ValueError):
            peer_fifth_decision(["S!A1"], ["S!A2"])
        with self.assertRaises(ValueError):
            peer_fifth_decision(["S!A1", "S!A2"], ["S!A2", "S!A2"])

    @patch("formulaguard.v4_peer_fifth.validate_label_free_output", return_value=[])
    @patch("formulaguard.v4_peer_fifth.audit_workbook")
    @patch("formulaguard.v4_peer_fifth.v4_scores")
    def test_runtime_exposes_peer_evidence(self, mock_v4, mock_audit, _mock_validate):
        mock_v4.return_value = [result(index) for index in range(1, 8)]
        mock_audit.return_value = audit()
        ranking = v4_peer_fifth_scores(SimpleNamespace())
        self.assertEqual(
            [row.cell_label for row in ranking],
            ["S!A1", "S!A2", "S!A3", "S!A4", "S!A7", "S!A5", "S!A6"],
        )
        self.assertEqual(ranking[4].evidence["model_version"], MODEL_VERSION)
        self.assertTrue(ranking[4].evidence["selected_peer_fifth"])
        self.assertEqual(ranking[4].evidence["peer_audit_sha256"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
