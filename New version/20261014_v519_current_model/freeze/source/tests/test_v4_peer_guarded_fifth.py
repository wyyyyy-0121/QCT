import unittest
from types import SimpleNamespace
from unittest.mock import patch

from formulaguard.localize import LocalizationResult
from formulaguard.v4_peer_guarded_fifth import (
    MODEL_VERSION,
    peer_guarded_fifth_decision,
    v4_peer_guarded_fifth_scores,
)


def result(index: int) -> LocalizationResult:
    return LocalizationResult(
        cell=("S", f"A{index}"),
        score=10.0 - index,
        candidate_formula=f"={index}",
        evidence={"model_version": "v4-dev-r1"},
    )


def audit(peer: list[str], tiers: dict[str, int]):
    return {
        "review_cells": {"peer": peer},
        "rankings": {"peer": peer},
        "records": [
            {
                "cell": cell,
                "evidence_tier": tiers[cell],
                "status": "evidence_supported" if tiers[cell] == 3 else "unsupported",
                "peer_disagreement": 0.5,
                "alternative_support": 2,
                "independent_support": 2,
            }
            for cell in peer
        ],
        "audit_sha256": "a" * 64,
    }


class V4PeerGuardedFifthTests(unittest.TestCase):
    def test_primary_outside_v4_top5_is_selected_without_fallback_gate(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        decision = peer_guarded_fifth_decision(
            v4,
            ["S!A7", "S!A6"],
            {"S!A7": 0, "S!A6": 3},
        )
        self.assertEqual(decision.top5, (*v4[:4], "S!A7"))
        self.assertEqual(decision.selection_reason, "peer_top1_outside_v4_top5")

    def test_supported_fallback_is_used_when_primary_is_already_reviewed(self):
        v4 = [f"S!A{i}" for i in range(1, 9)]
        decision = peer_guarded_fifth_decision(
            v4,
            ["S!A2", "S!A6", "S!A7", "S!A8"],
            {"S!A2": 3, "S!A6": 1, "S!A7": 3, "S!A8": 3},
        )
        self.assertEqual(decision.selected_peer, "S!A7")
        self.assertEqual(decision.top5, (*v4[:4], "S!A7"))
        self.assertEqual(decision.selection_reason, "evidence_supported_fallback")

    def test_weak_fallback_preserves_v4(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        decision = peer_guarded_fifth_decision(
            v4,
            ["S!A2", "S!A6", "S!A7"],
            {"S!A2": 3, "S!A6": 1, "S!A7": 0},
        )
        self.assertEqual(decision.ranking, tuple(v4))
        self.assertFalse(decision.changed)

    def test_invalid_inventory_duplicates_and_tiers_are_rejected(self):
        with self.assertRaises(ValueError):
            peer_guarded_fifth_decision(["S!A1"], ["S!A2"], {"S!A2": 3})
        with self.assertRaises(ValueError):
            peer_guarded_fifth_decision(
                ["S!A1", "S!A2"], ["S!A2", "S!A2"], {"S!A2": 3},
            )
        with self.assertRaises(ValueError):
            peer_guarded_fifth_decision(["S!A1"], ["S!A1"], {})

    @patch("formulaguard.v4_peer_guarded_fifth.validate_label_free_output", return_value=[])
    @patch("formulaguard.v4_peer_guarded_fifth.audit_workbook")
    @patch("formulaguard.v4_peer_guarded_fifth.v4_scores")
    def test_runtime_exposes_guard_and_selection_reason(
        self,
        mock_v4,
        mock_audit,
        _mock_validate,
    ):
        v4 = [result(index) for index in range(1, 8)]
        peer = ["S!A2", "S!A6", "S!A7", "S!A1", "S!A3", "S!A4", "S!A5"]
        tiers = {cell: (3 if cell == "S!A7" else 1) for cell in peer}
        mock_v4.return_value = v4
        mock_audit.return_value = audit(peer, tiers)
        ranking = v4_peer_guarded_fifth_scores(SimpleNamespace())
        self.assertEqual(ranking[4].cell_label, "S!A7")
        self.assertEqual(ranking[4].evidence["model_version"], MODEL_VERSION)
        self.assertTrue(ranking[4].evidence["selected_guarded_peer_fifth"])
        self.assertEqual(
            ranking[4].evidence["guarded_peer_selection_reason"],
            "evidence_supported_fallback",
        )


if __name__ == "__main__":
    unittest.main()
