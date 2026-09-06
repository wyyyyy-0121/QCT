"""Post-freeze observational profiler; not imported by prediction or scoring.

Run from the repository root: .venv/bin/python research/V518_COST_AUDIT.py
Uses predeclared engineering data, not confirmation inputs or labels.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formulaguard import v5_1_8_development as model_module
from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from scripts.build_v518_numeric_cases import build_case
from scripts.evaluate_v518_numeric import current_sources
from scripts.run_v512_evaluation import write_json
from scripts.v518_validation_common import AS_OF, load_model


def run():
    source_before = current_sources()
    output = ROOT / "research/V518_COST_AUDIT_V1"
    output.mkdir(parents=True, exist_ok=False)
    rows = []
    for backend in ("v4", "v511"):
        started = perf_counter()
        raw, document, approvals, _ = build_case(32, "product", "unique", "serial-benchmark")
        model = load_model(json.loads(json.dumps(raw)))
        load_seconds = perf_counter() - started
        started = perf_counter()
        ranking = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
        ranking_seconds = perf_counter() - started
        targets = {model_module.compose_edge_diagnosis.__code__: "candidate_preparation_seconds",
                   model_module._domain.__code__: "candidate_domain_seconds",
                   model_module._bounds.__code__: "bound_preparation_seconds",
                   model_module._result.__code__: "decision_output_seconds"}
        times = dict.fromkeys(targets.values(), 0.0)
        entries = {}

        def observe(frame, event, arg, targets=targets, entries=entries, times=times):
            if frame.f_code not in targets:
                return
            if event == "call":
                entries[id(frame)] = perf_counter()
            elif event == "return" and id(frame) in entries:
                times[targets[frame.f_code]] += perf_counter() - entries.pop(id(frame))

        sys.setprofile(observe)
        started = perf_counter()
        try:
            diagnosis = model_module.compose_joint_diagnosis(model, ranking, backend=backend,
                        documents=[document], approvals=approvals, as_of=AS_OF)
        finally:
            elapsed = perf_counter() - started
            sys.setprofile(None)
        started = perf_counter()
        model_module.verify_unique_solution(model, diagnosis, documents=[document], approvals=approvals, as_of=AS_OF)
        replay_seconds = perf_counter() - started
        started = perf_counter()
        result = diagnosis.to_results()
        json.dumps([{"cell": r.cell, "score": r.score, "candidate": r.candidate_formula, "evidence": r.evidence} for r in result])
        serialization_seconds = perf_counter() - started
        rows.append({"backend": backend, "candidate_cells": diagnosis.search.candidate_cells,
                     "status": diagnosis.search.status, **times, "diagnosis_seconds": elapsed,
                     "search_dispatch_initial_check_seconds": max(0.0, elapsed - sum(times.values())),
                     "input_construction_seconds": load_seconds, "ranking_seconds": ranking_seconds,
                     "proof_replay_seconds": replay_seconds, "serialization_seconds": serialization_seconds,
                     "observed_full_workflow_seconds": load_seconds + ranking_seconds + elapsed + replay_seconds + serialization_seconds,
                     "preparation_evaluations": diagnosis.search.preparation_evaluations,
                     "leaf_evaluations": diagnosis.search.evaluated, "visited_nodes": diagnosis.search.visited})
    if current_sources() != source_before:
        raise ValueError("frozen execution sources changed")
    write_json(output / "result.json", {"sources": source_before, "measurements": rows,
               "scope": "read-only profiler overhead included; residual includes initial checks and dispatch; input constructed in memory; not XLSX I/O latency"})
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    run()
