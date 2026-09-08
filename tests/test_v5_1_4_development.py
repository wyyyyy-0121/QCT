from copy import deepcopy

import pytest

from formulaguard.api import localize
from formulaguard.v5_1_4_development import (
    EdgeParameters,
    compose_edge_diagnosis,
    diagnose_v5_1_4_development,
    edge_proposals,
)
from formulaguard.workbook import WorkbookModel
from scripts.audit_v514_candidates import classify


def grid(formula="=Inputs!F5/Inputs!F$2", columns="FGHIJ"):
    formulas = {("Data", f"{col}{row}"): f"=Inputs!{col}{row}*Inputs!{col}$2"
                for row in range(5, 12) for col in columns}
    formulas[("Data", "F5")] = formula
    return WorkbookModel.from_cells({}, formulas)


@pytest.mark.parametrize("backend", ["v4", "v511"])
@pytest.mark.parametrize("mode", ["off", "propose_only", "orthogonal"])
@pytest.mark.parametrize("policy", ["structural", "review_only", "reject_all"])
def test_rank_invariant_and_edge_policy(backend, mode, policy):
    model = grid()
    before = deepcopy(model.formulas)
    reference = diagnose_v5_1_4_development(model, localization_backend=backend, edge_mode="off")
    result = diagnose_v5_1_4_development(model, localization_backend=backend, edge_mode=mode, repair_policy=policy)
    assert result.localization == reference.localization
    assert result.localization_sha256 == reference.localization_sha256
    target = next(d for d in result.decisions if d.cell == ("Data", "F5"))
    assert (target.accepted_formula is not None) == (mode == "orthogonal" and policy == "structural")
    assert model.formulas == before
    if mode != "off":
        assert len([p for p in result.candidates if p.cell == target.cell and p.source.startswith("edge_")]) == 2
    assert all(r.evidence["model_version"] == "v5.1.4-development" for r in result.to_results())


@pytest.mark.parametrize("formula", ["=Inputs!F5*Inputs!F$2*0.9", "=Inputs!F5*Inputs!F$2+7", "=SUM(Inputs!F5,Inputs!F$2)"])
def test_business_expression_changes_remain_review(formula):
    result = diagnose_v5_1_4_development(grid(formula), edge_mode="orthogonal")
    target = next(d for d in result.decisions if d.cell == ("Data", "F5"))
    assert target.state == "review"
    assert "expression_change" in target.reason


def test_single_axis_is_proposal_not_authorization():
    model = grid(columns="F")
    assert len(edge_proposals(model)) == 1
    result = diagnose_v5_1_4_development(model)
    assert all(d.accepted_formula is None for d in result.decisions)
    assert any(p.source == "edge_column" for p in result.candidates)


def test_hidden_and_block_endpoints_not_proposed():
    model = grid(columns="F")
    model.hidden_rows = {"Data": {5}}
    assert not edge_proposals(model)
    model = grid(columns="F")
    model.formulas[("Data", "F6")] = "=Inputs!F6/Inputs!F$2"
    assert not edge_proposals(model)


def test_high_support_threshold_does_not_change_ranking():
    model = grid()
    a = diagnose_v5_1_4_development(model)
    b = diagnose_v5_1_4_development(model, config=EdgeParameters(1000))
    assert a.localization_sha256 == b.localization_sha256
    assert all(d.accepted_formula is None for d in b.decisions)


def test_known_identifiability_limit_is_visible():
    # Identical workbook bytes may describe a legal boundary operation. There
    # is no business intent field here. Do not turn this into a false safety test.
    result = diagnose_v5_1_4_development(grid(), edge_mode="orthogonal")
    assert next(d for d in result.decisions if d.cell == ("Data", "F5")).accepted_formula is not None


def test_empty_and_bad_parameters():
    empty = WorkbookModel.from_cells({}, {})
    assert not compose_edge_diagnosis(empty, []).localization
    with pytest.raises(ValueError):
        EdgeParameters(2)
    with pytest.raises(ValueError):
        compose_edge_diagnosis(empty, [], edge_mode="accept_all")
    assert localize(empty, "v5.1.4-development") == []


def test_default_extends_proposals_without_new_edge_acceptance():
    result = diagnose_v5_1_4_development(grid())
    assert result.edge_mode == "propose_only"
    assert any(c.source.startswith("edge_") for c in result.candidates)
    assert all(d.accepted_formula is None for d in result.decisions)


def test_audit_categories_do_not_treat_truth_as_authority():
    class Proposal:
        passes = True
    assert classify([], False, "missing") == "no_correct_candidate"
    assert classify([Proposal()], False, "atomic_group_rejected") == "correct_candidate_insufficient_evidence"
    assert classify([Proposal()], False, "stable_copy_template") == "evidence_passed_but_rule_blocked"
    assert classify([], True, "accepted") == "repaired"
