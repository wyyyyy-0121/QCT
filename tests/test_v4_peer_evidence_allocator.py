import unittest
from types import SimpleNamespace
from unittest.mock import patch

from formulaguard.localize import LocalizationResult
from formulaguard.v4_peer_evidence_allocator import (
    MODEL_VERSION,
    peer_evidence_allocation_decision,
    v4_peer_evidence_allocator_scores,
)


def result(index: int, status: str = "pattern_only") -> LocalizationResult:
    return LocalizationResult(
        cell=("S", f"A{index}"),
        score=10.0 - index,
        candidate_formula=f"={index}",
        evidence={"model_version": "v4-dev-r1", "diagnostic_status": status},
    )


def tiers(cells: list[str], supported: set[str]) -> dict[str, int]:
    return {cell: (3 if cell in supported else 0) for cell in cells}


def statuses(cells: list[str], rank_four: str = "pattern_only") -> dict[str, str]:
    output = {cell: "pattern_only" for cell in cells}
    output[cells[3]] = rank_four
    return output


def audit(peer: list[str], evidence_tiers: dict[str, int]):
    return {
        "review_cells": {"peer": peer},
        "rankings": {"peer": peer},
        "records": [
            {
                "cell": cell,
                "evidence_tier": evidence_tiers[cell],
                "status": (
                    "evidence_supported" if evidence_tiers[cell] == 3 else "unsupported"
                ),
            }
            for cell in peer
        ],
        "audit_sha256": "a" * 64,
    }


class V4PeerEvidenceAllocatorTests(unittest.TestCase):
    def test_supported_second_peer_replaces_only_weak_v4_fourth_and_fifth(self):
        v4 = [f"S!A{i}" for i in range(1, 9)]
        peer = ["S!A8", "S!A7", "S!A2"]
        decision = peer_evidence_allocation_decision(
            v4,
            peer,
            tiers(peer, {"S!A7"}),
            statuses(v4),
        )
        self.assertEqual(decision.v4_prefix, 3)
        self.assertEqual(decision.top5, (*v4[:3], "S!A8", "S!A7"))
        self.assertEqual(decision.displaced_v4_cells, ("S!A4", "S!A5"))
        self.assertEqual(
            decision.allocation_reason,
            "supported_second_peer_dominates_weak_v4_fourth",
        )

    def test_nonweak_v4_fourth_blocks_second_peer(self):
        v4 = [f"S!A{i}" for i in range(1, 9)]
        peer = ["S!A8", "S!A7"]
        decision = peer_evidence_allocation_decision(
            v4,
            peer,
            tiers(peer, {"S!A7"}),
            statuses(v4, rank_four="moderate_counterfactual"),
        )
        self.assertEqual(decision.v4_prefix, 4)
        self.assertEqual(decision.top5, (*v4[:4], "S!A8"))

    def test_primary_inside_v4_uses_up_to_two_supported_fallbacks(self):
        v4 = [f"S!A{i}" for i in range(1, 9)]
        peer = ["S!A2", "S!A6", "S!A7", "S!A8"]
        decision = peer_evidence_allocation_decision(
            v4,
            peer,
            tiers(peer, {"S!A6", "S!A7", "S!A8"}),
            statuses(v4),
        )
        self.assertEqual(decision.selected_peers, ("S!A6", "S!A7"))
        self.assertEqual(decision.top5, (*v4[:3], "S!A6", "S!A7"))

    def test_weak_fallback_preserves_v4(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        peer = ["S!A2", "S!A6", "S!A7"]
        decision = peer_evidence_allocation_decision(
            v4,
            peer,
            tiers(peer, set()),
            statuses(v4),
        )
        self.assertEqual(decision.ranking, tuple(v4))
        self.assertFalse(decision.changed)

    def test_invalid_inputs_are_rejected(self):
        with self.assertRaises(ValueError):
            peer_evidence_allocation_decision(
                ["S!A1"], ["S!A2"], {"S!A2": 3}, {"S!A1": "pattern_only"},
            )
        with self.assertRaises(ValueError):
            peer_evidence_allocation_decision(
                ["S!A1", "S!A2"],
                ["S!A2", "S!A2"],
                {"S!A2": 3},
                {"S!A1": "pattern_only", "S!A2": "pattern_only"},
            )
        with self.assertRaises(ValueError):
            peer_evidence_allocation_decision(
                ["S!A1"], ["S!A1"], {}, {"S!A1": "pattern_only"},
            )

    @patch("formulaguard.v4_peer_evidence_allocator.validate_label_free_output", return_value=[])
    @patch("formulaguard.v4_peer_evidence_allocator.audit_workbook")
    @patch("formulaguard.v4_peer_evidence_allocator.v4_scores")
    def test_runtime_exposes_allocation_evidence(
        self,
        mock_v4,
        mock_audit,
        _mock_validate,
    ):
        v4 = [result(index) for index in range(1, 9)]
        peer = ["S!A8", "S!A7", "S!A2", "S!A1", "S!A3", "S!A4", "S!A5", "S!A6"]
        evidence_tiers = tiers(peer, {"S!A7"})
        mock_v4.return_value = v4
        mock_audit.return_value = audit(peer, evidence_tiers)
        ranking = v4_peer_evidence_allocator_scores(SimpleNamespace())
        self.assertEqual([row.cell_label for row in ranking[:5]], [
            "S!A1", "S!A2", "S!A3", "S!A8", "S!A7",
        ])
        self.assertEqual(ranking[3].evidence["model_version"], MODEL_VERSION)
        self.assertEqual(ranking[3].evidence["selected_peer_slot"], 4)
        self.assertEqual(ranking[4].evidence["selected_peer_slot"], 5)
        self.assertEqual(ranking[0].evidence["v4_prefix_quota"], 3)


if __name__ == "__main__":
    unittest.main()
