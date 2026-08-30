"""Fail-closed, input-only intake for the preregistered DRFV corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_drfv_spreadsheetbench_v1_intake_v1"
ARCHIVE_SHA256 = "9cf7228b54f1edcdd4b372eb736774adf29cb4f804c9920229bac6c154833399"
ARCHIVE_SIZE = 95_752_357
ARCHIVE_ROOT = "all_data_912_v0.1"
DATASET_MEMBER = f"{ARCHIVE_ROOT}/dataset.json"
SPREADSHEET_ROOT = PurePosixPath(ARCHIVE_ROOT, "spreadsheet")
EXPECTED_TASKS = 912
EXPECTED_INPUTS = 2_726
TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
MAX_MEMBER_SIZE = 512 * 1024 * 1024
MAX_TOTAL_INPUT_BYTES = 8 * 1024 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stream_sha256(handle: BinaryIO) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        size += len(block)
        digest.update(block)
    return digest.hexdigest(), size


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


def _git_commit() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _safe_member_name(value: str) -> PurePosixPath:
    if not value or "\\" in value or "\0" in value:
        raise ValueError(f"unsafe tar member name: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or any(not part for part in relative.parts):
        raise ValueError(f"unsafe tar member path: {value!r}")
    if not relative.parts or relative.parts[0] != ARCHIVE_ROOT:
        raise ValueError(f"tar member is outside the pinned archive root: {value!r}")
    return relative


def _input_identity(relative: PurePosixPath) -> tuple[str, str] | None:
    if len(relative.parts) != 4 or PurePosixPath(*relative.parts[:2]) != SPREADSHEET_ROOT:
        return None
    task_id, filename = relative.parts[2], relative.parts[3]
    if not TASK_ID_RE.fullmatch(task_id) or not filename.lower().endswith("_input.xlsx"):
        return None
    if PurePosixPath(filename).name != filename:
        return None
    return task_id, filename


def _answer_member(relative: PurePosixPath) -> bool:
    return (
        len(relative.parts) == 4
        and PurePosixPath(*relative.parts[:2]) == SPREADSHEET_ROOT
        and relative.name.lower().endswith("_answer.xlsx")
    )


def _validate_members(
    archive: tarfile.TarFile,
    *,
    expected_tasks: int,
    expected_inputs: int | None,
) -> tuple[list[tuple[tarfile.TarInfo, str, str]], tarfile.TarInfo, dict[str, int]]:
    seen_names: set[str] = set()
    selected: list[tuple[tarfile.TarInfo, str, str]] = []
    tasks: set[str] = set()
    dataset_member: tarfile.TarInfo | None = None
    answer_members = 0
    other_xlsx_members = 0
    total_input_bytes = 0

    for member in archive.getmembers():
        relative = _safe_member_name(member.name)
        canonical = relative.as_posix()
        if canonical in seen_names:
            raise ValueError(f"duplicate tar member: {canonical}")
        seen_names.add(canonical)
        if member.issym() or member.islnk() or member.isdev() or not (member.isfile() or member.isdir()):
            raise ValueError(f"unsupported tar member type: {canonical}")
        if member.size < 0 or member.size > MAX_MEMBER_SIZE:
            raise ValueError(f"tar member exceeds size limit: {canonical}")
        if canonical == DATASET_MEMBER:
            if not member.isfile():
                raise ValueError("dataset.json is not a regular file")
            dataset_member = member
        if member.isdir():
            continue
        identity = _input_identity(relative)
        if identity is not None:
            task_id, filename = identity
            tasks.add(task_id)
            total_input_bytes += member.size
            if total_input_bytes > MAX_TOTAL_INPUT_BYTES:
                raise ValueError("selected input members exceed the total size limit")
            selected.append((member, task_id, filename))
        elif _answer_member(relative):
            answer_members += 1
        elif relative.suffix.lower() in {".xlsx", ".xlsm", ".xls"}:
            other_xlsx_members += 1

    if dataset_member is None:
        raise ValueError("pinned dataset.json member is missing")
    if len(tasks) != expected_tasks:
        raise ValueError(f"expected {expected_tasks} input task directories, found {len(tasks)}")
    if expected_inputs is not None and len(selected) != expected_inputs:
        raise ValueError(f"expected {expected_inputs} input workbooks, found {len(selected)}")
    if not selected or answer_members < len(tasks):
        raise ValueError("archive input/answer accounting is incomplete")
    selected.sort(key=lambda item: (item[1], item[2]))
    return selected, dataset_member, {
        "task_directories": len(tasks),
        "input_members": len(selected),
        "answer_members_seen_not_read": answer_members,
        "other_excel_members_seen_not_read": other_xlsx_members,
        "selected_input_bytes": total_input_bytes,
    }


def intake(
    *,
    archive_path: Path,
    destination: Path,
    output_dir: Path,
    expected_archive_sha256: str = ARCHIVE_SHA256,
    expected_archive_size: int | None = ARCHIVE_SIZE,
    expected_tasks: int = EXPECTED_TASKS,
    expected_inputs: int | None = EXPECTED_INPUTS,
) -> Path:
    archive_path = archive_path.resolve()
    destination = destination.resolve()
    output_dir = output_dir.resolve()
    if not archive_path.is_file() or archive_path.is_symlink():
        raise ValueError("source archive is missing or is a symlink")
    if destination.exists() or output_dir.exists():
        raise ValueError("completed or partial intake output already exists")
    if expected_archive_size is not None and archive_path.stat().st_size != expected_archive_size:
        raise ValueError("source archive size differs from preregistration")
    observed_archive_hash = sha256(archive_path)
    if observed_archive_hash != expected_archive_sha256:
        raise ValueError("source archive hash differs from preregistration")

    destination.parent.mkdir(parents=True, exist_ok=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_destination = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    staging_output = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.tmp")
    if staging_destination.exists() or staging_output.exists():
        raise ValueError("staging path already exists")
    staging_destination.mkdir()
    staging_output.mkdir()
    installed_destination = False
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            selected, dataset_member, accounting = _validate_members(
                archive,
                expected_tasks=expected_tasks,
                expected_inputs=expected_inputs,
            )
            dataset_handle = archive.extractfile(dataset_member)
            if dataset_handle is None:
                raise ValueError("dataset.json cannot be read for hashing")
            dataset_sha256, dataset_bytes = _stream_sha256(dataset_handle)

            rows: list[dict[str, object]] = []
            for member, task_id, filename in selected:
                handle = archive.extractfile(member)
                if handle is None:
                    raise ValueError(f"input member cannot be opened: {member.name}")
                task_dir = staging_destination / task_id
                task_dir.mkdir(exist_ok=True)
                target = task_dir / filename
                if target.exists():
                    raise ValueError(f"duplicate destination filename: {task_id}/{filename}")
                temporary = target.with_suffix(target.suffix + ".tmp")
                digest = hashlib.sha256()
                written = 0
                with temporary.open("xb") as output:
                    for block in iter(lambda: handle.read(1024 * 1024), b""):
                        output.write(block)
                        written += len(block)
                        digest.update(block)
                if written != member.size:
                    raise ValueError(f"short extraction for input member: {member.name}")
                os.replace(temporary, target)
                rows.append({
                    "workbook_id": f"spreadsheetbench-v1:{task_id}:{filename}",
                    "task_id": task_id,
                    "relative_path": f"{task_id}/{filename}",
                    "bytes": written,
                    "sha256": digest.hexdigest(),
                })

        manifest = {
            "protocol": PROTOCOL,
            "archive_sha256": observed_archive_hash,
            "workbooks": rows,
        }
        manifest_path = staging_output / "input_manifest.json"
        _write_json_atomic(manifest_path, manifest)
        receipt = {
            "protocol": PROTOCOL,
            "complete": True,
            "git_commit": _git_commit(),
            "archive_name": archive_path.name,
            "archive_sha256": observed_archive_hash,
            "archive_size_bytes": archive_path.stat().st_size,
            "dataset_json_sha256": dataset_sha256,
            "dataset_json_bytes": dataset_bytes,
            **accounting,
            "extracted_inputs": len(rows),
            "input_manifest_sha256": sha256(manifest_path),
            "task_metadata_values_read": [],
            "instruction_inputs": [],
            "answer_position_inputs": [],
            "answer_workbook_inputs": [],
            "fault_label_inputs": [],
            "v4_rank_inputs": [],
            "protected_data_inputs": [],
            "raw_workbooks_redistributed": False,
        }
        _write_json_atomic(staging_output / "intake_receipt.json", receipt)
        os.replace(staging_destination, destination)
        installed_destination = True
        os.replace(staging_output, output_dir)
        return output_dir / "intake_receipt.json"
    except Exception:
        if installed_destination:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(staging_destination, ignore_errors=True)
        shutil.rmtree(staging_output, ignore_errors=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive",
        type=Path,
        default=ROOT / "data/external/v5_psl/raw/spreadsheetbench/repository/data/spreadsheetbench_912_v0.1.tar.gz",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=ROOT / "data/external/model_discovery/corpus/drfv_spreadsheetbench_v1_inputs",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "results/drfv_spreadsheetbench_v1_intake",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    receipt = intake(
        archive_path=args.archive,
        destination=args.destination,
        output_dir=args.output_dir,
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
