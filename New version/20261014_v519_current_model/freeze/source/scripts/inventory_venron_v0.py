#!/usr/bin/env python3
"""Inventory the pinned VEnron archive without extracting or reading workbooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_vhrl_venron_inventory_v0"
ACQUISITION_PROTOCOL = "formulaguard_vhrl_venron_acquisition_v1"
DEFAULT_ARCHIVE = ROOT / "data/external/model_discovery/raw/venron/VEnron1.0.7z"
DEFAULT_ACQUISITION_RECEIPT = ROOT / "results/venron_intake_v1/acquisition_receipt.json"
DEFAULT_OUTPUT = ROOT / "results/venron_inventory_v0"
WORKBOOK_EXTENSIONS = {".xls", ".xlsx", ".xlsm", ".xlsb"}


def hashes(path: Path) -> tuple[int, str, str]:
    size = 0
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(block)
            md5.update(block)
            sha256.update(block)
    return size, md5.hexdigest(), sha256.hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )


def _git(command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *command),
        cwd=ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def require_clean_pushed_worktree() -> str:
    if _git(("status", "--porcelain", "--untracked-files=no")).stdout.strip():
        raise ValueError("tracked worktree must be clean before VEnron inventory")
    commit = _git(("rev-parse", "HEAD")).stdout.strip()
    upstream = _git(
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ).stdout.strip()
    pushed = _git(("merge-base", "--is-ancestor", commit, upstream), check=False)
    if pushed.returncode != 0:
        raise ValueError("VEnron inventory implementation commit has not been pushed")
    return commit


def safe_member_name(value: str) -> PurePosixPath:
    if not value or "\\" in value or any(ord(character) < 32 for character in value):
        raise ValueError(f"unsafe archive member name: {value!r}")
    directory_marker = value.endswith("/")
    candidate = value[:-1] if directory_marker else value
    if not candidate or candidate.startswith("/") or "//" in candidate:
        raise ValueError(f"unsafe archive member path: {value!r}")
    parts = candidate.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"unsafe archive member path: {value!r}")
    if parts[0].endswith(":"):
        raise ValueError(f"drive-qualified archive member path: {value!r}")
    relative = PurePosixPath(*parts)
    if relative.is_absolute() or relative.as_posix() != candidate:
        raise ValueError(f"noncanonical archive member path: {value!r}")
    return relative


def build_inventory(names: Sequence[str]) -> tuple[dict[str, object], list[dict[str, object]]]:
    if not names:
        raise ValueError("VEnron archive contains no members")
    seen: set[str] = set()
    rows: list[dict[str, object]] = []
    extension_counts: Counter[str] = Counter()
    workbook_parent_counts: Counter[str] = Counter()
    directory_count = 0
    max_depth = 0

    for raw_name in names:
        relative = safe_member_name(raw_name)
        canonical = relative.as_posix()
        if canonical in seen:
            raise ValueError(f"duplicate VEnron archive member: {canonical!r}")
        seen.add(canonical)
        is_directory = raw_name.endswith("/")
        suffix = relative.suffix.lower() if not is_directory else ""
        is_workbook = not is_directory and suffix in WORKBOOK_EXTENSIONS
        max_depth = max(max_depth, len(relative.parts))
        if is_directory:
            directory_count += 1
        elif suffix:
            extension_counts[suffix] += 1
        if is_workbook:
            parent = PurePosixPath(*relative.parts[:-1]).as_posix()
            workbook_parent_counts[parent] += 1
        rows.append({
            "member_path": canonical,
            "path_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            "depth": len(relative.parts),
            "kind": "directory" if is_directory else ("workbook" if is_workbook else "other"),
            "extension": suffix,
        })

    parent_size_distribution = Counter(workbook_parent_counts.values())
    workbook_count = sum(workbook_parent_counts.values())
    if workbook_count == 0:
        raise ValueError("VEnron archive inventory contains no supported workbook members")
    summary = {
        "member_count": len(rows),
        "directory_member_count": directory_count,
        "workbook_member_count": workbook_count,
        "non_workbook_member_count": len(rows) - directory_count - workbook_count,
        "max_path_depth": max_depth,
        "workbook_extension_counts": dict(sorted(extension_counts.items())),
        "workbook_parent_candidate_count": len(workbook_parent_counts),
        "workbook_parent_size_distribution": {
            str(size): count for size, count in sorted(parent_size_distribution.items())
        },
    }
    return summary, rows


def resolve_bsdtar(explicit: str | None) -> str:
    executable = (
        shutil.which(explicit) if explicit and os.sep not in explicit else explicit
    ) or shutil.which("bsdtar")
    if not executable:
        raise ValueError("bsdtar is required for VEnron inventory")
    resolved = str(Path(executable).resolve())
    version = subprocess.run(
        (resolved, "--version"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if "libarchive" not in version:
        raise ValueError("bsdtar version output does not identify libarchive")
    return resolved


def list_members(archive: Path, bsdtar: str) -> list[str]:
    completed = subprocess.run(
        (bsdtar, "-tf", str(archive)),
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.splitlines()


def inventory(
    *,
    archive: Path,
    acquisition_receipt: Path,
    output_dir: Path,
    bsdtar: str | None = None,
) -> Path:
    archive = archive.resolve()
    acquisition_receipt = acquisition_receipt.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise ValueError("VEnron inventory output already exists")
    if not archive.is_file() or archive.is_symlink():
        raise ValueError("pinned VEnron archive is missing or is a symlink")
    if not acquisition_receipt.is_file() or acquisition_receipt.is_symlink():
        raise ValueError("VEnron acquisition receipt is missing or is a symlink")

    commit = require_clean_pushed_worktree()
    acquisition = json.loads(acquisition_receipt.read_text(encoding="ascii"))
    size, md5, archive_sha256 = hashes(archive)
    if (
        acquisition.get("protocol") != ACQUISITION_PROTOCOL
        or acquisition.get("complete") is not True
        or acquisition.get("bytes") != size
        or acquisition.get("md5") != md5
        or acquisition.get("sha256") != archive_sha256
        or acquisition.get("protected_data_inputs") != []
    ):
        raise ValueError("VEnron acquisition receipt or archive identity changed")

    executable = resolve_bsdtar(bsdtar)
    version = subprocess.run(
        (executable, "--version"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    summary, rows = build_inventory(list_members(archive, executable))
    staging = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.tmp")
    if staging.exists():
        raise ValueError("VEnron inventory staging path already exists")
    staging.mkdir(parents=True)
    try:
        manifest = {
            "protocol": PROTOCOL,
            "archive_sha256": archive_sha256,
            "members": rows,
        }
        manifest_path = staging / "member_manifest.json"
        _write_json(manifest_path, manifest)
        receipt = {
            "protocol": PROTOCOL,
            "implementation_commit": commit,
            "archive_sha256": archive_sha256,
            "acquisition_receipt_sha256": sha256(acquisition_receipt),
            "bsdtar": executable,
            "bsdtar_version": version,
            "member_manifest_sha256": sha256(manifest_path),
            "summary": summary,
            "archive_member_names_read": len(rows),
            "archive_members_extracted": 0,
            "workbook_contents_read": 0,
            "fault_label_inputs": [],
            "protected_data_inputs": [],
            "complete": True,
        }
        _write_json(staging / "inventory_receipt.json", receipt)
        os.replace(staging, output_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return output_dir / "inventory_receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument(
        "--acquisition-receipt",
        type=Path,
        default=DEFAULT_ACQUISITION_RECEIPT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bsdtar")
    args = parser.parse_args()
    try:
        receipt = inventory(
            archive=args.archive,
            acquisition_receipt=args.acquisition_receipt,
            output_dir=args.output,
            bsdtar=args.bsdtar,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"VEnron inventory refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
