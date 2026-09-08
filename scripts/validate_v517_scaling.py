"""Reproducible engineering validation, with small-space exhaustive comparison.

Run as a module. All artifacts go to a new directory; historical evidence is not
read or overwritten. Scaling begins only after every differential case passes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from time import perf_counter

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_3_development import Candidate, RankedCell, RepairDecision
from formulaguard.v5_1_5_development import model_binding
from formulaguard.v5_1_6_development import SearchParameters as ExhaustiveParameters
from formulaguard.v5_1_6_development import compose_joint_diagnosis as exhaustive
from formulaguard.v5_1_7_development import (
    JointDiagnosis,
    SearchAudit,
    SearchParameters,
    Terminal,
    compose_joint_diagnosis,
    verify_unique_solution,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_v515_constraint_cases import FAMILIES
from scripts.build_v517_scaling_cases import build_case

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 9, 6)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def actions(diagnosis):
    return {d.cell: d.accepted_formula for d in diagnosis.decisions if d.accepted_formula}


def replay_case(folder):
    saved = json.loads((folder / "input.json").read_text())
    measured = json.loads((folder / "measurement.json").read_text())
    raw = saved["workbook"]
    label = saved["label"]
    generated, document, approvals, expected_label = build_case(label["count"], label["family"], label["kind"], label["seed"])
    if raw != generated or label != expected_label or saved["document_hex"] != document.hex() or saved["approvals"] != approvals:
        raise ValueError("fixture provenance mismatch")
    if saved["document"] != json.loads(document) or saved["as_of"] != AS_OF.isoformat():
        raise ValueError("constraint context mismatch")
    model = WorkbookModel.from_cells({tuple(r[:2]): r[2] for r in raw["cells"]},
                                     {tuple(r[:2]): r[2] for r in raw["formulas"]})
    saved_diagnosis = json.loads((folder / "diagnosis.json").read_text())
    audit = saved_diagnosis["search"]
    audit["terminals"] = tuple(Terminal(tuple(t["prefix"]), t["constraint"]) for t in audit["terminals"])
    diagnosis = JointDiagnosis(
        saved_diagnosis["backend"], saved_diagnosis["repair_policy"],
        tuple(RankedCell(**{**r, "cell": tuple(r["cell"])}) for r in saved_diagnosis["localization"]),
        tuple(Candidate(**{**r, "cell": tuple(r["cell"])}) for r in saved_diagnosis["candidates"]),
        tuple(RepairDecision(**{**r, "cell": tuple(r["cell"])}) for r in saved_diagnosis["decisions"]), SearchAudit(**audit))
    ranking = (v4_scores if diagnosis.backend == "v4" else v5_1_1_development_scores)(model)
    baseline = exhaustive(model, ranking, backend=diagnosis.backend, documents=[document], approvals=approvals,
                          as_of=AS_OF, config=ExhaustiveParameters(1))
    if diagnosis.localization != baseline.localization or diagnosis.candidates != baseline.candidates:
        raise ValueError("persisted ranking or candidate mismatch")
    if measured["localization_sha256"] != diagnosis.localization_sha256 or measured["space_size"] != diagnosis.search.space_size:
        raise ValueError("measurement identity mismatch")
    if diagnosis.search.status == "unique_solution":
        verify_unique_solution(model, diagnosis, documents=[document], approvals=approvals, as_of=AS_OF)
        expected = {(e["sheet"], e["cell"]): e["expected_formula"] for e in label["errors"]}
        if label["decision"] != "repair" or actions(diagnosis) != expected:
            raise ValueError("persisted unsafe transaction")
    elif actions(diagnosis):
        raise ValueError("nonunique persisted transaction")
    if measured["status"] != diagnosis.search.status or measured["accepted_cells"] != len(actions(diagnosis)):
        raise ValueError("measurement outcome mismatch")
    return measured


def verify_artifacts(output):
    hashes = json.loads((output / "artifact_hashes.json").read_text())
    actual = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*.json")) if p.name != "artifact_hashes.json"}
    if hashes != actual:
        raise ValueError("artifact inventory or hash mismatch")
    lock = json.loads((output / "source_lock.json").read_text())["files"]
    if any(digest(ROOT / name) != value for name, value in lock.items()):
        raise ValueError("source no longer matches validation")
    result = json.loads((output / "result.json").read_text())
    for row in result["rows"]:
        if replay_case(output / "cases" / row["case_id"]) != row:
            raise ValueError("summary differs from case measurement")
    if len(result["rows"]) != len(list((output / "cases").iterdir())):
        raise ValueError("case population mismatch")
    print(f"Verified {len(result['rows'])} persisted case/backend records and their unique-solution proofs.", flush=True)


def run_case(output, count, family, kind, seed, backend, crosscheck):
    raw, document, approvals, label = build_case(count, family, kind, seed)
    model = WorkbookModel.from_cells({tuple(r[:2]): r[2] for r in raw["cells"]},
                                     {tuple(r[:2]): r[2] for r in raw["formulas"]})
    before = model_binding(model)
    args = {"documents": [document], "approvals": approvals, "as_of": AS_OF, "backend": backend}
    start = perf_counter()
    ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
    ranking_seconds = perf_counter() - start
    # Unfavorable fractional and mixed-sign cases retain their outcomes at these
    # declared resource limits; their candidate spaces are never truncated.
    config = SearchParameters(max_nodes=2048, max_evaluations=256) if kind in {"fractional", "mixed_no_solution"} else SearchParameters()
    start = perf_counter()
    diagnosis = compose_joint_diagnosis(model, ranking, config=config, **args)
    search_seconds = perf_counter() - start
    start = perf_counter()
    baseline = exhaustive(model, ranking, config=ExhaustiveParameters(2**count if crosscheck else 256), **args)
    baseline_seconds = perf_counter() - start
    if diagnosis.localization != baseline.localization or diagnosis.candidates != baseline.candidates:
        raise ValueError("localization or candidate portfolio changed")
    results = diagnosis.to_results()
    if [(r.cell, float(r.score).hex()) for r in results] != [(r.cell, float(r.score).hex()) for r in ranking]:
        raise ValueError("API ranking changed")
    if len(results) != len(model.formulas) or {r.cell for r in results} != set(model.formulas):
        raise ValueError("incomplete formula population")
    if diagnosis.search.space_size != baseline.search.space_size:
        raise ValueError("candidate space changed")
    if crosscheck and (diagnosis.search.status != baseline.search.status or actions(diagnosis) != actions(baseline)):
        raise ValueError("exhaustive differential mismatch")
    accepted = actions(diagnosis)
    expected = {(e["sheet"], e["cell"]): e["expected_formula"] for e in label["errors"]}
    if accepted and (label["decision"] != "repair" or accepted != expected):
        raise ValueError("unsafe or partial accepted transaction")
    start = perf_counter()
    proof_replayed = diagnosis.search.status == "unique_solution"
    if proof_replayed:
        verify_unique_solution(model, diagnosis, documents=[document], approvals=approvals, as_of=AS_OF)
    replay_seconds = perf_counter() - start
    if model_binding(model) != before:
        raise ValueError("workbook mutated")
    case_id = f"{count}_{family}_{kind}_{seed}_{backend}"
    folder = output / "cases" / case_id
    write_json(folder / "input.json", {"workbook": raw, "document": json.loads(document), "approvals": approvals,
                                       "document_hex": document.hex(), "as_of": AS_OF.isoformat(), "label": label})
    write_json(folder / "diagnosis.json", asdict(diagnosis))
    row = {"case_id": case_id, "stage": "exhaustive_crosscheck" if crosscheck else "scaling",
           "count": count, "family": family, "kind": kind, "backend": backend,
           "configuration": asdict(config), "status": diagnosis.search.status,
           "engine": diagnosis.search.engine, "fallback_reason": diagnosis.search.fallback_reason,
           "space_size": diagnosis.search.space_size, "visited": diagnosis.search.visited,
           "evaluated": diagnosis.search.evaluated, "preparation_evaluations": diagnosis.search.preparation_evaluations,
           "pruned_states": diagnosis.search.pruned_states, "complete": diagnosis.search.complete,
           "solutions_seen": diagnosis.search.solutions_seen, "proof_replayed": proof_replayed,
           "accepted_cells": len(accepted), "required_cells": len(expected),
           "baseline_status": baseline.search.status, "baseline_evaluated": baseline.search.evaluated,
           "ranking_seconds": ranking_seconds, "diagnosis_seconds": search_seconds,
           "end_to_end_seconds": ranking_seconds + search_seconds,
           "baseline_diagnosis_seconds": baseline_seconds, "proof_replay_seconds": replay_seconds,
           "localization_sha256": diagnosis.localization_sha256, "ranking_equal": True, "candidates_equal": True}
    write_json(folder / "measurement.json", row)
    print(f"{case_id}: {row['status']}, space={row['space_size']}, leaves={row['evaluated']}, accepted={len(accepted)}", flush=True)
    return row


def validate(output):
    if output.exists():
        raise FileExistsError("output must be a new directory")
    output.mkdir(parents=True)
    sources = sorted([*ROOT.glob("formulaguard/*.py"), ROOT / "scripts/build_v515_constraint_cases.py",
                      ROOT / "scripts/build_v517_scaling_cases.py", Path(__file__).resolve(),
                      ROOT / "tests/test_v5_1_7_development.py", ROOT / "research/V517_SEARCH_PROTOCOL.md"])
    lock = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    write_json(output / "source_lock.json", {"created_at": datetime.now(UTC).isoformat(), "files": lock,
                                           "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                                           "scope": "engineering validation; known generated families; not blind confirmation"})
    rows = []
    for count, families, seeds in ((9, FAMILIES, ("a", "b")), (10, ("product", "range"), ("a",)),
                                    (12, ("product",), ("a",))):
        for family in families:
            for seed in seeds:
                for backend in ("v4", "v511"):
                    rows.append(run_case(output, count, family, "unique", seed, backend, True))
    if not all(r["status"] == "unique_solution" and r["space_size"] > 256 and r["proof_replayed"] for r in rows):
        raise ValueError("first milestone not achieved")
    write_json(output / "milestone.json", {"completed_at": datetime.now(UTC).isoformat(), "comparisons": len(rows),
                                         "unique_cases": len({r["case_id"].rsplit("_", 1)[0] for r in rows}),
                                         "crosschecked_states": sum(r["baseline_evaluated"] for r in rows)})
    for count in (24, 32):
        for family, kinds in (("product", ("unique", "mixed_subtotals", "ambiguous", "mixed_total", "mixed_no_solution", "fractional")),
                              ("ratio", ("unique", "mixed_subtotals")), ("range", ("unique", "mixed_subtotals"))):
            for kind in kinds:
                for backend in ("v4", "v511"):
                    rows.append(run_case(output, count, family, kind, "scale", backend, False))
    if lock != {str(p.relative_to(ROOT)): digest(p) for p in sources}:
        raise ValueError("source changed during validation")
    summary = {"completed_at": datetime.now(UTC).isoformat(), "rows": rows,
               "case_backend_comparisons": len(rows), "status_counts": dict(Counter(r["status"] for r in rows)),
               "unsafe_accepted_groups": 0, "ranking_changes": 0, "candidate_changes": 0,
               "scope": "engineering validation only; 24/32 spaces verified by certificates, not exhaustive enumeration"}
    write_json(output / "result.json", summary)
    artifacts = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*.json"))}
    write_json(output / "artifact_hashes.json", artifacts)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    if args.verify:
        verify_artifacts(args.output)
    else:
        validate(args.output)
