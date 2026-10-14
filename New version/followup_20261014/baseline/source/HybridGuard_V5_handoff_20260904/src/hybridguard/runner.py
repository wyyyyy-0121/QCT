"""Run StructuralGuard and the supplied FormulaGuard V5 comparably."""

from __future__ import annotations

import argparse
import csv
import ctypes
import gc
import json
import platform
import sys
import time
from pathlib import Path
from typing import Callable

from formulaguard.v5_structural_guard import v5_structural_guard_scores
from formulaguard.workbook import WorkbookModel
from structuralguard.detector import analyze_workbook

from .hybrid import fuse_rankings
from .metrics import average_precision, rank_lookup, top_k_stats


class _ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _process_memory() -> tuple[float, float]:
    if sys.platform != "win32":
        return 0.0, 0.0
    counters = _ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(_ProcessMemoryCounters),
        ctypes.c_ulong,
    ]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    handle = kernel32.GetCurrentProcess()
    ok = psapi.GetProcessMemoryInfo(
        handle, ctypes.byref(counters), counters.cb
    )
    if not ok:
        return 0.0, 0.0
    scale = 1024 * 1024
    return counters.WorkingSetSize / scale, counters.PeakWorkingSetSize / scale


def _measure(call: Callable[[], object]) -> tuple[object, dict[str, float]]:
    gc.collect()
    cpu_start = time.process_time()
    wall_start = time.perf_counter()
    value = call()
    wall = time.perf_counter() - wall_start
    cpu = time.process_time() - cpu_start
    working_set, peak_working_set = _process_memory()
    return value, {
        "wall_seconds": wall,
        "cpu_seconds": cpu,
        "working_set_mib": working_set,
        "process_peak_working_set_mib": peak_working_set,
    }


def _load_truth(path: Path) -> tuple[dict[str, dict[str, object]], list[dict[str, object]], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cells = {row["cell"]: row for row in payload["errors"]}
    return cells, payload["groups"], payload["parallel_sheets"]


def _formula_payload(results) -> list[dict[str, object]]:
    rows = []
    for rank, item in enumerate(results, 1):
        rows.append({
            "rank": rank,
            "cell": item.cell_label,
            "cell_key": item.cell,
            "score": item.score,
            "candidate_formula": item.candidate_formula,
            "evidence": item.evidence,
        })
    return rows


def _evaluate_model(name: str, rows: list[dict[str, object]], truth: dict[str, dict[str, object]], groups):
    ranked = [str(row["cell"]) for row in rows]
    truth_cells = set(truth)
    ranks = rank_lookup(ranked)
    repairs = 0
    candidate_field = (
        "candidate_formula"
        if name.startswith("FormulaGuard")
        else "suggested_formula"
    )
    for row in rows:
        label = str(row["cell"])
        if label in truth and row.get(candidate_field) == truth[label]["correct_formula"]:
            repairs += 1
    group_rows = []
    for group in groups:
        member_ranks = [ranks[cell] for cell in group["cells"] if cell in ranks]
        group_rows.append({
            "group_id": group["group_id"],
            "kind": group["kind"],
            "size": len(group["cells"]),
            "best_rank": min(member_ranks) if member_ranks else None,
            "median_rank": sorted(member_ranks)[len(member_ranks) // 2] if member_ranks else None,
            "top10_detected": bool(member_ranks and min(member_ranks) <= 10),
            "top100_detected": bool(member_ranks and min(member_ranks) <= 100),
        })
    return {
        "model": name,
        "formula_cells_ranked": len(ranked),
        "error_cells": len(truth_cells),
        "average_precision": average_precision(ranked, truth_cells),
        "top_k": [top_k_stats(ranked, truth_cells, k) for k in (5, 10, 50, 100, 500, len(truth_cells))],
        "exact_repairs": repairs,
        "groups": group_rows,
    }


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = [
        "rank", "cell", "score", "structural_score", "hybrid_score", "status",
        "formulaguard_rank", "group_id", "group_size", "candidate_formula",
        "suggested_formula", "suggestion_source", "is_error", "error_kind",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in keys})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("workbook", type=Path)
    parser.add_argument("truth", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=24)
    args = parser.parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    truth, groups, parallel_sheets = _load_truth(args.truth)

    structural_report, structural_perf = _measure(lambda: analyze_workbook(args.workbook))
    structural_rows = []
    for row in structural_report["results"]:
        item = dict(row)
        item["cell"] = f"{row['sheet']}!{row['cell']}"
        structural_rows.append(item)

    formula_model, formula_load_perf = _measure(lambda: WorkbookModel.from_xlsx(args.workbook))
    formula_results, formula_perf = _measure(lambda: v5_structural_guard_scores(
        formula_model, candidate_limit=args.candidate_limit
    ))
    formula_rows = _formula_payload(formula_results)

    formulas = {
        f"{sheet}!{cell}": formula
        for (sheet, cell), formula in formula_model.formulas.items()
    }
    hybrid_result, hybrid_perf = _measure(lambda: fuse_rankings(
        structural_report["results"], formula_rows, formulas, parallel_sheets
    ))
    hybrid_rows, detected_groups = hybrid_result

    for rows in (structural_rows, formula_rows, hybrid_rows):
        for row in rows:
            label = str(row["cell"])
            row["is_error"] = label in truth
            row["error_kind"] = truth.get(label, {}).get("kind")

    evaluations = [
        _evaluate_model("StructuralGuard", structural_rows, truth, groups),
        _evaluate_model(
            "FormulaGuard V5 structural-semantic guard",
            formula_rows,
            truth,
            groups,
        ),
        _evaluate_model("HybridGuard", hybrid_rows, truth, groups),
    ]
    performance = {
        "StructuralGuard": structural_perf,
        "FormulaGuard V5 load": formula_load_perf,
        "FormulaGuard V5": formula_perf,
        "HybridGuard fusion": hybrid_perf,
    }
    result = {
        "protocol": "structuralguard_formulaguard_v5_comparison_v2",
        "workbook": str(args.workbook.resolve()),
        "truth_file": str(args.truth.resolve()),
        "python": sys.version,
        "platform": platform.platform(),
        "candidate_limit": args.candidate_limit,
        "performance": performance,
        "evaluations": evaluations,
        "hybrid_detected_groups": [group.__dict__ for group in detected_groups],
        "limitations": [
            "Synthetic parallel-sheet workbook; not evidence of real-workbook generalization.",
            "Hybrid group evidence relies on at least three comparable parallel sheets.",
            "FormulaGuard V5 is the supplied independent structural-semantic guard candidate.",
            "Peak working set is process-lifetime peak on Windows; later stages include earlier allocations.",
        ],
    }
    (args.output_dir / "comparison_results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_csv(args.output_dir / "structuralguard_ranking.csv", structural_rows)
    _write_csv(args.output_dir / "formulaguard_v5_ranking.csv", formula_rows)
    _write_csv(args.output_dir / "hybridguard_ranking.csv", hybrid_rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
