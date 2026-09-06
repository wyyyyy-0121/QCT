"""Predeclared 24-workbook G4 cohort, with actual full V516 enumeration."""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_6_development import SearchParameters as ExhaustiveParameters
from formulaguard.v5_1_6_development import compose_joint_diagnosis as exhaustive
from formulaguard.v5_1_7_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_8_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v518_numeric_cases import FAMILIES, build_case
from scripts.run_v512_evaluation import write_json
from scripts.score_v512_confirmation import sha256
from scripts.v518_validation_common import (
    AS_OF,
    actions,
    check_identity,
    load_model,
    save_diagnosis,
)

ROOT = Path(__file__).resolve().parents[1]


def compute(task):
    output, family, kind, seed, backend = task
    raw, document, approvals, label = build_case(13, family, kind, seed)
    model = load_model(raw)
    ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
    args = {"backend": backend, "documents": [document], "approvals": approvals, "as_of": AS_OF}
    started = perf_counter()
    previous = baseline(model, ranking, **args)
    baseline_seconds = perf_counter()-started
    started = perf_counter()
    current = compose_joint_diagnosis(model, ranking, **args)
    current_seconds = perf_counter()-started
    started = perf_counter()
    reference = exhaustive(model, ranking, config=ExhaustiveParameters(8192), **args)
    exhaustive_seconds = perf_counter()-started
    check_identity(model, previous, current)
    check_identity(model, reference, current)
    if current.search.status != reference.search.status or actions(current) != actions(reference):
        raise ValueError("G4 exhaustive differential failure")
    expected = {(r["sheet"],r["cell"]):r["expected_formula"] for r in label["errors"]}
    if current.search.status == "unique_solution":
        verify_unique_solution(model, current, documents=[document], approvals=approvals, as_of=AS_OF)
        if actions(current) != expected:
            raise ValueError("G4 unsafe transaction")
    case_id = f"{family}_{kind}_{seed}_{backend}"
    folder = Path(output) / "cases" / case_id
    write_json(folder / "input.json", {"workbook":raw,"document_hex":document.hex(),"approvals":approvals,"label":label})
    save_diagnosis(folder / "diagnosis.json", current)
    write_json(folder / "reference.json", {"search":asdict(reference.search),
                                          "actions":[[*cell,formula] for cell,formula in sorted(actions(reference).items())],
                                          "localization_sha256":reference.localization_sha256})
    row = {"case_id":case_id,"family":family,"kind":kind,"backend":backend,"seed":seed,
           "space_size":current.search.space_size,"baseline_status":previous.search.status,
           "baseline_fallback":previous.search.fallback_reason,"status":current.search.status,
           "engine":current.search.engine,"baseline_evaluated":previous.search.evaluated,
           "exhaustive_evaluated":reference.search.evaluated,"evaluated":current.search.evaluated,
           "pruned_states":current.search.pruned_states,"accepted_cells":len(actions(current)),
           "improved":previous.search.status=="budget_exceeded" and current.search.status=="unique_solution",
           "baseline_seconds":baseline_seconds,"diagnosis_seconds":current_seconds,"exhaustive_seconds":exhaustive_seconds,
           "ranking_equal":True,"candidates_equal":True,"proof_replayed":current.search.status=="unique_solution"}
    write_json(folder / "measurement.json", row)
    return row


def run(output, workers=4):
    output.mkdir(parents=True,exist_ok=False)
    files = sorted([*ROOT.glob("formulaguard/*.py"),*ROOT.glob("scripts/*v518*.py"),
                    ROOT/"scripts/build_v515_constraint_cases.py",ROOT/"research/V518_NUMERIC_PROTOCOL.md",
                    ROOT/"research/V518_DEVELOPMENT_PLAN.md"])
    hashes = {p.relative_to(ROOT).as_posix():sha256(p) for p in files}
    write_json(output / "source_lock.json", {"created_at":datetime.now(UTC).isoformat(),"files":hashes,"workers":workers,
                                           "scope":"engineering known seeds; timing under concurrent workers"})
    tasks = [(str(output),family,kind,f"engineering-{seed}",backend) for family in FAMILIES
             for kind in ("unique","mixed_subtotals") for seed in range(4) for backend in ("v4","v511")]
    rows = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for row in pool.map(compute,tasks):
            rows.append(row)
            print(f"{row['case_id']}: {row['baseline_status']} -> {row['status']}; exhaustive={row['exhaustive_evaluated']}",flush=True)
    if any(sha256(ROOT/name)!=value for name,value in hashes.items()):
        raise ValueError("G4 source changed during run")
    improved = {r["case_id"].rsplit("_",1)[0] for r in rows if r["improved"]}
    paired = all(sum(r["improved"] for r in rows if r["case_id"].rsplit("_",1)[0]==case)==2 for case in improved)
    gate = len(improved)>=12 and paired and all(sum(case.startswith(family+"_") for case in improved)>=2 for family in FAMILIES)
    summary={"completed_at":datetime.now(UTC).isoformat(),"workbooks":24,"comparisons":48,"rows":rows,
             "improved_workbooks":len(improved),"G4_passed":gate,"unsafe_groups":0,
             "exhaustive_states":sum(r["exhaustive_evaluated"] for r in rows)}
    write_json(output/"result.json",summary)
    write_json(output/"artifact_hashes.json",{p.relative_to(output).as_posix():sha256(p) for p in sorted(output.rglob("*.json"))})
    if not gate:
        raise ValueError("G4 milestone not achieved; complete cohort retained")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    run(args.output,args.workers)
