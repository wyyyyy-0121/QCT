"""Generate label-free, hash-locked rankings for an independent v4 blind set."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze FormulaGuard-v4 predictions before labels are opened")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True, help="Frozen v4 configuration")
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--methods", default=DEFAULT_METHODS)
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

    args.output.mkdir(parents=True, exist_ok=True)
    ranking_rows: list[dict[str, object]] = []
    workbook_hashes: dict[str, str] = {}
    for index, instance in enumerate(instances, 1):
        workbook = (args.manifest.parent / instance["workbook"]).resolve()
        if not workbook.is_file():
            raise SystemExit(f"Blind workbook not found: {workbook}")
        workbook_hashes[instance["instance_id"]] = sha256_file(workbook)
        model = WorkbookModel.from_xlsx(workbook)
        for method in methods:
            started = time.perf_counter()
            results = localize(model, method, candidate_limit=args.candidate_limit)
            elapsed = time.perf_counter() - started
            for rank, result in enumerate(results, 1):
                ranking_rows.append({
                    "instance_id": instance["instance_id"],
                    "workbook": instance["workbook"],
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
        print(f"[{index}/{len(instances)}] predictions frozen in memory: {instance['instance_id']}", flush=True)
    if not ranking_rows:
        raise SystemExit("No blind rankings were generated")

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
