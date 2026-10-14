import math
from dataclasses import replace
from itertools import product

import pytest

from formulaguard.v5_1_5_development import (
    Aggregate,
    _satisfaction,
    approved_aggregates,
)
from formulaguard.v5_1_7_development import _domain
from formulaguard.v519_components import (
    PreparationRefused,
    build_component_tables,
    component_bounds,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_v519_component_cases import (
    FAMILIES,
    STRUCTURES,
    build_component_case,
)
from scripts.v518_validation_common import AS_OF, load_model


def fixture(family="product", structure="pair", count=4):
    raw, document, approval, _ = build_component_case(count, family, structure)
    model = load_model(raw)
    aggregates = approved_aggregates(model, [document], approval, AS_OF)
    cells, options = _domain(model, aggregates)
    return model, aggregates, cells, options


def check_all(model, aggregates, cells, options):
    tables = build_component_tables(model, aggregates, cells, options)
    bounds = component_bounds(tables, aggregates)
    visited = set()
    for selection in product(*(range(len(c.assignments)) for c in tables.components)):
        original = tables.to_original(selection)
        assert original not in visited
        visited.add(original)
        assert tables.from_original(original) == selection
        overrides = {cell: values[i] for cell, values, i in zip(cells, options, original, strict=True) if i}
        reconstructed = tables.member_values(selection)
        values, errors = model.evaluate(overrides=overrides, targets=set(reconstructed))
        assert not errors
        assert {c: float(values[c]).hex() for c in reconstructed} == {c: v.hex() for c, v in reconstructed.items()}
        satisfied = _satisfaction(model, aggregates, overrides)
        for a, bound in zip(aggregates, bounds, strict=True):
            actual = math.fsum(float(values[c]) for c in a.members)
            assert bound.member_count == len(a.members)
            for length in range(len(selection)+1):
                low, high = bound.interval(selection[:length])
                assert low <= actual <= high
                if satisfied[a.identifier]:
                    assert not bound.excludes(selection[:length])
    assert visited == set(product(*(range(len(o)) for o in options)))
    return tables


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("structure", STRUCTURES)
def test_real_dependency_tables_match_all_global_assignments(family, structure):
    args = fixture(family, structure)
    before = dict(args[0].formulas), dict(args[0].cells)
    tables = check_all(*args)
    expected = {"pair": 2, "chain": 3, "fan_in": 3, "shared_bridge": 4}[structure]
    assert max(len(c.indices) for c in tables.components) == expected
    assert before == (args[0].formulas, args[0].cells)
    original = tables.member_values(tables.from_original((0,)*4))
    changed = tables.member_values(tables.from_original((1,0,0,0)))
    assert any(changed[c] != original[c] for c in tables.cells[1:])


@pytest.mark.parametrize("counts", [(3,3,3,3), (3,3,2,2,2,2)])
def test_multi_option_domains_preserve_all_assignments(counts):
    model, aggregates, cells, options = fixture(count=len(counts))
    expanded = tuple((*o, o[1]+"+0") if n == 3 else o for o, n in zip(options, counts, strict=True))
    tables = check_all(model, aggregates, cells, expanded)
    assert tables.space_size == math.prod(counts)


def custom(formulas, choices, constants=None):
    model = WorkbookModel.from_cells(constants or {}, formulas)
    cells = tuple(sorted(choices))
    options = tuple((None, *choices[c]) for c in cells)
    aggregates = (Aggregate("test", tuple(sorted(formulas)), 4.0, "test-only"),)
    return model, aggregates, cells, options


@pytest.mark.parametrize("candidate_only", [False, True])
def test_original_and_candidate_only_references_merge_supports(candidate_only):
    a, b, bridge = ("S", "A1"), ("S", "A2"), ("T", "B1")
    formula, choice = ("=1", "='T'!B1+1") if candidate_only else ("='T'!B1+1", "=1")
    args = custom({a: "=1", b: formula, bridge: "='S'!A1*0.125"}, {a: ("=2",), b: (choice,)})
    tables = check_all(*args)
    assert len(tables.components) == 1 and bridge in tables.components[0].members


def test_equal_values_do_not_merge_distinct_formula_assignments():
    a, b = ("S", "A1"), ("S", "A2")
    args = custom({a: "=1", b: "=3"}, {a: ("=1+0",), b: ("=3+0",)})
    tables = check_all(*args)
    assert tables.space_size == 4
    assert all(len(c.assignments) == 2 and c.values[0] == c.values[1] for c in tables.components)


def test_member_values_avoid_double_rounding_and_preserve_absolute_magnitude():
    a, b, c, d = (("S", f"A{i}") for i in range(1, 5))
    args = custom({a: "=1e16", b: "=A1*0+1", c: "=-1e16", d: "=1"},
                  {a: ("=1e16+0",), c: ("=-1e16+0",)})
    _, aggregates, _, _ = args
    tables = check_all(*args)
    vals = tables.member_values((0,0))
    assert math.fsum(vals.values()) == 2.0
    grouped = [math.fsum(component.values[0]) for component in tables.components]
    assert math.fsum([*grouped, *(v for _, v in tables.fixed)]) == 1.0
    bound = component_bounds(tables, aggregates)[0]
    assert bound.magnitude >= 2*10**16 and bound.member_count == 4


@pytest.mark.parametrize("defect,reason", [
    ("missing", "absent_reference"), ("cycle", "union_cycle"),
    ("unknown", "evaluation_incomplete"), ("nonfinite", "evaluation_incomplete"),
    ("range", "range_limit"),
])
def test_unsupported_preparation_has_no_partial_table(defect, reason):
    a, b = ("S", "A1"), ("S", "A2")
    bad = {"missing": "=Z99", "cycle": "=A2", "unknown": "=UNKNOWN(1)",
           "nonfinite": "=1e308*1e308", "range": "=SUM(B1:B10001)"}[defect]
    args = custom({a: "=1", b: "=A1+1"}, {a: (bad,)})
    with pytest.raises(PreparationRefused) as caught:
        build_component_tables(*args)
    assert caught.value.reason == reason


def test_budget_precheck_and_actual_evaluation_count(monkeypatch):
    model, aggregates, cells, options = fixture()
    original = model.evaluate
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(model, "evaluate", counted)
    for kw, reason in (({"max_preparations": 17}, "preparation_budget"),
                       ({"max_component_states": 3}, "component_state_limit")):
        with pytest.raises(PreparationRefused) as caught:
            build_component_tables(model, aggregates, cells, options, **kw)
        assert caught.value.reason == reason and caught.value.evaluations == 0 and not calls
    tables = build_component_tables(model, aggregates, cells, options, max_preparations=18)
    assert tables.preparation_evaluations == len(calls) == 18


def test_unknown_environment_refuses_bounds(monkeypatch):
    from formulaguard import v519_components as module
    model, aggregates, cells, options = fixture()
    tables = build_component_tables(model, aggregates, cells, options)
    monkeypatch.setattr(module, "runtime_supported", lambda: False)
    with pytest.raises(PreparationRefused, match="numeric_environment_unsupported"):
        component_bounds(tables, aggregates)


def test_invalid_assignment_and_domain_are_rejected():
    args = fixture()
    tables = build_component_tables(*args)
    for assignment in ((), (-1,0,0,0), (True,0,0,0), (2,0,0,0)):
        with pytest.raises(ValueError):
            tables.from_original(assignment)
    for selection in ((), (-1,0,0), (True,0,0), (99,0,0)):
        with pytest.raises(ValueError):
            tables.to_original(selection)
    with pytest.raises(ValueError):
        build_component_tables(args[0], args[1], args[2], (("=1",),)*4)


def test_no_candidate_domain_has_exactly_one_assignment():
    a, b = ("S", "A1"), ("S", "A2")
    tables = check_all(*custom({a: "=1", b: "=3"}, {}))
    assert tables.space_size == 1 and not tables.components


def test_bound_range_guard_counts_original_members():
    model, aggregates, cells, options = fixture()
    tables = build_component_tables(model, aggregates, cells, options)
    excessive = replace(aggregates[0], members=aggregates[0].members * 200)
    with pytest.raises(ValueError, match="outside reviewed domain"):
        component_bounds(tables, [excessive])


@pytest.mark.parametrize("backend", ["v4", "v511"])
def test_prototype_preserves_existing_backend_diagnoses(backend):
    from formulaguard.localize import v4_scores
    from formulaguard.v5_1_1_development import v5_1_1_development_scores
    from formulaguard.v5_1_8_development import compose_joint_diagnosis
    raw, document, approvals, _ = build_component_case(4, structure="chain")
    model = load_model(raw)
    ranker = v4_scores if backend == "v4" else v5_1_1_development_scores
    ranking = ranker(model)
    args = {"backend": backend, "documents": [document], "approvals": approvals, "as_of": AS_OF}
    before = compose_joint_diagnosis(model, ranking, **args)
    aggregates = approved_aggregates(model, [document], approvals, AS_OF)
    cells, options = _domain(model, aggregates)
    build_component_tables(model, aggregates, cells, options)
    after = compose_joint_diagnosis(model, ranker(model), **args)
    assert before == after
    assert [(r.cell, float(r.score).hex()) for r in ranking] == [
        (r.cell, float(r.score).hex()) for r in after.to_results()]
