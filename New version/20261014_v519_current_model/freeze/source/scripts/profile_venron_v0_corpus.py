#!/usr/bin/env python3
"""Convert and formula-profile the frozen ordered VEnron workbooks."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from formulaguard.venron import inspect_formula_workbook, stable_record_id

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_vhrl_venron_profile_v0"
PREPARE_PROTOCOL = "formulaguard_vhrl_venron_prepare_v0"
DEFAULT_SOURCE = ROOT / "data/external/model_discovery/raw/venron_extracted"
DEFAULT_PREPARE = ROOT / "results/venron_prepare_v0"
DEFAULT_DESTINATION = ROOT / "data/external/model_discovery/converted/venron_v0"
DEFAULT_OUTPUT = ROOT / "results/venron_profile_v0"
MAX_WORKERS = 24
DEFAULT_TIMEOUT_SECONDS = 180


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


def _git(command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *command), cwd=ROOT, check=check, capture_output=True, text=True
    )


def require_clean_pushed_worktree() -> str:
    if _git(("status", "--porcelain", "--untracked-files=no")).stdout.strip():
        raise ValueError("tracked worktree must be clean before VEnron profiling")
    commit = _git(("rev-parse", "HEAD")).stdout.strip()
    upstream = _git(
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ).stdout.strip()
    if _git(("merge-base", "--is-ancestor", commit, upstream), check=False).returncode:
        raise ValueError("VEnron profile implementation commit has not been pushed")
    return commit


def _safe_relative(value: str, suffix: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not relative.parts
        or relative.suffix.lower() != suffix
    ):
        raise ValueError(f"unsafe VEnron profile path: {value!r}")
    return relative


def _install(source: Path, target: Path) -> None:
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _convert_one(
    payload: tuple[dict[str, object], str, str, str, int],
) -> dict[str, object]:
    record, source_root_text, destination_text, libreoffice, timeout_seconds = payload
    source_root = Path(source_root_text)
    destination = Path(destination_text)
    relative = _safe_relative(str(record["source_relative_path"]), ".xls")
    source = source_root.joinpath(*relative.parts)
    output_relative = relative.with_suffix(".xlsx")
    target = destination.joinpath(*output_relative.parts)
    base = {
        "group_id": record["group_id"],
        "version_order": record["version_order"],
        "source_relative_path": relative.as_posix(),
        "source_sha256": record["source_sha256"],
        "source_bytes": record["source_bytes"],
        "converted_relative_path": output_relative.as_posix(),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.unlink(missing_ok=True)
        with tempfile.TemporaryDirectory(prefix="venron_lo_") as directory:
            temporary = Path(directory)
            profile = temporary / "profile"
            converted = temporary / "converted"
            profile.mkdir()
            converted.mkdir()
            subprocess.run(
                (
                    libreoffice,
                    f"-env:UserInstallation={profile.resolve().as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--nolockcheck",
                    "--nofirststartwizard",
                    "--convert-to",
                    "xlsx",
                    "--outdir",
                    str(converted),
                    str(source),
                ),
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            outputs = list(converted.glob("*.xlsx"))
            if len(outputs) != 1:
                raise ValueError(f"LibreOffice produced {len(outputs)} XLSX files")
            _install(outputs[0], target)
        formula_profile = inspect_formula_workbook(target)
        return {
            **base,
            "status": "parsed" if formula_profile["formula_count"] else "parsed_zero_formula",
            "converted_sha256": sha256(target),
            "converted_bytes": target.stat().st_size,
            "sheet_count": formula_profile["sheet_count"],
            "sheet_titles": formula_profile["sheet_titles"],
            "formula_count": formula_profile["formula_count"],
            "formulas": formula_profile["formulas"],
            "failure_type": "",
        }
    except Exception as exc:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        target.unlink(missing_ok=True)
        return {
            **base,
            "status": "conversion_or_parse_failure",
            "converted_sha256": "",
            "converted_bytes": 0,
            "sheet_count": 0,
            "sheet_titles": [],
            "formula_count": 0,
            "formulas": [],
            "failure_type": type(exc).__name__,
        }


def _shard_name(record: Mapping[str, object]) -> str:
    return stable_record_id(record["source_relative_path"]) + ".json"


def _validate_shard(
    path: Path, record: Mapping[str, object], destination: Path
) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if payload.get("protocol") != PROTOCOL or not isinstance(payload.get("result"), dict):
        raise ValueError(f"malformed VEnron profile shard: {path.name}")
    result = payload["result"]
    for key in ("source_relative_path", "source_sha256", "source_bytes"):
        if result.get(key) != record.get(key):
            raise ValueError(f"VEnron profile shard {key} mismatch: {path.name}")
    if result.get("status") in {"parsed", "parsed_zero_formula"}:
        relative = _safe_relative(str(result.get("converted_relative_path", "")), ".xlsx")
        converted = destination.joinpath(*relative.parts)
        if not converted.is_file() or sha256(converted) != result.get("converted_sha256"):
            raise ValueError(f"VEnron converted artifact changed: {path.name}")
    if len(result.get("formulas", [])) != int(result.get("formula_count", -1)):
        raise ValueError(f"VEnron formula profile count changed: {path.name}")
    return result


def _summary(
    result: Mapping[str, object], shard: str, shard_sha256: str
) -> dict[str, object]:
    return {
        "group_id": result["group_id"],
        "version_order": result["version_order"],
        "source_relative_path": result["source_relative_path"],
        "source_sha256": result["source_sha256"],
        "status": result["status"],
        "sheet_count": result["sheet_count"],
        "formula_count": result["formula_count"],
        "profile_shard": shard,
        "profile_shard_sha256": shard_sha256,
    }


def profile(
    *,
    source_root: Path,
    prepare_dir: Path,
    destination: Path,
    output_dir: Path,
    workers: int,
    libreoffice: str,
    timeout_seconds: int,
    resume: bool,
) -> Path:
    source_root = source_root.resolve()
    prepare_dir = prepare_dir.resolve()
    destination = destination.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if timeout_seconds < 1:
        raise ValueError("VEnron conversion timeout must be positive")
    commit = require_clean_pushed_worktree()
    prepare_receipt_path = prepare_dir / "prepare_receipt.json"
    version_manifest_path = prepare_dir / "version_manifest.json"
    prepare_receipt = json.loads(prepare_receipt_path.read_text(encoding="ascii"))
    version_manifest = json.loads(version_manifest_path.read_text(encoding="ascii"))
    if (
        prepare_receipt.get("protocol") != PREPARE_PROTOCOL
        or prepare_receipt.get("complete") is not True
        or prepare_receipt.get("group_workbook_contents_parsed") != 0
        or prepare_receipt.get("protected_data_inputs") != []
        or prepare_receipt.get("version_manifest_sha256") != sha256(version_manifest_path)
        or version_manifest.get("protocol") != PREPARE_PROTOCOL
    ):
        raise ValueError("VEnron prepare receipt or manifest changed")
    records = version_manifest.get("versions")
    if not isinstance(records, list) or len(records) != 7_294:
        raise ValueError("VEnron version manifest count is invalid")
    executable = shutil.which(libreoffice) if os.sep not in libreoffice else libreoffice
    if not executable or not Path(executable).is_file():
        raise ValueError(f"LibreOffice executable not found: {libreoffice}")
    executable = str(Path(executable).resolve())
    version = subprocess.run(
        (executable, "--version"), check=True, capture_output=True, text=True
    ).stdout.strip()

    complete_path = output_dir / "profile_receipt.json"
    if complete_path.exists():
        raise ValueError("completed VEnron profile receipt is immutable")
    metadata = {
        "protocol": PROTOCOL,
        "implementation_commit": commit,
        "prepare_receipt_sha256": sha256(prepare_receipt_path),
        "version_manifest_sha256": sha256(version_manifest_path),
        "source_count": len(records),
        "libreoffice": executable,
        "libreoffice_version": version,
        "timeout_seconds": timeout_seconds,
        "tool_sha256": sha256(Path(__file__).resolve()),
        "workers_requested": workers,
        "constant_cell_values_exported": False,
        "cached_formula_values_exported": False,
        "fault_label_inputs": [],
        "protected_data_inputs": [],
    }
    metadata_path = output_dir / "metadata.json"
    if output_dir.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("partial VEnron profile output exists; pass --resume after audit")
        existing = json.loads(metadata_path.read_text(encoding="ascii"))
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("VEnron profile resume metadata changed")
    else:
        output_dir.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    destination.mkdir(parents=True, exist_ok=True)
    shards = output_dir / "shards"
    shards.mkdir(exist_ok=True)

    summaries: dict[str, dict[str, object]] = {}
    pending: list[dict[str, object]] = []
    for record in records:
        shard_name = _shard_name(record)
        shard = shards / shard_name
        if shard.exists():
            result = _validate_shard(shard, record, destination)
            summaries[str(record["source_relative_path"])] = _summary(
                result, shard_name, sha256(shard)
            )
        else:
            pending.append(record)
    if pending:
        print(
            f"VEnron profiling scheduling: workers={min(workers, len(pending))}; "
            f"pending={len(pending)}; resumed={len(records) - len(pending)}",
            flush=True,
        )
        payloads = [
            (record, str(source_root), str(destination), executable, timeout_seconds)
            for record in pending
        ]
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_convert_one, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                source = str(result["source_relative_path"])
                shard_name = _shard_name(result)
                shard_path = shards / shard_name
                write_json_atomic(
                    shard_path,
                    {"protocol": PROTOCOL, "result": result},
                )
                summaries[source] = _summary(result, shard_name, sha256(shard_path))
                if index % 100 == 0 or index == len(pending):
                    statuses = Counter(row["status"] for row in summaries.values())
                    print(
                        f"VEnron profiled {index}/{len(pending)}; statuses={dict(statuses)}",
                        flush=True,
                    )

    ordered = [summaries[str(record["source_relative_path"])] for record in records]
    if len(ordered) != len(records):
        raise ValueError("VEnron profile result accounting is incomplete")
    index_payload = {"protocol": PROTOCOL, "profiles": ordered}
    index_path = output_dir / "profile_index.json"
    write_json_atomic(index_path, index_payload)
    statuses = Counter(str(row["status"]) for row in ordered)
    parsed = statuses["parsed"] + statuses["parsed_zero_formula"]
    receipt = {
        "protocol": PROTOCOL,
        "implementation_commit": commit,
        "source_workbooks": len(records),
        "accounted_workbooks": len(ordered),
        "statuses": dict(sorted(statuses.items())),
        "parsed_workbooks": parsed,
        "parse_coverage": round(parsed / len(records), 12),
        "total_formulas": sum(int(row["formula_count"]) for row in ordered),
        "profile_index_sha256": sha256(index_path),
        "metadata_sha256": sha256(metadata_path),
        "constant_cell_values_exported": False,
        "cached_formula_values_exported": False,
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "complete": len(ordered) == len(records),
    }
    write_json_atomic(complete_path, receipt)
    return complete_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--prepare", type=Path, default=DEFAULT_PREPARE)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--libreoffice", default="libreoffice")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        receipt = profile(
            source_root=args.source,
            prepare_dir=args.prepare,
            destination=args.destination,
            output_dir=args.output,
            workers=args.workers,
            libreoffice=args.libreoffice,
            timeout_seconds=args.timeout_seconds,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"VEnron profiling refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
