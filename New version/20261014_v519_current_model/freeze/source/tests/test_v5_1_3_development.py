from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from formulaguard.api import localize
from formulaguard.localize import LocalizationResult, v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_2_development import Parameters, v5_1_2_development_scores
from formulaguard.v5_1_3_development import (
    compose_diagnosis,
    diagnose_v5_1_3_development,
)
from formulaguard.workbook import WorkbookModel


def workbook(discount=False):
    cells = {("S", "B1"): "Units", ("S", "C1"): "Price", ("S", "D1"): "Revenue"}
    formulas = {}
    for row in range(2, 12):
        cells[("S", f"B{row}")] = row
        cells[("S", f"C{row}")] = 5
        formulas[("S", f"D{row}")] = f"=B{row}*C{row}"
    formulas[("S", "D6")] = "=B6*C6*0.9" if discount else "=B6+C6"
    return WorkbookModel.from_cells(cells, formulas)


def identity(results):
    return [(r.cell, r.score) for r in results]


@pytest.mark.parametrize("backend,ranker", [("v4", v4_scores), ("v511", v5_1_1_development_scores)])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_end_to_end_policy_never_changes_localization(backend, ranker, policy):
    model = workbook()
    before = deepcopy(model.formulas)
    expected = ranker(model)
    diagnosis = diagnose_v5_1_3_development(model, localization_backend=backend, repair_policy=policy)
    actual = diagnosis.to_results()
    assert identity(actual) == identity(expected)
    assert [r.evidence["final_rank"] for r in actual] == list(range(1, 11))
    assert model.formulas == before
    if policy == "structural":
        assert next(r for r in actual if r.cell == ("S", "D6")).candidate_formula == "=B6*C6"
    else:
        assert all(r.candidate_formula is None for r in actual)


def test_accept_review_reject_changes_decision_but_not_rank_or_score():
    model = workbook()
    base = [LocalizationResult(cell, .5, "=B6*C6") for cell in reversed(model.formula_cells)]
    repairs = v5_1_2_development_scores(model)
    diagnoses = [compose_diagnosis(model, base, repairs, repair_policy=p) for p in ("structural", "review_only", "reject_all")]
    assert len({d.localization_sha256 for d in diagnoses}) == 1
    assert [next(x.state for x in d.decisions if x.cell == ("S", "D6")) for d in diagnoses] == ["accepted", "review", "rejected"]
    assert all(identity(d.to_results()) == identity(base) for d in diagnoses)


def test_extreme_repair_threshold_cannot_remove_true_error_from_ranking():
    model = workbook()
    a = diagnose_v5_1_3_development(model)
    b = diagnose_v5_1_3_development(model, repair_config=Parameters(min_support=1000, min_anchor_each_side=1000))
    assert a.localization_sha256 == b.localization_sha256
    assert any(d.accepted_formula for d in a.decisions)
    assert all(d.accepted_formula is None for d in b.decisions)
    assert identity(a.to_results()) == identity(b.to_results())


def test_legal_discount_is_not_accepted_and_ranking_is_preserved():
    model = workbook(discount=True)
    base = v4_scores(model)
    diagnosis = diagnose_v5_1_3_development(model)
    assert identity(diagnosis.to_results()) == identity(base)
    assert all(d.accepted_formula is None for d in diagnosis.decisions)


def test_immutable_snapshot_and_detached_results():
    model = workbook()
    base = v4_scores(model)
    original = deepcopy(base)
    diagnosis = compose_diagnosis(model, base, v5_1_2_development_scores(model))
    assert base == original
    with pytest.raises(FrozenInstanceError):
        diagnosis.localization[0].score = 0
    results = diagnosis.to_results()
    results[0].score = -99
    results[0].evidence["final_rank"] = 999
    assert diagnosis.to_results()[0].score == original[0].score
    base[0].score = -88
    assert diagnosis.to_results()[0].score == original[0].score


@pytest.mark.parametrize("defect", ["missing", "duplicate", "nonfinite"])
def test_invalid_localization_fails_instead_of_silently_filtering(defect):
    model = workbook()
    base = v4_scores(model)
    if defect == "missing":
        base.pop()
    elif defect == "duplicate":
        base.append(base[0])
    else:
        base[0].score = float("nan")
    with pytest.raises(ValueError):
        compose_diagnosis(model, base, v5_1_2_development_scores(model))


def test_inconsistent_repair_group_fails_without_mutating_ranking():
    model = workbook()
    base = v4_scores(model)
    before = deepcopy(base)
    repair = v5_1_2_development_scores(model)
    next(r for r in repair if r.candidate_formula).evidence["group_size"] = 2
    with pytest.raises(ValueError, match="partial"):
        compose_diagnosis(model, base, repair)
    assert base == before


def test_empty_workbook_and_unknown_options():
    model = WorkbookModel.from_cells({}, {})
    assert compose_diagnosis(model, [], []).to_results() == []
    with pytest.raises(ValueError):
        diagnose_v5_1_3_development(model, repair_policy="accept_all")
    with pytest.raises(ValueError):
        diagnose_v5_1_3_development(model, localization_backend="missing")
    with pytest.raises(TypeError):
        localize(model, "v5.1.3-development", unknown=True)


def test_api_alias():
    model = workbook()
    assert identity(localize(model, "v513-development")) == identity(v4_scores(model))
