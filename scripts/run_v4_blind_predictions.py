"""Generate label-free, hash-locked rankings for an independent v4 blind set."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.localize import localize, v4_default_parameters
from formulaguard.workbook import WorkbookModel
from scripts.freeze_v4_model import verify_model_source_hashes
from scripts.run_external_evaluation import parse_methods, sha256_file


DEFAULT_METHODS = "graph,pattern,formulaguard,formulaguard_v3,formulaguard_v4"
FORBIDDEN_LABEL_FIELDS = {
    "source_cell",
    "source_cells",
    "correct_formula",
    "fault_cell",
    "fault_cells",
    "error_type",
    "mutation_type",
}


def validate_label_free_columns(fieldnames: list[str]) -> None:
    present = FORBIDDEN_LABEL_FIELDS & {name.strip().lower() for name in fieldnames}
    if present:
        raise ValueError(
            "Blind manifest contains forbidden label fields: " + ", ".join(sorted(present))
        )
    missing = {"instance_id", "workbook"} - set(fieldnames)
    if missing:
        raise ValueError("Blind manifest is missing: " + ", ".join(sorted(missing)))


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def evaluate_blind_workbook_method(
    task: tuple[str, str, str, str, int],
) -> tuple[str, str, list[dict[str, object]]]:
    """Return one complete ranking; the task contains no source labels."""
    workbook_text, instance_id, workbook_label, method, candidate_limit = task
    model = WorkbookModel.from_xlsx(Path(workbook_text))
    started = time.perf_counter()
    results = localize(model, method, candidate_limit=candidate_limit)
    elapsed = time.perf_counter() - started
    rows: list[dict[str, object]] = []
    for rank, result in enumerate(results, 1):
        rows.append({
            "instance_id": instance_id,
            "workbook": workbook_label,
            "method": method,
            "rank": rank,
            "formula_count": len(results),
            "cell": result.cell_label,
            "score": result.score,
            "candidate_formula": result.candidate_formula or "",
            "diagnostic_status": result.evidence.get("diagnostic_status", ""),
            "intervention_selected": result.evidence.get("intervention_selected", ""),
            "candidate_count": result.evidence.get("candidate_count", ""),
            "candidate_delta": result.evidence.get("candidate_delta", ""),
            "intervention_responsibility_gain": result.evidence.get(
                "intervention_responsibility_gain", ""
            ),
            "promotion_cap": result.evidence.get("promotion_cap", ""),
            "runtime_seconds": elapsed,
        })
    return instance_id, method, rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze FormulaGuard-v4 predictions before labels are opened")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True, help="Frozen v4 configuration")
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--methods", default=DEFAULT_METHODS)
    parser.add_argument(
        "--workers", type=int, default=0,
        help="Worker processes; 0 uses half of logical CPUs capped at 16",
    )
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parents[1]
    try:
        frozen = json.loads(args.config.read_text(encoding="utf-8"))
        if frozen.get("model_version") != "v4":
            raise ValueError("Frozen configuration is not for v4")
        if frozen.get("v4_parameters") != v4_default_parameters():
            raise ValueError("Frozen v4 parameters differ from the running implementation")
        verify_model_source_hashes(
            {"source_sha256": frozen.get("model_source_sha256")}, repository_root
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Blind prediction refused: {exc}") from exc
    if args.candidate_limit != int(frozen.get("candidate_limit", -1)):
        raise SystemExit("Blind prediction refused: candidate limit differs from frozen v4")

    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty blind output directory: {args.output}")
    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        instances = list(reader)
    try:
        validate_label_free_columns(fieldnames)
        methods = parse_methods(args.methods)
    except ValueError as exc:
        parser.error(str(exc))
    if not instances:
        raise SystemExit("Blind manifest is empty")
    ids = [row["instance_id"].strip() for row in instances]
    if any(not instance_id for instance_id in ids) or len(ids) != len(set(ids)):
        raise SystemExit("instance_id values must be non-empty and unique")

    workbook_labels = [row["workbook"].strip() for row in instances]
    if any(not workbook for workbook in workbook_labels):
        raise SystemExit("workbook values must be non-empty")
    if len(workbook_labels) != len(set(workbook_labels)):
        raise SystemExit(
            "Each blind event must use a distinct workbook to avoid pseudo-replication"
        )

    args.output.mkdir(parents=True, exist_ok=True)
    ranking_rows: list[dict[str, object]] = []
    workbook_hashes: dict[str, str] = {}
    tasks: list[tuple[str, str, str, str, int]] = []
    for instance in instances:
        workbook = (args.manifest.parent / instance["workbook"]).resolve()
        if not workbook.is_file():
            raise SystemExit(f"Blind workbook not found: {workbook}")
        workbook_hashes[instance["instance_id"]] = sha256_file(workbook)
        for method in methods:
            tasks.append((
                str(workbook), instance["instance_id"], instance["workbook"], method,
                args.candidate_limit,
            ))
    auto_workers = min(16, max(1, (os.cpu_count() or 2) // 2), len(tasks))
    workers = auto_workers if args.workers == 0 else max(1, min(args.workers, len(tasks)))
    print(
        f"[scheduler] events={len(instances)} method_jobs={len(tasks)} workers={workers}",
        flush=True,
    )
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(evaluate_blind_workbook_method, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            instance_id, method, rows = future.result()
            ranking_rows.extend(rows)
            print(f"[{index}/{len(tasks)}] {instance_id} :: {method}", flush=True)
    if not ranking_rows:
        raise SystemExit("No blind rankings were generated")

    instance_order = {instance_id: index for index, instance_id in enumerate(ids)}
    method_order = {method: index for index, method in enumerate(methods)}
    ranking_rows.sort(key=lambda row: (
        instance_order[str(row["instance_id"])],
        method_order[str(row["method"])],
        int(row["rank"]),
    ))

    rankings_path = args.output / "blind_rankings.csv"
    _write_csv(rankings_path, ranking_rows)
    source_paths = [
        repository_root / "formulaguard" / "localize.py",
        repository_root / "scripts" / "run_v4_blind_predictions.py",
        repository_root / "scripts" / "score_v4_blind_predictions.py",
    ]
    metadata = {
        "protocol": "label_free_prediction_then_sha256_lock",
        "manifest": str(args.manifest.resolve()),
        "manifest_sha256": sha256_file(args.manifest),
        "instances": len(instances),
        "methods": methods,
        "candidate_limit": args.candidate_limit,
        "worker_processes": workers,
        "scheduler_unit": "one_label_free_workbook_method_ranking",
        "frozen_config": str(args.config.resolve()),
        "frozen_config_sha256": sha256_file(args.config),
        "v4_parameters": v4_default_parameters(),
        "workbook_sha256": workbook_hashes,
        "source_sha256": {
            str(path.relative_to(repository_root)).replace("\\", "/"): sha256_file(path)
            for path in source_paths if path.is_file()
        },
        "label_fields_rejected": sorted(FORBIDDEN_LABEL_FIELDS),
    }
    metadata_path = args.output / "blind_prediction_metadata.json"
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    lock = {
        "lock_version": 1,
        "rankings_file": rankings_path.name,
        "rankings_sha256": sha256_file(rankings_path),
        "metadata_file": metadata_path.name,
        "metadata_sha256": sha256_file(metadata_path),
        "instruction": "Do not edit rankings or metadata after this lock is created.",
    }
    lock_path = args.output / "prediction_lock.json"
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2), encoding="utf-8")
    print(lock_path)


if __name__ == "__main__":
    main()
