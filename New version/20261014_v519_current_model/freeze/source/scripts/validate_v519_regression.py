"""Entire revealed V518 population, with fresh ranks and old/new proof replay."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_8_development import verify_unique_solution as verify_old
from formulaguard.v5_1_9_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.evaluate_v518_numeric import release_context
from scripts.score_v512_confirmation import canonical_formula
from scripts.v518_validation_common import (
    AS_OF,
    actions,
    check_identity,
    load_model,
    sha256,
    write_json,
)
from scripts.v519_validation_common import ROOT, decode, sources, verify_sources


def compute(task):
    output, stage, row, approval, truth, shard_hashes = task
    release = ROOT / f"results/v518_{stage}_release_v1"
    predictions = ROOT / f"results/v518_{stage}_predictions_v1"
    model = load_model(json.loads((release / "PUBLIC" / row["workbook_path"]).read_text()))
    document = (release / "PUBLIC" / row["document_path"]).read_bytes()
    records = []
    for backend in ("v4", "v511"):
        shard_name = f"shards/{backend}_numeric/{row['case_id']}.json"
        if sha256(predictions / shard_name) != shard_hashes[shard_name]:
            raise ValueError("old prediction changed")
        old = decode(json.loads((predictions / shard_name).read_text())["diagnosis"])
        ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
        args = {"documents": [document], "approvals": approval, "as_of": AS_OF}
        new = compose_joint_diagnosis(model, ranking, backend=backend, **args)
        check_identity(model, old, new)
        preserved = old.search.status == "unique_solution"
        if preserved:
            verify_old(model, old, **args)
            if actions(old) != actions(new):
                raise ValueError("former accepted group regressed")
        if new.search.status == "unique_solution":
            verify_unique_solution(model, new, localization=ranking, **args)
        expected = {(e["sheet"],e["cell"]): canonical_formula(e["expected_formula"]) for e in truth["errors"]}
        accepted = {c: canonical_formula(f) for c, f in actions(new).items()}
        unsafe = bool(accepted) and (truth["decision"] in {"abstain", "no_action"} or any(expected.get(c) != f for c, f in accepted.items()))
        path = Path(output) / "cases" / f"{stage}_{row['case_id']}_{backend}.json"
        write_json(path, asdict(new))
        records.append({"stage": stage, "case_id": row["case_id"], "backend": backend, "kind": truth["kind"],
                        "family": truth["family"], "count": truth["count"], "status": new.search.status,
                        "old_status": old.search.status, "old_accepted_preserved": preserved,
                        "engine": new.search.engine, "fallback_reason": new.search.fallback_reason,
                        "required_cells": len(expected), "correct_cells": sum(expected.get(c) == f for c, f in accepted.items()),
                        "accepted_cells": len(accepted), "unsafe_group": unsafe,
                        "proof_replayed": new.search.status == "unique_solution", "ranking_changes": 0, "candidate_changes": 0,
                        "diagnosis_sha256": sha256(path)})
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = sources()
    tasks = []
    receipts = {}
    for stage in ("development", "confirmation"):
        release = ROOT / f"results/v518_{stage}_release_v1"
        predictions = ROOT / f"results/v518_{stage}_predictions_v1"
        lock = ROOT / "results/v518_freeze_v1/source_lock.json" if stage == "confirmation" else None
        receipt, rows, registry = release_context(release, lock)
        old_result = ROOT / ("research/V518_VALIDATION_V1" if stage == "confirmation" else "research/V518_DEVELOPMENT_VALIDATION_V1")
        authorization = json.loads((old_result / "reveal_authorization.json").read_text())
        if authorization["prediction_lock_sha256"] != sha256(predictions / "prediction_lock.json"):
            raise ValueError("old revelation authorization mismatch")
        if sha256(release / "labels.json") != receipt["labels_sha256"]:
            raise ValueError("old label hash mismatch")
        labels = {r["case_id"]: r for r in json.loads((release / "labels.json").read_text())["cases"]}
        prediction = json.loads((predictions / "prediction_lock.json").read_text())
        if set(labels) != {r["case_id"] for r in rows}:
            raise ValueError("old population changed")
        for row in rows:
            tasks.append((str(args.output), stage, row, registry[row["case_id"]], labels[row["case_id"]], prediction["shards"]))
        receipts[stage] = {"release": sha256(release / "release_receipt.json"), "prediction": sha256(predictions / "prediction_lock.json")}
    if len(tasks) != 192:
        raise ValueError("incomplete regression population")
    write_json(args.output / "source_lock.json", {"files": hashes, "receipts": receipts, "created_at": datetime.now(UTC).isoformat()})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, rows in enumerate(pool.map(compute, tasks), 1):
            records.extend(rows)
            print(f"G3 {index}/192: {[r['status'] for r in rows]}", flush=True)
    verify_sources(hashes)
    passed = len(records) == 384 and not any(r["unsafe_group"] for r in records)
    passed &= sum(r["old_accepted_preserved"] for r in records) == 84
    write_json(args.output / "result.json", {"G3_passed": passed, "workbooks": 192, "diagnoses": len(records),
               "preserved_unique_diagnoses": sum(r["old_accepted_preserved"] for r in records),
               "unsafe_groups": sum(r["unsafe_group"] for r in records), "records": records,
               "completed_at": datetime.now(UTC).isoformat()})
    if not passed:
        raise ValueError("G3 gate failed; complete records retained")


if __name__ == "__main__":
    main()
