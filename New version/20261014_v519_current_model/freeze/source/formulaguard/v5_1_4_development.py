"""Edge proposal experiment with orthogonal support, preserving V513 ranking.

Orthogonal agreement is structural evidence, not proof of business intent.
This development module never writes workbooks or modifies the ranker.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from itertools import groupby
from typing import Literal

from .formula import parse_formula
from .localize import LocalizationResult, v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_2_development import _edit_distance, _regions, v5_1_2_development_scores
from .v5_1_3_development import Candidate, Diagnosis, RepairDecision, compose_diagnosis
from .v5_1_development import _safe_translate, _signature
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5.1.4-development"
EdgeMode = Literal["off", "propose_only", "orthogonal"]


@dataclass(frozen=True)
class EdgeParameters:
    min_support: int = 3

    def __post_init__(self):
        if isinstance(self.min_support, bool) or not isinstance(self.min_support, int) or self.min_support < 3:
            raise ValueError("edge min_support must be an integer at least three")


@dataclass(frozen=True)
class EdgeProposal:
    cell: CellKey
    formula: str
    axis: str
    anchors: tuple[CellKey, ...]
    bounded_edit: bool


@dataclass(frozen=True)
class EdgeDiagnosis(Diagnosis):
    edge_mode: EdgeMode = "propose_only"

    def to_results(self) -> list[LocalizationResult]:
        results = super().to_results()
        for result in results:
            result.evidence["model_version"] = MODEL_VERSION
            result.evidence["edge_mode"] = self.edge_mode
        return results


def edge_proposals(model: WorkbookModel, config: EdgeParameters | None = None) -> tuple[EdgeProposal, ...]:
    config = config or EdgeParameters()
    proposals = []
    for axis in ("row", "column"):
        for region in _regions(model, axis):
            runs = [(sig, list(cells)) for sig, cells in groupby(
                region, key=lambda cell: _signature(model.formulas[cell], cell[1])
            )]
            if len(runs) < 2:
                continue
            # Only singleton endpoints. Never rewrite a boundary block/column.
            for endpoint, neighbor in ((runs[0], runs[1]), (runs[-1], runs[-2])):
                if len(endpoint[1]) != 1 or len(neighbor[1]) < config.min_support:
                    continue
                cell = endpoint[1][0]
                anchors = tuple(neighbor[1])
                translated = [_safe_translate(model.formulas[a], a[1], cell[1]) for a in anchors]
                if any(value is None for value in translated):
                    continue
                if len({_signature(value, cell[1]) for value in translated}) != 1:
                    continue
                formula = translated[0]
                if _signature(formula, cell[1]) == _signature(model.formulas[cell], cell[1]):
                    continue
                proposals.append(EdgeProposal(
                    cell, formula, axis, anchors,
                    _edit_distance(parse_formula(model.formulas[cell]), parse_formula(formula)) == 1,
                ))
    return tuple(proposals)


def compose_edge_diagnosis(
    model: WorkbookModel, localization: list[LocalizationResult], *, backend="v4",
    edge_mode: EdgeMode = "propose_only", repair_policy="structural",
    config: EdgeParameters | None = None,
) -> EdgeDiagnosis:
    if edge_mode not in {"off", "propose_only", "orthogonal"}:
        raise ValueError("unknown edge mode")
    base = compose_diagnosis(model, localization, v5_1_2_development_scores(model),
                            backend=backend, repair_policy=repair_policy)
    if edge_mode == "off":
        return EdgeDiagnosis(base.backend, base.repair_policy, base.localization,
                             base.candidates, base.decisions, edge_mode)
    proposals = edge_proposals(model, config)
    by_cell = defaultdict(list)
    candidates = list(base.candidates)
    for proposal in proposals:
        by_cell[proposal.cell].append(proposal)
        candidates.append(Candidate(proposal.cell, proposal.formula, "edge_" + proposal.axis))
    decisions = []
    for decision in base.decisions:
        choices = by_cell[decision.cell]
        if not choices or decision.accepted_formula is not None:
            decisions.append(decision)
            continue
        signatures = {_signature(p.formula, p.cell[1]) for p in choices}
        axes = {p.axis for p in choices}
        # Row and column anchor cells must be distinct, not duplicated votes.
        anchor_sets = [set(p.anchors) for p in choices]
        disjoint = all(not left & right for i, left in enumerate(anchor_sets) for right in anchor_sets[i + 1:])
        supported = len(signatures) == 1 and axes == {"row", "column"} and disjoint
        bounded = all(p.bounded_edit for p in choices)
        accept = edge_mode == "orthogonal" and repair_policy == "structural" and supported and bounded
        formula = choices[0].formula
        evidence = json.dumps([{"axis": p.axis, "anchors": p.anchors, "formula": p.formula,
                                "bounded_edit": p.bounded_edit} for p in choices], sort_keys=True)
        reason = "edge_orthogonal_agreement" if accept else (
            "edge_policy_reject_all" if repair_policy == "reject_all" else
            "edge_review_only" if repair_policy == "review_only" or edge_mode == "propose_only" else
            "edge_expression_change_requires_review" if not bounded else
            "edge_conflicting_candidates" if len(signatures) > 1 else "edge_missing_orthogonal_support"
        )
        group_id = "v514_" + hashlib.sha256(json.dumps([decision.cell, formula]).encode()).hexdigest() if accept else ""
        decisions.append(RepairDecision(
            decision.cell, "accepted" if accept else "rejected" if repair_policy == "reject_all" else "review",
            formula if accept else None, reason + ":" + evidence, group_id, 1 if accept else 0, 1.0 if supported else 0.0,
        ))
    return EdgeDiagnosis(base.backend, base.repair_policy, base.localization,
                         tuple(candidates), tuple(decisions), edge_mode)


def diagnose_v5_1_4_development(model: WorkbookModel, *, localization_backend="v4", **kwargs) -> EdgeDiagnosis:
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    ranked = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    return compose_edge_diagnosis(model, ranked, backend=localization_backend, **kwargs)


def v5_1_4_development_scores(model: WorkbookModel, **kwargs) -> list[LocalizationResult]:
    return diagnose_v5_1_4_development(model, **kwargs).to_results()
