"""Evaluate only FormulaGuard V5 on a labeled development manifest.

The frozen reference methods are deliberately not recomputed here.  Their
locked rows are merged later by ``merge_v5_development_results.py``.
Labels are used only after V5 has produced a complete ranking.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.formula import FormulaSyntaxError, normalized_formula, parse_formula
from formulaguard.v5 import v5_default_parameters, v5_scores
from formulaguard.workbook import WorkbookModel
from scripts.run_external_evaluation import _event_context, sha256_file


METHOD = "formulaguard_v5"


def _evaluate_workbook(task: tuple[str, list[dict[str, str]], int]):
    workbook_text, instances, candidate_limit = task
    workbook_path = Path(workbook_text)
    if not workbook_path.is_file():
        return [], [
            {
                "instance_id": instance["instance_id"],
                "reason": f"workbook_not_found:{workbook_path}",
            }
            for instance in instances
        ], workbook_path.name
    try:
        model = WorkbookModel.from_xlsx(workbook_path)
    except Exception as exc:
        return [], [
            {
                "instance_id": instance["instance_id"],
                "reason": f"load_error:{type(exc).__name__}:{exc}",
            }
            for instance in instances
        ], workbook_path.name

    supported_formula_count = 0
    for formula in model.formulas.values():
        try:
            parse_formula(formula)
            supported_formula_count += 1
        except FormulaSyntaxError:
            pass

    # The ranking is computed once, before any labeled source is inspected.
    started = time.perf_counter()
    results = v5_scores(model, candidate_limit=candidate_limit)
    elapsed = time.perf_counter() - started
    contexts = []
    exclusions = []
    for instance in instances:
        context, exclusion = _event_context(instance, model)
        if exclusion:
            exclusions.append(exclusion)
        else:
            contexts.append(context)
    if not contexts:
        return [], exclusions, workbook_path.name

    parser_coverage = supported_formula_count / max(1, len(model.formulas))
    rows = []
    for context in contexts:
        instance = context["instance"]
        sources = context["sources"]
        formula_sources = context["formula_sources"]
        supported_sources = context["supported_sources"]
        ranked_hits = [
            (rank, result)
            for rank, result in enumerate(results, 1)
            if result.cell in supported_sources
        ]
        rank, source_result = min(
            ranked_hits,
            default=(len(results) + 1, None),
            key=lambda item: item[0],
        )
        repair = source_result.candidate_formula if source_result else None
        correct = instance.get("correct_formula", "")
        repair_exact = bool(
            len(supported_sources) == 1
            and correct
            and repair
            and normalized_formula(correct) == normalized_formula(repair)
        )
        evidence = source_result.evidence if source_result else {}
        rows.append({
            "instance_id": instance["instance_id"],
            "workbook": instance["workbook"],
            "error_event": instance.get("error_event", ""),
            "error_type": instance.get("error_type", ""),
            "error_subtype": instance.get("error_subtype", ""),
            "method": METHOD,
            "formula_count": len(model.formulas),
            "supported_formula_count": supported_formula_count,
            "parser_coverage": parser_coverage,
            "labeled_cell_count": len(sources),
            "labeled_formula_count": len(formula_sources),
            "supported_source_formula_count": len(supported_sources),
            "supported_source_cells": ";".join(
                f"{sheet}!{address}" for sheet, address in sorted(supported_sources)
            ),
            "source_parser_coverage": len(supported_sources) / max(1, len(formula_sources)),
            "rank": rank,
            "top1": int(rank <= 1),
            "top3": int(rank <= 3),
            "top5": int(rank <= 5),
            "mrr": 1 / rank,
            "exam": rank / max(1, len(model.formulas)),
            "repair_exact": int(repair_exact),
            "repair_evaluable": int(bool(correct)),
            "source_score": source_result.score if source_result else 0.0,
            "candidate_formula": repair or "",
            "top5_cells": ";".join(result.cell_label for result in results[:5]),
            "top5_diagnostic_statuses": ";".join(
                str(result.evidence.get("diagnostic_status", "")) for result in results[:5]
            ),
            "diagnostic_status": evidence.get("diagnostic_status", ""),
            "v4_diagnostic_status": evidence.get("v4_diagnostic_status", ""),
            "v4_final_rank": evidence.get("v4_final_rank", ""),
            "pattern_elite_limit": evidence.get("pattern_elite_limit", ""),
            "pattern_elite": evidence.get("pattern_elite", ""),
            "joint_eligible": evidence.get("joint_eligible", ""),
            "joint_candidate_count": evidence.get("joint_candidate_count", ""),
            "joint_gate_active": evidence.get("joint_gate_active", ""),
            "joint_confirmed": evidence.get("joint_confirmed", ""),
            "v5_override_reason": evidence.get("v5_override_reason", ""),
            "v5_final_rank": evidence.get("v5_final_rank", ""),
            "v5_rank_change": evidence.get("v5_rank_change", ""),
            "v5_promotion_distance": evidence.get("v5_promotion_distance", ""),
            "candidate_count": evidence.get("candidate_count", ""),
            "candidate_delta": evidence.get("candidate_delta", ""),
            "null_control_count": evidence.get("null_control_count", ""),
            "intervention_responsibility_gain": evidence.get(
                "intervention_responsibility_gain", ""
            ),
            "runtime_seconds": elapsed,
        })
    return rows, exclusions, workbook_path.name


def _write_summary(rows: list[dict[str, object]], path: Path) -> None:
    repair_rows = [row for row in rows if int(row["repair_evaluable"])]
    fields = [
        "method", "instances", "workbooks", "top1", "top3", "top5", "mrr", "exam",
        "parser_coverage_median", "repair_evaluable", "repair_exact", "runtime_median",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({
            "method": METHOD,
            "instances": len(rows),
            "workbooks": len({str(row["workbook"]) for row in rows}),
            "top1": statistics.fmean(int(row["top1"]) for row in rows),
            "top3": statistics.fmean(int(row["top3"]) for row in rows),
            "top5": statistics.fmean(int(row["top5"]) for row in rows),
            "mrr": statistics.fmean(float(row["mrr"]) for row in rows),
            "exam": statistics.fmean(float(row["exam"]) for row in rows),
            "parser_coverage_median": statistics.median(
                float(row["parser_coverage"]) for row in rows
            ),
            "repair_evaluable": len(repair_rows),
            "repair_exact": (
                statistics.fmean(int(row["repair_exact"]) for row in repair_rows)
                if repair_rows else ""
            ),
            "runtime_median": statistics.median(float(row["runtime_seconds"]) for row in rows),
        })


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate only preregistered FormulaGuard V5")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0, help="Engineering smoke only")
    args = parser.parse_args()

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        instances = list(reader)
        fieldnames = set(reader.fieldnames or [])
    required = {"instance_id", "workbook"}
    if missing := required - fieldnames:
        raise SystemExit(f"Manifest is missing required columns: {', '.join(sorted(missing))}")
    if "source_cell" not in fieldnames and "source_cells" not in fieldnames:
        raise SystemExit("Manifest must contain source_cell or source_cells")

    exclusions = []
    included = []
    for instance in instances:
        include = instance.get("include", "1").strip().lower() not in {
            "0", "false", "no", "exclude",
        }
        if include:
            included.append(instance)
        else:
            exclusions.append({
                "instance_id": instance["instance_id"],
                "reason": instance.get("exclusion_reason", "excluded_in_manifest")
                or "excluded_in_manifest",
            })
    if args.limit:
        included = included[:args.limit]
    if not included:
        raise SystemExit("No included labeled instances")

    workbook_groups: dict[str, list[dict[str, str]]] = {}
    for instance in included:
        workbook_path = (args.manifest.parent / instance["workbook"]).resolve()
        workbook_groups.setdefault(str(workbook_path), []).append(instance)
    tasks = [
        (path, group, args.candidate_limit)
        for path, group in workbook_groups.items()
    ]
    tasks.sort(key=lambda task: -Path(task[0]).stat().st_size if Path(task[0]).is_file() else 0)
    auto_workers = min(16, max(1, (os.cpu_count() or 2) // 2), len(tasks))
    workers = auto_workers if args.workers == 0 else max(1, min(args.workers, len(tasks)))
    print(
        f"[scheduler] events={len(included)} workbooks={len(tasks)} "
        f"v5_jobs={len(tasks)} workers={workers}",
        flush=True,
    )
    rows = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_evaluate_workbook, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            workbook_rows, workbook_exclusions, workbook_name = future.result()
            rows.extend(workbook_rows)
            exclusions.extend(workbook_exclusions)
            print(f"[{index}/{len(tasks)}] {workbook_name} :: {METHOD}", flush=True)
    rows.sort(key=lambda row: str(row["instance_id"]))
    exclusions = list({
        (row["instance_id"], row["reason"]): row for row in exclusions
    }.values())
    args.output.mkdir(parents=True, exist_ok=True)
    exclusions_path = args.output / "v5_exclusions.csv"
    with exclusions_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "reason"])
        writer.writeheader()
        writer.writerows(exclusions)
    if not rows:
        raise SystemExit(f"No instances could be evaluated. See {exclusions_path}")
    raw_path = args.output / "v5_raw.csv"
    with raw_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    _write_summary(rows, args.output / "v5_summary.csv")

    root = Path(__file__).resolve().parents[1]
    source_files = [
        root / "formulaguard" / "v5.py",
        root / "formulaguard" / "localize.py",
        root / "scripts" / "run_v5_external_evaluation.py",
        root / "scripts" / "merge_v5_development_results.py",
        root / "scripts" / "run_v5_clean_controls.py",
        root / "scripts" / "audit_v5_development.py",
        root / "research" / "V5_METHOD_SPEC.md",
        root / "research" / "V5_METHOD_SPEC_AMENDMENT_1.md",
    ]
    metadata = {
        "scope": "v5_only_development_evaluation",
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "candidate_limit": args.candidate_limit,
        "worker_processes": workers,
        "engineering_limit": args.limit,
        "method": METHOD,
        "v5_parameters": v5_default_parameters(),
        "label_isolation": "ranking_completed_before_labeled_source_lookup",
        "source_sha256": {
            str(path.relative_to(root)).replace("\\", "/"): sha256_file(path)
            for path in source_files if path.is_file()
        },
    }
    (args.output / "v5_run_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(raw_path)


if __name__ == "__main__":
    main()
