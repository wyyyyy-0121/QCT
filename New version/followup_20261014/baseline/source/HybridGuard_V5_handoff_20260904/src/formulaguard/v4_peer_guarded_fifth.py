"""Fixed-budget V4 ranker with a guarded peer-disagreement fifth cell."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .localize import LocalizationResult, v4_scores
from .model_discovery import audit_workbook, validate_label_free_output
from .workbook import WorkbookModel


MODEL_VERSION = "v4-peer-guarded-fifth-exploratory-v1"
ARCHITECTURE = "frozen_v4_top4_plus_guarded_peer_fifth"
REVIEW_BUDGET = 5
V4_PREFIX = 4
SUPPORTED_TIER = 3


@dataclass(frozen=True)
class PeerGuardedFifthDecision:
    ranking: tuple[str, ...]
    primary_peer: str | None
    selected_peer: str | None
    selection_reason: str
    displaced_v4_fifth: str | None
    changed: bool

    @property
    def top5(self) -> tuple[str, ...]:
        return self.ranking[:REVIEW_BUDGET]


def _unique(name: str, cells: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(cell) for cell in cells)
    if len(result) != len(set(result)):
        raise ValueError(f"{name} contains duplicate cells")
    return result


def peer_guarded_fifth_decision(
    v4_ranking: Sequence[str],
    peer_review_cells: Sequence[str],
    evidence_tiers: Mapping[str, int],
) -> PeerGuardedFifthDecision:
    """Use peer Top-1, or a supported fallback when Top-1 is already reviewed."""

    v4 = _unique("V4 ranking", v4_ranking)
    peers = _unique("peer review set", peer_review_cells)
    if any(cell not in v4 for cell in peers):
        raise ValueError("peer review set is outside the V4 formula inventory")
    if any(cell not in evidence_tiers for cell in peers):
        raise ValueError("peer review set is missing evidence tiers")

    primary = peers[0] if peers else None
    selected: str | None = None
    reason = "preserve_v4"
    if len(v4) > REVIEW_BUDGET and primary is not None:
        if primary not in v4[:REVIEW_BUDGET]:
            selected = primary
            reason = "peer_top1_outside_v4_top5"
        else:
            selected = next(
                (
                    cell
                    for cell in peers[1:]
                    if cell not in v4[:REVIEW_BUDGET]
                    and int(evidence_tiers[cell]) == SUPPORTED_TIER
                ),
                None,
            )
            if selected is not None:
                reason = "evidence_supported_fallback"

    if selected is None:
        return PeerGuardedFifthDecision(
            v4, primary, None, reason, None, False,
        )
    reordered = list(v4)
    reordered.remove(selected)
    reordered.insert(V4_PREFIX, selected)
    if len(reordered) != len(v4) or set(reordered) != set(v4):
        raise AssertionError("guarded peer reranking changed the formula inventory")
    return PeerGuardedFifthDecision(
        tuple(reordered), primary, selected, reason, v4[V4_PREFIX], True,
    )


def v4_peer_guarded_fifth_scores(
    model: WorkbookModel,
    *,
    candidate_limit: int = 15,
) -> list[LocalizationResult]:
    """Run frozen V4 and the deterministic label-free guarded peer audit."""

    v4 = v4_scores(model, candidate_limit=candidate_limit)
    audit = audit_workbook(model)
    errors = validate_label_free_output(audit)
    if errors:
        raise ValueError(f"peer audit is invalid: {'; '.join(errors)}")
    v4_cells = [row.cell_label for row in v4]
    peer_review_cells = [str(cell) for cell in audit["review_cells"]["peer"]]
    peer_records = {str(row["cell"]): row for row in audit["records"]}
    evidence_tiers = {
        cell: int(record["evidence_tier"])
        for cell, record in peer_records.items()
    }
    decision = peer_guarded_fifth_decision(
        v4_cells,
        peer_review_cells,
        evidence_tiers,
    )
    v4_by_cell = {row.cell_label: row for row in v4}
    v4_rank = {cell: rank for rank, cell in enumerate(v4_cells, start=1)}
    peer_rank = {
        str(cell): rank
        for rank, cell in enumerate(audit["rankings"]["peer"], start=1)
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
            "immutable_v4_prefix": V4_PREFIX,
            "original_v4_rank": v4_rank[cell],
            "peer_disagreement_rank": peer_rank[cell],
            "peer_evidence_tier": atomic["evidence_tier"],
            "peer_status": atomic["status"],
            "peer_disagreement": atomic["peer_disagreement"],
            "peer_alternative_support": atomic["alternative_support"],
            "peer_independent_support": atomic["independent_support"],
            "selected_guarded_peer_fifth": (
                cell == decision.selected_peer and rank == REVIEW_BUDGET
            ),
            "guarded_peer_selection_reason": decision.selection_reason,
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
    "MODEL_VERSION",
    "REVIEW_BUDGET",
    "SUPPORTED_TIER",
    "V4_PREFIX",
    "PeerGuardedFifthDecision",
    "peer_guarded_fifth_decision",
    "v4_peer_guarded_fifth_scores",
]
