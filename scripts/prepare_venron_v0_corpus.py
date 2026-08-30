#!/usr/bin/env python3
"""Build the ordered VEnron source manifest and safely extract group workbooks."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

from formulaguard.venron import ORDER_MEMBER, parse_order_workbook


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_vhrl_venron_prepare_v0"
INVENTORY_PROTOCOL = "formulaguard_vhrl_venron_inventory_v0"
ORDER_PROTOCOL = "formulaguard_vhrl_venron_order_schema_v0"
DEFAULT_ARCHIVE = ROOT / "data/external/model_discovery/raw/venron/VEnron1.0.7z"
DEFAULT_INVENTORY = ROOT / "results/venron_inventory_v0"
DEFAULT_ORDER = ROOT / "data/external/model_discovery/corpus/venron_order/FileOrder.xlsx"
DEFAULT_ORDER_RECEIPT = ROOT / "results/venron_order_schema_v0/order_intake_receipt.json"
DEFAULT_DESTINATION = ROOT / "data/external/model_discovery/raw/venron_extracted"
DEFAULT_OUTPUT = ROOT / "results/venron_prepare_v0"
MAX_WORKERS = 24


def file_hashes(path: Path) -> tuple[int, str, str]:
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
    return file_hashes(path)[2]


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )


def _git(command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *command), cwd=ROOT, check=check, capture_output=True, text=True
    )


def require_clean_pushed_worktree() -> str:
    if _git(("status", "--porcelain", "--untracked-files=no")).stdout.strip():
        raise ValueError("tracked worktree must be clean before VEnron extraction")
    commit = _git(("rev-parse", "HEAD")).stdout.strip()
    upstream = _git(
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ).stdout.strip()
    if _git(("merge-base", "--is-ancestor", commit, upstream), check=False).returncode:
        raise ValueError("VEnron extraction implementation commit has not been pushed")
    return commit


def validate_verbose_listing(text: str, expected_members: int) -> dict[str, int]:
    lines = text.splitlines()
    if len(lines) != expected_members:
        raise ValueError(
            f"verbose archive listing count changed: {len(lines)} vs {expected_members}"
        )
    types = Counter(line[0] if line else "" for line in lines)
    unsupported = set(types) - {"-", "d"}
    if unsupported:
        raise ValueError(f"VEnron archive contains unsupported member types: {unsupported}")
    return dict(sorted(types.items()))


def _tree_files(root: Path) -> set[str]:
    observed: set[str] = set()
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            path = current_path / name
            if path.is_symlink():
                raise ValueError(f"symlink directory extracted from VEnron: {path}")
        for name in files:
            path = current_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"non-regular file extracted from VEnron: {path}")
            relative = path.relative_to(root).as_posix()
            if relative in observed:
                raise ValueError(f"duplicate extracted VEnron path: {relative}")
            observed.add(relative)
    return observed


def _hash_record(payload: tuple[dict[str, object], str]) -> dict[str, object]:
    record, root_text = payload
    relative = PurePosixPath(str(record["source_relative_path"]))
    path = Path(root_text).joinpath(*relative.parts)
    size, md5, digest = file_hashes(path)
    return {
        **record,
        "source_bytes": size,
        "source_sha256": digest,
        "archive_member_md5": md5,
        "publisher_md5_matches_archive_bytes": md5 == record["source_md5"],
    }


def prepare(
    *,
    archive: Path,
    inventory_dir: Path,
    order_workbook: Path,
    order_receipt: Path,
    destination: Path,
    output_dir: Path,
    bsdtar: str,
    workers: int,
) -> Path:
    archive = archive.resolve()
    inventory_dir = inventory_dir.resolve()
    order_workbook = order_workbook.resolve()
    order_receipt = order_receipt.resolve()
    destination = destination.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if destination.exists() or output_dir.exists():
        raise ValueError("completed or partial VEnron prepare output already exists")
    commit = require_clean_pushed_worktree()

    inventory_receipt_path = inventory_dir / "inventory_receipt.json"
    member_manifest_path = inventory_dir / "member_manifest.json"
    inventory_receipt = json.loads(inventory_receipt_path.read_text(encoding="ascii"))
    member_manifest = json.loads(member_manifest_path.read_text(encoding="ascii"))
    order_result = json.loads(order_receipt.read_text(encoding="ascii"))
    if (
        inventory_receipt.get("protocol") != INVENTORY_PROTOCOL
        or inventory_receipt.get("complete") is not True
        or inventory_receipt.get("protected_data_inputs") != []
        or inventory_receipt.get("member_manifest_sha256") != sha256(member_manifest_path)
        or member_manifest.get("protocol") != INVENTORY_PROTOCOL
        or order_result.get("protocol") != ORDER_PROTOCOL
        or order_result.get("complete") is not True
        or order_result.get("evolution_group_workbook_contents_read") != 0
        or order_result.get("protected_data_inputs") != []
        or order_result.get("converted_order_sha256") != sha256(order_workbook)
        or order_result.get("archive_sha256") != sha256(archive)
    ):
        raise ValueError("VEnron prepare input receipt or artifact identity changed")
    members = member_manifest.get("members")
    if not isinstance(members, list):
        raise ValueError("VEnron member manifest is malformed")
    member_paths = {
        str(row.get("member_path", ""))
        for row in members
        if isinstance(row, dict) and row.get("kind") == "workbook"
    }
    records = parse_order_workbook(order_workbook, member_paths)
    selected = {str(row["source_relative_path"]) for row in records}
    if len(selected) != 7_294 or ORDER_MEMBER in selected:
        raise ValueError("VEnron selected workbook accounting is invalid")

    executable = shutil.which(bsdtar) if os.sep not in bsdtar else bsdtar
    if not executable or not Path(executable).is_file():
        raise ValueError(f"bsdtar executable not found: {bsdtar}")
    executable = str(Path(executable).resolve())
    version = subprocess.run(
        (executable, "--version"), check=True, capture_output=True, text=True
    ).stdout.strip()
    verbose = subprocess.run(
        (executable, "-tvf", str(archive)),
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    member_types = validate_verbose_listing(verbose, len(members))

    staging_destination = destination.with_name(f".{destination.name}.{os.getpid()}.tmp")
    staging_output = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.tmp")
    if staging_destination.exists() or staging_output.exists():
        raise ValueError("VEnron prepare staging path already exists")
    staging_destination.mkdir(parents=True)
    staging_output.mkdir(parents=True)
    installed_destination = False
    try:
        selection_path = staging_output / "selected_members.txt"
        selection_path.write_text("\n".join(sorted(selected)) + "\n", encoding="utf-8")
        subprocess.run(
            (
                executable,
                "-xf",
                str(archive),
                "-C",
                str(staging_destination),
                "--no-same-owner",
                "--no-same-permissions",
                "-T",
                str(selection_path),
            ),
            check=True,
            capture_output=True,
            timeout=1800,
        )
        actual = _tree_files(staging_destination)
        if actual != selected:
            raise ValueError(
                f"VEnron extracted file set mismatch: expected={len(selected)}, actual={len(actual)}"
            )

        payloads = [(record, str(staging_destination)) for record in records]
        enriched: list[dict[str, object]] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for index, result in enumerate(executor.map(_hash_record, payloads), 1):
                enriched.append(result)
                if index % 500 == 0 or index == len(records):
                    print(f"VEnron source identity {index}/{len(records)}", flush=True)
        manifest = {
            "protocol": PROTOCOL,
            "archive_sha256": order_result["archive_sha256"],
            "versions": enriched,
        }
        version_manifest_path = staging_output / "version_manifest.json"
        _write_json(version_manifest_path, manifest)
        publisher_mismatches = [
            row for row in enriched if not row["publisher_md5_matches_archive_bytes"]
        ]
        mismatch_identity = [
            {
                "source_relative_path": row["source_relative_path"],
                "publisher_md5": row["source_md5"],
                "archive_member_md5": row["archive_member_md5"],
            }
            for row in publisher_mismatches
        ]
        mismatch_identity_sha256 = hashlib.sha256(
            json.dumps(
                mismatch_identity,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("ascii")
        ).hexdigest()
        receipt = {
            "protocol": PROTOCOL,
            "implementation_commit": commit,
            "archive_sha256": order_result["archive_sha256"],
            "inventory_receipt_sha256": sha256(inventory_receipt_path),
            "member_manifest_sha256": sha256(member_manifest_path),
            "order_receipt_sha256": sha256(order_receipt),
            "order_workbook_sha256": sha256(order_workbook),
            "version_manifest_sha256": sha256(version_manifest_path),
            "bsdtar": executable,
            "bsdtar_version": version,
            "archive_member_types": member_types,
            "evolution_groups": len({int(row["group_id"]) for row in enriched}),
            "group_workbooks": len(enriched),
            "source_bytes": sum(int(row["source_bytes"]) for row in enriched),
            "publisher_md5_matches": len(enriched) - len(publisher_mismatches),
            "publisher_md5_mismatches": len(publisher_mismatches),
            "publisher_md5_mismatch_groups": len(
                {int(row["group_id"]) for row in publisher_mismatches}
            ),
            "publisher_md5_mismatch_identity_sha256": mismatch_identity_sha256,
            "group_workbook_bytes_hashed": len(enriched),
            "group_workbook_contents_parsed": 0,
            "fault_label_inputs": [],
            "protected_data_inputs": [],
            "complete": True,
        }
        _write_json(staging_output / "prepare_receipt.json", receipt)
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staging_destination, destination)
        installed_destination = True
        os.replace(staging_output, output_dir)
    except BaseException:
        shutil.rmtree(staging_destination, ignore_errors=True)
        shutil.rmtree(staging_output, ignore_errors=True)
        if installed_destination:
            shutil.rmtree(destination, ignore_errors=True)
        raise
    return output_dir / "prepare_receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--order-workbook", type=Path, default=DEFAULT_ORDER)
    parser.add_argument("--order-receipt", type=Path, default=DEFAULT_ORDER_RECEIPT)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bsdtar", default="bsdtar")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    try:
        receipt = prepare(
            archive=args.archive,
            inventory_dir=args.inventory,
            order_workbook=args.order_workbook,
            order_receipt=args.order_receipt,
            destination=args.destination,
            output_dir=args.output,
            bsdtar=args.bsdtar,
            workers=args.workers,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"VEnron prepare refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
