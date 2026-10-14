import json
import shutil

import pytest

from scripts import evaluate_v516_joint as workflow
from scripts.build_v516_joint_cases import build_cases
from scripts.score_v512_confirmation import sha256


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("joint-protocol")
    all_cases = build_cases("unit-joint", 1)
    selected = [c for c in all_cases if c[4]["family"] == "product"]
    original = workflow.build_cases
    try:
        workflow.build_cases = lambda seed, repeats: selected
        workflow.build(root / "release")
    finally:
        workflow.build_cases = original
    workflow.predict(root / "release", root / "predictions")
    return root


def test_joint_cohorts_and_full_denominator(prepared, tmp_path):
    workflow.score(prepared / "release", prepared / "predictions", tmp_path / "score")
    result = json.loads((tmp_path / "score/result.json").read_text())
    joint = result["variants"]["v4_joint"]
    assert joint["error_cells"] == 19
    assert joint["exact_candidate_coverage"] == 8 / 19
    assert joint["accepted_group_count"] == 4
    assert joint["unsafe_accepted_groups_all_workbooks"] == 0
    assert joint["by_cohort"]["cancel_subtotals"]["exact_candidate_coverage"] == 1
    assert joint["by_cohort"]["cancel_total"]["accepted_group_count"] == 0
    assert joint["search_status_counts"]["budget_exceeded"] == 1


@pytest.mark.parametrize("defect", ["hash", "ranking", "incomplete_search", "missing_variant"])
def test_corrupt_proof_rejected_before_reveal(prepared, tmp_path, defect):
    pred = tmp_path / "pred"
    shutil.copytree(prepared / "predictions", pred)
    lockpath = pred / "prediction_lock.json"
    lock = json.loads(lockpath.read_text())
    name = next(p for p in lock["shards"] if p.startswith("v4_joint/") and json.loads((pred / p).read_text())["accepted_group_count"])
    shard = json.loads((pred / name).read_text())
    if defect == "missing_variant":
        del lock["shards"][name]
    else:
        if defect == "incomplete_search":
            shard["search"]["complete"] = False
        else:
            shard["ranking"][0]["score"] += 123
        workflow.write_json(pred / name, shard)
        if defect != "hash":
            lock["shards"][name] = sha256(pred / name)
    workflow.write_json(lockpath, lock)
    with pytest.raises(ValueError):
        workflow.score(prepared / "release", pred, tmp_path / "score")
    assert not (tmp_path / "score/reveal_authorization.json").exists()


def test_generator_fixed_subtotals_and_determinism():
    data = build_cases("subtotal-proof", 1)
    assert data == build_cases("subtotal-proof", 1)
    assert len(data) == 72 and len({c[0] for c in data}) == 72
    for _, raw, payload, _, label in data:
        doc = json.loads(payload)
        assert "expected_formula" not in payload.decode()
        if label["cohort"] == "cancel_subtotals":
            assert len(doc["aggregates"]) == 3
            assert all(len(a["members"]) >= 6 for a in doc["aggregates"])
            assert len(raw["formulas"]) == len(doc["aggregates"][0]["members"])
