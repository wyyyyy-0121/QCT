"""Risk-ordered allocation of V4 and peer-disagreement review slots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .localize import LocalizationResult, v4_scores
from .model_discovery import audit_workbook, validate_label_free_output
from .workbook import WorkbookModel


MODEL_VERSION = "v4-peer-evidence-allocator-exploratory-v1"
ARCHITECTURE = "evidence_dominance_v4_peer_review_budget_allocator"
REVIEW_BUDGET = 5
DEFAULT_V4_PREFIX = 4
MINIMUM_V4_PREFIX = 3
SUPPORTED_PEER_TIER = 3
WEAK_V4_STATUSES = frozenset(("pattern_only", "no_candidate", "not_intervened"))


@dataclass(frozen=True)
class PeerEvidenceAllocationDecision:
    ranking: tuple[str, ...]
    primary_peer: str | None
    selected_peers: tuple[str, ...]
    v4_prefix: int
    allocation_reason: str
    displaced_v4_cells: tuple[str, ...]
    changed: bool

    @property
    def top5(self) -> tuple[str, ...]:
        return self.ranking[:REVIEW_BUDGET]


def _unique(name: str, cells: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(cell) for cell in cells)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} contains duplicate cells")
    return result


def peer_evidence_allocation_decision(
    v4_ranking: Sequence[str],
    peer_review_cells: Sequence[str],
    peer_evidence_tiers: Mapping[str, int],
    v4_statuses: Mapping[str, str],
) -> PeerEvidenceAllocationDecision:
    """Allocate a second peer slot only when its evidence dominates V4 rank four."""

    v4 = _unique("V4 ranking", v4_ranking)
    peers = _unique("peer review set", peer_review_cells)
    if any(cell not in v4 for cell in peers):
        raise ValueError("peer review set is outside the V4 formula inventory")
    if any(cell not in peer_evidence_tiers for cell in peers):
        raise ValueError("peer review set is missing evidence tiers")
    if any(cell not in v4_statuses for cell in v4):
        raise ValueError("V4 ranking is missing diagnostic statuses")

    primary = peers[0] if peers else None
    selected: list[str] = []
    if len(v4) > REVIEW_BUDGET and primary is not None:
        if primary not in v4[:REVIEW_BUDGET]:
            selected.append(primary)
        for cell in peers[1:]:
            if (
                cell not in v4[:REVIEW_BUDGET]
                and cell not in selected
                and int(peer_evidence_tiers[cell]) == SUPPORTED_PEER_TIER
            ):
                selected.append(cell)
                if len(selected) == REVIEW_BUDGET - MINIMUM_V4_PREFIX:
                    break

    rank_four_is_weak = (
        len(v4) >= DEFAULT_V4_PREFIX
        and v4_statuses[v4[DEFAULT_V4_PREFIX - 1]] in WEAK_V4_STATUSES
    )
    if not rank_four_is_weak:
        selected = selected[:1]
    if not selected:
        return PeerEvidenceAllocationDecision(
            v4,
            primary,
            (),
            DEFAULT_V4_PREFIX,
            "preserve_v4",
            (),
            False,
        )

    prefix = REVIEW_BUDGET - len(selected)
    top5 = (*v4[:prefix], *selected)
    reordered = (*top5, *(cell for cell in v4 if cell not in top5))
    if len(reordered) != len(v4) or set(reordered) != set(v4):
        raise AssertionError("peer allocation changed the formula inventory")
    if len(selected) == 2:
        reason = "supported_second_peer_dominates_weak_v4_fourth"
    elif primary == selected[0]:
        reason = "peer_top1_outside_v4_top5"
    else:
        reason = "evidence_supported_fallback"
    displaced = tuple(cell for cell in v4[prefix:REVIEW_BUDGET] if cell not in selected)
    return PeerEvidenceAllocationDecision(
        tuple(reordered),
        primary,
        tuple(selected),
        prefix,
        reason,
        displaced,
        tuple(reordered) != v4,
    )


def v4_peer_evidence_allocator_scores(
    model: WorkbookModel,
    *,
    candidate_limit: int = 15,
) -> list[LocalizationResult]:
    """Run V4 and allocate its five review slots by discrete evidence order."""

    v4 = v4_scores(model, candidate_limit=candidate_limit)
    audit = audit_workbook(model)
    errors = validate_label_free_output(audit)
    if errors:
        raise ValueError(f"peer audit is invalid: {'; '.join(errors)}")
    v4_cells = [row.cell_label for row in v4]
    peer_review = [str(cell) for cell in audit["review_cells"]["peer"]]
    peer_records = {str(row["cell"]): row for row in audit["records"]}
    peer_tiers = {
        cell: int(record["evidence_tier"])
        for cell, record in peer_records.items()
    }
    v4_statuses = {
        row.cell_label: str(row.evidence.get("diagnostic_status", ""))
        for row in v4
    }
    decision = peer_evidence_allocation_decision(
        v4_cells,
        peer_review,
        peer_tiers,
        v4_statuses,
    )
    v4_by_cell = {row.cell_label: row for row in v4}
    v4_rank = {cell: rank for rank, cell in enumerate(v4_cells, start=1)}
    peer_rank = {
        str(cell): rank
        for rank, cell in enumerate(audit["rankings"]["peer"], start=1)
    }
    selected_slots = {
        cell: rank
        for rank, cell in enumerate(decision.ranking[:REVIEW_BUDGET], start=1)
        if cell in decision.selected_peers
    }
    total = len(decision.ranking)
    results: list[LocalizationResult] = []
    for rank, cell in enumerate(decision.ranking, start=1):
        base = v4_by_cell[cell]
        atomic = peer_records[cell]
        evidence = dict(base.evidence)
        evidence.update({
            "model_version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "selection_role": "exploratory_development_not_formal_v5",
            "review_budget": REVIEW_BUDGET,
            "v4_prefix_quota": decision.v4_prefix,
            "minimum_v4_prefix": MINIMUM_V4_PREFIX,
            "original_v4_rank": v4_rank[cell],
            "peer_disagreement_rank": peer_rank[cell],
            "peer_evidence_tier": atomic["evidence_tier"],
            "peer_status": atomic["status"],
            "selected_peer_slot": selected_slots.get(cell),
            "peer_allocation_reason": decision.allocation_reason,
            "peer_audit_sha256": audit["audit_sha256"],
            "ranking_changed": decision.changed,
        })
        results.append(LocalizationResult(
            cell=base.cell,
            score=(total - rank + 1) / total if total else 0.0,
            candidate_formula=base.candidate_formula,
            evidence=evidence,
        ))
    return results


__all__ = [
    "ARCHITECTURE",
    "DEFAULT_V4_PREFIX",
    "MINIMUM_V4_PREFIX",
    "MODEL_VERSION",
    "REVIEW_BUDGET",
    "SUPPORTED_PEER_TIER",
    "WEAK_V4_STATUSES",
    "PeerEvidenceAllocationDecision",
    "peer_evidence_allocation_decision",
    "v4_peer_evidence_allocator_scores",
]
