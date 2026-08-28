"""Atomic, resumable, label-free predictions for the R2 confirmation protocol."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import parse_formula
from formulaguard.localize import LocalizationResult, v4_scores
from formulaguard.v4x import v4_3_scores
from formulaguard.v5_core_r2 import v5_core_r2_scores
from formulaguard.workbook import WorkbookModel

METHODS = ("v4", "v4_3", "r2_source", "r2_full")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = shutil.which("git") or (str(bundled) if bundled.is_file() else None)
    if executable is None:
        return "unavailable"
    completed = subprocess.run(
        [executable, "rev-parse", "HEAD"], cwd=ROOT,
        capture_output=True, text=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unavailable"


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["instance_id", "workbook"]:
            raise SystemExit("Public manifest must contain exactly instance_id,workbook")
        rows = list(reader)
    identifiers = [row["instance_id"] for row in rows]
    if not rows or len(set(identifiers)) != len(identifiers) or any(not value for value in identifiers):
        raise SystemExit("Public manifest needs unique non-empty instance_id values")
    return rows


def supported_model(model: WorkbookModel) -> tuple[WorkbookModel, tuple[tuple[str, str], ...]]:
    supported: dict[tuple[str, str], str] = {}
    unsupported: list[tuple[str, str]] = []
    for cell, formula in model.formulas.items():
        try:
            parse_formula(formula)
        except Exception:
            unsupported.append(cell)
        else:
            supported[cell] = formula
    return WorkbookModel(model.cells, supported, source=model.source), tuple(sorted(unsupported))


def append_unsupported(
    values: list[LocalizationResult],
    unsupported: tuple[tuple[str, str], ...],
    *,
    method: str,
) -> list[LocalizationResult]:
    result = list(values)
    for cell in unsupported:
        result.append(LocalizationResult(
            cell=cell, score=0.0, candidate_formula=None,
            evidence={
                "model_version": method,
                "diagnostic_status": "unsupported_coverage",
                "compatibility_adapter": "cached_value_no_candidate_complete_ranking_tail",
            },
        ))
    return result


def serial_result(item: LocalizationResult, rank: int, *, compact: bool) -> dict:
    return {
        "rank": rank,
        "cell": item.cell_label,
        "score": item.score,
        "candidate_formula": item.candidate_formula or "",
        "evidence": (
            {
                "diagnostic_status": item.evidence.get("diagnostic_status", ""),
                "compatibility_adapter": item.evidence.get("compatibility_adapter", ""),
            }
            if compact else dict(item.evidence)
        ),
    }


def task(payload: tuple[str, str, dict[str, str], dict[str, object]]) -> str:
    root_text, output_text, row, config = payload
    root, output = Path(root_text), Path(output_text)
    workbook = root / row["workbook"]
    original = WorkbookModel.from_xlsx(workbook)
    model, unsupported = supported_model(original)
    started = time.perf_counter()
    method_values: dict[str, list[LocalizationResult]] = {
        "v4": v4_scores(model, candidate_limit=15) if model.formulas else [],
        "v4_3": v4_3_scores(model, variant="b") if model.formulas else [],
        "r2_source": v5_core_r2_scores(model, stage="source", config=config) if model.formulas else [],
        "r2_full": v5_core_r2_scores(model, stage="full", config=config) if model.formulas else [],
    }
    rankings = {
        method: [
            serial_result(item, rank, compact=method in {"v4", "v4_3"})
            for rank, item in enumerate(append_unsupported(values, unsupported, method=method), 1)
        ]
        for method, values in method_values.items()
    }
    record = {
        "instance_id": row["instance_id"],
        "workbook": row["workbook"],
        "workbook_sha256": sha256(workbook),
        "formula_count": len(original.formulas),
        "supported_formula_count": len(model.formulas),
        "unsupported_formula_count": len(unsupported),
        "rankings": rankings,
        "wall_seconds": time.perf_counter() - started,
    }
    shard = output / "shards" / f"{row['instance_id']}.json"
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return row["instance_id"]


def audit_shard(path: Path, row: dict[str, str], root: Path) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("instance_id") != row["instance_id"]:
        raise SystemExit(f"Wrong instance in shard: {path}")
    if record.get("workbook_sha256") != sha256(root / row["workbook"]):
        raise SystemExit(f"Workbook changed after prediction: {row['workbook']}")
    if set(record.get("rankings", {})) != set(METHODS):
        raise SystemExit(f"Missing prediction methods: {path}")
    formula_count = int(record["formula_count"])
    expected_cells: set[str] | None = None
    for method, ranking in record["rankings"].items():
        cells = [str(item["cell"]) for item in ranking]
        if len(cells) != formula_count or len(set(cells)) != formula_count:
            raise SystemExit(f"Incomplete or duplicate {method} ranking: {path}")
        if [int(item["rank"]) for item in ranking] != list(range(1, formula_count + 1)):
            raise SystemExit(f"Non-contiguous {method} ranking: {path}")
        if expected_cells is None:
            expected_cells = set(cells)
        elif set(cells) != expected_cells:
            raise SystemExit(f"Methods rank different formula sets: {path}")
    for method in ("r2_source", "r2_full"):
        required = {
            "observational_rank", "diagnostic_status", "candidate_independent_source_ranking",
            "workbook_null_statistic", "wcn_variant", "clean_null_calibrated",
        }
        if any(not required <= set(item["evidence"]) for item in record["rankings"][method]
               if not item["evidence"].get("compatibility_adapter")):
            raise SystemExit(f"Incomplete R2 evidence contract: {path} {method}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-root", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    manifest_path = args.public_root / "manifest.csv"
    rows = read_manifest(manifest_path)
    for row in rows:
        path = (args.public_root / row["workbook"]).resolve()
        try:
            path.relative_to(args.public_root.resolve())
        except ValueError as exc:
            raise SystemExit(f"Workbook path escapes public root: {row['workbook']}") from exc
        if not path.is_file():
            raise SystemExit(f"Missing public workbook: {path}")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if not config.get("clean_null_scores"):
        raise SystemExit("R2 confirmation configuration must contain frozen clean-null scores")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "shards").mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_core_r2_label_free_confirmation_predictions_v1",
        "public_manifest_sha256": sha256(manifest_path),
        "config_sha256": sha256(args.config),
        "model_source_sha256": sha256(ROOT / "formulaguard/v5_core_r2.py"),
        "runner_source_sha256": sha256(Path(__file__)),
        "git_commit": git_commit(),
        "instance_count": len(rows),
        "methods": list(METHODS),
        "workers_requested": args.workers,
        "compatibility_policy": "bounded parser plus cached-value complete-ranking tail",
        "label_files_read": [],
    }
    metadata_path = args.output / "prediction_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Resume refused: code, commit, config, manifest, or inputs changed")
        if not args.resume:
            raise SystemExit("Output exists; pass --resume")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    pending = []
    by_id = {row["instance_id"]: row for row in rows}
    for row in rows:
        shard = args.output / "shards" / f"{row['instance_id']}.json"
        if shard.exists():
            audit_shard(shard, row, args.public_root)
        else:
            pending.append(row)
    workers = min(args.workers, max(1, len(pending)))
    print(f"R2 confirmation scheduling: {workers} workers; {len(pending)} pending.", flush=True)
    payloads = [(str(args.public_root), str(args.output), row, config) for row in pending]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(task, payload) for payload in payloads]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            print(f"[{index}/{len(futures)}] {future.result()}", flush=True)
    expected = set(by_id)
    shards = sorted((args.output / "shards").glob("*.json"))
    observed = {path.stem for path in shards}
    if observed != expected:
        raise SystemExit(f"Prediction merge refused: missing={len(expected-observed)}, extra={len(observed-expected)}")
    for shard in shards:
        audit_shard(shard, by_id[shard.stem], args.public_root)
    digest = hashlib.sha256()
    for shard in shards:
        digest.update(shard.name.encode("utf-8"))
        digest.update(bytes.fromhex(sha256(shard)))
    completion = {
        "protocol": "v5_core_r2_confirmation_prediction_completion_v1",
        "complete": True,
        "instances": len(rows),
        "methods": list(METHODS),
        "workers_requested": args.workers,
        "combined_shards_sha256": digest.hexdigest(),
        "metadata_sha256": sha256(metadata_path),
        "full_ranking_audit_passed": True,
        "labels_may_be_read_by_separate_scorer": True,
    }
    completion_path = args.output / "prediction_complete.json"
    completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8")
    print(completion_path)


if __name__ == "__main__":
    main()
