"""Run one model from a precommitted lock on label-free confirmation PUBLIC."""

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
_MODEL = ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


def write_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical_json(value))
    os.replace(temporary, path)


def git(*args: str, binary: bool = False):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=not binary
    )
    return result.stdout


def safe_path(root: Path, relative: str) -> Path:
    portable = PurePosixPath(relative)
    if portable.is_absolute() or ".." in portable.parts or "\\" in relative:
        raise ValueError(f"unsafe PUBLIC path: {relative}")
    candidate = (root / Path(*portable.parts)).resolve()
    if root.resolve() not in candidate.parents:
        raise ValueError(f"PUBLIC path escapes root: {relative}")
    return candidate


def load_public(public: Path, archive: Path) -> list[dict[str, str]]:
    with (public / "manifest.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != PUBLIC_FIELDS:
            raise ValueError("unexpected PUBLIC manifest fields")
        rows = list(reader)
    if len(rows) != 240 or len({row["case_id"] for row in rows}) != 240:
        raise ValueError("PUBLIC must contain 240 unique cases")
    clusters = Counter(row["cluster_id"] for row in rows)
    if len(clusters) != 20 or set(clusters.values()) != {12}:
        raise ValueError("PUBLIC must contain 20 clusters of 12 cases")
    for row in rows:
        workbook = safe_path(public, row["workbook_path"])
        if not workbook.is_file() or sha256_file(workbook) != row["workbook_sha256"]:
            raise ValueError(f"PUBLIC workbook integrity failure: {row['case_id']}")
    if not archive.is_file():
        raise ValueError("PUBLIC archive missing")
    return rows


def prepare_source(model: dict, destination: Path) -> tuple[str, str]:
    resolved = git("rev-parse", model["git_object"]).strip()
    if resolved != model["resolved_commit"]:
        raise ValueError(f"model ref moved: {model['name']}")
    tree = git("rev-parse", f"{resolved}^{{tree}}").strip()
    if tree != model["source_tree"]:
        raise ValueError(f"model tree changed: {model['name']}")
    raw = git("archive", "--format=tar", resolved, binary=True)
    with tarfile.open(fileobj=BytesIO(raw), mode="r:") as archive:
        for member in archive.getmembers():
            if (
                member.issym()
                or member.islnk()
                or ".." in PurePosixPath(member.name).parts
            ):
                raise ValueError("unsafe model archive")
        archive.extractall(destination, filter="data")
    return resolved, tree


def init_worker(source_root: str, model: str) -> None:
    global _MODEL
    _MODEL = model
    sys.path.insert(0, source_root)


def predict_one(task: tuple[dict[str, str], str]) -> dict[str, object]:
    row, workbook_path = task
    from formulaguard.workbook import WorkbookModel

    model = WorkbookModel.from_xlsx(Path(workbook_path))
    before = dict(model.formulas)
    if _MODEL == "v5_1_development":
        from formulaguard.v5_1_development import (
            MODEL_VERSION,
            v5_1_development_scores,
        )

        results = v5_1_development_scores(model)
        version = MODEL_VERSION
    elif _MODEL == "v4_r1":
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
    if model.formulas != before:
        raise ValueError(f"model mutated workbook: {row['case_id']}")
    cells = [result.cell for result in results]
    if len(cells) != len(model.formula_cells) or set(cells) != set(model.formula_cells):
        raise ValueError(f"incomplete ranking: {row['case_id']}")
    groups: dict[str, tuple[str, str]] = {}
    ranking = []
    for rank, result in enumerate(results, 1):
        if not math.isfinite(float(result.score)):
            raise ValueError(f"non-finite score: {row['case_id']}")
        evidence = {
            key: value
            for key, value in dict(result.evidence).items()
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
                "sheet": result.cell[0],
                "cell": result.cell[1],
                "score": result.score,
                "candidate_formula": result.candidate_formula,
                "evidence": evidence,
            }
        )
    return {
        "protocol": "v51_natural_confirmation_prediction_shard_v1",
        "model": _MODEL,
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
    parser.add_argument(
        "--model",
        choices=("v4_r1", "v5_v1", "v5_r2", "v5_1_development"),
        required=True,
    )
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--public-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    lock = json.loads(args.lock.read_text(encoding="utf-8"))
    model = lock["models"][args.model]
    public = args.public.resolve()
    rows = load_public(public, args.public_archive.resolve())
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"refusing to overwrite non-empty output: {args.output}")
    args.output.mkdir(parents=True)
    shards_dir = args.output / "shards"
    shards_dir.mkdir()
    with tempfile.TemporaryDirectory(prefix=f"v51-{args.model}-") as temporary:
        resolved, tree = prepare_source(model, Path(temporary))
        tasks = [(row, str(safe_path(public, row["workbook_path"]))) for row in rows]
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(args.workers, len(tasks)),
            initializer=init_worker,
            initargs=(temporary, args.model),
        ) as executor:
            for record in executor.map(predict_one, tasks):
                write_json(shards_dir / f"{record['case_id']}.json", record)
    paths = list(shards_dir.glob("*.json"))
    if len(paths) != len(rows):
        raise SystemExit("prediction shard count differs from PUBLIC")
    metadata = {
        "protocol": "v51_natural_confirmation_prediction_metadata_v1",
        "model": args.model,
        "resolved_commit": resolved,
        "source_tree": tree,
        "parameters": model["parameters"],
        "public_archive_sha256": sha256_file(args.public_archive.resolve()),
        "labels_read": [],
        "workers": min(args.workers, len(tasks)),
        "runner_commit": git("rev-parse", "HEAD").strip(),
        "runner_sha256": sha256_file(Path(__file__).resolve()),
        "excluded_volatile_evidence_fields": sorted(VOLATILE_EVIDENCE_FIELDS),
    }
    write_json(args.output / "prediction_metadata.json", metadata)
    write_json(
        args.output / "prediction_lock.json",
        {
            "protocol": "v51_natural_confirmation_prediction_lock_v1",
            "model": args.model,
            "cases": len(rows),
            "combined_shards_sha256": combined_hash(paths),
            "metadata_sha256": sha256_file(args.output / "prediction_metadata.json"),
            "labels_read": [],
            "locked": True,
        },
    )
    print((args.output / "prediction_lock.json").read_text(), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
