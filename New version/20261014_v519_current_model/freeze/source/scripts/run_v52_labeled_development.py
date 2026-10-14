"""Run one V5.2 variant on a labeled development or safety-regression set.

Labels are consulted only after the complete V4 ranking and the V5.2 rescue
decision have been computed.  This script is not valid for blind prediction;
the independent set has a separate label-free lock command.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.formula import FormulaSyntaxError, normalized_formula, parse_formula
from formulaguard.v52 import v52_default_parameters, v52_scores
from formulaguard.workbook import WorkbookModel
from scripts.run_external_evaluation import _event_context, sha256_file


def _ranking_hash(cells: list[str]) -> str:
    return hashlib.sha256("\n".join(cells).encode("utf-8")).hexdigest()


def _evaluate_workbook(task: tuple[str, list[dict[str, str]], str, int]):
    workbook_text, instances, variant, candidate_limit = task
    workbook_path = Path(workbook_text)
    if not workbook_path.is_file():
        return [], [
            {"instance_id": row["instance_id"], "reason": f"workbook_not_found:{workbook_path}"}
            for row in instances
        ], workbook_path.name
    try:
        model = WorkbookModel.from_xlsx(workbook_path)
    except Exception as exc:
        return [], [
            {"instance_id": row["instance_id"], "reason": f"load_error:{type(exc).__name__}:{exc}"}
            for row in instances
        ], workbook_path.name

    # Critical isolation boundary: ranking and rescue are complete before labels
    # are parsed by _event_context below.
    started = time.perf_counter()
    decision = v52_scores(model, variant=variant, candidate_limit=candidate_limit)
    elapsed = time.perf_counter() - started
    core = list(decision.core_ranking)
    core_cells = [result.cell_label for result in core]
    core_hash = _ranking_hash(core_cells)
    rescue = decision.rescue
    rescue_result = rescue.result if rescue else None
    rescue_cell = rescue_result.cell if rescue_result else None

    supported_formula_count = 0
    for formula in model.formulas.values():
        try:
            parse_formula(formula)
            supported_formula_count += 1
        except FormulaSyntaxError:
            pass

    contexts = []
    exclusions = []
    for instance in instances:
        context, exclusion = _event_context(instance, model)
        if exclusion:
            exclusions.append(exclusion)
        else:
            contexts.append(context)
    rows: list[dict[str, object]] = []
    for context in contexts:
        instance = context["instance"]
        sources = context["sources"]
        formula_sources = context["formula_sources"]
        supported_sources = context["supported_sources"]
        ranked_hits = [
            (rank, result) for rank, result in enumerate(core, 1)
            if result.cell in supported_sources
        ]
        rank, source_result = min(
            ranked_hits, default=(len(core) + 1, None), key=lambda item: item[0]
        )
        rescue_hit = bool(rescue_cell and rescue_cell in supported_sources)
        incremental_hit = bool(rank > 5 and rescue_hit)
        correct = instance.get("correct_formula", "")
        rescue_repair = rescue_result.candidate_formula if rescue_result else ""
        repair_exact = bool(
            rescue_hit and len(supported_sources) == 1 and correct and rescue_repair
            and normalized_formula(correct) == normalized_formula(rescue_repair)
        )
        rows.append({
            "instance_id": instance["instance_id"],
            "workbook": instance["workbook"],
            "error_event": instance.get("error_event", ""),
            "error_type": instance.get("error_type", instance.get("mutation_type", "")),
            "error_subtype": instance.get("error_subtype", ""),
            "variant": variant,
            "formula_count": len(core),
            "supported_formula_count": supported_formula_count,
            "parser_coverage": supported_formula_count / max(1, len(core)),
            "labeled_cell_count": len(sources),
            "labeled_formula_count": len(formula_sources),
            "supported_source_formula_count": len(supported_sources),
            "core_rank": rank,
            "core_top1": int(rank <= 1),
            "core_top3": int(rank <= 3),
            "core_top5": int(rank <= 5),
            "core_mrr": 1.0 / rank,
            "core_exam": rank / max(1, len(core)),
            "core_top5_cells": ";".join(core_cells[:5]),
            "v4_order_sha256": core_hash,
            "v52_core_order_sha256": core_hash,
            "rescue_status": decision.status,
            "rescue_reason": decision.reason,
            "eligible_candidate_count": len(decision.eligible),
            "rescue_alarm": int(rescue is not None),
            "rescue_cell": rescue_result.cell_label if rescue_result else "",
            "rescue_v4_rank": rescue.v4_rank if rescue else "",
            "rescue_formula_rank": rescue.formula_rank if rescue else "",
            "rescue_irg": rescue.irg if rescue else "",
            "rescue_delta": rescue.delta if rescue else "",
            "rescue_repair_sources": ",".join(rescue.repair_sources) if rescue else "",
            "rescue_repair_source_count": rescue.repair_source_count if rescue else "",
            "rescue_reference_quality": rescue.reference_quality if rescue else "",
            "rescue_candidate_formula": rescue_repair or "",
            "rescue_hit": int(rescue_hit),
            "incremental_rescue_hit": int(incremental_hit),
            "review6_hit": int(rank <= 5 or rescue_hit),
            "rescue_repair_evaluable": int(bool(correct)),
            "rescue_repair_exact": int(repair_exact),
            "runtime_seconds": elapsed,
        })
    return rows, exclusions, workbook_path.name


def _write_csv(path: Path, rows: list[dict[str, object]], fields: list[str] | None = None) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a V5.2 labeled development round")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant", choices=("a", "b", "c"), required=True)
    parser.add_argument("--dataset-role", required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--limit", type=int, default=0, help="Engineering smoke only")
    args = parser.parse_args()

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or [])
        instances = list(reader)
    if not {"instance_id", "workbook"} <= fieldnames:
        raise SystemExit("Manifest must contain instance_id and workbook")
    if not ({"source_cell", "source_cells"} & fieldnames):
        raise SystemExit("Development manifest must contain source_cell or source_cells")
    included = [
        row for row in instances
        if row.get("include", "1").strip().lower() not in {"0", "false", "no", "exclude"}
    ]
    if args.limit:
        included = included[:args.limit]
    if not included:
        raise SystemExit("No included development events")

    groups: dict[str, list[dict[str, str]]] = {}
    for instance in included:
        workbook = (args.manifest.parent / instance["workbook"]).resolve()
        groups.setdefault(str(workbook), []).append(instance)
    tasks = [(path, rows, args.variant, args.candidate_limit) for path, rows in groups.items()]
    tasks.sort(key=lambda item: -Path(item[0]).stat().st_size if Path(item[0]).is_file() else 0)
    workers = max(1, min(args.workers or min(24, os.cpu_count() or 1), len(tasks)))
    print(
        f"[scheduler] role={args.dataset_role} events={len(included)} "
        f"workbooks={len(tasks)} variant={args.variant} workers={workers}", flush=True,
    )
    rows: list[dict[str, object]] = []
    exclusions: list[dict[str, str]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_evaluate_workbook, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            workbook_rows, workbook_exclusions, name = future.result()
            rows.extend(workbook_rows)
            exclusions.extend(workbook_exclusions)
            print(f"[{index}/{len(tasks)}] {name} :: v5.2-{args.variant}", flush=True)
    rows.sort(key=lambda row: str(row["instance_id"]))
    args.output.mkdir(parents=True, exist_ok=True)
    _write_csv(
        args.output / "v52_exclusions.csv", exclusions,
        ["instance_id", "reason"],
    )
    if not rows:
        raise SystemExit("No development events could be evaluated")
    raw_path = args.output / "v52_raw.csv"
    _write_csv(raw_path, rows)
    alarms = [int(row["rescue_alarm"]) for row in rows]
    summary = {
        "dataset_role": args.dataset_role,
        "variant": args.variant,
        "events": len(rows),
        "workbooks": len({str(row["workbook"]) for row in rows}),
        "core_top1": statistics.fmean(int(row["core_top1"]) for row in rows),
        "core_top3": statistics.fmean(int(row["core_top3"]) for row in rows),
        "core_top5": statistics.fmean(int(row["core_top5"]) for row in rows),
        "core_mrr": statistics.fmean(float(row["core_mrr"]) for row in rows),
        "rescue_activations": sum(alarms),
        "rescue_activation_rate": statistics.fmean(alarms),
        "rescue_hits": sum(int(row["rescue_hit"]) for row in rows),
        "incremental_rescue_hits": sum(int(row["incremental_rescue_hit"]) for row in rows),
        "review6_hits": sum(int(row["review6_hit"]) for row in rows),
        "runtime_median": statistics.median(float(row["runtime_seconds"]) for row in rows),
        "worker_processes": workers,
        "engineering_limit": args.limit,
        "label_isolation": "v4_and_v52_decision_completed_before_event_label_parsing",
        "v52_parameters": v52_default_parameters(args.variant),
        "manifest_sha256": sha256_file(args.manifest),
        "raw_sha256": sha256_file(raw_path),
    }
    (args.output / "v52_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output / "v52_summary.json")


if __name__ == "__main__":
    main()
