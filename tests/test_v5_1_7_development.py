import hashlib
import json
import math
from dataclasses import replace
from datetime import date
from itertools import product

import pytest

from formulaguard.api import localize
from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_5_development import model_binding
from formulaguard.v5_1_6_development import SearchParameters as ExhaustiveParameters
from formulaguard.v5_1_6_development import compose_joint_diagnosis as exhaustive
from formulaguard.v5_1_7_development import (
    Bound,
    SearchParameters,
    Terminal,
    compose_joint_diagnosis,
    verify_unique_solution,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_v517_scaling_cases import build_case

AS_OF = date(2026, 9, 6)


def fixture(count=9, family="product", kind="unique", seed="test"):
    raw, document, approvals, label = build_case(count, family, kind, seed)
    model = WorkbookModel.from_cells({tuple(row[:2]): row[2] for row in raw["cells"]},
                                     {tuple(row[:2]): row[2] for row in raw["formulas"]})
    return model, {"documents": [document], "approvals": approvals, "as_of": AS_OF}, label


def actions(diagnosis):
    return {d.cell: d.accepted_formula for d in diagnosis.decisions if d.accepted_formula}


@pytest.mark.parametrize("family", ["product", "ratio", "sum", "difference", "weighted", "range"])
@pytest.mark.parametrize("backend", ["v4", "v511"])
def test_over_256_matches_existing_exhaustive_solver(family, backend):
    model, args, label = fixture(family=family)
    ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
    old = exhaustive(model, ranking, backend=backend, config=ExhaustiveParameters(512), **args)
    new = compose_joint_diagnosis(model, ranking, backend=backend, **args)
    assert new.localization == old.localization
    assert new.candidates == old.candidates
    assert new.search.space_size == old.search.space_size == 512
    assert new.search.status == old.search.status == "unique_solution"
    assert new.search.complete and new.search.evaluated + new.search.pruned_states == 512
    assert new.search.evaluated < old.search.evaluated
    assert actions(new) == actions(old) == {(e["sheet"], e["cell"]): e["expected_formula"] for e in label["errors"]}
    assert verify_unique_solution(model, new, **args) == actions(new)


@pytest.mark.parametrize("kind,status", [("ambiguous", "ambiguous_solutions"), ("no_solution", "no_solution"),
                                        ("clean", "original_satisfies_constraints"), ("fractional", "unique_solution"),
                                        ("mixed_subtotals", "unique_solution")])
def test_differential_controls(kind, status):
    model, args, _ = fixture(4, kind=kind)
    ranking = v4_scores(model)
    old = exhaustive(model, ranking, config=ExhaustiveParameters(256), **args)
    new = compose_joint_diagnosis(model, ranking, **args)
    assert new.search.status == old.search.status == status
    assert new.localization == old.localization and new.candidates == old.candidates
    assert actions(new) == actions(old)
    if kind == "fractional":
        assert new.search.engine == "exhaustive" and new.search.fallback_reason == "nonintegral_values"
    if status == "unique_solution":
        verify_unique_solution(model, new, **args)
    if status == "ambiguous_solutions":
        assert new.search.solutions_seen == 2 and not new.search.complete


@pytest.mark.parametrize("count", [24, 32])
@pytest.mark.parametrize("kind", ["unique", "mixed_subtotals"])
def test_large_space_certificate_and_full_ranking(count, kind):
    model, args, label = fixture(count, kind=kind)
    ranking = v4_scores(model)
    old = exhaustive(model, ranking, **args)
    new = compose_joint_diagnosis(model, ranking, **args)
    assert old.search.status == "budget_exceeded"
    assert new.localization == old.localization and new.candidates == old.candidates
    assert new.search.space_size == 2**count
    assert new.search.evaluated == 1
    assert new.search.visited == 2 * count + 1
    assert verify_unique_solution(model, new, **args) == {(e["sheet"], e["cell"]): e["expected_formula"] for e in label["errors"]}


@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_policies_and_api_preserve_localization(policy):
    model, args, _ = fixture()
    ranking = v4_scores(model)
    normal = compose_joint_diagnosis(model, ranking, **args)
    new = compose_joint_diagnosis(model, ranking, repair_policy=policy, **args)
    assert new.localization == normal.localization and new.candidates == normal.candidates
    assert bool(actions(new)) == (policy == "structural")
    verify_unique_solution(model, new, **args)
    results = localize(model, method="v5.1.7-development", repair_policy=policy, **args)
    assert [(r.cell, r.score) for r in results] == [(r.cell, r.score) for r in ranking]
    assert all(r.evidence["model_version"] == "v5.1.7-development" for r in results)


@pytest.mark.parametrize("config", [SearchParameters(max_nodes=1), SearchParameters(pruning=False, max_evaluations=1),
                                   SearchParameters(max_preparations=1, max_evaluations=1)])
def test_budgets_never_authorize_partial_search(config):
    model, args, _ = fixture()
    new = compose_joint_diagnosis(model, v4_scores(model), config=config, **args)
    assert new.search.status == "budget_exceeded" and not new.search.complete
    assert not actions(new)


@pytest.mark.parametrize("defect", ["missing", "duplicate", "false_prune", "incomplete", "space", "action", "binding"])
def test_certificate_tampering_is_rejected(defect):
    model, args, _ = fixture()
    new = compose_joint_diagnosis(model, v4_scores(model), **args)
    if defect == "missing":
        audit = replace(new.search, terminals=new.search.terminals[1:])
    elif defect == "duplicate":
        audit = replace(new.search, terminals=(new.search.terminals[0], *new.search.terminals))
    elif defect == "false_prune":
        audit = replace(new.search, terminals=(Terminal((), 0),), evaluated=0, pruned_states=new.search.space_size)
    elif defect == "incomplete":
        audit = replace(new.search, complete=False)
    elif defect == "space":
        audit = replace(new.search, space_size=256)
    elif defect == "binding":
        audit = replace(new.search, binding="changed")
    else:
        audit = new.search
        new = replace(new, decisions=tuple(replace(d, accepted_formula="=0") if d.accepted_formula else d for d in new.decisions))
    with pytest.raises(ValueError):
        verify_unique_solution(model, replace(new, search=audit), **args)


def test_integer_bounds_honor_existing_relative_tolerance():
    # At this scale an integer difference of one is within V515's tolerance.
    assert not Bound(10_000_000_001, (), 10_000_000_000.0).excludes(())
    assert Bound(10_000_000_002, (), 10_000_000_000.0).excludes(())
    assert not Bound(-10_000_000_001, (), -10_000_000_000.0).excludes(())
    assert Bound(-10_000_000_002, (), -10_000_000_000.0).excludes(())


def test_unknown_evaluation_cannot_prove_uniqueness(monkeypatch):
    from formulaguard import v5_1_7_development as module
    model, args, _ = fixture()
    original = module._satisfaction

    def fail(model, aggregates, overrides):
        if overrides:
            raise ValueError("unknown")
        return original(model, aggregates, overrides)

    monkeypatch.setattr(module, "_satisfaction", fail)
    for config in (SearchParameters(), SearchParameters(pruning=False)):
        new = compose_joint_diagnosis(model, v4_scores(model), config=config, **args)
        assert new.search.status == "evaluation_incomplete" and not actions(new)


@pytest.mark.parametrize("kwargs", [{"max_nodes": True}, {"max_evaluations": 0}, {"max_preparations": 1.5}, {"pruning": 1}])
def test_invalid_parameters(kwargs):
    with pytest.raises((ValueError, TypeError)):
        SearchParameters(**kwargs)


def rebound(model, args, modify=None):
    doc = json.loads(args["documents"][0])
    doc["workbook_binding"] = model_binding(model)
    if modify:
        modify(doc)
    payload = json.dumps(doc).encode()
    return {**args, "documents": [payload], "approvals": {doc["issuer"]: hashlib.sha256(payload).hexdigest()}}


@pytest.mark.parametrize("indirect", [False, True])
def test_cross_candidate_dependencies_fall_back_without_domain_loss(indirect):
    model, args, label = fixture(3)
    first = (label["errors"][0]["sheet"], label["errors"][0]["cell"])
    third = (label["errors"][2]["sheet"], label["errors"][2]["cell"])
    source = f"'{first[0]}'!{first[1]}"
    if indirect:
        model.formulas[("Helper", "A1")] = f"={source}"
        source = "Helper!A1"
    # A literal input of the third candidate now depends transitively on the first.
    b_cell = (third[0], third[1].replace("H", "B"))
    model.cells.pop(b_cell)
    model.formulas[b_cell] = f"={source}"
    args = rebound(model, args)
    ranking = v4_scores(model)
    old = exhaustive(model, ranking, config=ExhaustiveParameters(4096), **args)
    new = compose_joint_diagnosis(model, ranking, **args)
    assert new.search.engine == "exhaustive" and new.search.fallback_reason == "candidate_dependency"
    assert new.search.status == old.search.status
    assert new.search.space_size == old.search.space_size
    assert new.localization == old.localization and new.candidates == old.candidates
    assert actions(new) == actions(old)


def test_unapproved_constraints_keep_legacy_scope():
    model, args, _ = fixture(3)
    ranking = v4_scores(model)
    for context in ({"as_of": AS_OF}, {**args, "approvals": {}}):
        new = compose_joint_diagnosis(model, ranking, **context)
        old = exhaustive(model, ranking, **context)
        assert new.search.status == old.search.status
        assert new.decisions == old.decisions and new.localization == old.localization


def test_large_integer_values_use_exhaustive_fallback():
    model, args, _ = fixture(2)
    model.cells = {cell: value * 2**46 if cell[1].startswith("B") else value for cell, value in model.cells.items()}
    args = rebound(model, args)
    new = compose_joint_diagnosis(model, v4_scores(model), **args)
    assert new.search.engine == "exhaustive" and new.search.fallback_reason == "integer_sum_range"


def test_proof_is_bound_to_current_workbook_and_authority():
    model, args, _ = fixture()
    new = compose_joint_diagnosis(model, v4_scores(model), **args)
    with pytest.raises(ValueError):
        verify_unique_solution(model, new, **{**args, "approvals": {}})
    with pytest.raises(ValueError):
        verify_unique_solution(model, new, **{**args, "as_of": date(2026, 10, 1)})
    key = next(iter(model.cells))
    model.cells[key] += 1
    with pytest.raises(ValueError):
        verify_unique_solution(model, new, **args)


def test_one_solution_before_budget_is_not_unique():
    model, args, _ = fixture(2, kind="ambiguous")
    new = compose_joint_diagnosis(model, v4_scores(model),
                                  config=SearchParameters(pruning=False, max_evaluations=2), **args)
    assert new.search.status == "budget_exceeded" and new.search.solutions_seen == 1
    assert not new.search.complete and not actions(new)


def test_three_options_preserve_cartesian_domain(monkeypatch):
    from formulaguard import v5_1_4_development as edge
    from formulaguard import v5_1_6_development as old_module
    from formulaguard import v5_1_7_development as new_module
    model, args, _ = fixture(3)
    proposals = edge.edge_proposals(model)
    expanded = tuple(p for original in proposals for p in (original, replace(original, formula=original.formula.replace("*", "+"))))
    for module in (edge, old_module, new_module):
        monkeypatch.setattr(module, "edge_proposals", lambda model, config=None: expanded)
    ranking = v4_scores(model)
    old = exhaustive(model, ranking, **args)
    new = compose_joint_diagnosis(model, ranking, **args)
    assert new.search.space_size == old.search.space_size == 27
    assert new.candidates == old.candidates and new.localization == old.localization
    assert actions(new) == actions(old)
    verify_unique_solution(model, new, **args)


@pytest.mark.parametrize("constant", [-10_000_000_000, -10, 0, 10, 10_000_000_000])
def test_bound_exclusions_against_all_completions(constant):
    choices = ((-9, 0, 5), (-3, 2), (0, 8, 11))
    for target in (constant - 15, constant - 2, constant + 0.25, constant + 12, constant + 30):
        bound = Bound(constant, choices, float(target))
        for depth in range(4):
            for prefix in product(*(range(len(v)) for v in choices[:depth])):
                if bound.excludes(prefix):
                    for tail in product(*(range(len(v)) for v in choices[depth:])):
                        assignment = prefix + tail
                        actual = math.fsum([float(constant), *(float(choices[i][v]) for i, v in enumerate(assignment))])
                        assert not math.isclose(actual, target, rel_tol=1e-10, abs_tol=1e-8)
