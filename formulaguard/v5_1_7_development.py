"""Complete candidate-space search with replayable exact-integer bound proofs.

Bounds apply only to independent aggregate-member values whose absolute sum is
at most 2**52. All other models retain bounded exhaustive search. A pruned prefix
accounts for every assignment below it, never for a reduced candidate domain.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from .localize import v4_scores
from .v5_1_1_development import v5_1_1_development_scores
from .v5_1_3_development import Diagnosis, RepairDecision
from .v5_1_4_development import compose_edge_diagnosis, edge_proposals
from .v5_1_5_development import _satisfaction, approved_aggregates, model_binding
from .v5_1_development import _signature

MODEL_VERSION = "v5.1.7-development"
EVALUATION_ERRORS = (ValueError, TypeError, KeyError, OverflowError, RecursionError)


@dataclass(frozen=True)
class SearchParameters:
    max_nodes: int = 10000
    max_evaluations: int = 4096
    max_preparations: int = 4096
    pruning: bool = True

    def __post_init__(self):
        for name in ("max_nodes", "max_evaluations", "max_preparations"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.pruning, bool):
            raise TypeError("pruning must be boolean")


@dataclass(frozen=True)
class Terminal:
    prefix: tuple[int, ...]
    # -1 is an evaluated full assignment; otherwise this names a bound row.
    constraint: int = -1


@dataclass(frozen=True)
class SearchAudit:
    status: str
    space_size: int = 0
    candidate_cells: int = 0
    visited: int = 0
    evaluated: int = 0
    preparation_evaluations: int = 0
    pruned_states: int = 0
    solutions_seen: int = 0
    complete: bool = False
    engine: str = "not_started"
    fallback_reason: str = ""
    binding: str = ""
    terminals: tuple[Terminal, ...] = ()


@dataclass(frozen=True)
class JointDiagnosis(Diagnosis):
    search: SearchAudit = SearchAudit("not_started")

    def to_results(self):
        results = super().to_results()
        for result in results:
            result.evidence.update(
                model_version=MODEL_VERSION, search_status=self.search.status,
                search_space=self.search.space_size, search_evaluated=self.search.evaluated,
                search_complete=self.search.complete, solutions_seen=self.search.solutions_seen,
                search_engine=self.search.engine, search_pruned_states=self.search.pruned_states,
                search_binding=self.search.binding,
            )
        return results


@dataclass(frozen=True)
class Bound:
    constant: int
    contributions: tuple[tuple[int, ...], ...]
    total: float

    def excludes(self, prefix):
        fixed = self.constant + sum(self.contributions[i][v] for i, v in enumerate(prefix))
        remaining = self.contributions[len(prefix):]
        low = fixed + sum(min(values) for values in remaining)
        high = fixed + sum(max(values) for values in remaining)
        # All possible sums are exactly representable. On either side of total,
        # math.isclose acceptance is monotone toward total, including its tolerance.
        return ((low > self.total and not math.isclose(float(low), self.total, rel_tol=1e-10, abs_tol=1e-8))
                or (high < self.total and not math.isclose(float(high), self.total, rel_tol=1e-10, abs_tol=1e-8)))


class _PreparationFailure(ValueError):
    def __init__(self, count):
        super().__init__("candidate preparation could not be evaluated")
        self.count = count


def _domain(model, aggregates):
    members = {cell for aggregate in aggregates for cell in aggregate.members}
    choices = defaultdict(dict)
    for proposal in edge_proposals(model):
        if proposal.bounded_edit and proposal.cell in members:
            choices[proposal.cell][_signature(proposal.formula, proposal.cell[1])] = proposal.formula
    cells = tuple(sorted(choices))
    options = tuple((None, *(formula for _, formula in sorted(choices[cell].items()))) for cell in cells)
    return cells, options


def _binding(model, documents, approvals, as_of, cells, options):
    payload = [model_binding(model), [hashlib.sha256(d).hexdigest() for d in documents],
               sorted(approvals.items()), as_of.isoformat(), cells, options, MODEL_VERSION]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _bounds(model, aggregates, cells, options, max_preparations):
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
                return (), "candidate_dependency", 0
            pending.extend(graph.get(cell, ()))
    required = 2 * (1 + sum(len(values) - 1 for values in options))
    if required > max_preparations:
        return (), "preparation_budget", 0
    count = 0

    def checked_values(overrides):
        nonlocal count
        # The original evaluator also checks missing references, range limits,
        # unsupported computation and cycles for every variant, not just its value.
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

    original = checked_values({})
    value_options = {}
    for cell, values in zip(cells, options, strict=True):
        value_options[cell] = (original[cell], *(checked_values({cell: formula})[cell] for formula in values[1:]))
    rows = []
    for aggregate in aggregates:
        fixed = [float(original[cell]) for cell in aggregate.members if cell not in candidates]
        variable = tuple(tuple(float(value) for value in value_options[cell]) if cell in aggregate.members
                         else tuple(0.0 for _ in values) for cell, values in zip(cells, options, strict=True))
        all_values = [*fixed, *(value for values in variable for value in values)]
        if any(not math.isfinite(value) or not value.is_integer() for value in all_values):
            return (), "nonintegral_values", count
        magnitude = sum(abs(int(value)) for value in fixed) + sum(max(abs(int(value)) for value in values) for values in variable)
        if magnitude > 2**52:
            return (), "integer_sum_range", count
        rows.append(Bound(sum(int(value) for value in fixed),
                          tuple(tuple(int(value) for value in values) for values in variable), aggregate.total))
    return tuple(rows), "", count


def _overrides(cells, options, assignment):
    return {cell: options[i][v] for i, (cell, v) in enumerate(zip(cells, assignment, strict=True)) if v}


def _suffix_sizes(options):
    sizes = [1] * (len(options) + 1)
    for i in range(len(options) - 1, -1, -1):
        sizes[i] = sizes[i + 1] * len(options[i])
    return sizes


def compose_joint_diagnosis(model, localization, *, backend="v4", documents=(), approvals=None,
                            as_of: date, repair_policy="structural", config: SearchParameters | None = None):
    config = config or SearchParameters()
    documents, approvals = tuple(documents), approvals or {}
    base = compose_edge_diagnosis(model, localization, backend=backend, edge_mode="propose_only", repair_policy=repair_policy)

    def result(audit, solution=None, preserve_legacy=False):
        solution = solution or {}
        group = "v517_" + hashlib.sha256(json.dumps([audit.binding, sorted(solution.items())]).encode()).hexdigest()
        proposed = {candidate.cell for candidate in base.candidates}
        decisions = []
        for decision in base.decisions:
            if preserve_legacy:
                decisions.append(decision)
                continue
            accept = decision.cell in solution and repair_policy == "structural"
            state = "accepted" if accept else "rejected" if decision.cell in proposed and repair_policy == "reject_all" else "review" if decision.cell in proposed else "abstained"
            decisions.append(RepairDecision(decision.cell, state, solution[decision.cell] if accept else None,
                                            audit.status, group if accept else "", len(solution) if accept else 0,
                                            1.0 if accept else 0.0))
        return JointDiagnosis(base.backend, base.repair_policy, base.localization, base.candidates, tuple(decisions), audit)

    try:
        aggregates = approved_aggregates(model, documents, approvals, as_of)
        if not aggregates:
            return result(SearchAudit("no_approved_constraints"), preserve_legacy=True)
        original = _satisfaction(model, aggregates, {})
    except EVALUATION_ERRORS as exc:
        return result(SearchAudit("constraint_rejected:" + str(exc)), preserve_legacy=True)
    if all(original.values()):
        return result(SearchAudit("original_satisfies_constraints", evaluated=1, solutions_seen=1))
    cells, options = _domain(model, aggregates)
    suffix = _suffix_sizes(options)
    binding = _binding(model, documents, approvals, as_of, cells, options)
    rows, fallback, preparations = (), "pruning_disabled", 0
    try:
        if config.pruning:
            rows, fallback, preparations = _bounds(model, aggregates, cells, options, config.max_preparations)
    except EVALUATION_ERRORS as exc:
        return result(SearchAudit("evaluation_incomplete", space_size=suffix[0], candidate_cells=len(cells),
                                  preparation_evaluations=getattr(exc, "count", 0), binding=binding))
    engine = "independent_integer_bounds" if rows else "exhaustive"
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
            stack.extend((*prefix, value) for value in reversed(range(len(options[len(prefix)]))))
    complete = not stack and not stopped
    status = stopped or ("unique_solution" if len(solutions) == 1 else "no_solution")
    audit = SearchAudit(status, suffix[0], len(cells), visited, evaluated, preparations, pruned,
                        len(solutions), complete, engine, fallback, binding, tuple(terminals))
    return result(audit, solutions[0] if status == "unique_solution" and complete else None)


def verify_unique_solution(model, diagnosis, *, documents, approvals, as_of):
    """Replay the complete prefix partition and its bounds against current inputs.

    This does not rerun the search traversal. It rebuilds bounds from the workbook,
    checks disjoint coverage of the original domain, and evaluates every remaining
    leaf. Ranking provenance is checked separately against the selected backend.
    """
    audit = diagnosis.search
    if audit.status != "unique_solution" or not audit.complete or audit.solutions_seen != 1:
        raise ValueError("missing complete uniqueness claim")
    documents = tuple(documents)
    aggregates = approved_aggregates(model, documents, approvals, as_of)
    if not aggregates or all(_satisfaction(model, aggregates, {}).values()):
        raise ValueError("no unsatisfied approved constraints")
    cells, options = _domain(model, aggregates)
    suffix = _suffix_sizes(options)
    if audit.binding != _binding(model, documents, approvals, as_of, cells, options):
        raise ValueError("proof input binding mismatch")
    if audit.space_size != suffix[0] or audit.candidate_cells != len(cells):
        raise ValueError("proof candidate domain mismatch")
    rows = ()
    if audit.engine == "independent_integer_bounds":
        rows, reason, _ = _bounds(model, aggregates, cells, options, 2 * (1 + sum(len(v) - 1 for v in options)))
        if not rows or reason:
            raise ValueError("invalid independent bounds")
    elif audit.engine != "exhaustive":
        raise ValueError("unknown proof engine")
    cursor = evaluated = pruned = 0
    solutions = []
    for terminal in audit.terminals:
        prefix = terminal.prefix
        if len(prefix) > len(cells) or any(type(v) is not int or not 0 <= v < len(options[i]) for i, v in enumerate(prefix)):
            raise ValueError("invalid proof prefix")
        start = sum(v * suffix[i + 1] for i, v in enumerate(prefix))
        if start != cursor:
            raise ValueError("proof overlap, gap, or order mismatch")
        size = suffix[len(prefix)]
        cursor += size
        if type(terminal.constraint) is not int:
            raise ValueError("invalid proof constraint")
        if terminal.constraint >= 0:
            if terminal.constraint >= len(rows) or not rows[terminal.constraint].excludes(prefix):
                raise ValueError("unsound pruning certificate")
            pruned += size
        elif terminal.constraint == -1 and len(prefix) == len(cells):
            evaluated += 1
            overrides = _overrides(cells, options, prefix)
            if all(_satisfaction(model, aggregates, overrides).values()):
                solutions.append(overrides)
        else:
            raise ValueError("unevaluated proof leaf")
    if cursor != suffix[0] or pruned != audit.pruned_states or evaluated != audit.evaluated:
        raise ValueError("incomplete proof accounting")
    if len(solutions) != 1:
        raise ValueError("proof does not establish uniqueness")
    actions = {d.cell: d.accepted_formula for d in diagnosis.decisions if d.accepted_formula is not None}
    expected = solutions[0] if diagnosis.repair_policy == "structural" else {}
    if actions != expected:
        raise ValueError("actions differ from unique solution")
    accepted = [d for d in diagnosis.decisions if d.accepted_formula is not None]
    group = "v517_" + hashlib.sha256(json.dumps([audit.binding, sorted(solutions[0].items())]).encode()).hexdigest()
    if any(d.state != "accepted" or d.group_id != group or d.group_size != len(expected) for d in accepted):
        raise ValueError("invalid atomic repair group")
    if len({d.cell for d in diagnosis.decisions}) != len(diagnosis.decisions) or {d.cell for d in diagnosis.decisions} != set(model.formulas):
        raise ValueError("incomplete repair decisions")
    return solutions[0]


def diagnose_v5_1_7_development(model, *, localization_backend="v4", **kwargs):
    if localization_backend not in {"v4", "v511"}:
        raise ValueError("unknown localization backend")
    ranking = (v4_scores if localization_backend == "v4" else v5_1_1_development_scores)(model)
    return compose_joint_diagnosis(model, ranking, backend=localization_backend, **kwargs)


def v5_1_7_development_scores(model, **kwargs):
    return diagnose_v5_1_7_development(model, **kwargs).to_results()
