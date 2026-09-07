"""Budgeted component search and independently replayable full-domain proofs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import date

from . import v5_1_8_development as previous
from .localize import v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_3_development import RepairDecision
from .v5_1_4_development import compose_edge_diagnosis
from .v5_1_5_development import _satisfaction, approved_aggregates
from .v5_1_7_development import (
    EVALUATION_ERRORS,
    Terminal,
    _domain,
    _overrides,
    _suffix_sizes,
)
from .v518_numeric_bounds import RULE_VERSION, runtime_supported
from .v519_components import (
    PreparationRefused,
    build_component_tables,
    component_bounds,
)

MODEL_VERSION = "v5.1.9-development"
PROOF_VERSION = "v519-component-partition-1"


@dataclass(frozen=True)
class SearchParameters(previous.SearchParameters):
    components: bool = True
    max_component_states: int = 256

    def __post_init__(self):
        super().__post_init__()
        if type(self.components) is not bool:
            raise TypeError("components must be boolean")
        if type(self.max_component_states) is not int or self.max_component_states < 1:
            raise ValueError("invalid component state limit")


class BudgetExceeded(ValueError):
    pass


@dataclass
class Budget:
    config: SearchParameters
    preparation_evaluations: int = 0
    evaluated: int = 0
    visited: int = 0
    actual_evaluations: int = 0
    satisfaction_calls: int = 0
    direct_evaluate_calls: int = 0

    def consume(self, phase):
        field, maximum = ("preparation_evaluations", self.config.max_preparations) if phase == "prepare" else (
            "evaluated", self.config.max_evaluations) if phase == "leaf" else ("visited", self.config.max_nodes)
        if getattr(self, field) >= maximum:
            raise BudgetExceeded(phase)
        setattr(self, field, getattr(self, field)+1)


class CountedModel:
    """Per-diagnosis evaluator accounting; never mutates the underlying model."""

    def __init__(self, model, budget):
        self.model, self.budget, self.phase = model, budget, "prepare"

    def __getattr__(self, name):
        return getattr(self.model, name)

    def evaluate(self, *args, **kwargs):
        self.budget.consume(self.phase)
        self.budget.actual_evaluations += 1
        return self.model.evaluate(*args, **kwargs)


@dataclass(frozen=True)
class SearchAudit(previous.SearchAudit):
    proof_version: str = PROOF_VERSION
    configuration_json: str = ""
    component_indices: tuple[tuple[int, ...], ...] = ()
    radices: tuple[int, ...] = ()
    table_sha256: str = ""
    preparation_trace: tuple[tuple[str, int, int, str], ...] = ()
    actual_evaluations: int = 0
    satisfaction_calls: int = 0
    direct_evaluate_calls: int = 0


@dataclass(frozen=True)
class JointDiagnosis(previous.JointDiagnosis):
    search: SearchAudit = SearchAudit("not_started")

    def to_results(self):
        results = super().to_results()
        for result in results:
            result.evidence.update(model_version=MODEL_VERSION, proof_version=PROOF_VERSION,
                                   component_indices=self.search.component_indices)
        return results


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _table_hash(tables):
    if tables is None:
        return ""
    payload = [tables.cells, tables.options, [(c, v.hex()) for c, v in tables.fixed],
               [(c.indices, c.members, c.assignments, [[v.hex() for v in row] for row in c.values]) for c in tables.components]]
    return hashlib.sha256(_json(payload).encode()).hexdigest()


def _binding(model, documents, approvals, as_of, cells, options, runtime, config, backend, policy, groups, digest):
    old = previous._binding(model, documents, approvals, as_of, cells, options, runtime)
    return hashlib.sha256(_json([old, MODEL_VERSION, PROOF_VERSION, asdict(config), backend, policy, groups, digest]).encode()).hexdigest()


def _prepare(model, aggregates, cells, options, budget):
    trace = []
    config = budget.config

    def run(name, function):
        before, actual = budget.preparation_evaluations, budget.actual_evaluations
        count, reason = 0, ""
        try:
            result = function(config.max_preparations-before)
            count = result.preparation_evaluations if name == "components" else result[2]
            reason = "" if name == "components" else result[1]
            return result
        except EVALUATION_ERRORS as exc:
            count = getattr(exc, "evaluations", getattr(exc, "count", budget.preparation_evaluations-before))
            reason = getattr(exc, "reason", "evaluation_incomplete")
            raise
        finally:
            # Frozen preparers alternate satisfaction and direct evaluate calls.
            # Reconcile attempts that failed before reaching evaluate separately.
            consumed = budget.preparation_evaluations-before
            if count < consumed or before+count > config.max_preparations:
                raise ValueError("preparer accounting mismatch")
            budget.preparation_evaluations = before+count
            budget.satisfaction_calls += (count+1)//2
            budget.direct_evaluate_calls += count//2
            trace.append((name, count, budget.actual_evaluations-actual, reason))

    if not config.pruning:
        return (), None, "exhaustive", "pruning_disabled", tuple(trace)
    if budget.preparation_evaluations >= config.max_preparations:
        return (), None, "exhaustive", "preparation_budget", tuple(trace)
    try:
        rows, reason, _, engine = run("independent", lambda remaining: previous._bounds(
            model, aggregates, cells, options, replace(config, max_preparations=remaining)))
        if reason != "candidate_dependency" or not config.components:
            return rows, None, engine, reason, tuple(trace)
        if not config.numeric_bounds or not runtime_supported():
            return (), None, "exhaustive", "numeric_bounds_disabled" if not config.numeric_bounds else "numeric_environment_unsupported", tuple(trace)
        if budget.preparation_evaluations >= config.max_preparations:
            return (), None, "exhaustive", "preparation_budget", tuple(trace)
        tables = run("components", lambda remaining: build_component_tables(
            model, aggregates, cells, options, max_component_states=config.max_component_states, max_preparations=remaining))
        try:
            rows = component_bounds(tables, aggregates)
        except (ValueError, OverflowError):
            return (), None, "exhaustive", "numeric_enclosure_range", tuple(trace)
        return rows, tables, "component_binary64_bounds", "", tuple(trace)
    except PreparationRefused as exc:
        if exc.reason in {"component_state_limit", "preparation_budget", "union_cycle", "range_limit", "absent_reference"}:
            return (), None, "exhaustive", exc.reason, tuple(trace)
        return (), None, "incomplete", exc.reason, tuple(trace)
    except EVALUATION_ERRORS:
        return (), None, "incomplete", "evaluation_incomplete", tuple(trace)


def _result(base, audit, solution=None, preserve_legacy=False):
    solution = solution or {}
    group = "v519_" + hashlib.sha256(_json([audit.binding, sorted(solution.items())]).encode()).hexdigest()
    proposed = {c.cell for c in base.candidates}
    decisions = []
    for decision in base.decisions:
        if preserve_legacy:
            decisions.append(decision)
            continue
        accept = decision.cell in solution and base.repair_policy == "structural"
        state = "accepted" if accept else "rejected" if decision.cell in proposed and base.repair_policy == "reject_all" else "review" if decision.cell in proposed else "abstained"
        decisions.append(RepairDecision(decision.cell, state, solution[decision.cell] if accept else None,
                                        audit.status, group if accept else "", len(solution) if accept else 0, 1.0 if accept else 0.0))
    return JointDiagnosis(base.backend, base.repair_policy, base.localization, base.candidates, tuple(decisions), audit)


def compose_joint_diagnosis(model, localization, *, backend="v4", documents=(), approvals=None,
                            as_of: date, repair_policy="structural", config=None):
    config = config or SearchParameters()
    if backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    base = compose_edge_diagnosis(model, localization, backend=backend, edge_mode="propose_only", repair_policy=repair_policy)
    budget = Budget(config)
    counted = CountedModel(model, budget)
    documents, approvals, runtime = tuple(documents), approvals or {}, previous._runtime()
    common = {"runtime_json": runtime, "configuration_json": _json(asdict(config))}

    def audit(status, **kwargs):
        return SearchAudit(status, **common, **kwargs, preparation_evaluations=budget.preparation_evaluations,
                           evaluated=budget.evaluated, visited=budget.visited, actual_evaluations=budget.actual_evaluations,
                           satisfaction_calls=budget.satisfaction_calls, direct_evaluate_calls=budget.direct_evaluate_calls)

    try:
        aggregates = approved_aggregates(model, documents, approvals, as_of)
        if not aggregates:
            return _result(base, audit("no_approved_constraints"), preserve_legacy=True)
        budget.satisfaction_calls += 1
        original = _satisfaction(counted, aggregates, {})
    except EVALUATION_ERRORS as exc:
        return _result(base, audit("constraint_rejected:"+str(exc)), preserve_legacy=True)
    if all(original.values()):
        return _result(base, audit("original_satisfies_constraints", solutions_seen=1))
    cells, options = _domain(model, aggregates)
    rows, tables, engine, fallback, trace = _prepare(counted, aggregates, cells, options, budget)
    groups = tuple(c.indices for c in tables.components) if tables else tuple((i,) for i in range(len(cells)))
    radices = tuple(len(c.assignments) for c in tables.components) if tables else tuple(map(len, options))
    suffix = _suffix_sizes(tuple(range(r) for r in radices))
    digest = _table_hash(tables)
    binding = _binding(model, documents, approvals, as_of, cells, options, runtime, config, backend, repair_policy, groups, digest)
    metadata = {"space_size": suffix[0], "candidate_cells": len(cells), "engine": engine, "fallback_reason": fallback,
                "binding": binding, "component_indices": groups, "radices": radices, "table_sha256": digest, "preparation_trace": trace}
    if engine == "incomplete":
        return _result(base, audit("evaluation_incomplete", **metadata))
    stack, terminals, solutions, pruned, stopped = [()], [], [], 0, ""
    counted.phase = "leaf"
    while stack:
        try:
            budget.consume("node")
        except BudgetExceeded:
            stopped = "budget_exceeded"
            break
        prefix = stack.pop()
        excluded = next((i for i, row in enumerate(rows) if row.excludes(prefix)), None)
        if excluded is not None:
            terminals.append(Terminal(prefix, excluded))
            pruned += suffix[len(prefix)]
        elif len(prefix) == len(radices):
            if budget.evaluated >= config.max_evaluations:
                stopped = "budget_exceeded"
                break
            original = tables.to_original(prefix) if tables else prefix
            overrides = _overrides(cells, options, original)
            try:
                budget.satisfaction_calls += 1
                satisfied = _satisfaction(counted, aggregates, overrides)
            except BudgetExceeded:
                stopped = "budget_exceeded"
                break
            except EVALUATION_ERRORS:
                stopped = "evaluation_incomplete"
                break
            terminals.append(Terminal(prefix))
            if all(satisfied.values()):
                solutions.append(overrides)
                if len(solutions) == 2:
                    stopped = "ambiguous_solutions"
                    break
        else:
            stack.extend((*prefix, v) for v in reversed(range(radices[len(prefix)])))
    complete = not stack and not stopped
    status = stopped or ("unique_solution" if len(solutions) == 1 else "no_solution")
    search = audit(status, **metadata, pruned_states=pruned, solutions_seen=len(solutions), complete=complete, terminals=tuple(terminals))
    return _result(base, search, solutions[0] if status == "unique_solution" and complete else None)


def verify_unique_solution(model, diagnosis, *, documents, approvals, as_of, config=None, localization=None):
    """Rebuild preparation and replay a bounded complete partition, not a search."""
    config = config or SearchParameters()
    audit = diagnosis.search
    if len(model.formulas) > 100000 or audit.candidate_cells > 512 or len(audit.terminals) > min(config.max_nodes, 100000):
        raise ValueError("verification resource limit")
    if audit.status != "unique_solution" or not audit.complete or audit.solutions_seen != 1:
        raise ValueError("missing complete uniqueness claim")
    if (audit.configuration_json != _json(asdict(config)) or audit.proof_version != PROOF_VERSION
            or audit.numeric_rule != RULE_VERSION or audit.runtime_json != previous._runtime()):
        raise ValueError("proof configuration, rule or runtime changed")
    for field in ("candidate_cells", "space_size", "visited", "evaluated", "preparation_evaluations", "actual_evaluations",
                  "satisfaction_calls", "direct_evaluate_calls", "pruned_states", "solutions_seen"):
        if type(getattr(audit, field)) is not int or getattr(audit, field) < 0:
            raise ValueError("invalid proof counter")
    documents = tuple(documents)
    aggregates = approved_aggregates(model, documents, approvals, as_of)
    budget = Budget(config)
    counted = CountedModel(model, budget)
    budget.satisfaction_calls += 1
    if not aggregates or all(_satisfaction(counted, aggregates, {}).values()):
        raise ValueError("no unsatisfied approved constraints")
    cells, options = _domain(model, aggregates)
    if len(cells) > 512:
        raise ValueError("verification candidate limit")
    rows, tables, engine, fallback, trace = _prepare(counted, aggregates, cells, options, budget)
    groups = tuple(c.indices for c in tables.components) if tables else tuple((i,) for i in range(len(cells)))
    radices = tuple(len(c.assignments) for c in tables.components) if tables else tuple(map(len, options))
    digest = _table_hash(tables)
    if ((engine, fallback, trace, groups, radices, digest) != (audit.engine, audit.fallback_reason, audit.preparation_trace,
                                                            audit.component_indices, audit.radices, audit.table_sha256)
            or engine == "incomplete" or audit.preparation_evaluations != budget.preparation_evaluations):
        raise ValueError("proof preparation changed")
    binding = _binding(model, documents, approvals, as_of, cells, options, audit.runtime_json, config,
                       diagnosis.backend, diagnosis.repair_policy, groups, digest)
    if binding != audit.binding or audit.candidate_cells != len(cells):
        raise ValueError("proof binding or domain changed")
    suffix = _suffix_sizes(tuple(range(r) for r in radices))
    cursor = pruned = 0
    solutions, visited = [], set()
    counted.phase = "leaf"
    for terminal in audit.terminals:
        prefix = terminal.prefix
        if len(prefix) > len(radices) or any(type(v) is not int or not 0 <= v < radices[i] for i, v in enumerate(prefix)):
            raise ValueError("invalid proof prefix")
        start = sum(v*suffix[i+1] for i, v in enumerate(prefix))
        if start != cursor:
            raise ValueError("proof gap, overlap or order changed")
        size = suffix[len(prefix)]
        cursor += size
        visited.update(prefix[:i] for i in range(len(prefix)+1))
        if len(visited) > config.max_nodes:
            raise ValueError("proof node budget exceeded")
        if type(terminal.constraint) is not int:
            raise ValueError("invalid constraint index")
        if terminal.constraint >= 0:
            if terminal.constraint >= len(rows) or not rows[terminal.constraint].excludes(prefix):
                raise ValueError("invalid pruning proof")
            pruned += size
        elif terminal.constraint == -1 and len(prefix) == len(radices):
            original = tables.to_original(prefix) if tables else prefix
            overrides = _overrides(cells, options, original)
            budget.satisfaction_calls += 1
            if all(_satisfaction(counted, aggregates, overrides).values()):
                solutions.append(overrides)
        else:
            raise ValueError("unevaluated proof leaf")
    if (cursor != suffix[0] or audit.space_size != suffix[0] or audit.pruned_states != pruned
            or audit.visited != len(visited) or audit.evaluated != budget.evaluated or len(solutions) != 1
            or audit.actual_evaluations != budget.actual_evaluations or audit.satisfaction_calls != budget.satisfaction_calls
            or audit.direct_evaluate_calls != budget.direct_evaluate_calls):
        raise ValueError("proof completeness or counters changed")
    if diagnosis.backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    # A caller may supply a freshly recomputed reference to avoid duplicate
    # ranker work. The experiment verifier recomputes it from the locked input.
    if localization is None:
        localization = (v4_scores if diagnosis.backend == "v4" else v5_1_1_development_scores)(model)
    base = compose_edge_diagnosis(model, localization, backend=diagnosis.backend, edge_mode="propose_only", repair_policy=diagnosis.repair_policy)
    if diagnosis.candidates != base.candidates or diagnosis.localization != base.localization:
        raise ValueError("ranking or candidate portfolio changed")
    expected = _result(base, audit, solutions[0])
    if diagnosis.decisions != expected.decisions:
        raise ValueError("atomic decisions differ from unique solution")
    return solutions[0]


def diagnose_v5_1_9_development(model, *, localization_backend="v4", **kwargs):
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    ranking = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    return compose_joint_diagnosis(model, ranking, backend=localization_backend, **kwargs)


def v5_1_9_development_scores(model, **kwargs):
    return diagnose_v5_1_9_development(model, **kwargs).to_results()
