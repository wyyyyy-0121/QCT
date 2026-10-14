import hashlib
import json
from copy import deepcopy
from datetime import date

import pytest

from formulaguard.v5_1_5_development import diagnose_v5_1_5_development, model_binding
from formulaguard.workbook import WorkbookModel


def pair():
    cells = {("S", f"B{r}"): 10 + r for r in range(2, 8)}
    cells.update({("S", f"C{r}"): 3 for r in range(2, 8)})
    formulas = {("S", f"D{r}"): f"=B{r}*C{r}" for r in range(2, 8)}
    formulas[("S", "D2")] = "=B2/C2"
    return WorkbookModel.from_cells(cells, formulas)


def document(model, total=None, **changes):
    if total is None:
        total = sum((10 + r) * 3 for r in range(2, 8))
    raw = {"issuer": "approved-ledger", "workbook_binding": model_binding(model),
           "valid_from": "2026-09-01", "valid_until": "2026-09-30",
           "aggregates": [{"id": "ledger-total", "members": [["S", f"D{r}"] for r in range(2, 8)], "total": total}]}
    raw.update(changes)
    payload = json.dumps(raw).encode()
    return payload, {"approved-ledger": hashlib.sha256(payload).hexdigest()}


def run(model, doc, approvals, **kwargs):
    return diagnose_v5_1_5_development(model, documents=[doc], approvals=approvals,
                                     as_of=date(2026, 9, 6), **kwargs)


@pytest.mark.parametrize("backend", ["v4", "v511"])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_identical_workbook_different_approved_evidence(backend, policy):
    model = pair()
    before = deepcopy(model.formulas)
    healthy_doc, trusted = document(model)
    legal_total = sum((10 + r) * 3 for r in range(3, 8)) + 12 / 3
    legal_doc, legal_trusted = document(model, legal_total)
    error = run(model, healthy_doc, trusted, localization_backend=backend, repair_policy=policy)
    legal = run(model, legal_doc, legal_trusted, localization_backend=backend, repair_policy=policy)
    assert error.localization == legal.localization
    assert error.localization_sha256 == legal.localization_sha256
    assert sum(d.accepted_formula is not None for d in error.decisions) == (policy == "structural")
    assert all(d.accepted_formula is None for d in legal.decisions)
    assert model.formulas == before


@pytest.mark.parametrize("defect", ["unapproved", "expired", "wrong_binding", "tamper", "conflict"])
def test_invalid_or_conflicting_authority_does_not_accept(defect):
    model = pair()
    doc, trusted = document(model)
    if defect == "unapproved":
        trusted = {}
    elif defect == "expired":
        doc, trusted = document(model, valid_until="2026-09-02")
    elif defect == "wrong_binding":
        doc, trusted = document(model, workbook_binding="wrong")
    elif defect == "tamper":
        doc = doc.replace(b"ledger-total", b"attacker-total")
    else:
        raw = json.loads(doc)
        raw["aggregates"].append({**raw["aggregates"][0], "id": "conflicting", "total": 999})
        doc, trusted = document(model, aggregates=raw["aggregates"])
    result = run(model, doc, trusted)
    assert all(d.accepted_formula is None for d in result.decisions)


def test_absent_dependency_is_not_silently_zero():
    model = pair()
    model.cells.pop(("S", "B2"))
    doc, trusted = document(model)
    result = run(model, doc, trusted)
    assert "absent" in result.constraint_status
    assert all(d.accepted_formula is None for d in result.decisions)


def test_multiple_errors_not_individually_authorized_by_one_sum():
    model = pair()
    model.formulas[("S", "D7")] = "=B7/C7"
    doc, trusted = document(model)
    result = run(model, doc, trusted)
    assert all(d.accepted_formula is None for d in result.decisions)


def test_joint_numeric_compensation_cannot_authorize_two_edits():
    # Two endpoint fixes can each remove the same aggregate discrepancy alone;
    # jointly they overshoot. The transaction must be rejected, not half applied.
    model = pair()
    model.cells[("S", "B7")] = 12
    model.formulas[("S", "D7")] = "=B7/C7"
    current = 12 / 3 + sum((10 + r) * 3 for r in range(3, 7)) + 12 / 3
    doc, trusted = document(model, current + 32)
    result = run(model, doc, trusted)
    assert all(d.accepted_formula is None for d in result.decisions)
    assert any("joint_constraint_failure" in d.reason for d in result.decisions)


def test_valid_constraint_can_veto_legacy_interior_misrepair():
    model = pair()
    model.formulas[("S", "D2")] = "=B2*C2"
    model.formulas[("S", "D4")] = "=B4/C4"
    total = sum((10 + r) * 3 for r in range(2, 8) if r != 4) + 14 / 3
    doc, trusted = document(model, total)
    result = run(model, doc, trusted)
    assert all(d.accepted_formula is None for d in result.decisions)


def test_document_cannot_supply_formula_answers():
    model = pair()
    doc, trusted = document(model, expected_formula="=B2*C2")
    result = run(model, doc, trusted)
    assert result.constraint_status.startswith("constraint_rejected")


def test_two_distinct_candidates_with_same_numeric_answer_require_review():
    cells = {("S", f"{c}{r}"): 2 for r in range(2, 8) for c in "BCDEF"}
    formulas = {("S", f"H{r}"): f"=B{r}*C{r}" for r in range(2, 8)}
    formulas.update({("S", "I2"): "=C2+D2", ("S", "J2"): "=D2+E2", ("S", "K2"): "=E2+F2"})
    formulas[("S", "H2")] = "=B2/C2"
    model = WorkbookModel.from_cells(cells, formulas)
    doc, trusted = document(model, aggregates=[{"id": "sum", "members": [["S", f"H{r}"] for r in range(2, 8)], "total": 24}])
    result = run(model, doc, trusted)
    assert all(d.accepted_formula is None for d in result.decisions)
    assert any("ambiguous_numeric_solutions" in d.reason for d in result.decisions)


def test_api_requires_explicit_validation_date():
    from formulaguard.api import localize
    with pytest.raises(TypeError):
        localize(pair(), "v515-development")
    assert localize(pair(), "v515-development", as_of=date(2026, 9, 6))


def test_missing_range_member_is_not_silently_zero():
    model = pair()
    model.formulas = {("S", f"D{r}"): f"=SUM(B{r}:C{r})" for r in range(2, 8)}
    model.cells.pop(("S", "B2"))
    doc, trusted = document(model)
    result = run(model, doc, trusted)
    assert "absent cell" in result.constraint_status
