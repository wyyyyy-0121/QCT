from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import load_jsonl, parse_cell_label
from formulaguard.localize import gir_scores
from formulaguard.workbook import WorkbookModel
from scripts.run_experiments import resolve_worker_count


PROFILES = [
    ("intervention_heavy", (0.25, 0.60, 0.10, 0.05)),
    ("balanced", (0.35, 0.50, 0.10, 0.05)),
    ("prior_heavy", (0.45, 0.40, 0.10, 0.05)),
]


def select_threshold(mutant_scores, clean_scores, max_clean_alarm=0.25):
    values = sorted(set([*mutant_scores, *clean_scores]))
    epsilon = max(1e-12, abs(values[-1]) * 1e-12) if values else 1e-12
    feasible = []
    for threshold in values + ([values[-1] + epsilon] if values else [epsilon]):
        recall = statistics.fmean(score >= threshold for score in mutant_scores) if mutant_scores else 0.0
        alarm = statistics.fmean(score >= threshold for score in clean_scores) if clean_scores else 0.0
        if alarm <= max_clean_alarm + 1e-12:
            feasible.append((recall, threshold, alarm))
    return max(feasible, key=lambda item: (item[0], item[1]))


def evaluate_mutant(task):
    benchmark_text, instance, candidate_limits = task
    model = WorkbookModel.from_xlsx(Path(benchmark_text) / instance["mutant_workbook"])
    source = parse_cell_label(instance["source_cell"])
    rows = []
    for profile_name, gir_weights in PROFILES:
        for candidate_limit in candidate_limits:
            started = time.perf_counter()
            ranking = gir_scores(model, candidate_limit=candidate_limit, gir_weights=gir_weights)
            runtime = time.perf_counter() - started
            rank = next((i for i, result in enumerate(ranking, 1) if result.cell == source), len(ranking) + 1)
            source_result = next((result for result in ranking if result.cell == source), None)
            rows.append({
                "instance_id": instance["instance_id"],
                "template_family": instance["template_family"],
                "profile": profile_name,
                "gir_weights": json.dumps(gir_weights),
                "candidate_limit": candidate_limit,
                "rank": rank,
                "top1": int(rank <= 1),
                "top5": int(rank <= 5),
                "mrr": 1.0 / rank,
                "source_score": source_result.score if source_result else 0.0,
                "runtime_seconds": runtime,
            })
    return instance["instance_id"], rows


def evaluate_clean(task):
    benchmark_text, record, candidate_limits = task
    model = WorkbookModel.from_xlsx(Path(benchmark_text) / record["path"])
    scores = {}
    for profile_name, gir_weights in PROFILES:
        for candidate_limit in candidate_limits:
            ranking = gir_scores(model, candidate_limit=candidate_limit, gir_weights=gir_weights)
            scores[(profile_name, candidate_limit)] = ranking[0].score if ranking else 0.0
    return record["cleanId"], scores


def main():
    parser = argparse.ArgumentParser(description="FormulaGuard candidate-count and weight sensitivity")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limits", default="5,10,15,20")
    parser.add_argument("--limit", type=int, default=48, help="Bound runtime; 0 means all instances")
    parser.add_argument("--workers", type=int, default=0, help="Worker processes; 0 uses 75% of logical CPUs")
    args = parser.parse_args()
    if args.workers < 0:
        parser.error("--workers must be 0 (auto) or a positive integer")
    instances = list(load_jsonl(args.validation))
    if args.limit:
        instances = instances[: args.limit]
    if not instances:
        raise SystemExit(f"No validated instances found in: {args.validation}")
    candidate_limits = [int(value) for value in args.candidate_limits.split(",") if value.strip()]
    if not candidate_limits or any(value < 1 for value in candidate_limits):
        raise SystemExit("Candidate limits must be positive integers.")

    rows = []
    worker_count = resolve_worker_count(args.workers, len(instances))
    tasks = [(str(args.benchmark), instance, tuple(candidate_limits)) for instance in instances]
    print(f"Sensitivity scheduling: {worker_count} worker process(es) for {len(tasks)} mutant workbooks.", flush=True)
    if worker_count == 1:
        evaluated = map(evaluate_mutant, tasks)
        for index, (instance_id, instance_rows) in enumerate(evaluated, 1):
            rows.extend(instance_rows)
            print(f"[{index}/{len(instances)}] {instance_id}", flush=True)
    else:
        try:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=worker_count)
        except PermissionError as exc:
            print(f"Parallel workers unavailable ({exc}); falling back to one process.", flush=True)
            worker_count = 1
            evaluated = map(evaluate_mutant, tasks)
            for index, (instance_id, instance_rows) in enumerate(evaluated, 1):
                rows.extend(instance_rows)
                print(f"[{index}/{len(instances)}] {instance_id}", flush=True)
        else:
            with executor:
                evaluated = executor.map(evaluate_mutant, tasks, chunksize=1)
                for index, (instance_id, instance_rows) in enumerate(evaluated, 1):
                    rows.extend(instance_rows)
                    print(f"[{index}/{len(instances)}] {instance_id}", flush=True)

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "sensitivity_raw.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    clean_manifest = json.loads((args.benchmark / "clean_manifest.json").read_text(encoding="utf-8"))
    clean_scores = {(profile_name, candidate_limit): [] for profile_name, _ in PROFILES for candidate_limit in candidate_limits}
    clean_tasks = [(str(args.benchmark), record, tuple(candidate_limits)) for record in clean_manifest]
    clean_workers = resolve_worker_count(args.workers, len(clean_tasks))
    if clean_workers == 1:
        clean_evaluated = map(evaluate_clean, clean_tasks)
        for _, score_map in clean_evaluated:
            for key, score in score_map.items():
                clean_scores[key].append(score)
    else:
        try:
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=clean_workers)
        except PermissionError as exc:
            print(f"Parallel clean-workbook workers unavailable ({exc}); falling back to one process.", flush=True)
            clean_evaluated = map(evaluate_clean, clean_tasks)
            for _, score_map in clean_evaluated:
                for key, score in score_map.items():
                    clean_scores[key].append(score)
        else:
            with executor:
                clean_evaluated = executor.map(evaluate_clean, clean_tasks, chunksize=1)
                for _, score_map in clean_evaluated:
                    for key, score in score_map.items():
                        clean_scores[key].append(score)

    summary = []
    for profile_name, gir_weights in PROFILES:
        for candidate_limit in candidate_limits:
            group = [row for row in rows if row["profile"] == profile_name and row["candidate_limit"] == candidate_limit]
            recall, threshold, clean_alarm = select_threshold(
                [float(row["source_score"]) for row in group],
                clean_scores[(profile_name, candidate_limit)],
            )
            summary.append({
                "profile": profile_name,
                "gir_weights": json.dumps(gir_weights),
                "candidate_limit": candidate_limit,
                "instances": len(group),
                "top1": statistics.fmean(row["top1"] for row in group),
                "top5": statistics.fmean(row["top5"] for row in group),
                "mrr": statistics.fmean(row["mrr"] for row in group),
                "runtime_median": statistics.median(row["runtime_seconds"] for row in group),
                "selected_threshold": threshold,
                "calibration_mutant_recall": recall,
                "calibration_clean_alarm_rate": clean_alarm,
                "threshold_gate_passed": int(recall >= 0.80 and clean_alarm <= 0.25),
            })
    with (args.output / "sensitivity_summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
        writer.writeheader()
        writer.writerows(summary)


if __name__ == "__main__":
    main()
