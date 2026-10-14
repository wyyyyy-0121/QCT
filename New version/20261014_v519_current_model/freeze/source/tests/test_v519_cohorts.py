from itertools import product

import pytest

from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_5_development import _satisfaction, approved_aggregates
from formulaguard.v5_1_7_development import _domain, _overrides
from formulaguard.v5_1_9_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v519_confirmation_cases import FAMILIES, KINDS, build_case
from scripts.v518_validation_common import AS_OF, actions, load_model


@pytest.mark.parametrize("family", FAMILIES)
@pytest.mark.parametrize("kind", KINDS)
def test_all_confirmation_cohorts_against_original_full_enumeration(family, kind):
    count = 9 if kind == "oversized_component" else 4
    raw, document, approvals, label = build_case(count, family, kind, "g5-preflight")
    model = load_model(raw)
    ranking = v5_1_1_development_scores(model)
    args = {"documents":[document], "approvals":approvals, "as_of":AS_OF}
    diagnosis = compose_joint_diagnosis(model, ranking, backend="v511", **args)
    if kind in {"invalid_approval", "original_satisfies"}:
        assert not actions(diagnosis)
        return
    aggregates = approved_aggregates(model, [document], approvals, AS_OF)
    cells, options = _domain(model, aggregates)
    assert len(cells) == count and all(len(o) == 2 for o in options)
    solutions = [overrides for assignment in product(*(range(len(o)) for o in options))
                 if all(_satisfaction(model,aggregates,overrides := _overrides(cells,options,assignment)).values())]
    expected = "unique_solution" if len(solutions)==1 else "no_solution" if not solutions else "ambiguous_solutions"
    assert diagnosis.search.status == expected
    if len(solutions)==1:
        verify_unique_solution(model,diagnosis,localization=ranking,**args)
        assert actions(diagnosis) == solutions[0] == {(e["sheet"],e["cell"]):e["expected_formula"] for e in label["errors"]}
    else:
        assert not actions(diagnosis)
    if kind=="candidate_only":
        before,_=model.evaluate(overrides={cells[1]:options[1][1]},targets=[cells[1]])
        after,_=model.evaluate(overrides={cells[0]:options[0][1],cells[1]:options[1][1]},targets=[cells[1]])
        assert before[cells[1]] != after[cells[1]]
        assert diagnosis.search.engine=="component_binary64_bounds"
