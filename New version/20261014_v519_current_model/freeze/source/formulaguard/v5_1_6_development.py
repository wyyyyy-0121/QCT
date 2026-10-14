"""Exhaustive bounded joint edge repair; uniqueness is never inferred from truncation."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from itertools import product

from .localize import v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_3_development import Diagnosis, RepairDecision
from .v5_1_4_development import compose_edge_diagnosis, edge_proposals
from .v5_1_5_development import _satisfaction, approved_aggregates
from .v5_1_development import _signature

MODEL_VERSION = "v5.1.6-development"


@dataclass(frozen=True)
class SearchParameters:
    max_states: int = 256

    def __post_init__(self):
        if isinstance(self.max_states, bool) or not isinstance(self.max_states, int) or self.max_states < 1:
            raise ValueError("max_states must be a positive integer")


@dataclass(frozen=True)
class SearchAudit:
    status: str
    space_size: int = 0
    evaluated: int = 0
    solutions_seen: int = 0
    complete: bool = False
    candidate_cells: int = 0


@dataclass(frozen=True)
class JointDiagnosis(Diagnosis):
    search: SearchAudit = SearchAudit("not_started")

    def to_results(self):
        results = super().to_results()
        for r in results:
            r.evidence.update(model_version=MODEL_VERSION, search_status=self.search.status,
                              search_space=self.search.space_size, search_evaluated=self.search.evaluated,
                              search_complete=self.search.complete, solutions_seen=self.search.solutions_seen)
        return results


def compose_joint_diagnosis(model, localization, *, backend="v4", documents=(), approvals=None,
                            as_of: date, repair_policy="structural", config: SearchParameters | None = None):
    config = config or SearchParameters()
    base = compose_edge_diagnosis(model, localization, backend=backend, edge_mode="propose_only", repair_policy=repair_policy)
    def result(audit, solution=None, preserve_legacy=False):
        solution = solution or {}
        group = "v516_" + hashlib.sha256(json.dumps(sorted(solution.items())).encode()).hexdigest()
        decisions = []
        for d in base.decisions:
            if preserve_legacy:
                decisions.append(d)
                continue
            accept = d.cell in solution and repair_policy == "structural"
            proposed = any(c.cell == d.cell for c in base.candidates)
            decisions.append(RepairDecision(
                d.cell, "accepted" if accept else "rejected" if proposed and repair_policy == "reject_all" else "review" if proposed else "abstained",
                solution[d.cell] if accept else None, audit.status,
                group if accept else "", len(solution) if accept else 0, 1.0 if accept else 0.0,
            ))
        return JointDiagnosis(base.backend, base.repair_policy, base.localization, base.candidates, tuple(decisions), audit)
    try:
        aggregates = approved_aggregates(model, documents, approvals or {}, as_of)
        if not aggregates:
            return result(SearchAudit("no_approved_constraints"), preserve_legacy=True)
        original = _satisfaction(model, aggregates, {})
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return result(SearchAudit("constraint_rejected:" + str(exc)), preserve_legacy=True)
    if all(original.values()):
        # Includes cancelling errors: existing evidence cannot authorize a change.
        return result(SearchAudit("original_satisfies_constraints", evaluated=1, solutions_seen=1))
    members = {cell for a in aggregates for cell in a.members}
    choices = defaultdict(dict)
    for p in edge_proposals(model):
        if p.bounded_edit and p.cell in members:
            choices[p.cell][_signature(p.formula, p.cell[1])] = p.formula
    cells = sorted(choices)
    options = [(None, *[form for _, form in sorted(choices[cell].items())]) for cell in cells]
    space = math.prod(len(values) for values in options)
    if space > config.max_states:
        return result(SearchAudit("budget_exceeded", space, candidate_cells=len(cells)))
    solutions = []
    evaluated = 0
    for assignment in product(*options):
        overrides = {cell: formula for cell, formula in zip(cells, assignment, strict=True) if formula is not None}
        evaluated += 1
        try:
            satisfied = _satisfaction(model, aggregates, overrides)
        except (ValueError, TypeError, KeyError, OverflowError):
            return result(SearchAudit("evaluation_incomplete", space, evaluated, len(solutions), False, len(cells)))
        if all(satisfied.values()):
            solutions.append(overrides)
    status = "unique_solution" if len(solutions) == 1 else "ambiguous_solutions" if solutions else "no_solution"
    return result(SearchAudit(status, space, evaluated, len(solutions), True, len(cells)),
                  solutions[0] if len(solutions) == 1 else None)


def diagnose_v5_1_6_development(model, *, localization_backend="v4", **kwargs):
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    ranking = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    return compose_joint_diagnosis(model, ranking, backend=localization_backend, **kwargs)


def v5_1_6_development_scores(model, **kwargs):
    return diagnose_v5_1_6_development(model, **kwargs).to_results()
