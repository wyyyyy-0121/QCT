"""Run one hash-locked FormulaGuard model on a label-free PUBLIC release."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_FIELDS = (
    "case_id",
    "cluster_id",
    "workbook_path",
    "workbook_sha256",
    "file_format",
    "integrity_status",
)
VOLATILE_EVIDENCE_FIELDS = {"localization_seconds"}


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(value))
    os.replace(temporary, path)


def git(*args: str, binary: bool = False):
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=not binary,
    )
    return completed.stdout


def safe_path(root: Path, relative: str) -> Path:
    portable = PurePosixPath(relative)
    if portable.is_absolute() or ".." in portable.parts or "\\" in relative:
        raise ValueError(f"unsafe path: {relative}")
    result = (root / Path(*portable.parts)).resolve()
    if root.resolve() not in result.parents:
        raise ValueError(f"path escapes PUBLIC: {relative}")
    return result


def load_public(public: Path, archive: Path) -> list[dict[str, str]]:
    if (
        sha256_file(archive)
        != (public / "PUBLIC_ARCHIVE_SHA256.txt").read_text().strip()
    ):
        raise ValueError("PUBLIC archive self-hash receipt differs")
    with (public / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != PUBLIC_FIELDS:
            raise ValueError("unexpected PUBLIC manifest fields")
        rows = list(reader)
    if len(rows) != 360 or len({row["case_id"] for row in rows}) != 360:
        raise ValueError("PUBLIC must contain 360 unique cases")
    clusters = Counter(row["cluster_id"] for row in rows)
    if len(clusters) != 30 or set(clusters.values()) != {12}:
        raise ValueError("PUBLIC must contain 30 clusters of 12")
    for row in rows:
        workbook = safe_path(public, row["workbook_path"])
        if not workbook.is_file() or sha256_file(workbook) != row["workbook_sha256"]:
            raise ValueError(f"workbook integrity failure: {row['case_id']}")
    return rows


def prepare_source(model_lock: dict, destination: Path) -> tuple[str, str]:
    resolved = git("rev-parse", model_lock["git_object"]).strip()
    if resolved != model_lock["resolved_commit"]:
        raise ValueError(f"model ref moved: {model_lock['name']}")
    tree = git("rev-parse", f"{resolved}^{{tree}}").strip()
    if tree != model_lock["source_tree"]:
        raise ValueError(f"model tree changed: {model_lock['name']}")
    archive = git("archive", "--format=tar", resolved, binary=True)
    with tarfile.open(fileobj=BytesIO(archive), mode="r:") as bundle:
        for member in bundle.getmembers():
            parts = PurePosixPath(member.name).parts
            if member.issym() or member.islnk() or ".." in parts:
                raise ValueError("unsafe path in git archive")
        bundle.extractall(destination, filter="data")
    return resolved, tree


_SOURCE_ROOT = ""
_MODEL_KIND = ""


def init_worker(source_root: str, model_kind: str) -> None:
    global _SOURCE_ROOT, _MODEL_KIND
    _SOURCE_ROOT = source_root
    _MODEL_KIND = model_kind
    sys.path.insert(0, source_root)


def predict_one(task: tuple[dict[str, str], str]) -> dict[str, object]:
    row, workbook_path = task
    from formulaguard.workbook import WorkbookModel

    model = WorkbookModel.from_xlsx(Path(workbook_path))
    original = dict(model.formulas)
    if _MODEL_KIND == "v4_r1":
        from formulaguard.localize import v4_scores

        results = v4_scores(model)
        version = "v4-r1"
    else:
        from formulaguard.v5_structural_guard import (
            MODEL_VERSION,
            v5_structural_guard_scores,
        )

        results = v5_structural_guard_scores(model)
        version = MODEL_VERSION
    if model.formulas != original:
        raise ValueError(f"model mutated workbook: {row['case_id']}")
    cells = [item.cell for item in results]
    if len(cells) != len(model.formula_cells) or set(cells) != set(model.formula_cells):
        raise ValueError(f"incomplete ranking: {row['case_id']}")
    groups: dict[str, tuple[str, str]] = {}
    ranking = []
    for rank, item in enumerate(results, 1):
        if not math.isfinite(float(item.score)):
            raise ValueError(f"non-finite score: {row['case_id']}")
        evidence = {
            key: value
            for key, value in dict(item.evidence).items()
            if key not in VOLATILE_EVIDENCE_FIELDS
        }
        group_id = str(evidence.get("group_id", ""))
        if group_id:
            groups[group_id] = (
                str(evidence.get("group_state", "")),
                str(evidence.get("group_reason", "")),
            )
        ranking.append(
            {
                "rank": rank,
                "sheet": item.cell[0],
                "cell": item.cell[1],
                "score": item.score,
                "candidate_formula": item.candidate_formula,
                "evidence": evidence,
            }
        )
    return {
        "protocol": "structural_guard_fresh_blind_prediction_shard_v1_1",
        "model": _MODEL_KIND,
        "model_version": version,
        "case_id": row["case_id"],
        "cluster_id": row["cluster_id"],
        "workbook_sha256": row["workbook_sha256"],
        "formula_count": len(ranking),
        "candidate_count": sum(
            item["candidate_formula"] is not None for item in ranking
        ),
        "accepted_group_count": sum(
            state == "accepted" for state, _ in groups.values()
        ),
        "ranking": ranking,
    }


def combined_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--model", choices=("v4_r1", "v5_v1", "v5_r2"), required=True)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--public-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    model_lock = lock["models"][args.model]
    rows = load_public(args.public.resolve(), args.public_archive.resolve())
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {args.output}")
    args.output.mkdir(parents=True)
    shards_dir = args.output / "shards"
    shards_dir.mkdir()
    with tempfile.TemporaryDirectory(prefix=f"fg-{args.model}-") as temporary:
        resolved, tree = prepare_source(model_lock, Path(temporary))
        tasks = [
            (row, str(safe_path(args.public.resolve(), row["workbook_path"])))
            for row in rows
        ]
        print(f"{args.model}: cases={len(tasks)} workers={args.workers}", flush=True)
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(args.workers, len(tasks)),
            initializer=init_worker,
            initargs=(temporary, model_lock["kind"]),
        ) as executor:
            for index, record in enumerate(executor.map(predict_one, tasks), 1):
                write_json(shards_dir / f"{record['case_id']}.json", record)
                if index == 1 or index % 20 == 0 or index == len(tasks):
                    print(f"[{index}/{len(tasks)}]", flush=True)
    paths = list(shards_dir.glob("*.json"))
    if len(paths) != 360:
        raise SystemExit("prediction shard count differs from PUBLIC")
    metadata = {
        "protocol": "structural_guard_fresh_blind_prediction_metadata_v1_1",
        "model": args.model,
        "resolved_commit": resolved,
        "source_tree": tree,
        "parameters": model_lock["parameters"],
        "public_archive_sha256": sha256_file(args.public_archive.resolve()),
        "labels_read": [],
        "workers": min(args.workers, len(tasks)),
        "runner_commit": git("rev-parse", "HEAD").strip(),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "excluded_volatile_evidence_fields": sorted(VOLATILE_EVIDENCE_FIELDS),
    }
    write_json(args.output / "prediction_metadata.json", metadata)
    lock_payload = {
        "protocol": "structural_guard_fresh_blind_prediction_lock_v1_1",
        "model": args.model,
        "cases": 360,
        "combined_shards_sha256": combined_hash(paths),
        "metadata_sha256": sha256_file(args.output / "prediction_metadata.json"),
        "labels_read": [],
        "locked": True,
    }
    write_json(args.output / "prediction_lock.json", lock_payload)
    print(json.dumps(lock_payload, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
