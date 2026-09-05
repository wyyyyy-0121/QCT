"""Exploratory five-slot ranker combining frozen V4 with the static anchor.

The model preserves V4 positions one through four and its complete tail.  The
highest static-anchor cell outside that prefix occupies position five.  It has
no learned weights, thresholds, corpus features, or selective action state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .localize import LocalizationResult, v4_scores
from .v5_psl import diagnose_v5_psl
from .workbook import WorkbookModel


MODEL_VERSION = "v4-static-fifth-exploratory-v1"
ARCHITECTURE = "frozen_v4_top4_plus_static_anchor_fifth"
V4_PREFIX = 4
REVIEW_BUDGET = 5


@dataclass(frozen=True)
class StaticFifthDecision:
    ranking: tuple[str, ...]
    static_candidate: str | None
    displaced_v4_fifth: str | None
    changed: bool

    @property
    def top5(self) -> tuple[str, ...]:
        return self.ranking[:REVIEW_BUDGET]


def _validate_ranking(name: str, ranking: Sequence[str]) -> tuple[str, ...]:
    result = tuple(str(cell) for cell in ranking)
    if len(set(result)) != len(result):
        raise ValueError(f"{name} ranking contains duplicate cells")
    return result


def static_fifth_decision(
    v4_ranking: Sequence[str],
    static_ranking: Sequence[str],
) -> StaticFifthDecision:
    """Return the complete deterministic four-plus-one ranking."""

    v4 = _validate_ranking("V4", v4_ranking)
    static = _validate_ranking("static", static_ranking)
    if set(v4) != set(static):
        raise ValueError("V4 and static rankings have different formula inventories")
    if len(v4) <= V4_PREFIX:
        return StaticFifthDecision(v4, None, None, False)

    prefix = v4[:V4_PREFIX]
    candidate = next(cell for cell in static if cell not in prefix)
    reordered = (*prefix, candidate, *(cell for cell in v4[V4_PREFIX:] if cell != candidate))
    if len(reordered) != len(v4) or set(reordered) != set(v4):
        raise AssertionError("static-fifth reranking changed the formula inventory")
    changed = candidate != v4[V4_PREFIX]
    return StaticFifthDecision(
        ranking=tuple(reordered),
        static_candidate=candidate,
        displaced_v4_fifth=v4[V4_PREFIX] if changed else None,
        changed=changed,
    )


def v4_static_fifth_scores(
    model: WorkbookModel,
    *,
    candidate_limit: int = 15,
) -> list[LocalizationResult]:
    """Run V4 and the label-free static anchor, then apply the fixed slot rule."""

    v4 = v4_scores(model, candidate_limit=candidate_limit)
    static = list(diagnose_v5_psl(model, ablation="no_perturbation").ranking)
    decision = static_fifth_decision(
        [row.cell_label for row in v4],
        [row.cell_label for row in static],
    )
    v4_by_cell = {row.cell_label: row for row in v4}
    v4_rank = {row.cell_label: rank for rank, row in enumerate(v4, start=1)}
    static_rank = {row.cell_label: rank for rank, row in enumerate(static, start=1)}
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
            "immutable_v4_prefix": V4_PREFIX,
            "original_v4_rank": v4_rank[cell],
            "static_anchor_rank": static_rank[cell],
            "selected_static_fifth": cell == decision.static_candidate and rank == REVIEW_BUDGET,
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
    "V4_PREFIX",
    "StaticFifthDecision",
    "static_fifth_decision",
    "v4_static_fifth_scores",
]
