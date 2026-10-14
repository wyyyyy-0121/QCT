import json
from dataclasses import replace
from datetime import timedelta

import pytest
from test_v5_1_9_development import fixture, replay

from formulaguard.v5_1_9_development import SearchParameters, compose_joint_diagnosis
from scripts.build_v515_constraint_cases import binding, encode
from scripts.build_v519_component_cases import build_component_case
from scripts.v518_validation_common import AS_OF, actions, load_model


@pytest.mark.parametrize("defect", ["missing", "cycle", "unknown", "nonfinite"])
def test_actual_invalid_inputs_do_not_accept(defect):
    import hashlib

    from formulaguard.v5_1_1_development import v5_1_1_development_scores
    raw, document, _, _ = build_component_case(4)
    first = next(r for r in raw["formulas"] if r[0] == "Dept_000" and r[1].startswith("H"))
    target = next(r for r in raw["cells"] if r[:2] == [first[0], "B"+first[1][1:]])
    raw["cells"].remove(target)
    formula = {"missing": "=Z999", "cycle": "="+first[1], "unknown": "=UNKNOWN(1)", "nonfinite": "=1e308*1e308"}[defect]
    raw["formulas"].append([*target[:2], formula])
    doc = json.loads(document)
    doc["workbook_binding"] = binding(raw)
    document = encode(doc)
    model = load_model(raw)
    new = compose_joint_diagnosis(model, v5_1_1_development_scores(model), backend="v511", documents=[document],
                                  approvals={doc["issuer"]: hashlib.sha256(document).hexdigest()}, as_of=AS_OF)
    assert not actions(new) and new.search.status.startswith("constraint_rejected:")


def test_runtime_fallback_and_exact_node_boundary(monkeypatch):
    from formulaguard import v5_1_9_development as module
    model, ranking, args, _ = fixture()
    valid = compose_joint_diagnosis(model, ranking, **args)
    for limit in (valid.search.visited-1, valid.search.visited):
        new = compose_joint_diagnosis(model, ranking, config=SearchParameters(max_nodes=limit), **args)
        assert bool(actions(new)) == (limit == valid.search.visited)
    monkeypatch.setattr(module, "runtime_supported", lambda: False)
    new = compose_joint_diagnosis(model, ranking, config=SearchParameters(max_evaluations=1), **args)
    assert new.search.fallback_reason == "numeric_environment_unsupported" and not actions(new)


def test_unknown_leaf_refuses(monkeypatch):
    from formulaguard import v5_1_9_development as module
    model, ranking, args, _ = fixture()
    original = module._satisfaction

    def fail(model, aggregates, overrides):
        if overrides:
            raise ValueError("unknown leaf")
        return original(model, aggregates, overrides)

    monkeypatch.setattr(module, "_satisfaction", fail)
    new = compose_joint_diagnosis(model, ranking, config=SearchParameters(pruning=False), **args)
    assert new.search.status == "evaluation_incomplete" and not actions(new)


@pytest.mark.parametrize("defect", ["approval", "date", "configuration", "policy", "backend", "input", "decision_population"])
def test_certificate_binds_external_context(defect):
    model, ranking, args, _ = fixture()
    new = compose_joint_diagnosis(model, ranking, **args)
    config = None
    if defect == "approval":
        args["approvals"] = {}
    elif defect == "date":
        args["as_of"] = AS_OF + timedelta(days=1)
    elif defect == "configuration":
        config = SearchParameters(max_nodes=9999)
    elif defect == "policy":
        new = replace(new, repair_policy="review_only")
    elif defect == "backend":
        new = replace(new, backend="v4")
    elif defect == "input":
        model = load_model({"cells": [[*c,v] for c,v in model.cells.items()] + [["Extra","A1",1]],
                            "formulas": [[*c,f] for c,f in model.formulas.items()]})
    else:
        new = replace(new, decisions=new.decisions[1:])
    with pytest.raises(ValueError):
        replay(model, new, ranking, args, config)
