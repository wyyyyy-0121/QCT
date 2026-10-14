"""Preregistered FormulaGuard V5 consensus gate over the frozen V4 model."""

from __future__ import annotations

import math
import time
from typing import Sequence

from .localize import (
    LocalizationResult,
    V4_STRONG_MIN_CONTROLS,
    V4_STRONG_MIN_DELTA,
    V4_STRONG_MIN_IRG,
    v4_scores,
)
from .workbook import CellKey, WorkbookModel


V5_PATTERN_FRACTION = 0.02
V5_PATTERN_MIN_ELITE = 3
V5_PATTERN_MAX_ELITE = 10
V5_MAX_JOINT_CANDIDATES = 5
V5_RESCUE_BELOW_RANK = 5


def v5_default_parameters() -> dict[str, float | int | str]:
    """Return the preregistered public parameter contract for FormulaGuard V5."""
    return {
        "model_version": "v5-pcg-r1",
        "base_model": "v4-dev-r1",
        "fusion": "pattern_counterfactual_consensus_gate_over_frozen_v4",
        "pattern_fraction": V5_PATTERN_FRACTION,
        "pattern_min_elite": V5_PATTERN_MIN_ELITE,
        "pattern_max_elite": V5_PATTERN_MAX_ELITE,
        "max_joint_candidates": V5_MAX_JOINT_CANDIDATES,
        "rescue_below_v4_rank": V5_RESCUE_BELOW_RANK,
        "strong_min_controls": V4_STRONG_MIN_CONTROLS,
        "strong_min_delta": V4_STRONG_MIN_DELTA,
        "strong_min_irg": V4_STRONG_MIN_IRG,
        "strong_min_support": 2,
        "fallback": "exact_v4_order_when_joint_gate_is_inactive",
    }


def _v5_pattern_elite_limit(formula_count: int) -> int:
    return min(
        V5_PATTERN_MAX_ELITE,
        max(V5_PATTERN_MIN_ELITE, math.ceil(V5_PATTERN_FRACTION * formula_count)),
    )


def _v5_consensus_order(
    v4_results: Sequence[LocalizationResult],
) -> tuple[list[LocalizationResult], set[CellKey], int, bool]:
    """Apply the preregistered V5 gate to already-computed frozen V4 results."""
    elite_limit = _v5_pattern_elite_limit(len(v4_results))
    joint = [
        result for result in v4_results
        if int(result.evidence.get("formula_rank", len(v4_results) + 1)) <= elite_limit
        and result.evidence.get("diagnostic_status") == "strong_counterfactual"
        and int(result.evidence.get("final_rank", len(v4_results) + 1)) > V5_RESCUE_BELOW_RANK
    ]
    joint_cells = {result.cell for result in joint}
    gate_active = 1 <= len(joint) <= V5_MAX_JOINT_CANDIDATES
    if not gate_active:
        return list(v4_results), joint_cells, elite_limit, False
    ordered_joint = sorted(
        joint,
        key=lambda result: (
            int(result.evidence["formula_rank"]),
            -float(result.evidence["intervention_responsibility_gain"]),
            -float(result.evidence["candidate_delta"]),
            int(result.evidence["final_rank"]),
            result.cell,
        ),
    )
    ordered = ordered_joint + [result for result in v4_results if result.cell not in joint_cells]
    return ordered, joint_cells, elite_limit, True


def v5_scores(model: WorkbookModel, *, candidate_limit: int = 15):
    """Pattern-counterfactual consensus gate over the frozen V4 ranking."""
    started = time.perf_counter()
    v4_results = v4_scores(model, candidate_limit=candidate_limit)
    ordered, joint_cells, elite_limit, gate_active = _v5_consensus_order(v4_results)
    joint_count = len(joint_cells)
    n = len(ordered)
    results: list[LocalizationResult] = []
    for final_rank, base in enumerate(ordered, 1):
        evidence = dict(base.evidence)
        v4_status = str(evidence.get("diagnostic_status", ""))
        v4_rank = int(evidence.get("final_rank", final_rank))
        pattern_elite = int(evidence.get("formula_rank", n + 1)) <= elite_limit
        joint_eligible = base.cell in joint_cells
        if gate_active and joint_eligible:
            status = "joint_confirmed"
            reason = "pattern_elite_strong_counterfactual_and_v4_top5_rescue"
        elif joint_count > V5_MAX_JOINT_CANDIDATES and joint_eligible:
            status = "ambiguous_joint_evidence"
            reason = "joint_candidate_count_exceeds_selectivity_limit"
        elif v4_status == "strong_counterfactual":
            status = "strong_counterfactual_only"
            reason = (
                "already_in_v4_top5_no_rescue_needed"
                if v4_rank <= V5_RESCUE_BELOW_RANK
                else "strong_counterfactual_without_active_pattern_consensus"
            )
        else:
            status = v4_status
            reason = "frozen_v4_fallback"
        evidence.update({
            "model_version": "v5-pcg-r1",
            "fusion_policy": "pattern_counterfactual_consensus_gate_over_frozen_v4",
            "v4_diagnostic_status": v4_status,
            "v4_final_rank": v4_rank,
            "pattern_elite_limit": elite_limit,
            "pattern_elite": int(pattern_elite),
            "joint_eligible": int(joint_eligible),
            "joint_candidate_count": joint_count,
            "joint_gate_active": int(gate_active),
            "joint_confirmed": int(gate_active and joint_eligible),
            "diagnostic_status": status,
            "v5_override_reason": reason,
            "v5_final_rank": final_rank,
            "v5_rank_change": v4_rank - final_rank,
            "v5_promotion_distance": max(0, v4_rank - final_rank),
        })
        results.append(LocalizationResult(
            cell=base.cell,
            score=float(n - final_rank + 1),
            candidate_formula=base.candidate_formula,
            evidence=evidence,
        ))
    elapsed = time.perf_counter() - started
    for result in results:
        result.evidence["localization_seconds"] = elapsed
    return results
