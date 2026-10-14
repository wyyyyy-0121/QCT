import json
import shutil

import pytest

from scripts import evaluate_v515_constraints as workflow
from scripts.build_v515_constraint_cases import build_cases
from scripts.score_v512_confirmation import sha256


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("v515-protocol")
    cases = build_cases("unit-ledger", 1)
    selected = [next(c for c in cases if c[4]["cohort"] == k)
                for k in ("error", "legal_exception", "clean", "no_approval")]
    original = workflow.build_cases
    try:
        workflow.build_cases = lambda seed, repeats: selected
        workflow.build(root / "release")
    finally:
        workflow.build_cases = original
    workflow.predict(root / "release", root / "predictions")
    return root


def test_paired_scoring_preserves_full_denominator(prepared, tmp_path):
    workflow.score(prepared / "release", prepared / "predictions", tmp_path / "result")
    result = json.loads((tmp_path / "result/result.json").read_text())
    value = result["variants"]["v4_trusted"]
    assert value["error_cells"] == 2
    assert value["exact_candidate_coverage"] == .5
    assert value["qualified"]["exact_candidate_coverage"] == 1
    assert value["unsafe_accepted_groups_all_workbooks"] == 0
    assert result["pairs"][0]["identical_workbook"]


@pytest.mark.parametrize("defect", ["hash", "rank", "approval", "document", "missing"])
def test_protocol_tampering_rejected_before_reveal(prepared, tmp_path, defect):
    release, pred = tmp_path / "release", tmp_path / "predictions"
    shutil.copytree(prepared / "release", release)
    shutil.copytree(prepared / "predictions", pred)
    lock_path = pred / "prediction_lock.json"
    lock = json.loads(lock_path.read_text())
    name = next(p for p in lock["shards"] if p.startswith("v4_trusted/"))
    if defect in {"hash", "rank"}:
        shard = json.loads((pred / name).read_text())
        shard["ranking"][0]["score"] += 100
        workflow.write_json(pred / name, shard)
        if defect == "rank":
            lock["shards"][name] = sha256(pred / name)
            workflow.write_json(lock_path, lock)
    elif defect == "approval":
        workflow.write_json(release / "APPROVALS.json", {})
    elif defect == "document":
        workflow.write_json(next((release / "PUBLIC/documents").glob("*.json")), {})
    else:
        del lock["shards"][name]
        workflow.write_json(lock_path, lock)
    with pytest.raises(ValueError):
        workflow.score(release, pred, tmp_path / "result")
    assert not (tmp_path / "result/reveal_authorization.json").exists()


def test_generator_pair_identity_and_answer_separation():
    cases = build_cases("pair-identity", 1)
    assert cases == build_cases("pair-identity", 1)
    for family in {c[4]["family"] for c in cases}:
        error = next(c for c in cases if c[4]["family"] == family and c[4]["cohort"] == "error")
        legal = next(c for c in cases if c[4]["family"] == family and c[4]["cohort"] == "legal_exception")
        assert error[1] == legal[1]
        assert error[2] != legal[2]
        assert b"expected_formula" not in error[2] and b"=" not in error[2]
        assert error[4]["errors"] and not legal[4]["errors"]
