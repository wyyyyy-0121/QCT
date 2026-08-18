"""Shared validation and lock helpers for the V4/V5.2 independent study."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts.run_external_evaluation import sha256_file


PUBLIC_COLUMNS = ("instance_id", "workbook")
FORBIDDEN_LABEL_FIELDS = {
    "source_cell", "source_cells", "correct_formula", "original_formula",
    "fault_cell", "fault_cells", "error_type", "error_subtype", "mutation_type",
    "exception_cell", "exception_cells", "label", "answer",
}


def validate_public_manifest(
    manifest: Path,
    *,
    expected_events: int = 15,
) -> tuple[list[dict[str, str]], dict[str, str]]:
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    if fieldnames != PUBLIC_COLUMNS:
        forbidden = FORBIDDEN_LABEL_FIELDS & {field.strip().lower() for field in fieldnames}
        detail = f"; forbidden fields: {', '.join(sorted(forbidden))}" if forbidden else ""
        raise ValueError(
            f"Public manifest must contain exactly {PUBLIC_COLUMNS}, got {fieldnames}{detail}"
        )
    if len(rows) != expected_events:
        raise ValueError(f"Expected exactly {expected_events} independent events, got {len(rows)}")
    ids = [row["instance_id"].strip() for row in rows]
    workbooks = [row["workbook"].strip() for row in rows]
    if any(not value for value in ids) or len(ids) != len(set(ids)):
        raise ValueError("instance_id values must be non-empty and unique")
    if any(not value for value in workbooks) or len(workbooks) != len(set(workbooks)):
        raise ValueError("Each event must name one distinct non-empty workbook")
    public_root = manifest.parent.resolve()
    hashes: dict[str, str] = {}
    for row in rows:
        relative = Path(row["workbook"])
        workbook = (manifest.parent / relative).resolve()
        if relative.is_absolute() or not workbook.is_relative_to(public_root):
            raise ValueError(f"Workbook escapes the public blind directory: {relative}")
        if workbook.suffix.lower() != ".xlsx" or not workbook.is_file():
            raise ValueError(f"Independent workbook must be an existing .xlsx file: {workbook}")
        hashes[row["instance_id"]] = sha256_file(workbook)
    return rows, hashes


def verify_joint_lock(lock_path: Path) -> tuple[dict[str, Path], dict[str, object]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    files = {}
    for key in ("v4_rankings", "v52_decisions", "metadata"):
        descriptor = lock["files"][key]
        path = lock_path.parent / str(descriptor["file"])
        if sha256_file(path) != descriptor["sha256"]:
            raise ValueError(f"Joint blind lock hash mismatch: {key}")
        files[key] = path
    return files, lock
