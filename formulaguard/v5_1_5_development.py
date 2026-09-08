"""Externally approved aggregate constraints for experimental edge acceptance.

Approval pins document bytes out-of-band. It does not establish business truth.
The caller must supply independently justified approvals and an explicit date.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date

from .a1 import iter_rect
from .formula import Range, iter_refs
from .localize import LocalizationResult, v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_3_development import Diagnosis, RepairDecision
from .v5_1_4_development import compose_edge_diagnosis, edge_proposals
from .v5_1_development import _signature
from .workbook import CellKey, WorkbookModel

MODEL_VERSION = "v5.1.5-development"


def model_binding(model: WorkbookModel) -> str:
    payload = {"cells": [[*k, v] for k, v in sorted(model.cells.items())],
               "formulas": [[*k, v] for k, v in sorted(model.formulas.items())]}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class Aggregate:
    identifier: str
    members: tuple[CellKey, ...]
    total: float
    document_sha256: str


def approved_aggregates(model: WorkbookModel, documents: Sequence[bytes], approvals: Mapping[str, str], as_of: date):
    aggregates = []
    identifiers = set()
    binding = model_binding(model)
    for document in documents:
        digest = hashlib.sha256(document).hexdigest()
        raw = json.loads(document)
        if set(raw) != {"issuer", "workbook_binding", "valid_from", "valid_until", "aggregates"}:
            raise ValueError("invalid constraint document schema")
        if approvals.get(raw["issuer"]) != digest:
            raise ValueError("constraint document is not externally approved")
        if raw["workbook_binding"] != binding:
            raise ValueError("constraint workbook binding mismatch")
        if not date.fromisoformat(raw["valid_from"]) <= as_of <= date.fromisoformat(raw["valid_until"]):
            raise ValueError("constraint is stale or not yet valid")
        for entry in raw["aggregates"]:
            if set(entry) != {"id", "members", "total"}:
                raise ValueError("invalid aggregate schema")
            members = tuple(tuple(k) for k in entry["members"])
            if len(set(members)) != len(members) or len(members) < 2 or not set(members) <= set(model.formulas):
                raise ValueError("aggregate needs at least two distinct existing formula cells")
            if not isinstance(entry["id"], str) or not entry["id"] or entry["id"] in identifiers:
                raise ValueError("duplicate or invalid aggregate identity")
            total = entry["total"]
            if isinstance(total, bool) or not isinstance(total, (int, float)) or not math.isfinite(total):
                raise ValueError("aggregate total must be a finite number")
            identifiers.add(entry["id"])
            aggregates.append(Aggregate(entry["id"], members, float(total), digest))
    return tuple(aggregates)


@dataclass(frozen=True)
class ConstraintDiagnosis(Diagnosis):
    constraint_status: str = "no_approved_constraints"

    def to_results(self):
        results = super().to_results()
        for result in results:
            result.evidence["model_version"] = MODEL_VERSION
            result.evidence["constraint_status"] = self.constraint_status
        return results


def _satisfaction(model, aggregates, overrides):
    targets = {cell for a in aggregates for cell in a.members}
    graph = model.dependency_graph(overrides)
    pending = list(targets)
    seen = set()
    while pending:
        cell = pending.pop()
        if cell in seen:
            continue
        seen.add(cell)
        if cell not in model.cells and cell not in model.formulas:
            raise ValueError("constraint depends on an absent cell")
        pending.extend(graph.precedents.get(cell, ()))
        if cell in model.formulas:
            for ref in iter_refs(model.ast(overrides.get(cell, model.formulas[cell]))):
                if isinstance(ref, Range):
                    start, end = ref.start.address, ref.end.address
                    if (abs(start.row - end.row) + 1) * (abs(start.col - end.col) + 1) > 10000:
                        raise ValueError("constraint range exceeds explicit completeness-check limit")
                    sheet = ref.start.sheet or ref.end.sheet or cell[0]
                    pending.extend((sheet, address) for address in iter_rect(start, end))
    values, errors = model.evaluate(overrides=overrides, targets=targets)
    if errors or any(isinstance(values.get(k), bool) or not isinstance(values.get(k), (int, float))
                     or not math.isfinite(values[k]) for k in targets):
        raise ValueError("constraint computation is unsupported or nonfinite")
    return {a.identifier: math.isclose(math.fsum(float(values[k]) for k in a.members), a.total,
                                     rel_tol=1e-10, abs_tol=1e-8) for a in aggregates}


def compose_constraint_diagnosis(
    model: WorkbookModel, localization: list[LocalizationResult], *, backend="v4",
    documents: Sequence[bytes] = (), approvals: Mapping[str, str] | None = None,
    as_of: date, repair_policy="structural",
) -> ConstraintDiagnosis:
    base = compose_edge_diagnosis(model, localization, backend=backend,
                                 edge_mode="propose_only", repair_policy=repair_policy)
    def result(decisions, status):
        return ConstraintDiagnosis(base.backend, base.repair_policy, base.localization,
                                   base.candidates, tuple(decisions), status)
    try:
        aggregates = approved_aggregates(model, documents, approvals or {}, as_of)
        if not aggregates:
            return result(base.decisions, "no_approved_constraints")
        baseline = _satisfaction(model, aggregates, {})
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return result(base.decisions, "constraint_rejected:" + str(exc))
    choices = defaultdict(dict)
    for p in edge_proposals(model):
        if p.bounded_edit:
            choices[p.cell][_signature(p.formula, p.cell[1])] = p.formula
    pending = {}
    reasons = {}
    existing = {d.cell: d.accepted_formula for d in base.decisions if d.accepted_formula}
    base_decisions = list(base.decisions)
    if existing:
        try:
            old_after = _satisfaction(model, aggregates, existing)
            if not all(old_after.values()):
                raise ValueError("legacy accepted changes violate approved constraints")
        except (ValueError, TypeError, OverflowError):
            # Preserve atomicity: revoke the entire old action set, not a subset
            # of a coupled accepted group. Proposals and ranks remain available.
            base_decisions = [RepairDecision(d.cell, "review", None, "legacy_actions_conflict_with_constraints")
                              if d.accepted_formula else d for d in base.decisions]
            existing = {}
    for decision in base_decisions:
        cell = decision.cell
        if cell in existing or not choices[cell]:
            continue
        relevant = [a for a in aggregates if cell in a.members]
        if not relevant:
            reasons[cell] = "no_constraint_for_candidate"
            continue
        if all(baseline[a.identifier] for a in relevant):
            reasons[cell] = "original_satisfies_constraints"
            continue
        passing = []
        for formula in choices[cell].values():
            try:
                after = _satisfaction(model, aggregates, {cell: formula})
            except (ValueError, TypeError, OverflowError):
                continue
            if all(after[a.identifier] for a in relevant) and all(after[k] for k, was_ok in baseline.items() if was_ok):
                passing.append(formula)
        if len(passing) == 1:
            pending[cell] = passing[0]
            reasons[cell] = "unique_candidate_restores_approved_aggregate"
        else:
            reasons[cell] = "ambiguous_numeric_solutions" if passing else "no_candidate_satisfies_constraints"
    if pending:
        try:
            joint = _satisfaction(model, aggregates, {**existing, **pending})
            if not all(joint.values()):
                raise ValueError("joint changes violate a constraint")
        except (ValueError, TypeError, OverflowError):
            for cell in pending:
                reasons[cell] = "joint_constraint_failure"
            pending = {}
    # New actions form one atomic transaction because aggregate checks couple cells.
    group = "v515_" + hashlib.sha256(json.dumps(sorted(pending.items())).encode()).hexdigest()
    decisions = []
    for decision in base_decisions:
        if decision.cell not in reasons:
            decisions.append(decision)
            continue
        accept = decision.cell in pending and repair_policy == "structural"
        provenance = [{"id": a.identifier, "source_sha256": a.document_sha256}
                      for a in aggregates if decision.cell in a.members]
        decisions.append(RepairDecision(
            decision.cell, "accepted" if accept else "rejected" if repair_policy == "reject_all" else "review",
            pending[decision.cell] if accept else None,
            reasons[decision.cell] + ":" + json.dumps(provenance, sort_keys=True),
            group if accept else "", len(pending) if accept else 0, 1.0 if accept else 0.0,
        ))
    return result(decisions, "approved_aggregate_constraints_checked")


def diagnose_v5_1_5_development(model: WorkbookModel, *, localization_backend="v4", **kwargs):
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    ranking = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    return compose_constraint_diagnosis(model, ranking, backend=localization_backend, **kwargs)


def v5_1_5_development_scores(model: WorkbookModel, **kwargs):
    return diagnose_v5_1_5_development(model, **kwargs).to_results()
