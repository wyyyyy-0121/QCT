"""FormulaGuard V5.2 non-interference rescue channel.

V5.2 never changes the frozen V4 ranking.  It may expose one additional
formula for human review when pattern and counterfactual evidence agree.
The three variants are deliberately discrete development hypotheses rather
than continuously tuned score combinations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from .formula import FormulaSyntaxError, parse_formula
from .localize import LocalizationResult, generate_candidates, v4_scores
from .workbook import WorkbookModel


V52_VARIANTS = ("a", "b", "c")
V52_PATTERN_FRACTION = 0.02
V52_PATTERN_MIN_ELITE = 3
V52_PATTERN_MAX_ELITE = 10
V52_RESCUE_BELOW_RANK = 5
V52_UNIQUENESS_IRG_MARGIN = 1.0
V52_UNIQUENESS_DELTA_MARGIN = 0.02
V52_MIN_DISTINCT_REPAIR_SOURCES = 2
V52_MIN_REFERENCE_QUALITY = 0.80


@dataclass(frozen=True)
class RescueEvidence:
    """Evidence for one eligible cell before the rescue decision."""

    result: LocalizationResult
    v4_rank: int
    formula_rank: int
    irg: float
    delta: float
    repair_source_count: int
    repair_sources: tuple[str, ...]
    reference_quality: float
    repair_parseable: bool


@dataclass(frozen=True)
class V52Decision:
    """One workbook-level V5.2 decision with an immutable V4 core."""

    variant: str
    core_ranking: tuple[LocalizationResult, ...]
    rescue: RescueEvidence | None
    eligible: tuple[RescueEvidence, ...]
    status: str
    reason: str
    pattern_elite_limit: int

    @property
    def core_top5(self) -> tuple[LocalizationResult, ...]:
        return self.core_ranking[:5]

    @property
    def review_set(self) -> tuple[LocalizationResult, ...]:
        if self.rescue is None:
            return self.core_top5
        return self.core_top5 + (self.rescue.result,)


def v52_default_parameters(variant: str) -> dict[str, float | int | str]:
    variant = _normalize_variant(variant)
    return {
        "model_version": f"v5.2-{variant}",
        "base_model": "v4-dev-r1",
        "fusion": "non_interference_dual_channel_rescue",
        "core_policy": "exact_frozen_v4_order",
        "review_policy": "v4_top5_plus_at_most_one_external_rescue",
        "pattern_fraction": V52_PATTERN_FRACTION,
        "pattern_min_elite": V52_PATTERN_MIN_ELITE,
        "pattern_max_elite": V52_PATTERN_MAX_ELITE,
        "rescue_below_v4_rank": V52_RESCUE_BELOW_RANK,
        "uniqueness_irg_margin": V52_UNIQUENESS_IRG_MARGIN,
        "uniqueness_delta_margin": V52_UNIQUENESS_DELTA_MARGIN,
        "minimum_distinct_repair_sources": (
            V52_MIN_DISTINCT_REPAIR_SOURCES if variant == "c" else 0
        ),
        "minimum_reference_quality": (
            V52_MIN_REFERENCE_QUALITY if variant == "c" else 0.0
        ),
        "label_inputs": "forbidden",
    }


def _normalize_variant(variant: str) -> str:
    normalized = variant.strip().lower().removeprefix("v5.2-")
    if normalized not in V52_VARIANTS:
        raise ValueError(f"Unknown V5.2 variant: {variant}")
    return normalized


def _pattern_elite_limit(formula_count: int) -> int:
    return min(
        V52_PATTERN_MAX_ELITE,
        max(V52_PATTERN_MIN_ELITE, math.ceil(V52_PATTERN_FRACTION * formula_count)),
    )


def _candidate_metadata(
    model: WorkbookModel,
    result: LocalizationResult,
    candidate_limit: int,
) -> tuple[int, tuple[str, ...], float, bool]:
    formula = result.candidate_formula
    if not formula:
        return 0, (), 0.0, False
    try:
        parse_formula(formula)
        parseable = True
    except FormulaSyntaxError:
        parseable = False
    for candidate in generate_candidates(model, result.cell, candidate_limit):
        if candidate.formula == formula:
            return (
                len(candidate.sources),
                candidate.sources,
                float(candidate.reference_quality),
                parseable,
            )
    sources = tuple(
        sorted(filter(None, str(result.evidence.get("candidate_source", "")).split(",")))
    )
    return len(sources), sources, 0.0, parseable


def _eligible_candidates(
    model: WorkbookModel,
    v4_results: Sequence[LocalizationResult],
    candidate_limit: int,
) -> tuple[list[RescueEvidence], int]:
    elite_limit = _pattern_elite_limit(len(v4_results))
    eligible: list[RescueEvidence] = []
    for fallback_rank, result in enumerate(v4_results, 1):
        evidence = result.evidence
        v4_rank = int(evidence.get("final_rank", fallback_rank))
        formula_rank = int(evidence.get("formula_rank", len(v4_results) + 1))
        if (
            v4_rank <= V52_RESCUE_BELOW_RANK
            or formula_rank > elite_limit
            or evidence.get("diagnostic_status") != "strong_counterfactual"
            or not result.candidate_formula
        ):
            continue
        source_count, sources, reference_quality, parseable = _candidate_metadata(
            model, result, candidate_limit
        )
        eligible.append(RescueEvidence(
            result=result,
            v4_rank=v4_rank,
            formula_rank=formula_rank,
            irg=float(evidence.get("intervention_responsibility_gain", 0.0)),
            delta=float(evidence.get("candidate_delta", 0.0)),
            repair_source_count=source_count,
            repair_sources=sources,
            reference_quality=reference_quality,
            repair_parseable=parseable,
        ))
    eligible.sort(key=lambda item: (
        item.formula_rank,
        -item.irg,
        -item.delta,
        item.v4_rank,
        item.result.cell,
    ))
    return eligible, elite_limit


def _exact_primary_tie(first: RescueEvidence, second: RescueEvidence) -> bool:
    return (
        first.formula_rank == second.formula_rank
        and math.isclose(first.irg, second.irg, rel_tol=0.0, abs_tol=1e-12)
        and math.isclose(first.delta, second.delta, rel_tol=0.0, abs_tol=1e-12)
    )


def _dominates(first: RescueEvidence, second: RescueEvidence) -> bool:
    if first.formula_rank < second.formula_rank:
        return True
    if first.formula_rank > second.formula_rank:
        return False
    return (
        first.irg - second.irg >= V52_UNIQUENESS_IRG_MARGIN
        and first.delta - second.delta >= V52_UNIQUENESS_DELTA_MARGIN
    )


def v52_from_v4(
    model: WorkbookModel,
    v4_results: Sequence[LocalizationResult],
    *,
    variant: str,
    candidate_limit: int = 15,
) -> V52Decision:
    """Apply a label-free V5.2 rescue policy to an existing V4 ranking."""
    variant = _normalize_variant(variant)
    core = tuple(v4_results)
    if any(
        int(result.evidence.get("final_rank", rank)) != rank
        for rank, result in enumerate(core, 1)
    ):
        raise ValueError("V5.2 requires a complete V4 ranking in final-rank order")

    eligible, elite_limit = _eligible_candidates(model, core, candidate_limit)
    if not eligible:
        return V52Decision(
            variant, core, None, (), "no_rescue", "no_common_gate_candidate", elite_limit
        )

    best = eligible[0]
    if len(eligible) > 1 and _exact_primary_tie(best, eligible[1]):
        return V52Decision(
            variant, core, None, tuple(eligible), "ambiguous",
            "top_candidates_tied_on_pattern_irg_and_delta", elite_limit,
        )

    if variant in {"b", "c"} and len(eligible) > 1 and not _dominates(best, eligible[1]):
        return V52Decision(
            variant, core, None, tuple(eligible), "ambiguous",
            "best_candidate_lacks_preregistered_dominance_margin", elite_limit,
        )

    if variant == "c" and (
        best.repair_source_count < V52_MIN_DISTINCT_REPAIR_SOURCES
        or best.reference_quality < V52_MIN_REFERENCE_QUALITY
        or not best.repair_parseable
    ):
        return V52Decision(
            variant, core, None, tuple(eligible), "rejected_repair_evidence",
            "repair_lacks_two_sources_or_valid_references", elite_limit,
        )

    return V52Decision(
        variant, core, best, tuple(eligible), "rescue", "all_variant_gates_passed", elite_limit
    )


def v52_scores(
    model: WorkbookModel,
    *,
    variant: str,
    candidate_limit: int = 15,
) -> V52Decision:
    """Compute frozen V4 once and return a separate V5.2 review decision."""
    v4_results = v4_scores(model, candidate_limit=candidate_limit)
    return v52_from_v4(
        model, v4_results, variant=variant, candidate_limit=candidate_limit
    )
