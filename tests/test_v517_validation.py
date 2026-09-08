import json
import shutil
from dataclasses import replace
from datetime import date

import pytest

from formulaguard.localize import v4_scores
from formulaguard.v5_1_6_development import compose_joint_diagnosis as exhaustive
from formulaguard.v5_1_7_development import compose_joint_diagnosis
from formulaguard.workbook import WorkbookModel
from scripts.build_v516_joint_cases import build_cases
from scripts.build_v517_scaling_cases import build_case
from scripts.validate_v517_scaling import replay_case, run_case, write_json


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    root = tmp_path_factory.mktemp("v517-proof")
    row = run_case(root, 2, "product", "unique", "replay", "v4", True)
    folder = root / "cases" / row["case_id"]
    assert replay_case(folder) == row
    return folder


@pytest.mark.parametrize("defect", ["ranking", "candidates", "missing_prefix", "false_prune", "action", "input"])
def test_saved_certificate_replay_rejects_tampering(recorded, tmp_path, defect):
    folder = tmp_path / "case"
    shutil.copytree(recorded, folder)
    path = folder / ("input.json" if defect == "input" else "diagnosis.json")
    data = json.loads(path.read_text())
    if defect == "ranking":
        data["localization"][0]["score"] += 1
    elif defect == "candidates":
        data["candidates"].pop()
    elif defect == "missing_prefix":
        data["search"]["terminals"].pop(0)
    elif defect == "false_prune":
        data["search"]["terminals"] = [{"prefix": [], "constraint": 0}]
        data["search"]["evaluated"] = 0
        data["search"]["pruned_states"] = data["search"]["space_size"]
    elif defect == "action":
        next(d for d in data["decisions"] if d["accepted_formula"])["accepted_formula"] = "=0"
    else:
        data["workbook"]["cells"][0][2] += 1
    write_json(path, data)
    with pytest.raises(ValueError):
        replay_case(folder)


@pytest.mark.parametrize("kind", ["cancel_total", "numeric_collision"])
def test_existing_satisfaction_never_authorizes_changes(kind):
    _, raw, document, approvals, _ = next(c for c in build_cases("v517-boundary", 1)
                                        if c[4]["family"] == "product" and c[4]["cohort"] == kind)
    model = WorkbookModel.from_cells({tuple(r[:2]): r[2] for r in raw["cells"]},
                                     {tuple(r[:2]): r[2] for r in raw["formulas"]})
    args = {"documents": [document], "approvals": approvals, "as_of": date(2026, 9, 6)}
    ranking = v4_scores(model)
    new = compose_joint_diagnosis(model, ranking, **args)
    old = exhaustive(model, ranking, **args)
    assert new.search.status == old.search.status == "original_satisfies_constraints"
    assert new.localization == old.localization and new.candidates == old.candidates
    assert not any(d.accepted_formula for d in new.decisions)


def test_dependency_introduced_only_by_candidate_is_not_independent(monkeypatch):
    from formulaguard import v5_1_4_development as edge
    from formulaguard import v5_1_6_development as old_module
    from formulaguard import v5_1_7_development as new_module
    raw, document, approvals, label = build_case(3)
    model = WorkbookModel.from_cells({tuple(r[:2]): r[2] for r in raw["cells"]},
                                     {tuple(r[:2]): r[2] for r in raw["formulas"]})
    first, last = label["errors"][0], label["errors"][-1]
    key = (last["sheet"], last["cell"])
    formula = f"='{first['sheet']}'!{first['cell']}*C{last['cell'][1:]}"
    proposals = tuple(replace(p, formula=formula) if p.cell == key else p for p in edge.edge_proposals(model))
    for module in (edge, old_module, new_module):
        monkeypatch.setattr(module, "edge_proposals", lambda model, config=None: proposals)
    args = {"documents": [document], "approvals": approvals, "as_of": date(2026, 9, 6)}
    ranking = v4_scores(model)
    new = compose_joint_diagnosis(model, ranking, **args)
    old = exhaustive(model, ranking, **args)
    assert new.search.engine == "exhaustive" and new.search.fallback_reason == "candidate_dependency"
    assert new.search.status == old.search.status and new.search.space_size == old.search.space_size
    assert new.localization == old.localization and new.candidates == old.candidates
    assert {d.cell: d.accepted_formula for d in new.decisions} == {d.cell: d.accepted_formula for d in old.decisions}
