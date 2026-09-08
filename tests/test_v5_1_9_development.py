from dataclasses import replace
from itertools import product

import pytest

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_5_development import _satisfaction, approved_aggregates
from formulaguard.v5_1_7_development import _domain, _overrides
from formulaguard.v5_1_8_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_9_development import (
    Budget,
    BudgetExceeded,
    SearchParameters,
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v518_numeric_cases import FAMILIES, KINDS, build_case
from scripts.build_v519_component_cases import STRUCTURES, build_component_case
from scripts.v518_validation_common import AS_OF, actions, check_identity, load_model


def fixture(family="product", kind="pair", count=4, backend="v511"):
    raw, doc, approvals, label = (build_component_case(count, family, kind) if kind in STRUCTURES
                                  else build_case(count, family, kind))
    model = load_model(raw)
    ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
    return model, ranking, {"documents": [doc], "approvals": approvals, "as_of": AS_OF, "backend": backend}, label


def replay(model, diagnosis, ranking, args, config=None):
    return verify_unique_solution(model, diagnosis, localization=ranking, config=config,
                                  **{k: v for k, v in args.items() if k != "backend"})


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("kind", (*STRUCTURES, *KINDS))
def test_small_full_domain_differential(family, kind):
    model, ranking, args, _ = fixture(family, kind)
    new = compose_joint_diagnosis(model, ranking, **args)
    old = baseline(model, ranking, **args)
    check_identity(model, old, new)
    if not args["approvals"] or new.search.status == "original_satisfies_constraints":
        assert actions(new) == actions(old)
        return
    aggregates = approved_aggregates(model, args["documents"], args["approvals"], AS_OF)
    cells, options = _domain(model, aggregates)
    solutions = [o for p in product(*(range(len(v)) for v in options))
                 if all(_satisfaction(model, aggregates, o := _overrides(cells, options, p)).values())]
    expected = "unique_solution" if len(solutions) == 1 else "no_solution" if not solutions else "ambiguous_solutions"
    assert new.search.status == expected
    if len(solutions) == 1:
        assert actions(new) == solutions[0]
        assert replay(model, new, ranking, args) == solutions[0]
    else:
        assert not actions(new)


@pytest.mark.parametrize("backend", ["v4", "v511"])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_policies_and_full_ranking(backend, policy):
    model, ranking, args, _ = fixture(backend=backend)
    new = compose_joint_diagnosis(model, ranking, repair_policy=policy, **args)
    replay(model, new, ranking, args)
    assert bool(actions(new)) == (policy == "structural")
    assert [(r.cell, r.score.hex()) for r in new.to_results()] == [(r.cell, r.score.hex()) for r in ranking]


@pytest.mark.parametrize("limit", [1, 18, 19])
def test_preparation_count_and_remaining_budget_fallback(limit, monkeypatch):
    model, ranking, args, _ = fixture()
    actual = []
    original = model.evaluate

    def evaluate(*a, **kw):
        actual.append(1)
        return original(*a, **kw)

    # Isolate search accounting from the separate candidate/ranker evaluations.
    from formulaguard import v5_1_9_development as module
    base = module.compose_edge_diagnosis(model, ranking, backend=args["backend"])
    monkeypatch.setattr(module, "compose_edge_diagnosis", lambda *a, **kw: base)
    monkeypatch.setattr(model, "evaluate", evaluate)
    config = SearchParameters(max_preparations=limit, max_evaluations=2)
    new = compose_joint_diagnosis(model, ranking, config=config, **args)
    assert new.search.preparation_evaluations <= limit
    assert new.search.actual_evaluations == len(actual)
    assert new.search.actual_evaluations == new.search.preparation_evaluations + new.search.evaluated
    if limit < 19:
        assert new.search.fallback_reason == "preparation_budget" and new.search.evaluated == 2
        assert new.search.status == "budget_exceeded" and not actions(new)
    else:
        assert new.search.status == "unique_solution" and new.search.preparation_evaluations == 19


def test_component_limit_keeps_full_domain_and_counters():
    model, ranking, args, _ = fixture()
    config = SearchParameters(max_component_states=3, max_evaluations=2)
    new = compose_joint_diagnosis(model, ranking, config=config, **args)
    assert new.search.space_size == 16 and new.search.fallback_reason == "component_state_limit"
    assert new.search.preparation_evaluations == 1 and new.search.evaluated == 2 and not actions(new)


def test_bounds_failure_after_preparation_does_not_reset_counters(monkeypatch):
    from formulaguard import v5_1_9_development as module
    model, ranking, args, _ = fixture()

    def fail(*args):
        raise ValueError("injected enclosure failure")

    monkeypatch.setattr(module, "component_bounds", fail)
    new = compose_joint_diagnosis(model, ranking, config=SearchParameters(max_evaluations=2), **args)
    assert new.search.preparation_evaluations == 19 and new.search.actual_evaluations == 21
    assert new.search.fallback_reason == "numeric_enclosure_range" and not actions(new)


def test_one_solution_then_budget_never_accepts():
    model, ranking, args, _ = fixture(kind="ambiguous", count=2)
    new = compose_joint_diagnosis(model, ranking, config=SearchParameters(pruning=False,max_evaluations=2), **args)
    assert new.search.solutions_seen == 1 and new.search.status == "budget_exceeded" and not actions(new)


@pytest.mark.parametrize("field", ["max_nodes", "max_evaluations", "max_preparations"])
def test_budget_object_never_resets(field):
    budget = Budget(SearchParameters(**{field: 1}))
    phase = {"max_nodes": "node", "max_evaluations": "leaf", "max_preparations": "prepare"}[field]
    budget.consume(phase)
    with pytest.raises(BudgetExceeded):
        budget.consume(phase)


def test_disabled_components_matches_baseline():
    model, ranking, args, _ = fixture(count=8)
    new = compose_joint_diagnosis(model, ranking, config=SearchParameters(components=False), **args)
    old = baseline(model, ranking, **args)
    assert new.search.status == old.search.status and actions(new) == actions(old)
    assert new.search.visited == old.search.visited and new.search.evaluated == old.search.evaluated


def test_multi_option_domain_and_same_value_assignments(monkeypatch):
    from formulaguard import v5_1_9_development as module
    for count, triples in ((4,4), (6,2)):
        model, ranking, args, _ = fixture(count=count)
        aggregates = approved_aggregates(model, args["documents"], args["approvals"], AS_OF)
        cells, options = _domain(model, aggregates)
        options = tuple((*o, o[1]+"+0") if i < triples else o for i, o in enumerate(options))
        monkeypatch.setattr(module, "_domain", lambda *a, c=cells, o=options: (c,o))
        new = compose_joint_diagnosis(model, ranking, **args)
        assert new.search.space_size == (81 if count == 4 else 144)
        assert new.search.status == "ambiguous_solutions" and not actions(new)


def test_unknown_preparation_never_becomes_unique(monkeypatch):
    from formulaguard import v519_components as component
    model, ranking, args, _ = fixture()
    original = component._satisfaction

    def fail(model, aggregates, overrides):
        if overrides:
            raise ValueError("injected unknown")
        return original(model, aggregates, overrides)

    monkeypatch.setattr(component, "_satisfaction", fail)
    new = compose_joint_diagnosis(model, ranking, **args)
    assert new.search.status == "evaluation_incomplete" and not actions(new)
    assert new.search.satisfaction_calls + new.search.direct_evaluate_calls > new.search.actual_evaluations


@pytest.mark.parametrize("defect", ["prefix", "duplicate", "prune", "rule", "runtime", "binding", "complete", "action",
                                    "groups", "radices", "table", "config", "visited", "actual", "trace", "ranking", "portfolio"])
def test_certificate_rejects_tampering(defect):
    from formulaguard.v5_1_7_development import Terminal
    model, ranking, args, _ = fixture()
    new = compose_joint_diagnosis(model, ranking, **args)
    audit = new.search
    changes = {"prefix": {"terminals": audit.terminals[1:]}, "duplicate": {"terminals": (*audit.terminals,audit.terminals[-1])},
               "prune": {"terminals": (Terminal((),0),)}, "rule": {"proof_version": "wrong"},
               "runtime": {"runtime_json": "wrong"}, "binding": {"binding": "wrong"}, "complete": {"complete": False},
               "groups": {"component_indices": ((0,),)}, "radices": {"radices": (16,)}, "table": {"table_sha256": "wrong"},
               "config": {"configuration_json": "{}"}, "visited": {"visited": audit.visited+1},
               "actual": {"actual_evaluations": audit.actual_evaluations+1}, "trace": {"preparation_trace": ()}}
    if defect == "action":
        new = replace(new, decisions=tuple(replace(d, group_size=99) if d.accepted_formula else d for d in new.decisions))
    elif defect == "ranking":
        new = replace(new, localization=tuple(reversed(new.localization)))
    elif defect == "portfolio":
        new = replace(new, candidates=new.candidates[1:])
    else:
        new = replace(new, search=replace(audit, **changes[defect]))
    with pytest.raises(ValueError):
        replay(model, new, ranking, args)
