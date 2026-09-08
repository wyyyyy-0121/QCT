"""G1 component tables; no repair acceptance or uniqueness certificate API."""

from __future__ import annotations

import math
from dataclasses import dataclass
from fractions import Fraction
from itertools import product

from .a1 import iter_rect
from .formula import Range, iter_refs
from .v5_1_5_development import _satisfaction
from .v5_1_7_development import EVALUATION_ERRORS
from .v518_numeric_bounds import NumericBound, runtime_supported
from .workbook import CellKey


class PreparationRefused(ValueError):
    def __init__(self, reason, evaluations=0):
        super().__init__(reason)
        self.reason = reason
        self.evaluations = evaluations


@dataclass(frozen=True)
class Component:
    indices: tuple[int, ...]
    members: tuple[CellKey, ...]
    assignments: tuple[tuple[int, ...], ...]
    values: tuple[tuple[float, ...], ...]


@dataclass(frozen=True)
class ComponentTables:
    cells: tuple[CellKey, ...]
    options: tuple[tuple[str | None, ...], ...]
    fixed: tuple[tuple[CellKey, float], ...]
    components: tuple[Component, ...]
    preparation_evaluations: int
    graph_edges: int

    @property
    def space_size(self):
        return math.prod(map(len, self.options))

    def to_original(self, selection):
        if len(selection) != len(self.components):
            raise ValueError("invalid component selection length")
        original = [0] * len(self.cells)
        for component, choice in zip(self.components, selection, strict=True):
            if type(choice) is not int or not 0 <= choice < len(component.assignments):
                raise ValueError("invalid component choice")
            for index, value in zip(component.indices, component.assignments[choice], strict=True):
                original[index] = value
        return tuple(original)

    def from_original(self, assignment):
        if len(assignment) != len(self.options) or any(
            type(v) is not int or not 0 <= v < len(o) for v, o in zip(assignment, self.options, strict=True)
        ):
            raise ValueError("invalid original assignment")
        return tuple(c.assignments.index(tuple(assignment[i] for i in c.indices)) for c in self.components)

    def member_values(self, selection):
        self.to_original(selection)
        values = dict(self.fixed)
        for component, choice in zip(self.components, selection, strict=True):
            values.update(zip(component.members, component.values[choice], strict=True))
        return values


def _union_graph(model, targets, cells, options):
    variants = {cell: (model.formulas[cell], *values[1:]) for cell, values in zip(cells, options, strict=True)}
    graph, pending = {}, list(targets)
    while pending:
        cell = pending.pop()
        if cell in graph:
            continue
        if cell not in model.cells and cell not in model.formulas:
            raise PreparationRefused("absent_reference")
        refs = set()
        for formula in variants.get(cell, (model.formulas[cell],) if cell in model.formulas else ()):
            for ref in iter_refs(model.ast(formula)):
                if isinstance(ref, Range):
                    start, end = ref.start.address, ref.end.address
                    if (abs(start.row-end.row)+1) * (abs(start.col-end.col)+1) > 10000:
                        raise PreparationRefused("range_limit")
                    sheet = ref.start.sheet or ref.end.sheet or cell[0]
                    refs.update((sheet, address) for address in iter_rect(start, end))
                else:
                    refs.add((ref.sheet or cell[0], ref.address.a1.replace("$", "")))
        graph[cell] = refs
        pending.extend(refs)
    # A union-cycle can be conservative even if each concrete variant is acyclic.
    # G1 refuses it rather than infer independence from a cyclic support graph.
    incoming = {cell: len(refs) for cell, refs in graph.items()}
    dependents = {cell: set() for cell in graph}
    for cell, refs in graph.items():
        for ref in refs:
            dependents[ref].add(cell)
    ready = [cell for cell, count in incoming.items() if count == 0]
    visited = 0
    while ready:
        cell = ready.pop()
        visited += 1
        for child in dependents[cell]:
            incoming[child] -= 1
            if incoming[child] == 0:
                ready.append(child)
    if visited != len(graph):
        raise PreparationRefused("union_cycle")
    return graph


