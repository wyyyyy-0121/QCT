import copy
import json

import pytest

from scripts.score_v512_confirmation import (
    canonical_formula,
    score_case,
    sha256,
    summarize,
    verify_double_run,
    verify_run,
)


def fixture():
    ranking = [{
        "rank": i, "sheet": "S", "cell": f"D{i}", "score": 1 / i,
        "candidate_formula": f"=B{i}*C{i}",
        "evidence": {"group_state": "accepted", "group_id": "g", "group_size": 2},
    } for i in (1, 2)]
    shard = {"case_id": "c", "model": "v512", "workbook_sha256": "a" * 64,
             "formula_count": 2, "accepted_group_count": 1, "ranking": ranking}
    label = {"case_id": "c", "cluster_id": "cluster", "family": "f", "cohort": "block",
             "truth_completeness": "complete", "decision": "detect_and_repair",
             "workbook_sha256": "a" * 64,
             "errors": [{"sheet": "S", "cell": f"D{i}", "expected_formula": f"=B{i}*C{i}"} for i in (1, 2)]}
    return shard, label


def test_one_wrong_member_makes_whole_group_unsafe():
    shard, label = fixture()
    shard["ranking"][1]["candidate_formula"] = "=B2+C2"
    summary = summarize([score_case(shard, label)])
    assert summary["accepted_cell_precision"] == .5
    assert summary["accepted_group_precision"] == 0
    assert summary["unsafe_accepted_groups_in_repair_workbooks"] == 1


def test_clean_cell_inside_repair_workbook_is_counted_as_unsafe():
    shard, label = fixture()
    label["errors"].pop()
    row = score_case(shard, label)
    assert row["unsafe_groups"] == 1
    assert row["exact_groups"] == 0


def test_global_denominator_includes_control_candidates():
    shard, label = fixture()
    repair = score_case(shard, label)
    label["decision"] = "no_action"
    label["errors"] = []
    control = score_case(shard, label)
    summary = summarize([repair, control])
    assert summary["global_candidate_location_precision"] == .5
    assert summary["accepted_group_precision"] == .5
    assert summary["control_workbook_candidate_fpr"] == 1
    assert summary["unsafe_accepted_groups_all_workbooks"] == 1


def test_partial_real_truth_cannot_produce_safety_claim():
    shard, label = fixture()
    label["truth_completeness"] = "known_errors_only"
    with pytest.raises(ValueError, match="complete truth"):
        score_case(shard, label)


@pytest.mark.parametrize("mutation", ["duplicate", "size", "count", "nan", "missing_formula", "label_identity"])
def test_inconsistent_records_are_rejected(mutation):
    shard, label = fixture()
    if mutation == "duplicate":
        shard["ranking"][1]["cell"] = "D1"
    elif mutation == "size":
        shard["ranking"][0]["evidence"]["group_size"] = 3
    elif mutation == "count":
        shard["accepted_group_count"] = 0
    elif mutation == "nan":
        shard["ranking"][0]["score"] = float("nan")
    elif mutation == "missing_formula":
        shard["ranking"][0]["candidate_formula"] = None
    else:
        label["case_id"] = "different"
    with pytest.raises(ValueError):
        score_case(shard, label)


def write_run(path, shard):
    (path / "shards").mkdir(parents=True)
    (path / "shards/c.json").write_text(json.dumps(shard))
    (path / "prediction_metadata.json").write_text(json.dumps({"model": "v512", "labels_read": []}))
    lock = {"protocol": "v512_prediction_lock_v1", "model": "v512", "cases": 1,
            "labels_read": [], "metadata_sha256": sha256(path / "prediction_metadata.json"),
            "shards": {"shards/c.json": sha256(path / "shards/c.json")}}
    (path / "prediction_lock.json").write_text(json.dumps(lock))
    return sha256(path / "prediction_lock.json")


@pytest.mark.parametrize("target", ["shard", "metadata", "extra", "missing"])
def test_changed_bytes_are_rejected_even_with_unchanged_lock(tmp_path, target):
    shard, _ = fixture()
    digest = write_run(tmp_path, shard)
    if target == "shard":
        (tmp_path / "shards/c.json").write_text("{}")
    elif target == "metadata":
        (tmp_path / "prediction_metadata.json").write_text("{}")
    elif target == "extra":
        (tmp_path / "shards/extra.json").write_text("{}")
    else:
        (tmp_path / "shards/c.json").unlink()
    with pytest.raises(ValueError):
        verify_run(tmp_path, digest, {"c": {"workbook_sha256": "a" * 64}})


def test_second_run_is_verified_and_compared(tmp_path):
    shard, _ = fixture()
    a = write_run(tmp_path / "run_a", shard)
    second = copy.deepcopy(shard)
    second["ranking"][0]["score"] = .99
    b = write_run(tmp_path / "run_b", second)
    with pytest.raises(ValueError, match="double-run"):
        verify_double_run(tmp_path, {"run_a": a, "run_b": b}, {"c": {"workbook_sha256": "a" * 64}})


def test_empty_acceptance_does_not_receive_perfect_precision():
    shard, label = fixture()
    for r in shard["ranking"]:
        r["candidate_formula"] = None
        r["evidence"] = {}
    shard["accepted_group_count"] = 0
    result = summarize([score_case(shard, label)])
    assert result["accepted_group_precision"] is None
    assert result["exact_candidate_coverage"] == 0


def test_formula_canonicalization_preserves_quoted_literals():
    assert canonical_formula('=IF(A1=1,"a b","c")') != canonical_formula('=IF(A1=1,"ab","c")')
    assert canonical_formula("=B1 * C1") == canonical_formula("=(B1*C1)")


def test_serialization_excludes_only_declared_timer():
    from scripts.run_v512_evaluation import stable_evidence
    evidence = {"localization_seconds": 1.25, "score": .8, "candidate_formula": "=B1*C1", "other_seconds": 7}
    assert stable_evidence(evidence) == {"score": .8, "candidate_formula": "=B1*C1", "other_seconds": 7}
    assert "localization_seconds" in evidence
