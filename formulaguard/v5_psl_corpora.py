"""Acquisition and inventory adapters for V5-PSL public development corpora."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from .v5_psl_protocol import canonical_json_sha256, sha256

CORPUS_IDS = (
    "modified_euses", "info1", "integer_corpus", "enron_error",
    "forepbench", "spreadsheetbench",
)
LOCALIZATION_CORPORA = {
    "modified_euses", "info1", "integer_corpus", "enron_error",
}
INVENTORY_FIELDS = (
    "corpus_id", "item_id", "relative_path", "sha256", "file_type",
    "task_scope", "label_sidecar", "source_cells_raw",
    "include_for_localization", "exclusion_reason",
)
WORKBOOK_SUFFIXES = {".xls", ".xlsx", ".xlsm"}


def load_registry(path: Path) -> dict[str, dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol") != "v5_psl_public_corpus_registry_v1":
        raise ValueError("Public corpus registry protocol is invalid")
    rows = payload.get("corpora")
    if not isinstance(rows, list):
        raise ValueError("Public corpus registry must contain a corpora list")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    by_id = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in CORPUS_IDS:
            raise ValueError("Public corpus registry contains an unknown corpus")
        corpus_id = str(row["id"])
        if corpus_id in by_id:
            raise ValueError(f"Duplicate public corpus: {corpus_id}")
        acquisition = row.get("acquisition")
        license_row = row.get("license")
        if not isinstance(acquisition, dict) or acquisition.get("kind") not in {"http_zip", "git"}:
            raise ValueError(f"Invalid acquisition record for {corpus_id}")
        if not str(acquisition.get("url", "")).startswith("https://"):
            raise ValueError(f"Corpus URL must use HTTPS: {corpus_id}")
        if acquisition["kind"] == "http_zip" and not re.fullmatch(
            r"[0-9a-f]{64}", str(acquisition.get("sha256", "")),
        ):
            raise ValueError(f"HTTP corpus requires a pinned SHA-256: {corpus_id}")
        if acquisition["kind"] == "git" and not re.fullmatch(
            r"[0-9a-f]{40}", str(acquisition.get("commit", "")),
        ):
            raise ValueError(f"Git corpus requires a pinned commit: {corpus_id}")
        if not isinstance(license_row, dict) or license_row.get("redistribution_by_this_project") is not False:
            raise ValueError(f"Registry must conservatively disable raw redistribution: {corpus_id}")
        by_id[corpus_id] = row
    if tuple(sorted(by_id)) != tuple(sorted(CORPUS_IDS)):
        raise ValueError("Public corpus registry must contain all six preregistered corpora")
    return by_id


def _download(url: str, output: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "FormulaGuard-corpus-audit/1"})
    temporary = output.with_suffix(output.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=120) as response, temporary.open("wb") as handle:
            shutil.copyfileobj(response, handle, length=1024 * 1024)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def safe_extract_zip(archive_path: Path, output: Path) -> int:
    if output.exists() and any(output.iterdir()):
        raise ValueError(f"Refusing to overwrite non-empty extraction directory: {output}")
    output.mkdir(parents=True, exist_ok=True)
    extracted = 0
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            name = item.filename
            relative = Path(name)
            mode = item.external_attr >> 16
            if (
                not name or "\\" in name or relative.is_absolute()
                or ".." in relative.parts or stat.S_ISLNK(mode)
            ):
                raise ValueError(f"Unsafe ZIP member: {name!r}")
            target = (output / relative).resolve()
            target.relative_to(output.resolve())
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination, length=1024 * 1024)
            extracted += 1
    return extracted


def acquire_corpus(
    spec: Mapping[str, object],
    root: Path,
    *,
    accept_terms: bool,
    extract: bool = True,
) -> dict[str, object]:
    if not accept_terms:
        raise ValueError("Acquisition requires explicit --accept-terms acknowledgement")
    corpus_id = str(spec["id"])
    destination = root / corpus_id
    if destination.exists():
        raise ValueError(f"Refusing to overwrite existing corpus directory: {destination}")
    destination.mkdir(parents=True)
    acquisition = spec["acquisition"]
    if not isinstance(acquisition, Mapping):
        raise ValueError(f"Invalid acquisition record for {corpus_id}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    kind = str(acquisition["kind"])
    receipt: dict[str, object] = {
        "protocol": "v5_psl_public_corpus_acquisition_v1",
        "corpus_id": corpus_id,
        "source_url": acquisition["url"],
        "license_status": spec["license"],
        "terms_acknowledged": True,
        "raw_redistribution_authorized_by_project": False,
    }
    try:
        if kind == "http_zip":
            archive = destination / "source.zip"
            _download(str(acquisition["url"]), archive)
            observed = sha256(archive)
            if observed != acquisition["sha256"]:
                raise ValueError(f"Downloaded SHA-256 differs for {corpus_id}")
            expected_size = int(acquisition.get("size_bytes", archive.stat().st_size))
            if archive.stat().st_size != expected_size:
                raise ValueError(f"Downloaded byte count differs for {corpus_id}")
            receipt.update({
                "archive_sha256": observed,
                "archive_size_bytes": archive.stat().st_size,
                "files_extracted": safe_extract_zip(archive, destination / "extracted") if extract else 0,
            })
        elif kind == "git":
            repository = destination / "repository"
            completed = subprocess.run(
                [
                    "git", "clone", "--filter=blob:none", "--no-checkout",
                    str(acquisition["url"]), str(repository),
                ],
                text=True, capture_output=True, check=False,
            )
            if completed.returncode:
                raise ValueError((completed.stderr or completed.stdout).strip())
            completed = subprocess.run(
                ["git", "checkout", "--detach", str(acquisition["commit"])],
                cwd=repository, text=True, capture_output=True, check=False,
            )
            if completed.returncode:
                raise ValueError((completed.stderr or completed.stdout).strip())
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, text=True,
                capture_output=True, check=True,
            ).stdout.strip()
            if head != acquisition["commit"]:
                raise ValueError(f"Pinned Git commit differs for {corpus_id}")
            verified_content = {}
            for relative, expected in dict(spec.get("content_hashes", {})).items():
                path = repository / relative
                if not path.is_file() or sha256(path) != expected:
                    raise ValueError(f"Pinned content hash differs for {corpus_id}: {relative}")
                verified_content[relative] = expected
            receipt.update({
                "git_commit": head,
                "content_hashes_verified": verified_content,
            })
        else:
            raise ValueError(f"Unsupported acquisition kind: {kind}")
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    receipt["receipt_sha256"] = canonical_json_sha256(receipt)
    (destination / "acquisition_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return receipt


def parse_java_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    pending = ""
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = pending + raw_line.strip()
        if line.endswith("\\"):
            pending = line[:-1]
            continue
        pending = ""
        if not line or line.startswith(("#", "!")):
            continue
        match = re.match(r"([^:=\s]+)\s*[:=]\s*(.*)", line)
        if match:
            result[match.group(1).strip()] = match.group(2).strip()
    return result


def _item_id(corpus_id: str, relative: str) -> str:
    return f"{corpus_id}_{hashlib.sha256(relative.encode('utf-8')).hexdigest()[:16]}"


def _contained_path(root: Path, relative: str) -> Path:
    if not relative or "\\" in relative or Path(relative).is_absolute():
        raise ValueError(f"Non-portable corpus path: {relative!r}")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Corpus path escapes source root: {relative}") from exc
    return path


def _sfl_inventory(corpus_id: str, source: Path, task_scope: str) -> list[dict[str, object]]:
    rows = []
    for workbook in sorted(
        path for path in source.rglob("*") if path.is_file() and path.suffix.lower() in WORKBOOK_SUFFIXES
    ):
        relative = workbook.relative_to(source).as_posix()
        sidecar = workbook.with_suffix(".properties")
        properties = parse_java_properties(sidecar) if sidecar.is_file() else {}
        faulty = [
            value for key, value in sorted(properties.items())
            if key.upper().lstrip("\ufeff").startswith("FAULTY_CELLS_")
        ]
        reasons = []
        if workbook.suffix.lower() != ".xlsx":
            reasons.append("requires_macro_free_xlsx_conversion")
        if not sidecar.is_file():
            reasons.append("missing_properties_label_sidecar")
        if not faulty:
            reasons.append("missing_faulty_cell_record")
        reasons.append("requires_manual_sheet_index_mapping_and_case_review")
        rows.append({
            "corpus_id": corpus_id,
            "item_id": _item_id(corpus_id, relative),
            "relative_path": relative,
            "sha256": sha256(workbook),
            "file_type": workbook.suffix.lower().lstrip("."),
            "task_scope": task_scope,
            "label_sidecar": sidecar.relative_to(source).as_posix() if sidecar.is_file() else "",
            "source_cells_raw": ";".join(faulty),
            "include_for_localization": "0",
            "exclusion_reason": ";".join(reasons),
        })
    return rows


def _enron_manifest_inventory(source: Path, task_scope: str) -> list[dict[str, object]] | None:
    manifest = source / "manifest.csv"
    if not manifest.is_file():
        return None
    with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    required = {"instance_id", "workbook", "source_cell", "include", "exclusion_reason"}
    if not source_rows or not required <= set(source_rows[0]):
        raise ValueError("Enron manifest fields are incomplete")
    identifiers = [row["instance_id"] for row in source_rows]
    if (
        len(identifiers) != len(set(identifiers))
        or any(not re.fullmatch(r"[A-Za-z0-9._-]+", value) for value in identifiers)
    ):
        raise ValueError("Enron manifest instance identifiers must be unique and portable")
    workbook_names = [row["workbook"] for row in source_rows]
    if len(workbook_names) != len(set(workbook_names)):
        raise ValueError("Enron manifest workbook paths must be unique")
    rows = []
    for row in source_rows:
        if row["include"] not in {"0", "1"}:
            raise ValueError(f"Enron manifest include must be 0 or 1: {row['instance_id']}")
        workbook = _contained_path(source, row["workbook"])
        is_xlsx = workbook.suffix.lower() == ".xlsx"
        included = row["include"] == "1" and workbook.is_file() and is_xlsx
        reason = row["exclusion_reason"]
        if not included and not reason:
            if row["include"] == "0":
                reason = "excluded_by_source_audit"
            elif not workbook.is_file():
                reason = "manifest_included_file_missing"
            else:
                reason = "requires_macro_free_xlsx_conversion"
        if included and not row["source_cell"].strip():
            raise ValueError(f"Included Enron error lacks a source cell: {row['instance_id']}")
        rows.append({
            "corpus_id": "enron_error",
            "item_id": row["instance_id"],
            "relative_path": row["workbook"],
            "sha256": sha256(workbook) if workbook.is_file() else "",
            "file_type": Path(row["workbook"]).suffix.lower().lstrip("."),
            "task_scope": task_scope,
            "label_sidecar": "manifest.csv",
            "source_cells_raw": row["source_cell"],
            "include_for_localization": "1" if included else "0",
            "exclusion_reason": reason,
        })
    return rows


def _forepbench_inventory(source: Path, task_scope: str) -> list[dict[str, object]]:
    candidates = list(source.rglob("FoRepBenchmarks.json"))
    if len(candidates) != 1:
        raise ValueError("FoRepBench adapter requires exactly one FoRepBenchmarks.json")
    path = candidates[0]
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("FoRepBenchmarks.json must contain a list")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    relative = path.relative_to(source).as_posix()
    return [
        {
            "corpus_id": "forepbench",
            "item_id": f"forepbench_{index + 1:04d}",
            "relative_path": f"{relative}#{index}",
            "sha256": sha256(path),
            "file_type": "json_record",
            "task_scope": task_scope,
            "label_sidecar": "embedded_correct_formula",
            "source_cells_raw": "",
            "include_for_localization": "0",
            "exclusion_reason": "repair_only_explicit_error_not_silent_source_localization",
        }
        for index, _row in enumerate(data)
    ]


def _spreadsheetbench_inventory(source: Path, task_scope: str) -> list[dict[str, object]]:
    rows = []
    candidates = sorted(
        path for path in source.rglob("*")
        if path.is_file() and path.suffix.lower() in WORKBOOK_SUFFIXES | {".gz"}
    )
    for path in candidates:
        relative = path.relative_to(source).as_posix()
        rows.append({
            "corpus_id": "spreadsheetbench",
            "item_id": _item_id("spreadsheetbench", relative),
            "relative_path": relative,
            "sha256": sha256(path),
            "file_type": "tar_gzip" if path.suffix.lower() == ".gz" else path.suffix.lower().lstrip("."),
            "task_scope": task_scope,
            "label_sidecar": "",
            "source_cells_raw": "",
            "include_for_localization": "0",
            "exclusion_reason": "parser_stress_only_no_root_cause_ground_truth",
        })
    return rows


def adapt_corpus(
    corpus_id: str,
    source: Path,
    spec: Mapping[str, object],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    if corpus_id not in CORPUS_IDS or spec.get("id") != corpus_id:
        raise ValueError(f"Unknown or mismatched corpus adapter: {corpus_id}")
    task_scope = str(spec["task_scope"])
    if corpus_id in {"modified_euses", "info1", "integer_corpus"}:
        rows = _sfl_inventory(corpus_id, source, task_scope)
    elif corpus_id == "enron_error":
        rows = _enron_manifest_inventory(source, task_scope)
        if rows is None:
            rows = _sfl_inventory(corpus_id, source, task_scope)
    elif corpus_id == "forepbench":
        rows = _forepbench_inventory(source, task_scope)
    else:
        rows = _spreadsheetbench_inventory(source, task_scope)
    if not rows:
        raise ValueError(f"Corpus adapter found no auditable items: {corpus_id}")
    audit = {
        "protocol": "v5_psl_public_corpus_inventory_v1",
        "corpus_id": corpus_id,
        "source_root": str(source.resolve()),
        "items": len(rows),
        "task_scope": task_scope,
        "included_for_localization": sum(row["include_for_localization"] == "1" for row in rows),
        "excluded_or_pending": sum(row["include_for_localization"] != "1" for row in rows),
        "license": spec["license"],
        "raw_data_redistributed": False,
        "inventory_sha256": canonical_json_sha256(rows),
    }
    return rows, audit


def write_inventory(
    output: Path,
    rows: Sequence[Mapping[str, object]],
    audit: Mapping[str, object],
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    with (output / "inventory.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    payload = dict(audit)
    payload["inventory_file_sha256"] = sha256(output / "inventory.csv")
    (output / "inventory_audit.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )


__all__ = [
    "CORPUS_IDS", "INVENTORY_FIELDS", "LOCALIZATION_CORPORA",
    "acquire_corpus", "adapt_corpus", "load_registry", "parse_java_properties",
    "safe_extract_zip", "write_inventory",
]
