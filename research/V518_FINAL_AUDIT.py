"""Read-only post-scoring audit of frozen V518 confirmation artifacts."""

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.evaluate_v518_numeric import (
    BACKENDS,
    MODES,
    current_sources,
    release_context,
)
from scripts.score_v512_confirmation import canonical_formula
from scripts.v518_validation_common import decode, sha256, write_json


def main():
    release = ROOT / "results/v518_confirmation_release_v1"
    predictions = ROOT / "results/v518_confirmation_predictions_v1"
    lock_path = ROOT / "results/v518_freeze_v1/source_lock.json"
    output = ROOT / "research/V518_VALIDATION_V1"
    read = lambda p: json.loads(p.read_text())
    lock = read(lock_path)
    receipt, rows, _ = release_context(release, lock_path)
    prediction = read(predictions / "prediction_lock.json")
    authorization = read(output / "reveal_authorization.json")
    result = read(output / "result.json")
    assert authorization["all_inputs_rankings_proofs_verified"]
    assert authorization["prediction_lock_sha256"] == sha256(predictions / "prediction_lock.json")
    assert current_sources() == lock["artifacts"] == prediction["sources"]
    for name, digest in lock["artifacts"].items():
        assert sha256(lock_path.parent / "source" / name) == digest
    times = [lock["frozen_at"], receipt["generated_at"], prediction["completed_at"],
             authorization["authorized_at"], result["completed_at"]]
    assert sorted(map(datetime.fromisoformat, times)) == list(map(datetime.fromisoformat, times))
    assert sha256(release / "labels.json") == receipt["labels_sha256"]
    labels = {r["case_id"]: r for r in read(release / "labels.json")["cases"]}
    expected = {f"shards/{b}_{m}/{r['case_id']}.json" for b in BACKENDS for m in MODES for r in rows}
    assert expected == set(prediction["shards"])
    assert expected == {p.relative_to(predictions).as_posix() for p in (predictions / "shards").rglob("*.json")}
    records = {(r["case_id"], r["backend"], r["mode"]): r for r in result["records"]}
    accepted_groups = 0
    paths = Counter()
    strata = Counter()
    for label in labels.values():
        strata[f"{label['family']}:{label['kind']}:{label['count']}"] += 1
    assert len(strata) == 72 and set(strata.values()) == {2}
    for name in sorted(expected):
        assert sha256(predictions / name) == prediction["shards"][name]
        shard = read(predictions / name)
        diagnosis = decode(shard["diagnosis"])
        record = records[(shard["case_id"], shard["backend"], shard["mode"])]
        label = labels[shard["case_id"]]
        truth = {(e["sheet"], e["cell"]): canonical_formula(e["expected_formula"]) for e in label["errors"]}
        accepted = [d for d in diagnosis.decisions if d.accepted_formula is not None]
        assert record["required_cells"] == len(truth)
        assert record["correct_cells"] == len(accepted)
        assert not record["unsafe_group"]
        if accepted:
            assert label["decision"] not in {"abstain", "no_action"}
            assert diagnosis.search.complete and diagnosis.search.solutions_seen == 1
            assert record["proof_replayed"] and record["status"] == "unique_solution"
            assert len({d.group_id for d in accepted}) == 1 and accepted[0].group_id
            assert all(d.state == "accepted" and d.group_size == len(accepted) for d in accepted)
            assert all(truth.get(d.cell) == canonical_formula(d.accepted_formula) for d in accepted)
            accepted_groups += 1
        if shard["mode"] == "numeric":
            paths[f"{shard['backend']}:{diagnosis.search.engine}:{diagnosis.search.fallback_reason}"] += 1
    assert result["stage"] == "confirmation" and result["workbooks"] == 144
    assert result["diagnoses"] == len(records) == 1728 and result["gate_passed"]
    assert result["ranking_changes"] == result["candidate_changes"] == 0
    for backend in BACKENDS:
        assert result["summaries"][backend + "_numeric"]["coverage"] > result["summaries"][backend + "_baseline"]["coverage"]
    write_json(output / "final_audit.json", {"passed": True, "frozen_files": len(lock["artifacts"]),
               "shards_verified": len(expected), "accepted_groups_checked": accepted_groups,
               "chronology": times, "numeric_paths": dict(paths), "strata": dict(strata),
               "scope": "post-score raw hash, population, transaction and chronology audit; proof replay and ranking recomputation performed by scorer"})
    print(json.dumps({"passed": True, "accepted_groups": accepted_groups, "numeric_paths": dict(paths)}))


if __name__ == "__main__":
    main()
