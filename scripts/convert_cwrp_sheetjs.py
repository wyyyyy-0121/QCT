"""Convert the pinned CWRP SheetJS corpus and emit content-free audits."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from collections import Counter
from collections.abc import Mapping
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(ROOT))

from formulaguard.formula import FormulaSyntaxError, parse_formula
from formulaguard.workbook import WorkbookModel
from scripts.acquire_cwrp_sheetjs import (
    COMMIT,
    sha256,
    stable_hash,
)
from scripts.acquire_cwrp_sheetjs import (
    PROTOCOL as ACQUISITION_PROTOCOL,
)

PROTOCOL = "formulaguard_cwrp_sheetjs_conversion_v2"
DEFAULT_SOURCE = ROOT / "data/external/model_discovery/raw/sheetjs_enron"
DEFAULT_ACQUISITION = ROOT / "results/cwrp_sheetjs_acquisition_v1"
DEFAULT_DESTINATION = ROOT / "data/external/model_discovery/converted/sheetjs_enron"
DEFAULT_OUTPUT = ROOT / "results/cwrp_sheetjs_conversion_v2"
MIN_PARSEABLE_FRACTION = 0.5
MAX_WORKERS = 24
DEFAULT_TIMEOUT_SECONDS = 180


def _safe_relative(value: str, suffix: str) -> PurePosixPath:
    if not value or "\\" in value:
        raise ValueError(f"invalid manifest path: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe manifest path: {value!r}")
    if not relative.parts or relative.parts[0] != "nuix":
        raise ValueError(f"manifest path is outside nuix/: {value!r}")
    if relative.suffix.lower() != suffix:
        raise ValueError(f"manifest path does not end in {suffix}: {value!r}")
    return relative


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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


def read_acquisition(
    acquisition_dir: Path,
    source_root: Path,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    receipt_path = acquisition_dir / "acquisition_receipt.json"
    manifest_path = acquisition_dir / "source_manifest.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if receipt.get("protocol") != ACQUISITION_PROTOCOL or not receipt.get("complete"):
        raise ValueError("acquisition receipt is incomplete or has the wrong protocol")
    if receipt.get("commit") != COMMIT or manifest.get("commit") != COMMIT:
        raise ValueError("acquisition does not use the preregistered SheetJS commit")
    if receipt.get("source_manifest_sha256") != sha256(manifest_path):
        raise ValueError("source manifest hash differs from acquisition receipt")
    rows = manifest.get("workbooks")
    if not isinstance(rows, list) or not rows:
        raise ValueError("source manifest has no workbooks")
    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("source manifest row is not an object")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
        relative = _safe_relative(str(item.get("relative_path", "")), ".xls")
        source_id = str(item.get("source_id", ""))
        declared_hash = str(item.get("sha256", ""))
        declared_bytes = item.get("bytes")
        if not source_id or source_id in seen_ids:
            raise ValueError(f"duplicate or empty source_id: {source_id!r}")
        seen_ids.add(source_id)
        path = source_root.joinpath(*relative.parts).resolve()
        if source_root.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"source workbook is missing or outside source root: {relative}")
        if path.is_symlink():
            raise ValueError(f"source workbook may not be a symlink: {relative}")
        if path.stat().st_size != declared_bytes or sha256(path) != declared_hash:
            raise ValueError(f"source workbook differs from acquisition manifest: {relative}")
        normalized.append({
            "source_id": source_id,
            "relative_path": relative.as_posix(),
            "source_sha256": declared_hash,
            "source_bytes": int(declared_bytes),
        })
    if len(normalized) != receipt.get("local_workbook_count"):
        raise ValueError("source manifest count differs from acquisition receipt")
    return sorted(normalized, key=lambda row: str(row["source_id"])), receipt


def _shard_name(source_id: str) -> str:
    return hashlib.sha256(source_id.encode("utf-8")).hexdigest() + ".json"


def _external_link_parts(path: Path) -> int:
    with zipfile.ZipFile(path) as package:
        return sum(
            name.startswith("xl/externalLinks/") and name.endswith(".xml")
            for name in package.namelist()
        )


def _inspect_converted(path: Path) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(path)
    formula_count = len(model.formulas)
    parseable_count = 0
    for formula in model.formulas.values():
        try:
            parse_formula(formula)
        except (FormulaSyntaxError, ValueError, TypeError):
            continue
        parseable_count += 1
    fraction = parseable_count / formula_count if formula_count else 0.0
    sheets = {sheet for sheet, _ in set(model.cells) | set(model.formulas)}
    if formula_count == 0:
        status = "excluded_no_formula"
    elif fraction < MIN_PARSEABLE_FRACTION:
        status = "excluded_low_parse_coverage"
    else:
        status = "eligible"
    return {
        "status": status,
        "sheet_count": len(sheets),
        "formula_count": formula_count,
        "parseable_formula_count": parseable_count,
        "parseable_formula_fraction": round(fraction, 12),
        "external_link_parts": _external_link_parts(path),
    }


def install_converted(source: Path, target: Path) -> None:
    """Install a converted file atomically even when source is on another FS."""

    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    try:
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _convert_one(
    payload: tuple[dict[str, object], str, str, str, int],
) -> dict[str, object]:
    row, source_root_text, destination_text, libreoffice, timeout_seconds = payload
    source_root = Path(source_root_text)
    destination = Path(destination_text)
    relative = _safe_relative(str(row["relative_path"]), ".xls")
    source = source_root.joinpath(*relative.parts)
    output_relative = relative.with_suffix(".xlsx")
    target = destination.joinpath(*output_relative.parts)
    base = {
        "source_id": row["source_id"],
        "source_sha256": row["source_sha256"],
        "source_bytes": row["source_bytes"],
        "source_relative_path": relative.as_posix(),
        "converted_relative_path": output_relative.as_posix(),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.unlink()
        with tempfile.TemporaryDirectory(prefix="cwrp_lo_") as directory:
            temporary = Path(directory)
            profile = temporary / "profile"
            converted = temporary / "converted"
            profile.mkdir()
            converted.mkdir()
            command = (
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
            )
            subprocess.run(
                command,
                check=True,
                capture_output=True,
                timeout=timeout_seconds,
            )
            outputs = sorted(converted.glob("*.xlsx"))
            if len(outputs) != 1:
                raise ValueError(f"LibreOffice produced {len(outputs)} xlsx files")
            install_converted(outputs[0], target)
        inspection = _inspect_converted(target)
        return {
            **base,
            **inspection,
            "converted_sha256": sha256(target),
            "converted_bytes": target.stat().st_size,
            "failure_type": "",
            "failure_errno": None,
        }
    except Exception as exc:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        target.unlink(missing_ok=True)
        return {
            **base,
            "status": "excluded_conversion_or_parse_failure",
            "sheet_count": 0,
            "formula_count": 0,
            "parseable_formula_count": 0,
            "parseable_formula_fraction": 0.0,
            "external_link_parts": 0,
            "converted_sha256": "",
            "converted_bytes": 0,
            "failure_type": type(exc).__name__,
            "failure_errno": getattr(exc, "errno", None),
        }


def _validate_shard(
    path: Path,
    expected: Mapping[str, object],
    destination: Path,
) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("protocol") != PROTOCOL:
        raise ValueError(f"wrong conversion shard protocol: {path.name}")
    result = record.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"malformed conversion shard: {path.name}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    for key in ("source_id", "source_sha256", "source_bytes"):
        if result.get(key) != expected.get(key):
            raise ValueError(f"conversion shard {key} mismatch: {path.name}")
    if result.get("status") in {"eligible", "excluded_no_formula", "excluded_low_parse_coverage"}:
        relative = _safe_relative(str(result.get("converted_relative_path", "")), ".xlsx")
        target = destination.joinpath(*relative.parts)
        if not target.is_file() or sha256(target) != result.get("converted_sha256"):
            raise ValueError(f"converted workbook hash mismatch: {path.name}")
    return result


def convert(
    *,
    source_root: Path,
    acquisition_dir: Path,
    destination: Path,
    output_dir: Path,
    workers: int,
    libreoffice: str,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    resume: bool = False,
) -> Path:
    source_root = source_root.resolve()
    acquisition_dir = acquisition_dir.resolve()
    destination = destination.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if timeout_seconds < 1:
        raise ValueError("timeout must be positive")
    executable = shutil.which(libreoffice) if os.sep not in libreoffice else libreoffice
    if not executable or not Path(executable).is_file():
        raise ValueError(f"LibreOffice executable not found: {libreoffice}")
    version = subprocess.run(
        (str(executable), "--version"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    rows, acquisition_receipt = read_acquisition(acquisition_dir, source_root)

    complete_path = output_dir / "conversion_receipt.json"
    if complete_path.exists():
        raise ValueError("conversion is already complete; completed receipts are immutable")
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "acquisition_receipt_sha256": sha256(acquisition_dir / "acquisition_receipt.json"),
        "source_manifest_sha256": acquisition_receipt["source_manifest_sha256"],
        "source_commit": acquisition_receipt["commit"],
        "source_count": len(rows),
        "libreoffice_version": version,
        "timeout_seconds": timeout_seconds,
        "min_parseable_formula_fraction": MIN_PARSEABLE_FRACTION,
        "tool_sha256": sha256(Path(__file__).resolve()),
        "workers_requested": workers,
        "cell_text_exported": False,
        "formula_text_exported": False,
        "fault_label_inputs": [],
        "protected_data_inputs": [],
    }
    metadata_path = output_dir / "metadata.json"
    if output_dir.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("partial conversion output exists; pass --resume after audit")
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("partial conversion metadata differs from this run")
    else:
        output_dir.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    destination.mkdir(parents=True, exist_ok=True)
    shards = output_dir / "shards"
    shards.mkdir(exist_ok=True)

    results: dict[str, dict[str, object]] = {}
    pending: list[dict[str, object]] = []
    for row in rows:
        shard = shards / _shard_name(str(row["source_id"]))
        if shard.exists():
            result = _validate_shard(shard, row, destination)
            results[str(row["source_id"])] = result
        else:
            pending.append(row)

    payloads = [
        (row, str(source_root), str(destination), str(executable), timeout_seconds)
        for row in pending
    ]
    if payloads:
        worker_count = min(workers, len(payloads))
        print(
            f"CWRP conversion scheduling: workers={worker_count}; "
            f"pending={len(payloads)}; resumed={len(rows) - len(payloads)}",
            flush=True,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_convert_one, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                source_id = str(result["source_id"])
                shard = shards / _shard_name(source_id)
                write_json_atomic(shard, {"protocol": PROTOCOL, "result": result})
                results[source_id] = result
                print(f"[{index}/{len(payloads)}] {source_id}: {result['status']}", flush=True)

    ordered = [results[str(row["source_id"])] for row in rows]
    if len(ordered) != len(rows):
        raise ValueError("conversion result accounting is incomplete")
    manifest = {"protocol": PROTOCOL, "results": ordered}
    manifest_path = output_dir / "conversion_manifest.json"
    write_json_atomic(manifest_path, manifest)
    statuses = Counter(str(row["status"]) for row in ordered)
    receipt = {
        "protocol": PROTOCOL,
        "source_commit": COMMIT,
        "source_workbooks": len(rows),
        "accounted_workbooks": len(ordered),
        "statuses": dict(sorted(statuses.items())),
        "eligible_workbooks": statuses["eligible"],
        "total_formulas_in_converted_workbooks": sum(int(row["formula_count"]) for row in ordered),
        "total_parseable_formulas": sum(int(row["parseable_formula_count"]) for row in ordered),
        "conversion_manifest_sha256": sha256(manifest_path),
        "conversion_inventory_sha256": stable_hash(ordered),
        "metadata_sha256": sha256(metadata_path),
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "complete": len(ordered) == len(rows),
    }
    write_json_atomic(complete_path, receipt)
    return complete_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--acquisition", type=Path, default=DEFAULT_ACQUISITION)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--libreoffice", default="libreoffice")
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        receipt = convert(
            source_root=args.source,
            acquisition_dir=args.acquisition,
            destination=args.destination,
            output_dir=args.output,
            workers=args.workers,
            libreoffice=args.libreoffice,
            timeout_seconds=args.timeout_seconds,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"CWRP conversion refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
