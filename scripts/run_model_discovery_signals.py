"""Generate label-free model-discovery signal shards.

The profile CSV is used only to enumerate already-audited workbook inputs.  No
fault manifest or label column is passed to :func:`audit_workbook`.  A separate
scoring command is responsible for reading revealed labels after every shard
has been written and verified.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.model_discovery import (
    FORBIDDEN_LABEL_FIELDS,
    MODEL_VERSION,
    PROTOCOL,
    SignalAuditConfig,
    audit_workbook,
    validate_label_free_output,
)
from formulaguard.workbook import WorkbookModel

RUN_PROTOCOL = "formulaguard_model_discovery_signal_run_v1"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/workbook_profiles.csv"
DEFAULT_OUTPUT = ROOT / "results/model_discovery_signal_audit"
FORBIDDEN_PREFIXES = (
    "data/external/v5_psl/revealed_trial",
    "data/external/v5_psl/custodian",
    "data/external/v5_psl/final_blind",
)
ALLOWED_INPUT_ROOTS = (
    ROOT / "data",
    ROOT / "results/v5_psl_pressure_inputs",
)
REQUIRED_PROFILE_FIELDS = {
    "unit_id",
    "cohort",
    "structure_cluster_id",
    "path",
    "workbook_sha256",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def git_commit() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def safe_input_path(value: str) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"invalid profile path: {value!r}")
    candidate = (ROOT / value).resolve()
    allowed = tuple(path.resolve() for path in ALLOWED_INPUT_ROOTS)
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise ValueError(f"profile path is outside revealed-input allowlist: {value!r}")
    relative = candidate.relative_to(ROOT).as_posix()
    if any(relative == prefix or relative.startswith(prefix + "/") for prefix in FORBIDDEN_PREFIXES):
        raise ValueError(f"profile path is protected: {value!r}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def read_profiles(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("workbook profile CSV is empty")
    missing = REQUIRED_PROFILE_FIELDS - set(rows[0])
    if missing:
        raise ValueError(f"workbook profile CSV is missing fields: {sorted(missing)}")
    seen_units: set[str] = set()
    seen_paths: set[Path] = set()
    normalized: list[dict[str, str]] = []
    for row in rows:
        unit_id = str(row["unit_id"])
        if not unit_id or unit_id in seen_units:
            raise ValueError(f"duplicate or empty unit_id: {unit_id!r}")
        seen_units.add(unit_id)
        workbook = safe_input_path(str(row["path"]))
        if workbook in seen_paths:
            raise ValueError(f"workbook appears more than once: {workbook}")
        seen_paths.add(workbook)
        actual = sha256(workbook)
        if actual != str(row["workbook_sha256"]):
            raise ValueError(f"profile hash mismatch for {row['path']!r}")
        normalized.append({
            "unit_id": unit_id,
            "cohort": str(row["cohort"]),
            "structure_cluster_id": str(row["structure_cluster_id"]),
            "path": str(row["path"]),
            "workbook_sha256": actual,
        })
    return sorted(normalized, key=lambda row: row["unit_id"])


def shard_name(unit_id: str) -> str:
    return hashlib.sha256(unit_id.encode("utf-8")).hexdigest() + ".json"


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _worker(payload: tuple[str, str, str, str, Mapping[str, int]]) -> str:
    path_text, unit_id, expected_hash, output_text, config_values = payload
    path = safe_input_path(path_text)
    model = WorkbookModel.from_xlsx(path)
    config = SignalAuditConfig(**{
        key: int(value) for key, value in config_values.items()
    })
    audit = audit_workbook(model, config=config)
    errors = validate_label_free_output(audit)
    if errors:
        raise ValueError(f"label-free audit failed for {unit_id}: {'; '.join(errors)}")
    if audit.get("input_sha256") != expected_hash:
        raise ValueError(f"input hash changed while reading {unit_id}")
    record = {
        "protocol": RUN_PROTOCOL,
        "unit_id": unit_id,
        "workbook_sha256": expected_hash,
        "audit": audit,
    }
    path_out = Path(output_text) / "shards" / shard_name(unit_id)
    write_json_atomic(path_out, record)
    return unit_id


def _source_hashes() -> dict[str, str]:
    paths = (
        ROOT / "formulaguard/model_discovery.py",
        ROOT / "scripts/run_model_discovery_signals.py",
    )
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in paths}


def _combined_shards(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _validate_record(path: Path, expected: Mapping[str, str]) -> dict[str, object]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"cannot read shard {path.name}: {exc}") from exc
    if not isinstance(record, dict) or record.get("protocol") != RUN_PROTOCOL:
        raise ValueError(f"invalid shard protocol: {path.name}")
    unit_id = str(record.get("unit_id", ""))
    if unit_id != expected["unit_id"]:
        raise ValueError(f"shard unit mismatch: {path.name}")
    if record.get("workbook_sha256") != expected["workbook_sha256"]:
        raise ValueError(f"shard workbook hash mismatch: {path.name}")
    audit = record.get("audit")
    if not isinstance(audit, dict):
        raise ValueError(f"shard audit payload is malformed: {path.name}")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    errors = validate_label_free_output(audit)
    if errors:
        raise ValueError(f"invalid label-free audit {path.name}: {'; '.join(errors)}")
    if audit.get("input_sha256") != expected["workbook_sha256"]:
        raise ValueError(f"audit input hash mismatch: {path.name}")
    return record


def run(
    *,
    profiles_path: Path,
    output_dir: Path,
    workers: int,
    resume: bool,
    config: SignalAuditConfig,
) -> Path:
    profiles_path = profiles_path.resolve()
    if not profiles_path.is_file():
        raise FileNotFoundError(profiles_path)
    rows = read_profiles(profiles_path)
    output_dir = output_dir.resolve()
    shards_dir = output_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": RUN_PROTOCOL,
        "signal_protocol": PROTOCOL,
        "model_version": MODEL_VERSION,
        "git_commit": git_commit(),
        "profiles_path": profiles_path.relative_to(ROOT).as_posix() if profiles_path.is_relative_to(ROOT) else str(profiles_path),
        "profiles_sha256": sha256(profiles_path),
        "profile_count": len(rows),
        "configuration": config.as_dict(),
        "configuration_sha256": stable_hash(config.as_dict()),
        "source_hashes": _source_hashes(),
        "workers_requested": workers,
        "label_inputs_to_prediction": [],
        "forbidden_label_fields": list(FORBIDDEN_LABEL_FIELDS),
        "forbidden_input_prefixes": list(FORBIDDEN_PREFIXES),
    }
    metadata_path = output_dir / "metadata.json"
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        # Worker count is operational and may change on resume; all scientific
        # inputs must remain identical.
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("existing signal run metadata differs; use a new output directory")
        if not resume and (output_dir / "complete.json").exists():
            raise ValueError("signal run is complete; choose a new output directory")
    else:
        write_json_atomic(metadata_path, metadata)

    expected_by_unit = {row["unit_id"]: row for row in rows}
    pending = []
    for row in rows:
        target = shards_dir / shard_name(row["unit_id"])
        if target.exists():
            _validate_record(target, row)
        else:
            pending.append(row)
    if pending:
        worker_count = min(max(1, workers), len(pending))
        payloads = [
            (row["path"], row["unit_id"], row["workbook_sha256"], str(output_dir), config.as_dict())
            for row in pending
        ]
        print(
            f"model-discovery signal scheduling: workers={worker_count}; "
            f"pending={len(pending)}; resumed={len(rows) - len(pending)}",
            flush=True,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(futures)}] {future.result()}", flush=True)

    shard_paths = sorted(shards_dir.glob("*.json"), key=lambda path: path.name)
    if len(shard_paths) != len(rows):
        raise ValueError(f"expected {len(rows)} shards, found {len(shard_paths)}")
    for path in shard_paths:
        record = _validate_record(path, expected_by_unit[str(json.loads(path.read_text(encoding="utf-8")).get("unit_id", ""))])
        if not record:
            raise ValueError(f"empty record: {path.name}")
    completion = {
        "protocol": RUN_PROTOCOL,
        "complete": True,
        "profile_count": len(rows),
        "shard_count": len(shard_paths),
        "metadata_sha256": sha256(metadata_path),
        "profiles_sha256": sha256(profiles_path),
        "combined_shards_sha256": _combined_shards(shard_paths),
        "label_inputs_to_prediction": [],
        "forbidden_label_fields": list(FORBIDDEN_LABEL_FIELDS),
        "third_party_confirmation_files_read": [],
    }
    completion_path = output_dir / "complete.json"
    if completion_path.exists():
        existing = json.loads(completion_path.read_text(encoding="utf-8"))
        if existing != completion:
            raise ValueError("completed signal run would change; refusing overwrite")
    else:
        write_json_atomic(completion_path, completion)
    return completion_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate label-free model-discovery signal shards")
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    try:
        completion = run(
            profiles_path=args.profiles,
            output_dir=args.output,
            workers=args.workers,
            resume=args.resume,
            config=SignalAuditConfig(),
        )
    except Exception as exc:
        raise SystemExit(f"model-discovery signal run refused: {exc}") from exc
    print(completion)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