def build_component_tables(model, aggregates, cells, options, *, max_component_states=256, max_preparations=4096):
    """Enumerate each dependency component using the original evaluator.

    The caller supplies the unchanged V517 domain. Explicit domains support G1
    multi-option tests; this function does not generate or authorize candidates.
    """
    cells, options = tuple(cells), tuple(tuple(o) for o in options)
    if any(type(v) is not int or v < 1 for v in (max_component_states, max_preparations)):
        raise ValueError("invalid preparation budget")
    targets = {cell for a in aggregates for cell in a.members}
    if (len(cells) != len(options) or len(set(cells)) != len(cells) or not set(cells) <= targets
            or not set(cells) <= set(model.formulas) or any(not o or o[0] is not None
                or any(not isinstance(f, str) for f in o[1:]) for o in options)):
        raise ValueError("invalid candidate domain")
    count = 0
    try:
        graph = _union_graph(model, targets, cells, options)
        supports = {}
        neighbors = {i: set() for i in range(len(cells))}
        indices = {cell: i for i, cell in enumerate(cells)}
        for target in sorted(targets):
            pending, seen = [target], set()
            while pending:
                cell = pending.pop()
                if cell in seen:
                    continue
                seen.add(cell)
                pending.extend(graph[cell])
            support = {indices[c] for c in seen if c in indices}
            supports[target] = support
            for i in support:
                neighbors[i].update(support - {i})
        groups, unseen = [], set(neighbors)
        while unseen:
            pending, group = [min(unseen)], set()
            while pending:
                i = pending.pop()
                if i in group:
                    continue
                group.add(i)
                pending.extend(neighbors[i] - group)
            unseen -= group
            groups.append(tuple(sorted(group)))
        sizes = [math.prod(len(options[i]) for i in g) for g in groups]
        if any(size > max_component_states for size in sizes):
            raise PreparationRefused("component_state_limit")
        if 2 * (1 + sum(sizes)) > max_preparations:
            raise PreparationRefused("preparation_budget")

        def checked(overrides):
            nonlocal count
            # _satisfaction performs one evaluate on these prevalidated graphs;
            # retain a separate evaluate to collect the actual member floats.
            count += 1
            _satisfaction(model, aggregates, overrides)
            count += 1
            values, errors = model.evaluate(overrides=overrides, targets=targets)
            if errors or any(isinstance(values.get(c), bool) or not isinstance(values.get(c), (int, float))
                             or not math.isfinite(values[c]) for c in targets):
                raise PreparationRefused("evaluation_incomplete", count)
            return {c: float(values[c]) for c in targets}

        original = checked({})
        components = []
        for group in groups:
            members = tuple(c for c, support in supports.items() if support & set(group))
            assert all(supports[c] <= set(group) for c in members)
            assignments = tuple(product(*(range(len(options[i])) for i in group)))
            rows = []
            for assignment in assignments:
                overrides = {cells[i]: options[i][v] for i, v in zip(group, assignment, strict=True) if v}
                values = checked(overrides)
                rows.append(tuple(values[c] for c in members))
            components.append(Component(group, members, assignments, tuple(rows)))
        fixed = tuple((c, original[c]) for c in sorted(targets) if not supports[c])
        return ComponentTables(cells, options, fixed, tuple(components), count, sum(map(len, graph.values())))
    except PreparationRefused:
        raise
    except EVALUATION_ERRORS as exc:
        raise PreparationRefused("evaluation_incomplete", count) from exc


def component_bounds(tables, aggregates):
    """Exact member-float sums, with V518's original binary64 envelope."""
    if not runtime_supported():
        raise PreparationRefused("numeric_environment_unsupported", tables.preparation_evaluations)
    bounds = []
    for aggregate in aggregates:
        members = set(aggregate.members)
        fixed = [Fraction.from_float(v) for c, v in tables.fixed if c in members]
        contributions, magnitude = [], sum(map(abs, fixed), Fraction())
        for component in tables.components:
            rows = [tuple(Fraction.from_float(v) for c, v in zip(component.members, row, strict=True) if c in members)
                    for row in component.values]
            contributions.append(tuple(sum(row, Fraction()) for row in rows))
            magnitude += max(sum(map(abs, row), Fraction()) for row in rows)
        bounds.append(NumericBound(sum(fixed, Fraction()), tuple(contributions), aggregate.total,
                                   len(aggregate.members), magnitude))
    return tuple(bounds)
