from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import math
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import load_jsonl, parse_cell_label, values_differ
from formulaguard.formula import normalized_formula
from formulaguard.localize import generate_candidates, localize
from formulaguard.workbook import WorkbookModel


CORE_METHODS = [
    "random", "excel_like", "pattern", "graph", "behavior",
    "excelint_like", "warder_like", "formulaguard", "sfl_oracle",
]
ABLATION_METHODS = [
    "ablate_formula", "ablate_graph", "ablate_behavior",
    "ablate_influence", "ablate_intervention",
]


def bootstrap_ci(values, samples=1000, seed=20260810):
    if not values:
        return [None, None]
    rng = random.Random(seed)
    means = []
    for _ in range(samples):
        draw = [rng.choice(values) for _ in values]
        means.append(statistics.fmean(draw))
    means.sort()
    lo = means[int(0.025 * (len(means) - 1))]
    hi = means[int(0.975 * (len(means) - 1))]
    return [lo, hi]


def mean(values):
    return statistics.fmean(values) if values else 0.0


def write_csv(path, rows, fieldnames=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def failed_sinks(clean, mutant):
    clean_values, clean_errors = clean.evaluate()
    mutant_values, mutant_errors = mutant.evaluate()
    sinks = set(clean.dependency_graph().sinks(clean.formula_cells)) | set(mutant.dependency_graph().sinks(mutant.formula_cells))
    return {
        sink for sink in sinks
        if sink not in clean_errors and sink not in mutant_errors
        and values_differ(clean_values.get(sink), mutant_values.get(sink))
    }


def resolve_worker_count(requested, task_count, logical_cpus=None):
    if requested < 0:
        raise ValueError("workers must be 0 (auto) or a positive integer")
    if task_count < 1:
        return 1
    if requested > 0:
        return min(requested, task_count)
    logical = logical_cpus or os.cpu_count() or 2
    return min(task_count, max(1, math.floor(logical * 0.75)))


def evaluate_instance(task):
    benchmark_text, instance, methods, candidate_limit, gir_weights = task
    benchmark = Path(benchmark_text)
    clean = WorkbookModel.from_xlsx(benchmark / instance["clean_workbook"])
    mutant = WorkbookModel.from_xlsx(benchmark / instance["mutant_workbook"])
    source = parse_cell_label(instance["source_cell"])
    oracle_failed = None
    rows = []
    for method in methods:
        if method == "sfl_oracle" and oracle_failed is None:
            oracle_failed = failed_sinks(clean, mutant)
        started = time.perf_counter()
        results = localize(
            mutant,
            method,
            failed_sinks=oracle_failed if method == "sfl_oracle" else None,
            candidate_limit=candidate_limit,
            gir_weights=gir_weights,
        )
        elapsed = time.perf_counter() - started
        rank = next((rank for rank, result in enumerate(results, 1) if result.cell == source), len(results) + 1)
        source_result = next((result for result in results if result.cell == source), None)
        top_score = results[0].score if results else 0.0
        second_score = results[1].score if len(results) > 1 else 0.0
        repair = source_result.candidate_formula if source_result else None
        correct = instance["correct_formula"]
        repair_exact = bool(repair) and normalized_formula(repair) == normalized_formula(correct)
        candidate_rank = None
        if method == "formulaguard":
            source_candidates = generate_candidates(mutant, source, limit=max(10, candidate_limit))
            candidate_rank = next(
                (
                    candidate_index
                    for candidate_index, candidate in enumerate(source_candidates, 1)
                    if normalized_formula(candidate.formula) == normalized_formula(correct)
                ),
                None,
            )
        rows.append({
            "instance_id": instance["instance_id"],
            "template_family": instance["template_family"],
            "data_split": instance.get("data_split", "unspecified"),
            "mutation_type": instance["mutation_type"],
            "expected_depth": instance["expected_depth"],
            "actual_depth": instance["actual_depth"],
            "depth_bin": instance["depth_bin"],
            "formula_count": len(mutant.formulas),
            "method": method,
            "rank": rank,
            "top1": int(rank <= 1),
            "top3": int(rank <= 3),
            "top5": int(rank <= 5),
            "mrr": 1.0 / rank,
            "exam": rank / max(1, len(mutant.formulas)),
            "repair_exact": int(repair_exact),
            "candidate_formula": repair or "",
            "candidate_rank": candidate_rank if method == "formulaguard" and candidate_rank is not None else "",
            "candidate_coverage_at_10": int(candidate_rank <= 10) if method == "formulaguard" and candidate_rank is not None else (0 if method == "formulaguard" else ""),
            "candidate_coverage_at_15": int(candidate_rank <= 15) if method == "formulaguard" and candidate_rank is not None else (0 if method == "formulaguard" else ""),
            "source_score": source_result.score if source_result else 0.0,
            "top_score": top_score,
            "top_score_margin": top_score - second_score,
            "runtime_seconds": elapsed,
            "candidate_quality": source_result.evidence.get("candidate_quality", "") if source_result and method == "formulaguard" else "",
            "candidate_support": source_result.evidence.get("candidate_support", "") if source_result and method == "formulaguard" else "",
            "candidate_edit_kind": source_result.evidence.get("candidate_edit_kind", "") if source_result and method == "formulaguard" else "",
            "candidate_source": source_result.evidence.get("candidate_source", "") if source_result and method == "formulaguard" else "",
        })
    return instance["instance_id"], rows


def run(args):
    benchmark = args.benchmark
    validation_file = args.validation or benchmark / "validation" / "validated_instances.jsonl"
    instances = list(load_jsonl(validation_file))
    if args.limit:
        instances = instances[: args.limit]
    if not instances:
        raise SystemExit(f"No validated benchmark instances found in: {validation_file}")
    methods = CORE_METHODS + (ABLATION_METHODS if args.ablations else [])
    gir_weights = (0.35, 0.50, 0.10, 0.05)
    if args.config:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        args.candidate_limit = int(config["candidate_limit"])
        gir_weights = tuple(float(value) for value in config["gir_weights"])
        if len(gir_weights) != 4:
            raise SystemExit("Frozen configuration gir_weights must contain four values.")
    raw_rows = []
    worker_count = resolve_worker_count(args.workers, len(instances))
    tasks = [
        (str(benchmark), instance, tuple(methods), args.candidate_limit, tuple(gir_weights))
        for instance in instances
    ]
    started_all = time.perf_counter()
    print(f"Experiment scheduling: {worker_count} worker process(es) for {len(tasks)} workbooks.", flush=True)
    if worker_count == 1:
        evaluated = map(evaluate_instance, tasks)
        for index, (instance_id, rows) in enumerate(evaluated, 1):
            raw_rows.extend(rows)
            print(f"[{index}/{len(instances)}] {instance_id}", flush=True)
    else:
        try:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=worker_count)
        except PermissionError as exc:
            print(f"Parallel workers unavailable ({exc}); falling back to one process.", flush=True)
            worker_count = 1
            evaluated = map(evaluate_instance, tasks)
            for index, (instance_id, rows) in enumerate(evaluated, 1):
                raw_rows.extend(rows)
                print(f"[{index}/{len(instances)}] {instance_id}", flush=True)
        else:
            with executor:
                evaluated = executor.map(evaluate_instance, tasks, chunksize=1)
                for index, (instance_id, rows) in enumerate(evaluated, 1):
                    raw_rows.extend(rows)
                    print(f"[{index}/{len(instances)}] {instance_id}", flush=True)
    wall_seconds = time.perf_counter() - started_all

    output = args.output
    write_csv(output / "raw_results.csv", raw_rows)
    summary_rows = []
    for method in methods:
        rows = [row for row in raw_rows if row["method"] == method]
        mrrs = [float(row["mrr"]) for row in rows]
        summary_rows.append({
            "method": method,
            "instances": len(rows),
            "top1": mean([int(row["top1"]) for row in rows]),
            "top3": mean([int(row["top3"]) for row in rows]),
            "top5": mean([int(row["top5"]) for row in rows]),
            "mrr": mean(mrrs),
            "mrr_ci_low": bootstrap_ci(mrrs, args.bootstrap_samples)[0],
            "mrr_ci_high": bootstrap_ci(mrrs, args.bootstrap_samples)[1],
            "exam": mean([float(row["exam"]) for row in rows]),
            "repair_exact": mean([int(row["repair_exact"]) for row in rows]),
            "candidate_coverage_at_10": mean([
                int(row["candidate_coverage_at_10"])
                for row in rows
                if row["candidate_coverage_at_10"] != ""
            ]),
            "candidate_coverage_at_15": mean([
                int(row["candidate_coverage_at_15"])
                for row in rows
                if row["candidate_coverage_at_15"] != ""
            ]),
            "runtime_median": statistics.median([float(row["runtime_seconds"]) for row in rows]) if rows else 0.0,
            "runtime_p95": sorted(float(row["runtime_seconds"]) for row in rows)[max(0, math.ceil(0.95 * len(rows)) - 1)] if rows else 0.0,
        })
    summary_rows.sort(key=lambda row: (-row["mrr"], row["method"]))
    write_csv(output / "summary.csv", summary_rows)

    def grouped(group_key):
        out = []
        keys = sorted({str(row[group_key]) for row in raw_rows})
        for key in keys:
            for method in methods:
                rows = [r for r in raw_rows if str(r[group_key]) == key and r["method"] == method]
                if rows:
                    out.append({
                        group_key: key,
                        "method": method,
                        "instances": len(rows),
                        "top1": mean([int(r["top1"]) for r in rows]),
                        "top5": mean([int(r["top5"]) for r in rows]),
                        "mrr": mean([float(r["mrr"]) for r in rows]),
                    })
        return out

    write_csv(output / "by_depth.csv", grouped("depth_bin"))
    write_csv(output / "by_error.csv", grouped("mutation_type"))
    write_csv(output / "by_family.csv", grouped("template_family"))
    write_csv(output / "by_split.csv", grouped("data_split"))

    no_oracle_baselines = [m for m in CORE_METHODS if m not in ("formulaguard", "sfl_oracle")]
    summary_map = {row["method"]: row for row in summary_rows}
    strongest = max(no_oracle_baselines, key=lambda m: summary_map[m]["mrr"])
    fg = {row["instance_id"]: float(row["mrr"]) for row in raw_rows if row["method"] == "formulaguard"}
    base = {row["instance_id"]: float(row["mrr"]) for row in raw_rows if row["method"] == strongest}
    paired = [fg[key] - base[key] for key in sorted(fg.keys() & base.keys())]
    comparison = {
        "strongest_no_oracle_baseline": strongest,
        "paired_instances": len(paired),
        "mean_mrr_difference": mean(paired),
            "bootstrap_95_ci": bootstrap_ci(paired, args.bootstrap_samples),
        "formula_guard_better_fraction": mean([int(value > 0) for value in paired]),
        "formula_guard_equal_fraction": mean([int(value == 0) for value in paired]),
    }
    (output / "paired_comparison.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    report = {
        "benchmark": str(benchmark),
        "instances": len(instances),
        "methods": methods,
        "candidate_limit": args.candidate_limit,
        "gir_weights": gir_weights,
        "worker_processes": worker_count,
        "experiment_wall_seconds": wall_seconds,
        "summary": summary_rows,
        "comparison": comparison,
        "warning": "These are measured prototype results, not competition award guarantees.",
    }
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--validation", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--ablations", action="store_true")
    parser.add_argument("--config", type=Path, help="Frozen quick configuration used by full evaluation")
    parser.add_argument("--workers", type=int, default=0, help="Worker processes; 0 uses 75% of logical CPUs")
    args = parser.parse_args()
    if args.workers < 0:
        parser.error("--workers must be 0 (auto) or a positive integer")
    args.output.mkdir(parents=True, exist_ok=True)
    run(args)


if __name__ == "__main__":
    main()
