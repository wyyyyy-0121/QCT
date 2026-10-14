"""Joint repair with conditional binary64 enclosures and complete-space proofs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date

from . import v518_numeric_bounds as numeric
from .localize import v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_3_development import RepairDecision
from .v5_1_4_development import compose_edge_diagnosis
from .v5_1_5_development import _satisfaction, approved_aggregates
from .v5_1_7_development import (
    EVALUATION_ERRORS,
    Bound,
    Terminal,
    _domain,
    _overrides,
    _PreparationFailure,
    _suffix_sizes,
)
from .v5_1_7_development import (
    JointDiagnosis as PreviousDiagnosis,
)
from .v5_1_7_development import (
    SearchAudit as PreviousAudit,
)
from .v5_1_7_development import (
    SearchParameters as PreviousParameters,
)
from .v5_1_7_development import (
    _binding as previous_binding,
)

MODEL_VERSION = "v5.1.8-development"


@dataclass(frozen=True)
class SearchParameters(PreviousParameters):
    numeric_bounds: bool = True

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.numeric_bounds, bool):
            raise TypeError("numeric_bounds must be boolean")


@dataclass(frozen=True)
class SearchAudit(PreviousAudit):
    numeric_rule: str = numeric.RULE_VERSION
    runtime_json: str = ""


@dataclass(frozen=True)
class JointDiagnosis(PreviousDiagnosis):
    search: SearchAudit = SearchAudit("not_started")

    def to_results(self):
        results = super().to_results()
        for result in results:
            result.evidence.update(model_version=MODEL_VERSION, numeric_rule=self.search.numeric_rule)
        return results


def _runtime():
    try:
        return json.dumps(numeric.runtime_identity(), sort_keys=True)
    except (OSError, AttributeError):
        return "unavailable"


def _binding(model, documents, approvals, as_of, cells, options, runtime):
    old = previous_binding(model, documents, approvals, as_of, cells, options)
    return hashlib.sha256(json.dumps([old, MODEL_VERSION, numeric.RULE_VERSION, runtime]).encode()).hexdigest()


def _bounds(model, aggregates, cells, options, config):
    # V517's preparation contract is retained here without editing its frozen
    # implementation; numeric rows reuse the same independent option evaluations.
    targets = {cell for aggregate in aggregates for cell in aggregate.members}
    candidates = set(cells)
    graph = {cell: set(refs) for cell, refs in model.dependency_graph().precedents.items()}
    for cell, values in zip(cells, options, strict=True):
        for formula in values[1:]:
            graph.setdefault(cell, set()).update(model.dependency_graph({cell: formula}).precedents[cell])
    for target in targets:
        pending, seen = list(graph.get(target, ())), set()
        while pending:
            cell = pending.pop()
            if cell in seen:
                continue
            seen.add(cell)
            if cell in candidates:
                return (), "candidate_dependency", 0, "exhaustive"
            pending.extend(graph.get(cell, ()))
    required = 2 * (1 + sum(len(values) - 1 for values in options))
    if required > config.max_preparations:
        return (), "preparation_budget", 0, "exhaustive"
    count = 0

    def checked(overrides):
        nonlocal count
        try:
            count += 1
            _satisfaction(model, aggregates, overrides)
            count += 1
            values, errors = model.evaluate(overrides=overrides, targets=targets)
            if errors:
                raise ValueError("independent value evaluation failed")
        except EVALUATION_ERRORS as exc:
            raise _PreparationFailure(count) from exc
        return values

    original = checked({})
    option_values = {cell: (original[cell], *(checked({cell: formula})[cell] for formula in values[1:]))
                     for cell, values in zip(cells, options, strict=True)}
    data = []
    integer_rows = []
    for aggregate in aggregates:
        fixed = tuple(float(original[cell]) for cell in aggregate.members if cell not in candidates)
        variable = tuple(tuple(float(v) for v in option_values[cell]) if cell in aggregate.members
                         else tuple(0.0 for _ in values) for cell, values in zip(cells, options, strict=True))
        data.append((fixed, variable, aggregate.total))
        values = (*fixed, *(v for row in variable for v in row))
        integral = all(v.is_integer() for v in values)
        magnitude = sum(abs(int(v)) for v in fixed) + sum(max(abs(int(v)) for v in row) for row in variable) if integral else 2**53
        if integral and magnitude <= 2**52:
            integer_rows.append(Bound(sum(int(v) for v in fixed), tuple(tuple(int(v) for v in row) for row in variable), aggregate.total))
    if len(integer_rows) == len(aggregates):
        return tuple(integer_rows), "", count, "independent_integer_bounds"
    if not config.numeric_bounds:
        return (), "numeric_bounds_disabled", count, "exhaustive"
    if not numeric.runtime_supported():
        return (), "numeric_environment_unsupported", count, "exhaustive"
    try:
        rows = tuple(numeric.make_bound(*row) for row in data)
    except (ValueError, OverflowError):
        return (), "numeric_enclosure_range", count, "exhaustive"
    return rows, "", count, "independent_binary64_bounds"


def _result(base, audit, solution=None, preserve_legacy=False):
    solution = solution or {}
    group = "v518_" + hashlib.sha256(json.dumps([audit.binding, sorted(solution.items())]).encode()).hexdigest()
    proposed = {candidate.cell for candidate in base.candidates}
    decisions = []
    for decision in base.decisions:
        if preserve_legacy:
            decisions.append(decision)
            continue
        accept = decision.cell in solution and base.repair_policy == "structural"
        state = "accepted" if accept else "rejected" if decision.cell in proposed and base.repair_policy == "reject_all" else "review" if decision.cell in proposed else "abstained"
        decisions.append(RepairDecision(decision.cell, state, solution[decision.cell] if accept else None, audit.status,
                                        group if accept else "", len(solution) if accept else 0, 1.0 if accept else 0.0))
    return JointDiagnosis(base.backend, base.repair_policy, base.localization, base.candidates, tuple(decisions), audit)


def compose_joint_diagnosis(model, localization, *, backend="v4", documents=(), approvals=None,
                            as_of: date, repair_policy="structural", config: SearchParameters | None = None):
    config = config or SearchParameters()
    documents, approvals = tuple(documents), approvals or {}
    base = compose_edge_diagnosis(model, localization, backend=backend, edge_mode="propose_only", repair_policy=repair_policy)
    runtime = _runtime()
    try:
        aggregates = approved_aggregates(model, documents, approvals, as_of)
        if not aggregates:
            return _result(base, SearchAudit("no_approved_constraints", runtime_json=runtime), preserve_legacy=True)
        original = _satisfaction(model, aggregates, {})
    except EVALUATION_ERRORS as exc:
        return _result(base, SearchAudit("constraint_rejected:" + str(exc), runtime_json=runtime), preserve_legacy=True)
    if all(original.values()):
        return _result(base, SearchAudit("original_satisfies_constraints", evaluated=1, solutions_seen=1, runtime_json=runtime))
    cells, options = _domain(model, aggregates)
    suffix = _suffix_sizes(options)
    binding = _binding(model, documents, approvals, as_of, cells, options, runtime)
    rows, fallback, preparations, engine = (), "pruning_disabled", 0, "exhaustive"
    try:
        if config.pruning:
            rows, fallback, preparations, engine = _bounds(model, aggregates, cells, options, config)
    except EVALUATION_ERRORS as exc:
        return _result(base, SearchAudit("evaluation_incomplete", space_size=suffix[0], candidate_cells=len(cells),
                                        preparation_evaluations=getattr(exc, "count", 0), binding=binding, runtime_json=runtime))
    stack, terminals, solutions = [()], [], []
    visited = evaluated = pruned = 0
    stopped = ""
    while stack:
        if visited >= config.max_nodes:
            stopped = "budget_exceeded"
            break
        prefix = stack.pop()
        visited += 1
        excluded = next((i for i, row in enumerate(rows) if row.excludes(prefix)), None)
        if excluded is not None:
            terminals.append(Terminal(prefix, excluded))
            pruned += suffix[len(prefix)]
        elif len(prefix) == len(cells):
            if evaluated >= config.max_evaluations:
                stopped = "budget_exceeded"
                break
            evaluated += 1
            overrides = _overrides(cells, options, prefix)
            try:
                satisfied = _satisfaction(model, aggregates, overrides)
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
            stack.extend((*prefix, v) for v in reversed(range(len(options[len(prefix)]))))
    complete = not stack and not stopped
    status = stopped or ("unique_solution" if len(solutions) == 1 else "no_solution")
    audit = SearchAudit(status, suffix[0], len(cells), visited, evaluated, preparations, pruned, len(solutions),
                        complete, engine, fallback, binding, tuple(terminals), numeric.RULE_VERSION, runtime)
    return _result(base, audit, solutions[0] if status == "unique_solution" and complete else None)


def verify_unique_solution(model, diagnosis, *, documents, approvals, as_of):
    audit = diagnosis.search
    if audit.status != "unique_solution" or not audit.complete or audit.solutions_seen != 1:
        raise ValueError("missing complete uniqueness claim")
    if audit.numeric_rule != numeric.RULE_VERSION or audit.runtime_json != _runtime():
        raise ValueError("numeric rule or runtime mismatch")
    documents = tuple(documents)
    aggregates = approved_aggregates(model, documents, approvals, as_of)
    if not aggregates or all(_satisfaction(model, aggregates, {}).values()):
        raise ValueError("no unsatisfied approved constraints")
    cells, options = _domain(model, aggregates)
    suffix = _suffix_sizes(options)
    if audit.binding != _binding(model, documents, approvals, as_of, cells, options, audit.runtime_json):
        raise ValueError("proof input binding mismatch")
    if audit.space_size != suffix[0] or audit.candidate_cells != len(cells):
        raise ValueError("proof candidate domain mismatch")
    rows = ()
    if audit.engine in {"independent_integer_bounds", "independent_binary64_bounds"}:
        rows, reason, _, engine = _bounds(model, aggregates, cells, options,
                                          SearchParameters(max_preparations=2 * (1 + sum(len(v)-1 for v in options))))
        if reason or not rows or engine != audit.engine:
            raise ValueError("unsupported proof bounds")
    elif audit.engine != "exhaustive":
        raise ValueError("unknown proof engine")
    cursor = evaluated = pruned = 0
    solutions = []
    for terminal in audit.terminals:
        prefix = terminal.prefix
        if len(prefix) > len(cells) or any(type(v) is not int or not 0 <= v < len(options[i]) for i, v in enumerate(prefix)):
            raise ValueError("invalid proof prefix")
        start = sum(v * suffix[i+1] for i, v in enumerate(prefix))
        if start != cursor:
            raise ValueError("proof overlap, gap, or order mismatch")
        size = suffix[len(prefix)]
        cursor += size
        if type(terminal.constraint) is not int:
            raise ValueError("invalid proof constraint")
        if terminal.constraint >= 0:
            if terminal.constraint >= len(rows) or not rows[terminal.constraint].excludes(prefix):
                raise ValueError("unsound numeric pruning certificate")
            pruned += size
        elif terminal.constraint == -1 and len(prefix) == len(cells):
            evaluated += 1
            overrides = _overrides(cells, options, prefix)
            if all(_satisfaction(model, aggregates, overrides).values()):
                solutions.append(overrides)
        else:
            raise ValueError("unevaluated proof leaf")
    if cursor != suffix[0] or pruned != audit.pruned_states or evaluated != audit.evaluated or len(solutions) != 1:
        raise ValueError("incomplete uniqueness proof")
    expected = solutions[0] if diagnosis.repair_policy == "structural" else {}
    actions = {d.cell: d.accepted_formula for d in diagnosis.decisions if d.accepted_formula is not None}
    if actions != expected:
        raise ValueError("actions differ from unique solution")
    group = "v518_" + hashlib.sha256(json.dumps([audit.binding, sorted(solutions[0].items())]).encode()).hexdigest()
    if any(d.state != "accepted" or d.group_id != group or d.group_size != len(expected)
           for d in diagnosis.decisions if d.accepted_formula is not None):
        raise ValueError("invalid atomic repair group")
    if len({d.cell for d in diagnosis.decisions}) != len(diagnosis.decisions) or {d.cell for d in diagnosis.decisions} != set(model.formulas):
        raise ValueError("incomplete repair decisions")
    return solutions[0]


def diagnose_v5_1_8_development(model, *, localization_backend="v4", **kwargs):
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    ranking = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    return compose_joint_diagnosis(model, ranking, backend=localization_backend, **kwargs)


def v5_1_8_development_scores(model, **kwargs):
    return diagnose_v5_1_8_development(model, **kwargs).to_results()
