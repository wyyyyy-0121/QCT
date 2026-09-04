"""Run reproducible, label-free V5 Structural Guard PUBLIC predictions."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import time
import zipfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from formulaguard.v5_structural_guard import (
    MODEL_VERSION,
    v5_structural_guard_default_parameters,
    v5_structural_guard_scores,
)
from formulaguard.workbook import WorkbookModel

ROOT = Path(__file__).resolve().parents[1]
LOCKED_MODEL_COMMIT = "2232a870e3be089650ccd1676049e6c5c35cd692"
LOCKED_MODEL_FILES = (
    "formulaguard/a1.py",
    "formulaguard/formula.py",
    "formulaguard/localize.py",
    "formulaguard/v5_structural_guard.py",
    "formulaguard/workbook.py",
)
PUBLIC_FIELDS = (
    "case_id",
    "cluster_id",
    "workbook_path",
    "workbook_sha256",
    "file_format",
    "integrity_status",
)
FORBIDDEN_PUBLIC_TOKENS = (
    "answer",
    "correct",
    "label",
    "original",
    "secret",
    "source_cell",
    "truth",
)
CASE_PATTERN = re.compile(r"k_[0-9a-f]{20}")
CLUSTER_PATTERN = re.compile(r"c_[0-9a-f]{14}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(payload))
    os.replace(temporary, path)


def git_output(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def verify_model_lock() -> dict[str, str]:
    if git_output("status", "--porcelain", "--untracked-files=all"):
        raise ValueError("tracked or untracked repository files are present")
    source_hashes: dict[str, str] = {}
    for relative in LOCKED_MODEL_FILES:
        current = (ROOT / relative).read_bytes()
        locked = subprocess.run(
            ["git", "show", f"{LOCKED_MODEL_COMMIT}:{relative}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if current != locked:
            raise ValueError(f"model dependency changed after PUBLIC release: {relative}")
        source_hashes[relative] = sha256_bytes(current)
    return source_hashes


def safe_public_path(public_root: Path, relative: str) -> Path:
    portable = PurePosixPath(relative)
    if portable.is_absolute() or ".." in portable.parts or "\\" in relative:
        raise ValueError(f"unsafe PUBLIC path: {relative!r}")
    candidate = (public_root / Path(*portable.parts)).resolve()
    resolved_root = public_root.resolve()
    if resolved_root not in candidate.parents:
        raise ValueError(f"PUBLIC path escapes the root: {relative!r}")
    return candidate


def parse_sha256s(path: Path) -> dict[str, str]:
    records: dict[str, str] = {}
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            raise ValueError(f"invalid SHA256SUMS line {number}")
        relative = parts[1].strip().removeprefix("*")
        if relative in records:
            raise ValueError(f"duplicate SHA256SUMS path: {relative}")
        records[relative] = parts[0]
    return records


def validate_public_manifest_fields(fieldnames: Sequence[str] | None) -> None:
    actual = tuple(fieldnames or ())
    if actual != PUBLIC_FIELDS:
        raise ValueError(f"PUBLIC manifest fields differ: expected={PUBLIC_FIELDS}, actual={actual}")
    lowered = {field.lower() for field in actual}
    leaked = {
        field
        for field in lowered
        if any(token in field for token in FORBIDDEN_PUBLIC_TOKENS)
    }
    if leaked:
        raise ValueError(f"PUBLIC manifest contains label-like fields: {sorted(leaked)}")


def validate_source_archive(archive: Path, public_root: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
        unsafe = [
            name
            for name in names
            if PurePosixPath(name).is_absolute()
            or ".." in PurePosixPath(name).parts
            or "\\" in name
        ]
        symbolic_links = [
            item.filename
            for item in bundle.infolist()
            if ((item.external_attr >> 16) & 0o170000) == 0o120000
        ]
        if unsafe or symbolic_links:
            raise ValueError("source archive contains unsafe paths or symbolic links")
        files = {name for name in names if not name.endswith("/")}
        extracted_files = {
            "PUBLIC/" + path.relative_to(public_root).as_posix()
            for path in public_root.rglob("*")
            if path.is_file()
        }
        if files != extracted_files:
            raise ValueError("source archive and extracted PUBLIC file sets differ")
        for name in sorted(files):
            if sha256_bytes(bundle.read(name)) != sha256(public_root.parent / name):
                raise ValueError(f"extracted PUBLIC file differs from source archive: {name}")


def validate_public_root(public_root: Path, source_archive: Path) -> list[dict[str, str]]:
    manifest = public_root / "manifest.csv"
    sums_path = public_root / "SHA256SUMS.txt"
    if not manifest.is_file() or not sums_path.is_file():
        raise ValueError("PUBLIC requires manifest.csv and SHA256SUMS.txt")
    forbidden_files = [
        path
        for path in public_root.rglob("*")
        if path.is_file()
        and any(token in path.name.lower() for token in FORBIDDEN_PUBLIC_TOKENS)
    ]
    if forbidden_files:
        raise ValueError(f"PUBLIC contains label-like filenames: {forbidden_files[:3]}")
    with manifest.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        validate_public_manifest_fields(reader.fieldnames)
        rows = list(reader)
    if len(rows) != 360:
        raise ValueError(f"PUBLIC must contain exactly 360 cases, found {len(rows)}")
    case_ids = [row["case_id"].strip() for row in rows]
    if len(set(case_ids)) != 360 or any(not CASE_PATTERN.fullmatch(value) for value in case_ids):
        raise ValueError("PUBLIC case IDs must be 360 unique anonymous IDs")
    clusters = Counter(row["cluster_id"].strip() for row in rows)
    if len(clusters) != 30 or set(clusters.values()) != {12}:
        raise ValueError("PUBLIC must contain 30 anonymous clusters with 12 cases each")
    if any(not CLUSTER_PATTERN.fullmatch(value) for value in clusters):
        raise ValueError("PUBLIC cluster IDs are not anonymous")
    commitments = parse_sha256s(sums_path)
    expected_paths: set[str] = set()
    for row in rows:
        relative = row["workbook_path"].strip()
        workbook = safe_public_path(public_root, relative)
        if workbook.parent != (public_root / "workbooks").resolve():
            raise ValueError(f"workbook is outside PUBLIC/workbooks: {relative}")
        if workbook.suffix.lower() != ".xlsx" or row["file_format"].strip().lower() != "xlsx":
            raise ValueError(f"PUBLIC workbook is not XLSX: {relative}")
        if not workbook.is_file():
            raise ValueError(f"PUBLIC workbook is missing: {relative}")
        expected = row["workbook_sha256"].strip()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError(f"invalid workbook hash: {relative}")
        if expected != sha256(workbook) or commitments.get(relative) != expected:
            raise ValueError(f"workbook hash mismatch: {relative}")
        expected_paths.add(relative)
    if set(commitments) != expected_paths:
        raise ValueError("SHA256SUMS workbook set differs from the manifest")
    actual_files = {
        path.relative_to(public_root).as_posix()
        for path in public_root.rglob("*")
        if path.is_file()
    }
    if actual_files != expected_paths | {"manifest.csv", "SHA256SUMS.txt"}:
        raise ValueError("PUBLIC contains missing or extra files")
    validate_source_archive(source_archive, public_root)
    return rows


def prediction_record(task: tuple[str, Mapping[str, str]]) -> tuple[dict[str, object], float]:
    workbook_text, row = task
    workbook = Path(workbook_text)
    model = WorkbookModel.from_xlsx(workbook)
    original_formulas = dict(model.formulas)
    started = time.perf_counter()
    results = v5_structural_guard_scores(model)
    elapsed = time.perf_counter() - started
    if model.formulas != original_formulas:
        raise ValueError(f"V5 mutated the workbook model: {row['case_id']}")
    ranked_cells = [result.cell for result in results]
    if (
        len(results) != len(model.formula_cells)
        or len(set(ranked_cells)) != len(results)
        or set(ranked_cells) != set(model.formula_cells)
    ):
        raise ValueError(f"V5 returned an incomplete ranking: {row['case_id']}")
    if any(not math.isfinite(float(result.score)) for result in results):
        raise ValueError(f"V5 returned a non-finite score: {row['case_id']}")
    groups: dict[str, tuple[str, str]] = {}
    ranking: list[dict[str, object]] = []
    for rank, result in enumerate(results, 1):
        evidence = dict(result.evidence)
        group_id = str(evidence.get("group_id", ""))
        if group_id:
            identity = (str(evidence.get("group_state", "")), str(evidence.get("group_reason", "")))
            if group_id in groups and groups[group_id] != identity:
                raise ValueError(f"inconsistent group evidence: {row['case_id']} {group_id}")
            groups[group_id] = identity
        ranking.append(
            {
                "rank": rank,
                "sheet": result.cell[0],
                "cell": result.cell[1],
                "score": result.score,
                "candidate_formula": result.candidate_formula,
                "evidence": evidence,
            }
        )
    candidate_count = sum(item["candidate_formula"] is not None for item in ranking)
    record = {
        "protocol": "v5_structural_guard_public_prediction_shard_v1",
        "case_id": row["case_id"],
        "cluster_id": row["cluster_id"],
        "workbook": row["workbook_path"],
        "workbook_sha256": row["workbook_sha256"],
        "input_integrity_status": row["integrity_status"],
        "model_version": MODEL_VERSION,
        "formula_count": len(results),
        "candidate_count": candidate_count,
        "accepted_group_count": sum(state == "accepted" for state, _ in groups.values()),
        "abstained_group_count": sum(state == "abstained" for state, _ in groups.values()),
        "group_rejection_reasons": dict(
            sorted(Counter(reason for state, reason in groups.values() if state == "abstained").items())
        ),
        "ranking": ranking,
    }
    return record, elapsed


def audit_shard(path: Path, row: Mapping[str, str], public_root: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != "v5_structural_guard_public_prediction_shard_v1":
        raise ValueError(f"invalid shard protocol: {path}")
    for key, expected in (
        ("case_id", row["case_id"]),
        ("cluster_id", row["cluster_id"]),
        ("workbook", row["workbook_path"]),
        ("workbook_sha256", row["workbook_sha256"]),
        ("model_version", MODEL_VERSION),
    ):
        if payload.get(key) != expected:
            raise ValueError(f"shard identity mismatch for {key}: {path}")
    workbook = safe_public_path(public_root, row["workbook_path"])
    if sha256(workbook) != row["workbook_sha256"]:
        raise ValueError(f"workbook changed after prediction: {path}")
    model = WorkbookModel.from_xlsx(workbook)
    ranking = payload.get("ranking")
    if not isinstance(ranking, list) or payload.get("formula_count") != len(model.formula_cells):
        raise ValueError(f"shard formula count is invalid: {path}")
    cells = {(item.get("sheet"), item.get("cell")) for item in ranking}
    if len(ranking) != len(cells) or cells != set(model.formula_cells):
        raise ValueError(f"shard ranking is incomplete: {path}")
    if [item.get("rank") for item in ranking] != list(range(1, len(ranking) + 1)):
        raise ValueError(f"shard rank sequence is invalid: {path}")
    return payload


def combined_shards_sha256(paths: Sequence[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256(path)))
    return digest.hexdigest()


def aggregate_summary(shards: Sequence[dict[str, object]]) -> dict[str, object]:
    formula_counts = [int(row["formula_count"]) for row in shards]
    candidate_counts = [int(row["candidate_count"]) for row in shards]
    rejection_reasons: Counter[str] = Counter()
    for row in shards:
        rejection_reasons.update(row["group_rejection_reasons"])
    return {
        "protocol": "v5_structural_guard_public_unlabeled_summary_v1",
        "evidence_scope": "label_free_public_pre_recalc_engineering_prediction",
        "accuracy_scoring_available": False,
        "cases": len(shards),
        "clusters": len({str(row["cluster_id"]) for row in shards}),
        "formula_cells": sum(formula_counts),
        "candidate_cells": sum(candidate_counts),
        "cases_with_candidates": sum(count > 0 for count in candidate_counts),
        "candidate_action_rate": sum(candidate_counts) / sum(formula_counts),
        "median_candidates_per_case": statistics.median(candidate_counts),
        "maximum_candidates_in_one_case": max(candidate_counts),
        "accepted_groups": sum(int(row["accepted_group_count"]) for row in shards),
        "abstained_groups": sum(int(row["abstained_group_count"]) for row in shards),
        "group_rejection_reasons": dict(sorted(rejection_reasons.items())),
        "complete_ranking_audit_passed": True,
        "labels_read": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=min(16, max(1, (os.cpu_count() or 2) // 2)))
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    public_root = args.public.resolve()
    source_archive = args.source_archive.resolve()
    if not public_root.is_dir() or not source_archive.is_file():
        parser.error("PUBLIC directory and source archive must exist")
    if args.output.exists() and any(args.output.iterdir()) and not args.resume:
        raise SystemExit(f"refusing to overwrite non-empty output: {args.output}")

    try:
        source_hashes = verify_model_lock()
        rows = validate_public_root(public_root, source_archive)
    except (OSError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"PUBLIC prediction refused: {exc}") from exc

    args.output.mkdir(parents=True, exist_ok=True)
    shards_dir = args.output / "shards"
    shards_dir.mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_structural_guard_public_prediction_metadata_v1",
        "evidence_scope": "label_free_public_pre_recalc_engineering_prediction",
        "formal_blind_accuracy_claim_allowed": False,
        "reason_formal_claim_deferred": "external_recalc_and_SECRET_labels_are_pending",
        "public_archive": source_archive.name,
        "public_archive_sha256": sha256(source_archive),
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "sha256s_file_sha256": sha256(public_root / "SHA256SUMS.txt"),
        "cases": len(rows),
        "clusters": len({row["cluster_id"] for row in rows}),
        "model_origin_commit": LOCKED_MODEL_COMMIT,
        "prediction_runner_commit": git_output("rev-parse", "HEAD"),
        "model_version": MODEL_VERSION,
        "parameters": v5_structural_guard_default_parameters(),
        "model_source_sha256": source_hashes,
        "runner_sha256": sha256(Path(__file__).resolve()),
        "manifest_fields": list(PUBLIC_FIELDS),
        "forbidden_public_tokens": list(FORBIDDEN_PUBLIC_TOKENS),
        "labels_read": [],
        "public_seen_before_runner_commit": True,
        "post_public_model_change_detected": False,
    }
    metadata_path = args.output / "prediction_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("resume refused: prediction metadata changed")
    else:
        write_json(metadata_path, metadata)

    rows_by_id = {row["case_id"]: row for row in rows}
    pending: list[tuple[str, Mapping[str, str]]] = []
    runtimes: dict[str, float] = {}
    for row in rows:
        shard = shards_dir / f"{row['case_id']}.json"
        if shard.exists():
            audit_shard(shard, row, public_root)
        else:
            workbook = safe_public_path(public_root, row["workbook_path"])
            pending.append((str(workbook), row))

    workers = min(args.workers, max(1, len(pending)))
    started = time.perf_counter()
    print(f"V5 Structural Guard PUBLIC: cases={len(rows)} pending={len(pending)} workers={workers}", flush=True)
    if pending:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(prediction_record, task) for task in pending]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                record, elapsed = future.result()
                case_id = str(record["case_id"])
                write_json(shards_dir / f"{case_id}.json", record)
                runtimes[case_id] = elapsed
                if index == 1 or index % 10 == 0 or index == len(pending):
                    print(f"[{index}/{len(pending)}] completed", flush=True)
    wall_seconds = time.perf_counter() - started

    shard_paths = sorted(shards_dir.glob("*.json"))
    if {path.stem for path in shard_paths} != set(rows_by_id):
        raise SystemExit("prediction lock refused: shard set differs from PUBLIC cases")
    shards = [audit_shard(path, rows_by_id[path.stem], public_root) for path in shard_paths]
    summary = aggregate_summary(shards)
    summary_path = args.output / "unlabeled_summary.json"
    write_json(summary_path, summary)
    lock = {
        "protocol": "v5_structural_guard_public_prediction_lock_v1",
        "locked": True,
        "evidence_scope": "label_free_public_pre_recalc_engineering_prediction",
        "cases": len(shards),
        "combined_shards_sha256": combined_shards_sha256(shard_paths),
        "metadata_sha256": sha256(metadata_path),
        "summary_sha256": sha256(summary_path),
        "complete_ranking_audit_passed": True,
        "labels_read": [],
        "accuracy_scoring_deferred": True,
        "instruction": "Do not edit predictions; rerun after externally recalculated PUBLIC is separately committed.",
    }
    write_json(args.output / "prediction_lock.json", lock)
    performance = {
        "protocol": "v5_structural_guard_public_prediction_performance_v1",
        "worker_processes": workers,
        "wall_seconds": wall_seconds,
        "completed_in_this_invocation": len(runtimes),
        "per_case_runtime_seconds": dict(sorted(runtimes.items())),
    }
    write_json(args.output / "performance.json", performance)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    print(args.output / "prediction_lock.json", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
