import hashlib
import json
from datetime import date

import pytest

from formulaguard.v5_1_5_development import diagnose_v5_1_5_development, model_binding
from formulaguard.v5_1_6_development import (
    SearchParameters,
    diagnose_v5_1_6_development,
)
from formulaguard.workbook import WorkbookModel


def fixture(total=216):
    cells = {(s, f"{col}{r}"): value for s in ["S"] for r in range(2, 8) for col, value in (("B", 12), ("C", 3))}
    formulas = {("S", f"H{r}"): f"=B{r}*C{r}" for r in range(2, 8)}
    formulas[("S", "H2")] = "=B2/C2"
    formulas[("S", "H7")] = "=B7/C7"
    model = WorkbookModel.from_cells(cells, formulas)
    doc = json.dumps({"issuer": "ledger", "workbook_binding": model_binding(model),
                      "valid_from": "2026-09-01", "valid_until": "2026-09-30",
                      "aggregates": [{"id": "whole-category", "members": [["S", f"H{r}"] for r in range(2, 8)], "total": total}]}).encode()
    args = {"documents": [doc], "approvals": {"ledger": hashlib.sha256(doc).hexdigest()}, "as_of": date(2026, 9, 6)}
    return model, args


@pytest.mark.parametrize("backend", ["v4", "v511"])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_joint_only_repair_preserves_ranking_and_atomicity(backend, policy):
    model, args = fixture()
    old = diagnose_v5_1_5_development(model, localization_backend=backend, **args)
    new = diagnose_v5_1_6_development(model, localization_backend=backend, repair_policy=policy, **args)
    assert old.localization == new.localization
    assert all(d.accepted_formula is None for d in old.decisions)
    assert new.search.status == "unique_solution"
    assert new.search.complete and new.search.evaluated == new.search.space_size == 4
    actions = [d for d in new.decisions if d.accepted_formula]
    assert len(actions) == (2 if policy == "structural" else 0)
    if actions:
        assert len({d.group_id for d in actions}) == 1
        assert all(d.group_size == 2 for d in actions)


@pytest.mark.parametrize("total,status,count", [(184, "ambiguous_solutions", 2), (999, "no_solution", 0), (152, "original_satisfies_constraints", 1)])
def test_ambiguity_no_solution_and_already_satisfied(total, status, count):
    model, args = fixture(total)
    d = diagnose_v5_1_6_development(model, **args)
    assert d.search.status == status
    assert d.search.solutions_seen == count
    assert all(r.accepted_formula is None for r in d.decisions)


def test_budget_cannot_be_mistaken_for_unique_solution():
    model, args = fixture()
    limited = diagnose_v5_1_6_development(model, config=SearchParameters(3), **args)
    complete = diagnose_v5_1_6_development(model, config=SearchParameters(4), **args)
    assert limited.search.status == "budget_exceeded"
    assert limited.search.evaluated == 0 and not limited.search.complete
    assert not any(d.accepted_formula for d in limited.decisions)
    assert limited.localization == complete.localization


def test_unknown_candidate_evaluation_prevents_uniqueness(monkeypatch):
    from formulaguard import v5_1_6_development as module
    original = module._satisfaction
    model, args = fixture()
    def evaluator(model, aggregates, overrides):
        if len(overrides) == 1:
            raise ValueError("unknown evaluation")
        return original(model, aggregates, overrides)
    monkeypatch.setattr(module, "_satisfaction", evaluator)
    d = module.diagnose_v5_1_6_development(model, **args)
    assert d.search.status == "evaluation_incomplete"
    assert not d.search.complete and not any(r.accepted_formula for r in d.decisions)


def test_parameters_and_absent_authority():
    with pytest.raises(ValueError):
        SearchParameters(True)
    model, _ = fixture()
    d = diagnose_v5_1_6_development(model, as_of=date(2026, 9, 6))
    assert d.search.status == "no_approved_constraints"
