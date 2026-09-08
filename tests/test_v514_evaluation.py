import json
import shutil

import pytest

from scripts import evaluate_v514_edges as workflow
from scripts.build_v514_edge_cases import build_cases
from scripts.score_v512_confirmation import sha256


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    root = tmp_path_factory.mktemp("v514-eval")
    all_cases = build_cases("unit-protocol", 1)
    selected = [next(c for c in all_cases if c[2]["cohort"] == kind)
                for kind in ("edge_operator", "clean", "short")]
    original = workflow.build_cases
    try:
        workflow.build_cases = lambda seed, repeats: selected
        workflow.build(root / "release")
    finally:
        workflow.build_cases = original
    workflow.predict(root / "release/PUBLIC", root / "predictions")
    return root


def test_scoring_and_denominators(prepared, tmp_path):
    workflow.score(prepared / "release", prepared / "predictions", tmp_path / "result")
    result = json.loads((tmp_path / "result/result.json").read_text())
    orthogonal = result["variants"]["v511_orthogonal_structural"]
    assert orthogonal["candidate_oracle_denominator"] == 1
    assert orthogonal["candidate_oracle_covered"] == 1
    assert orthogonal["exact_candidate_coverage"] == 1
    assert result["variants"]["v511_propose_only_structural"]["exact_candidate_coverage"] == 0
    assert (tmp_path / "result/reveal_authorization.json").is_file()


@pytest.mark.parametrize("defect", ["hash", "rank", "coverage", "missing_variant"])
def test_corrupt_predictions_rejected_before_reveal(prepared, tmp_path, defect):
    destination = tmp_path / "predictions"
    shutil.copytree(prepared / "predictions", destination)
    lock_path = destination / "prediction_lock.json"
    lock = json.loads(lock_path.read_text())
    name = next(p for p in lock["shards"] if p.startswith("v4_orthogonal_structural/"))
    path = destination / name
    value = json.loads(path.read_text())
    if defect in {"hash", "rank"}:
        value["ranking"][0]["score"] += 123
    elif defect == "coverage":
        value["ranking"].pop()
        value["formula_count"] -= 1
    else:
        del lock["shards"][name]
    if defect != "missing_variant":
        workflow.write_json(path, value)
        if defect != "hash":
            lock["shards"][name] = sha256(path)
    workflow.write_json(lock_path, lock)
    with pytest.raises(ValueError):
        workflow.score(prepared / "release", destination, tmp_path / "result")
    assert not (tmp_path / "result/reveal_authorization.json").exists()


def test_generator_is_deterministic_and_has_declared_categories():
    a = build_cases("test", 1)
    assert a == build_cases("test", 1)
    assert a != build_cases("different", 1)
    assert len(a) == 66
    assert len({c[0] for c in a}) == 66
    for _, raw, label in a:
        assert len({tuple(f[:2]) for f in raw["formulas"]}) == len(raw["formulas"])
        errors = {(e["sheet"], e["cell"]) for e in label["errors"]}
        assert errors <= {tuple(f[:2]) for f in raw["formulas"]}
        if label["decision"] == "no_action":
            assert not errors
