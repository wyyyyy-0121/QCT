import pytest

from formulaguard.api import localize
from formulaguard.formula import parse_formula
from formulaguard.v5_1_2_development import (
    Parameters,
    _edit_distance,
    v5_1_2_development_scores,
)
from formulaguard.workbook import WorkbookModel


def model(wrong=(), header=True, formula=None):
    cells = {("Ops", "B1"): "Units", ("Ops", "C1"): "Price", ("Ops", "D1"): "Revenue"} if header else {}
    formulas = {}
    for row in range(2, 22):
        cells[("Ops", f"B{row}")] = row + 10
        cells[("Ops", f"C{row}")] = 5
        formulas[("Ops", f"D{row}")] = (
            formula.format(r=row) if formula else f"=B{row}{'+' if row in wrong else '*'}C{row}"
        )
    return WorkbookModel.from_cells(cells, formulas)


def candidates(workbook):
    return {r.cell: r.candidate_formula for r in v5_1_2_development_scores(workbook) if r.candidate_formula}


@pytest.mark.parametrize("header", [True, False])
def test_singleton_independent_of_header(header):
    assert candidates(model((8,), header)) == {("Ops", "D8"): "=B8*C8"}


@pytest.mark.parametrize("header", [True, False])
def test_contiguous_block_with_candidate_majority(header):
    result = candidates(model(range(8, 13), header))
    assert result == {("Ops", f"D{r}"): f"=B{r}*C{r}" for r in range(8, 13)}


def test_long_block_uses_two_anchors_each_side_and_semantic_agreement():
    assert len(candidates(model(range(4, 20)))) == 16
    assert not candidates(model(range(3, 21)))


@pytest.mark.parametrize("formula", ["=B{r}*C{r}*0.9", "=B{r}*C{r}+0", "=B{r}*C{r}", "=B{r}+C{r}"])
def test_uniform_business_expression_never_reconstructed_from_header(formula):
    assert not candidates(model(formula=formula))


@pytest.mark.parametrize("formula", ["=B8*C8*0.9", "=B8*C8+0", "=IF(B8>0,B8,0)", "=B8*C8+1"])
def test_isolated_business_exception_is_review_only(formula):
    workbook = model()
    workbook.formulas[("Ops", "D8")] = formula
    assert not candidates(workbook)


def test_header_only_without_any_anchors_abstains():
    assert not candidates(model(range(2, 22)))


def test_tied_alternating_templates_abstain():
    assert not candidates(model(range(2, 22, 2)))


def test_gap_prevents_cross_region_repair():
    workbook = model((8,))
    del workbook.formulas[("Ops", "D7")]
    assert not candidates(workbook)


def test_hidden_cell_breaks_region_and_is_not_accepted():
    workbook = model((8,))
    workbook.cell_visibility[("Ops", "D8")] = False
    assert not candidates(workbook)


def test_horizontal_and_absolute_reference_structure():
    from formulaguard.a1 import num_to_col
    formulas = {("S", f"{num_to_col(c)}4"): f"={num_to_col(c)}2*$A$1" for c in range(2, 18)}
    formulas[("S", "H4")] = "=H2+$A$1"
    workbook = WorkbookModel.from_cells({}, formulas)
    assert candidates(workbook) == {("S", "H4"): "=H2*$A$1"}


def test_complete_deterministic_ranking_and_no_mutation():
    workbook = model((8,))
    before = dict(workbook.formulas)
    a = localize(workbook, "v5.1.2-development")
    b = v5_1_2_development_scores(workbook)
    assert a == b
    assert {r.cell for r in a} == set(before)
    assert workbook.formulas == before


def test_shape_guard_checks_constants_functions_and_unary_nodes():
    for left, right in [("=B2*C2*0.9", "=B2*C2"), ("=-SUM(B2:C2)", "=-AVERAGE(B2:C2)"), ("=B2*0.8", "=B2*0.9")]:
        assert _edit_distance(parse_formula(left), parse_formula(right)) > 1
    assert _edit_distance(parse_formula("=-SUM(B2:C2)"), parse_formula("=-SUM(B2:D2)")) == 1


@pytest.mark.parametrize("kwargs", [{"min_support": 0}, {"min_support": True}, {"min_dominance": float("nan")}, {"min_candidate_margin": 0}])
def test_invalid_parameters_fail(kwargs):
    with pytest.raises(ValueError):
        Parameters(**kwargs)


def test_cross_axis_disagreement_rejects_tied_candidates(monkeypatch):
    from formulaguard import v5_1_2_development as module
    cell = ("Ops", "D8")
    proposals = [
        module.Proposal(cell, "=B8*C8", "column", (cell,), .9, 9, 4, 5, True, "stable"),
        module.Proposal(cell, "=B8-C8", "row", (cell,), .9, 9, 4, 5, True, "stable"),
    ]
    monkeypatch.setattr(module, "_proposals", lambda *_: proposals)
    results = module.v5_1_2_development_scores(model((8,)))
    target = next(r for r in results if r.cell == cell)
    assert target.candidate_formula is None
    assert target.evidence["group_reason"] == "candidate_tie_or_small_margin"


def test_one_weak_member_rejects_whole_group(monkeypatch):
    from formulaguard import v5_1_2_development as module
    cells = (("Ops", "D8"), ("Ops", "D9"), ("Ops", "D10"))
    proposals = [module.Proposal(
        cell, f"=B{r}*C{r}", "column", cells, score, 9, 4, 5, passes, "test"
    ) for cell, r, score, passes in zip(cells, (8, 9, 10), (.99, .98, .4), (True, True, False), strict=True)]
    monkeypatch.setattr(module, "_proposals", lambda *_: proposals)
    assert not candidates(model((8, 9, 10)))


def test_group_id_binds_full_membership_and_formula():
    result = [r for r in v5_1_2_development_scores(model((8, 9, 10))) if r.candidate_formula]
    assert len(result) == 3
    assert len({r.evidence["group_id"] for r in result}) == 1
    assert all(r.evidence["group_size"] == 3 for r in result)
