from dataclasses import replace
from datetime import date

import pytest

from formulaguard.api import localize
from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_6_development import SearchParameters as ExhaustiveParameters
from formulaguard.v5_1_6_development import compose_joint_diagnosis as exhaustive
from formulaguard.v5_1_7_development import Terminal
from formulaguard.v5_1_8_development import (
    SearchParameters,
    compose_joint_diagnosis,
    verify_unique_solution,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_v518_numeric_cases import FAMILIES, KINDS, build_case


def fixture(count=4, family="product", kind="unique"):
    raw, document, approvals, label = build_case(count, family, kind)
    model = WorkbookModel.from_cells({tuple(r[:2]): r[2] for r in raw["cells"]},
                                     {tuple(r[:2]): r[2] for r in raw["formulas"]})
    return model, {"documents": [document], "approvals": approvals, "as_of": date(2026,9,6)}, label


def actions(diagnosis):
    return {d.cell: d.accepted_formula for d in diagnosis.decisions if d.accepted_formula}


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("kind", KINDS)
def test_all_cohorts_match_exhaustive_classification(family, kind):
    model, args, label = fixture(family=family, kind=kind)
    ranking = v4_scores(model)
    old = exhaustive(model, ranking, config=ExhaustiveParameters(256), **args)
    new = compose_joint_diagnosis(model, ranking, **args)
    assert new.search.status == old.search.status
    assert new.localization == old.localization and new.candidates == old.candidates
    assert new.search.space_size == old.search.space_size and actions(new) == actions(old)
    if new.search.status == "unique_solution":
        verify_unique_solution(model, new, **args)
        assert actions(new) == {(e["sheet"],e["cell"]):e["expected_formula"] for e in label["errors"]}
    if kind == "candidate_dependency":
        assert new.search.engine == "exhaustive" and new.search.fallback_reason == "candidate_dependency"


@pytest.mark.parametrize("backend", ["v4", "v511"])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_api_policies_and_complete_localization(backend, policy):
    model, args, _ = fixture()
    ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
    new = compose_joint_diagnosis(model, ranking, backend=backend, repair_policy=policy, **args)
    assert new.search.engine == "independent_binary64_bounds" and new.search.complete
    verify_unique_solution(model, new, **args)
    result = localize(model, method="v5.1.8-development", localization_backend=backend, repair_policy=policy, **args)
    assert [(r.cell, r.score) for r in result] == [(r.cell,r.score) for r in ranking]
    assert bool(actions(new)) == (policy == "structural")


@pytest.mark.parametrize("defect", ["prefix", "duplicate", "prune", "rule", "runtime", "binding", "complete", "action"])
def test_numeric_certificate_tampering(defect):
    model, args, _ = fixture()
    new = compose_joint_diagnosis(model, v4_scores(model), **args)
    audit = new.search
    if defect == "prefix":
        audit = replace(audit, terminals=audit.terminals[1:])
    elif defect == "duplicate":
        audit = replace(audit, terminals=(*audit.terminals, audit.terminals[-1]))
    elif defect == "prune":
        audit = replace(audit, terminals=(Terminal((),0),), evaluated=0, pruned_states=audit.space_size)
    elif defect == "rule":
        audit = replace(audit, numeric_rule="unreviewed")
    elif defect == "runtime":
        audit = replace(audit, runtime_json="unknown")
    elif defect == "binding":
        audit = replace(audit, binding="changed")
    elif defect == "complete":
        audit = replace(audit, complete=False)
    else:
        new = replace(new, decisions=tuple(replace(d, accepted_formula="=0") if d.accepted_formula else d for d in new.decisions))
    with pytest.raises(ValueError):
        verify_unique_solution(model, replace(new, search=audit), **args)


def test_unknown_environment_and_budget_fall_back(monkeypatch):
    from formulaguard import v518_numeric_bounds as numeric
    model,args,_ = fixture()
    ranking = v4_scores(model)
    monkeypatch.setattr(numeric, "runtime_supported", lambda: False)
    new = compose_joint_diagnosis(model, ranking, config=SearchParameters(max_evaluations=1), **args)
    assert new.search.fallback_reason == "numeric_environment_unsupported"
    assert new.search.status == "budget_exceeded" and not actions(new)


def test_single_solution_then_budget_cannot_authorize(monkeypatch):
    model,args,_ = fixture(2, kind="ambiguous")
    new = compose_joint_diagnosis(model, v4_scores(model), config=SearchParameters(pruning=False,max_evaluations=2), **args)
    assert new.search.solutions_seen == 1 and new.search.status == "budget_exceeded" and not actions(new)


def test_unknown_preparation_and_leaf_fail_closed(monkeypatch):
    from formulaguard import v5_1_8_development as module
    model,args,_ = fixture()
    original = module._satisfaction

    def fail(model, aggregates, overrides):
        if overrides:
            raise ValueError("injected unknown evaluation")
        return original(model, aggregates, overrides)

    monkeypatch.setattr(module, "_satisfaction", fail)
    for config in (SearchParameters(), SearchParameters(pruning=False)):
        new = compose_joint_diagnosis(model, v4_scores(model), config=config, **args)
        assert new.search.status == "evaluation_incomplete" and not actions(new)


@pytest.mark.parametrize("count", [2,8,9,10,12])
def test_exhaustive_size_ladder(count):
    model,args,_=fixture(count, family="ratio")
    ranking=v4_scores(model)
    old=exhaustive(model,ranking,config=ExhaustiveParameters(2**count),**args)
    new=compose_joint_diagnosis(model,ranking,**args)
    assert old.search.complete and old.search.evaluated==2**count
    assert old.search.status==new.search.status=="unique_solution"
    assert actions(new)==actions(old) and old.candidates==new.candidates and old.localization==new.localization
    verify_unique_solution(model,new,**args)


def test_multi_option_numeric_domain(monkeypatch):
    from formulaguard import v5_1_4_development as edge
    from formulaguard import v5_1_6_development as oracle
    from formulaguard import v5_1_7_development as domain
    model,args,_=fixture(3)
    expanded=tuple(p for original in edge.edge_proposals(model)
                   for p in (original,replace(original,formula=original.formula.replace("*","+"))))
    for module in (edge,oracle,domain):
        monkeypatch.setattr(module,"edge_proposals",lambda model,config=None:expanded)
    ranking=v4_scores(model)
    old=exhaustive(model,ranking,**args)
    new=compose_joint_diagnosis(model,ranking,**args)
    assert old.search.space_size==new.search.space_size==27
    assert old.candidates==new.candidates and old.localization==new.localization and actions(new)==actions(old)
    verify_unique_solution(model,new,**args)
