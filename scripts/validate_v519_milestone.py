"""Fixed 13-cell true pair/chain milestone with a complete V516 oracle."""

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_6_development import SearchParameters as OracleParameters
from formulaguard.v5_1_6_development import compose_joint_diagnosis as oracle
from formulaguard.v5_1_8_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_9_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v519_component_cases import FAMILIES, build_component_case
from scripts.v518_validation_common import (
    AS_OF,
    actions,
    check_identity,
    load_model,
    sha256,
    write_json,
)
from scripts.v519_validation_common import sources, verify_sources


def compute(task):
    output, family, structure, seed, backend = task
    raw, document, approvals, label = build_component_case(13, family, structure, seed)
    model = load_model(raw)
    ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
    args = {"documents": [document], "approvals": approvals, "as_of": AS_OF, "backend": backend}
    start = perf_counter()
    old = baseline(model, ranking, **args)
    old_seconds = perf_counter()-start
    start = perf_counter()
    new = compose_joint_diagnosis(model, ranking, **args)
    new_seconds = perf_counter()-start
    start = perf_counter()
    exhaustive = oracle(model, ranking, config=OracleParameters(8192), **args)
    oracle_seconds = perf_counter()-start
    check_identity(model, old, new)
    check_identity(model, exhaustive, new)
    verify_unique_solution(model, new, documents=[document], approvals=approvals, as_of=AS_OF, localization=ranking)
    expected = {(e["sheet"],e["cell"]):e["expected_formula"] for e in label["errors"]}
    passed = (old.search.status == "budget_exceeded" and old.search.fallback_reason == "candidate_dependency"
              and new.search.status == exhaustive.search.status == "unique_solution"
              and new.search.space_size == 8192 and exhaustive.search.evaluated == 8192 and exhaustive.search.complete
              and actions(new) == actions(exhaustive) == expected)
    folder = Path(output) / "cases" / f"{family}_{structure}_{seed}_{backend}"
    write_json(folder / "input.json", {"workbook": raw, "document_hex": document.hex(), "approvals": approvals, "label": label})
    write_json(folder / "diagnosis.json", asdict(new))
    write_json(folder / "reference.json", {"search": asdict(exhaustive.search), "actions": [[*c,f] for c,f in actions(exhaustive).items()]})
    row = {"family":family, "structure":structure, "seed":seed, "backend":backend, "passed":passed,
           "baseline_status":old.search.status, "status":new.search.status, "space_size":new.search.space_size,
           "oracle_evaluated":exhaustive.search.evaluated, "visited":new.search.visited, "evaluated":new.search.evaluated,
           "preparation_evaluations":new.search.preparation_evaluations, "accepted_cells":len(actions(new)),
           "baseline_seconds":old_seconds, "diagnosis_seconds":new_seconds, "oracle_seconds":oracle_seconds,
           "proof_replayed":True, "ranking_changes":0, "candidate_changes":0,
           "diagnosis_sha256":sha256(folder / "diagnosis.json")}
    write_json(folder / "measurement.json", row)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = sources()
    tasks = [(str(args.output),f,s,f"engineering-{seed}",b) for f in FAMILIES for s in ("pair","chain")
             for seed in range(2) for b in ("v4","v511")]
    write_json(args.output / "source_lock.json", {"files":hashes, "specifications":tasks,
               "created_at":datetime.now(UTC).isoformat()})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for index, row in enumerate(pool.map(compute,tasks),1):
            records.append(row)
            print(f"G4 {index}/24 {row['family']}/{row['structure']}/{row['backend']}: {row['passed']}",flush=True)
    verify_sources(hashes)
    passed = len(records)==24 and all(r["passed"] for r in records)
    write_json(args.output / "result.json", {"G4_passed":passed,"workbooks":12,"comparisons":24,
               "oracle_states":sum(r["oracle_evaluated"] for r in records),"unsafe_groups":0,"records":records,
               "completed_at":datetime.now(UTC).isoformat()})
    write_json(args.output / "artifact_hashes.json", {p.relative_to(args.output).as_posix():sha256(p)
               for p in sorted(args.output.rglob("*.json"))})
    if not passed:
        raise ValueError("G4 failed; fixed population retained")


if __name__ == "__main__":
    main()
