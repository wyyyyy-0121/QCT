"""Coverage-gated allocation of V4 and static-anchor review slots."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .localize import LocalizationResult, v4_scores
from .v5_psl import diagnose_v5_psl
from .workbook import WorkbookModel


MODEL_VERSION = "v4-static-allocator-exploratory-v1"
ARCHITECTURE = "frozen_v4_prefix_plus_coverage_gated_static_slots"
REVIEW_BUDGET = 5
DEFAULT_V4_PREFIX = 4
UNSUPPORTED_V4_PREFIX = 3


@dataclass(frozen=True)
class StaticAllocationDecision:
    ranking: tuple[str, ...]
    v4_prefix: int
    static_state: str
    static_candidates: tuple[str, ...]
    displaced_v4_cells: tuple[str, ...]
    changed: bool

    @property
    def top5(self) -> tuple[str, ...]:
        return self.ranking[:REVIEW_BUDGET]


def _ranking(name: str, cells: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(cell) for cell in cells)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} ranking contains duplicate cells")
    return result


def static_allocation_decision(
    v4_ranking: Sequence[str],
    static_ranking: Sequence[str],
    *,
    static_state: str,
) -> StaticAllocationDecision:
    """Allocate one or two static slots using only the label-free coverage state."""

    v4 = _ranking("V4", v4_ranking)
    static = _ranking("static", static_ranking)
    if set(v4) != set(static):
        raise ValueError("V4 and static rankings have different formula inventories")
    prefix_size = (
        UNSUPPORTED_V4_PREFIX
        if static_state == "unsupported"
        else DEFAULT_V4_PREFIX
    )
    if len(v4) <= REVIEW_BUDGET:
        return StaticAllocationDecision(
            v4, prefix_size, static_state, (), (), False,
        )

    prefix = v4[:prefix_size]
    static_slots = REVIEW_BUDGET - prefix_size
    candidates = tuple(
        cell for cell in static if cell not in prefix
    )[:static_slots]
    top5 = (*prefix, *candidates)
    reordered = (*top5, *(cell for cell in v4 if cell not in top5))
    if len(reordered) != len(v4) or set(reordered) != set(v4):
        raise AssertionError("static allocation changed the formula inventory")
    displaced = tuple(cell for cell in v4[prefix_size:REVIEW_BUDGET] if cell not in candidates)
    return StaticAllocationDecision(
        ranking=tuple(reordered),
        v4_prefix=prefix_size,
        static_state=static_state,
        static_candidates=candidates,
        displaced_v4_cells=displaced,
        changed=tuple(reordered) != v4,
    )


def v4_static_allocator_scores(
    model: WorkbookModel,
    *,
    candidate_limit: int = 15,
) -> list[LocalizationResult]:
    """Run V4 and allocate the fixed five-cell review budget."""

    v4 = v4_scores(model, candidate_limit=candidate_limit)
    static = diagnose_v5_psl(model, ablation="no_perturbation")
    v4_cells = [row.cell_label for row in v4]
    static_cells = [row.cell_label for row in static.ranking]
    decision = static_allocation_decision(
        v4_cells, static_cells, static_state=static.state,
    )
    v4_by_cell = {row.cell_label: row for row in v4}
    v4_rank = {cell: rank for rank, cell in enumerate(v4_cells, start=1)}
    static_rank = {cell: rank for rank, cell in enumerate(static_cells, start=1)}
    selected_slots = {
        cell: rank
        for rank, cell in enumerate(decision.ranking[:REVIEW_BUDGET], start=1)
        if cell in decision.static_candidates and cell not in v4_cells[:decision.v4_prefix]
    }
    total = len(decision.ranking)
    results: list[LocalizationResult] = []
    for rank, cell in enumerate(decision.ranking, start=1):
        base = v4_by_cell[cell]
        evidence = dict(base.evidence)
        evidence.update({
            "model_version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "selection_role": "exploratory_development_not_formal_v5",
            "review_budget": REVIEW_BUDGET,
            "static_anchor_state": static.state,
            "v4_prefix_quota": decision.v4_prefix,
            "original_v4_rank": v4_rank[cell],
            "static_anchor_rank": static_rank[cell],
            "selected_static_slot": selected_slots.get(cell),
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
    "MODEL_VERSION",
    "REVIEW_BUDGET",
    "UNSUPPORTED_V4_PREFIX",
    "StaticAllocationDecision",
    "static_allocation_decision",
    "v4_static_allocator_scores",
]
