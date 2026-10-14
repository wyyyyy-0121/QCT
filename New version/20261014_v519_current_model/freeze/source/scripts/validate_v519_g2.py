"""All 72 fixed G1 workbooks: budgeted G2 search, full identity and replay."""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_8_development import SearchParameters as BaselineParameters
from formulaguard.v5_1_8_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_9_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v515_constraint_cases import encode
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
    output, reference = task
    folder = ROOT / "research/V519_G1_V1/cases" / reference["name"]
    if sha256(folder / "input.json") != reference["input_sha256"] or sha256(folder / "tables.json") != reference["tables_sha256"]:
        raise ValueError("G1 reference changed")
    raw = json.loads((folder / "input.json").read_text())
    model = load_model(raw["workbook"])
    document = encode(raw["document"])
    rows = []
    for backend in ("v4", "v511"):
        ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
        args = {"documents": [document], "approvals": raw["approvals"], "as_of": AS_OF, "backend": backend}
        old = baseline(model, ranking, config=BaselineParameters(max_nodes=1), **args)
        new = compose_joint_diagnosis(model, ranking, **args)
        check_identity(model, old, new)
        path = Path(output) / "cases" / f"{reference['name']}_{backend}.json"
        write_json(path, asdict(new))
        persisted = decode(json.loads(path.read_text()))
        if persisted != new:
            raise ValueError("diagnosis serialization changed")
        if new.search.status == "unique_solution":
            verify_unique_solution(model, persisted, documents=[document], approvals=raw["approvals"],
                                   as_of=AS_OF, localization=ranking)
            expected = {(e["sheet"], e["cell"]): e["expected_formula"] for e in raw["label"]["errors"]}
            if actions(new) != expected or len(reference["satisfying_assignments"]) != 1:
                raise ValueError("G2 differs from complete G1 oracle")
        elif actions(new):
            raise ValueError("incomplete G2 accepted")
        family, structure, count, seed = reference["specification"]
        rows.append({"case": reference["name"], "family": family, "structure": structure, "count": count, "seed": seed,
                     "backend": backend, "status": new.search.status, "engine": new.search.engine,
                     "visited": new.search.visited, "evaluated": new.search.evaluated,
                     "preparation_evaluations": new.search.preparation_evaluations,
                     "space_size": new.search.space_size, "accepted_cells": len(actions(new)),
                     "proof_replayed": new.search.status == "unique_solution", "ranking_changes": 0, "candidate_changes": 0,
                     "diagnosis_sha256": sha256(path)})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = sources()
    oracle_path = ROOT / "research/V519_G1_V1/result.json"
    oracle = json.loads(oracle_path.read_text())
    if not oracle["passed"] or len(oracle["records"]) != 72:
        raise ValueError("incomplete G1 oracle")
    write_json(args.output / "source_lock.json", {"files": hashes, "oracle_sha256": sha256(oracle_path),
               "created_at": datetime.now(UTC).isoformat()})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, rows in enumerate(pool.map(compute, ((str(args.output), r) for r in oracle["records"])), 1):
            records.extend(rows)
            print(f"G2 {index}/72: {[r['status'] for r in rows]}", flush=True)
    minimum = [r for r in records if r["structure"] in {"pair", "chain"} and r["count"] in {4,8}]
    passed = len(minimum) == 48 and all(r["proof_replayed"] for r in minimum)
    verify_sources(hashes)
    write_json(args.output / "result.json", {"G2_passed": passed, "workbooks": 72, "diagnoses": len(records),
               "minimum_workbooks": 24, "unique_diagnoses": sum(r["proof_replayed"] for r in records),
               "unsafe_groups": 0, "records": records, "completed_at": datetime.now(UTC).isoformat()})
    if not passed:
        raise ValueError("G2 minimum gate failed; complete results retained")


if __name__ == "__main__":
    main()
