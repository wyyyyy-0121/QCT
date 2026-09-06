"""V5.1.3: immutable localization followed by independent repair decisions.

This is a composition experiment, not a redesigned ranking model. The selected
backend supplies the entire ordering and every localization score. Repair policy
can only change repair fields. It cannot sort, filter, or rescore localization.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from .localize import LocalizationResult, v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_2_development import Parameters, v5_1_2_development_scores
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5.1.3-development"
Backend = Literal["v4", "v511"]
RepairPolicy = Literal["structural", "review_only", "reject_all"]


@dataclass(frozen=True)
class RankedCell:
    cell: CellKey
    rank: int
    score: float
    evidence_json: str


@dataclass(frozen=True)
class Candidate:
    cell: CellKey
    formula: str
    source: str


@dataclass(frozen=True)
class RepairDecision:
    cell: CellKey
    state: str
    accepted_formula: str | None
    reason: str
    group_id: str = ""
    group_size: int = 0
    repair_score: float = 0.0


@dataclass(frozen=True)
class Diagnosis:
    backend: Backend
    repair_policy: RepairPolicy
    localization: tuple[RankedCell, ...]
    candidates: tuple[Candidate, ...]
    decisions: tuple[RepairDecision, ...]

    @property
    def localization_sha256(self) -> str:
        payload = [(r.cell, r.rank, float(r.score).hex()) for r in self.localization]
        return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()

    def to_results(self) -> list[LocalizationResult]:
        decisions = {d.cell: d for d in self.decisions}
        portfolio = defaultdict(list)
        for candidate in self.candidates:
            portfolio[candidate.cell].append({"formula": candidate.formula, "source": candidate.source})
        digest = self.localization_sha256
        result = []
        # Iteration order and score come exclusively from the immutable ranking.
        for ranked in self.localization:
            decision = decisions[ranked.cell]
            result.append(LocalizationResult(
                cell=ranked.cell, score=ranked.score, candidate_formula=decision.accepted_formula,
                evidence={
                    "model_version": MODEL_VERSION, "localization_backend": self.backend,
                    "localization_score": ranked.score, "final_rank": ranked.rank,
                    "localization_sha256": digest,
                    "localization_evidence_json": ranked.evidence_json,
                    "repair_policy": self.repair_policy, "decision": decision.state,
                    "repair_score": decision.repair_score, "repair_score_is_probability": False,
                    "candidate_portfolio_json": json.dumps(portfolio[ranked.cell], sort_keys=True),
                    "group_state": "accepted" if decision.accepted_formula is not None else "not_applicable",
                    "group_reason": decision.reason, "group_id": decision.group_id,
                    "group_size": decision.group_size, "automatic_edit_applied": False,
                },
            ))
        return result


def _validate_complete(model: WorkbookModel, results: Sequence[LocalizationResult]) -> None:
    cells = [result.cell for result in results]
    if len(cells) != len(set(cells)) or set(cells) != set(model.formulas):
        raise ValueError("ranking must contain every formula cell exactly once")
    if any(isinstance(result.score, bool) or not math.isfinite(result.score) for result in results):
        raise ValueError("localization and repair scores must be finite numbers")


def compose_diagnosis(
    model: WorkbookModel,
    localization: Sequence[LocalizationResult],
    repairs: Sequence[LocalizationResult],
    *,
    backend: Backend = "v4",
    repair_policy: RepairPolicy = "structural",
) -> Diagnosis:
    """Compose already computed layers, validating coverage and atomic groups.

    This function never calls a ranker and never reads labels. Supplied rankings
    are caller-provided evidence; evaluation must additionally verify their input
    and source provenance before using cached rankings.
    """
    if backend not in {"v4", "v511"} or repair_policy not in {"structural", "review_only", "reject_all"}:
        raise ValueError("unknown localization backend or repair policy")
    _validate_complete(model, localization)
    _validate_complete(model, repairs)
    frozen = tuple(RankedCell(
        result.cell, rank, result.score,
        json.dumps({k: v for k, v in result.evidence.items() if k != "localization_seconds"},
                   sort_keys=True, allow_nan=False),
    ) for rank, result in enumerate(localization, 1))
    repair_by_cell = {result.cell: result for result in repairs}
    groups = defaultdict(list)
    for repair in repairs:
        if repair.candidate_formula is not None:
            evidence = repair.evidence
            if evidence.get("group_state") != "accepted" or not evidence.get("group_id"):
                raise ValueError("structural acceptance requires an explicit group")
            groups[evidence["group_id"]].append(repair)
        elif repair.evidence.get("group_state") == "accepted":
            raise ValueError("accepted group member is missing its candidate")
    for members in groups.values():
        if any(member.evidence.get("group_size") != len(members) for member in members):
            raise ValueError("partial or inconsistent accepted group")

    candidates = []
    decisions = []
    for base in localization:
        repair = repair_by_cell[base.cell]
        choices = []
        if base.candidate_formula:
            choices.append((base.candidate_formula, "localization_backend_proposal"))
        if repair.candidate_formula:
            choices.append((repair.candidate_formula, "structural_accepted_proposal"))
        elif repair.evidence.get("review_formula"):
            choices.append((str(repair.evidence["review_formula"]), "structural_review_proposal"))
        for formula, origin in choices:
            if not isinstance(formula, str) or not formula.startswith("="):
                raise ValueError("invalid proposed formula")
            candidates.append(Candidate(base.cell, formula, origin))
        accepted = repair.candidate_formula if repair_policy == "structural" else None
        if accepted is not None:
            state = "accepted"
            reason = str(repair.evidence.get("group_reason", "structural_acceptance"))
        elif choices:
            state = "rejected" if repair_policy == "reject_all" else "review"
            reason = "policy_reject_all" if repair_policy == "reject_all" else (
                "policy_review_only" if repair_policy == "review_only" else "no_accepted_structural_evidence"
            )
        else:
            state, reason = "abstained", "no_repair_proposal"
        decisions.append(RepairDecision(
            base.cell, state, accepted, reason,
            str(repair.evidence["group_id"]) if accepted else "",
            int(repair.evidence["group_size"]) if accepted else 0,
            repair.score,
        ))
    return Diagnosis(backend, repair_policy, frozen, tuple(candidates), tuple(decisions))


def diagnose_v5_1_3_development(
    model: WorkbookModel, *, localization_backend: Backend = "v4",
    repair_policy: RepairPolicy = "structural", repair_config: Parameters | None = None,
) -> Diagnosis:
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    if repair_policy not in {"structural", "review_only", "reject_all"}:
        raise ValueError("unknown repair policy")
    # Compute and detach localization before invoking the repair layer. Never
    # forward repair thresholds to the localization backend.
    ranked = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    localization = [LocalizationResult(r.cell, r.score, r.candidate_formula, dict(r.evidence)) for r in ranked]
    repairs = v5_1_2_development_scores(model, config=repair_config)
    return compose_diagnosis(model, localization, repairs, backend=localization_backend, repair_policy=repair_policy)


def v5_1_3_development_scores(model: WorkbookModel, **kwargs) -> list[LocalizationResult]:
    return diagnose_v5_1_3_development(model, **kwargs).to_results()


def v5_1_3_development_default_parameters() -> dict:
    return {
        "model_version": MODEL_VERSION, "architecture": "localization_preserving_composition",
        "localization_backend": "v4", "repair_backend": "v5.1.2-development",
        "repair_policy": "structural", "repair_parameters": vars(Parameters()),
        "ranking_modified_by_repair": False, "automatic_edit_applied": False,
        "new_core_ranking_model": False,
    }
