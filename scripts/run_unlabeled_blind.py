"""Freeze rankings for a human-created blind workbook set without reading labels."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.formula import FormulaSyntaxError, parse_formula
from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


FORBIDDEN_PUBLIC_COLUMNS = {"source_cell", "source_cells", "correct_formula", "error_formula", "error_type"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def evaluate_task(task: tuple[str, list[dict[str, str]], str, int]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    workbook_text, instances, method, candidate_limit = task
    workbook = Path(workbook_text)
    try:
        model = WorkbookModel.from_xlsx(workbook)
    except Exception as exc:
        return [], [{"instance_id": row["instance_id"], "reason": f"load_error:{type(exc).__name__}:{exc}"} for row in instances]
    supported = 0
    for formula in model.formulas.values():
        try:
            parse_formula(formula)
            supported += 1
        except FormulaSyntaxError:
            pass
    started = time.perf_counter()
    ranked = localize(model, method, candidate_limit=candidate_limit)
    elapsed = time.perf_counter() - started
    rows: list[dict[str, Any]] = []
    for instance in instances:
        for rank, result in enumerate(ranked, 1):
            rows.append({
                "instance_id": instance["instance_id"],
                "workbook": instance["workbook"],
                "method": method,
                "formula_count": len(model.formulas),
                "supported_formula_count": supported,
                "parser_coverage": supported / max(1, len(model.formulas)),
                "rank": rank,
                "sheet": result.cell[0],
                "address": result.cell[1],
                "score": result.score,
                "candidate_formula": result.candidate_formula or "",
                "diagnostic_status": result.evidence.get("diagnostic_status", ""),
                "runtime_seconds": elapsed,
            })
    return rows, []


def main() -> None:
    parser = argparse.ArgumentParser(description="Create immutable FormulaGuard rankings for an unlabeled blind study")
    parser.add_argument("--manifest", type=Path, required=True, help="Public CSV with only instance_id,workbook")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--methods", default="formulaguard_v3_real,graph,pattern")
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--frozen-config", type=Path, default=Path("research/frozen_config_v3_real.json"))
    args = parser.parse_args()
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = set(reader.fieldnames or [])
    if not rows or {"instance_id", "workbook"} - fields:
        raise SystemExit("Public manifest must contain non-empty instance_id and workbook columns")
    leaked = sorted(FORBIDDEN_PUBLIC_COLUMNS & fields)
    if leaked:
        raise SystemExit(f"Public manifest must not contain private label columns: {', '.join(leaked)}")
    if len({row["instance_id"] for row in rows}) != len(rows):
        raise SystemExit("Public manifest has duplicate instance_id values")
    methods = [item.strip() for item in args.methods.split(",") if item.strip()]
    if not methods:
        raise SystemExit("At least one method is required")
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        workbook = (args.manifest.parent / row["workbook"]).resolve()
        groups.setdefault(str(workbook), []).append(row)
    tasks = [(path, group, method, args.candidate_limit) for path, group in groups.items() for method in methods]
    tasks.sort(key=lambda task: (-Path(task[0]).stat().st_size if Path(task[0]).is_file() else 0, task[2]))
    workers = min(len(tasks), max(1, (os.cpu_count() or 2) // 2)) if args.workers == 0 else min(len(tasks), max(1, args.workers))
    print(f"[blind scheduler] instances={len(rows)} workbooks={len(groups)} method_jobs={len(tasks)} workers={workers}", flush=True)
    predictions: list[dict[str, Any]] = []
    exclusions: list[dict[str, str]] = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(evaluate_task, task): task for task in tasks}
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            task = futures[future]
            task_rows, task_exclusions = future.result()
            predictions.extend(task_rows)
            exclusions.extend(task_exclusions)
            print(f"[{index}/{len(tasks)}] {Path(task[0]).name} :: {task[2]}", flush=True)
    if not predictions:
        raise SystemExit("No predictions were produced; inspect blind_exclusions.csv")
    predictions.sort(key=lambda row: (row["instance_id"], row["method"], int(row["rank"])))
    args.output.mkdir(parents=True, exist_ok=True)
    prediction_path = args.output / "predictions.csv"
    fields_out = list(predictions[0])
    with prediction_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields_out)
        writer.writeheader()
        writer.writerows(predictions)
    with (args.output / "blind_exclusions.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "reason"])
        writer.writeheader()
        writer.writerows(exclusions)
    root = Path(__file__).resolve().parents[1]
    config = args.frozen_config.resolve()
    manifest = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "label_access": "none: only public instance_id/workbook manifest was read",
        "public_manifest_sha256": sha256(args.manifest),
        "predictions_sha256": sha256(prediction_path),
        "frozen_config": str(config),
        "frozen_config_sha256": sha256(config) if config.is_file() else None,
        "source_hashes": {
            "formulaguard/localize.py": sha256(root / "formulaguard" / "localize.py"),
            "runner": sha256(Path(__file__).resolve()),
        },
        "instances": len(rows),
        "methods": methods,
        "candidate_limit": args.candidate_limit,
        "workers": workers,
        "prediction_rows": len(predictions),
        "exclusions": len(exclusions),
        "instruction": "Do not alter predictions.csv before private labels are unsealed and audited.",
    }
    (args.output / "prediction_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Predictions: {prediction_path}")
    print(f"Freeze manifest: {args.output / 'prediction_manifest.json'}")


if __name__ == "__main__":
    main()
