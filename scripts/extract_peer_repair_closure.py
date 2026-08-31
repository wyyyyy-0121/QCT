"""Extract label-free Peer Repair Closure features on public workbooks."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.model_discovery import validate_label_free_output  # noqa: E402
from formulaguard.peer_repair_closure import (  # noqa: E402
    CANDIDATE_POLICY,
    MODEL_VERSION,
    PROTOCOL,
    probe_repair_closure,
    validate_probe_output,
)
from formulaguard.workbook import WorkbookModel  # noqa: E402
from scripts.run_model_discovery_signals import (  # noqa: E402
    read_profiles,
    safe_input_path,
    sha256,
    shard_name,
    write_json_atomic,
)


RUN_PROTOCOL = "formulaguard_peer_repair_closure_run_v1"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_V4 = ROOT / "results/model_discovery_v4_baseline"
DEFAULT_SIGNALS = ROOT / "results/model_discovery_signal_audit_observed"
DEFAULT_OUTPUT = ROOT / "results/peer_repair_closure_v1"


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _relative(path: Path) -> str:
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else str(resolved)


def _reject_protected(path: Path) -> None:
    if "FormulaGuard_240_120" in path.resolve().parts:
        raise ValueError(f"protected path is forbidden for public closure extraction: {path}")


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _combined_shards(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _load_sources(
    directory: Path,
    profiles: Sequence[Mapping[str, str]],
    *,
    kind: str,
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    _reject_protected(directory)
    complete = _load_json(directory / "complete.json")
    if complete.get("complete") is not True:
        raise ValueError(f"incomplete {kind} source")
    if complete.get("label_inputs_to_prediction") != []:
        raise ValueError(f"label-contaminated {kind} source")
    if int(complete.get("profile_count", -1)) != len(profiles):
        raise ValueError(f"{kind} profile count differs")
    paths = sorted((directory / "shards").glob("*.json"), key=lambda path: path.name)
    if len(paths) != int(complete.get("shard_count", -1)):
        raise ValueError(f"{kind} shard count differs")
    if _combined_shards(paths) != complete.get("combined_shards_sha256"):
        raise ValueError(f"{kind} combined shard hash differs")
    expected = {str(row["unit_id"]): row for row in profiles}
    result: dict[str, dict[str, object]] = {}
    for path in paths:
        payload = _load_json(path)
        unit_id = str(payload.get("unit_id", ""))
        if unit_id not in expected or unit_id in result:
            raise ValueError(f"unexpected or duplicate {kind} unit: {unit_id!r}")
        row = expected[unit_id]
        if path.name != shard_name(unit_id):
            raise ValueError(f"unexpected {kind} shard name: {path.name}")
        if payload.get("workbook_sha256") != row["workbook_sha256"]:
            raise ValueError(f"{kind} workbook hash differs: {unit_id}")
        if kind == "peer signals":
            audit = payload.get("audit")
            if not isinstance(audit, dict):
                raise ValueError(f"peer audit is malformed: {unit_id}")
            errors = validate_label_free_output(audit)
            if errors:
                raise ValueError(f"peer audit is invalid for {unit_id}: {'; '.join(errors)}")
            if audit.get("input_sha256") != row["workbook_sha256"]:
                raise ValueError(f"peer audit input hash differs: {unit_id}")
        elif kind == "V4":
            ranking = payload.get("ranking")
            if not isinstance(ranking, list) or not ranking:
                raise ValueError(f"V4 ranking is malformed: {unit_id}")
            cells = [str(item.get("cell", "")) for item in ranking if isinstance(item, Mapping)]
            if len(cells) != len(ranking) or not all(cells) or len(cells) != len(set(cells)):
                raise ValueError(f"V4 formula inventory is malformed: {unit_id}")
            if payload.get("label_inputs") != []:
                raise ValueError(f"V4 shard consumed labels: {unit_id}")
        else:
            raise ValueError(f"unknown source kind: {kind}")
        result[unit_id] = payload
    if set(result) != set(expected):
        raise ValueError(f"{kind} unit inventory differs from profiles")
    return result, complete


def _worker(
    payload: tuple[Mapping[str, str], Sequence[str], Mapping[str, object], str],
) -> str:
    profile, v4_cells, source_audit, output_text = payload
    workbook = safe_input_path(str(profile["path"]))
    if sha256(workbook) != str(profile["workbook_sha256"]):
        raise ValueError(f"workbook changed while probing {profile['unit_id']}")
    model = WorkbookModel.from_xlsx(workbook)
    probe = probe_repair_closure(model, v4_cells, source_audit)
    errors = validate_probe_output(probe)
    if errors:
        raise ValueError(f"invalid repair-closure probe for {profile['unit_id']}: {'; '.join(errors)}")
    record: dict[str, object] = {
        "protocol": RUN_PROTOCOL,
        "unit_id": str(profile["unit_id"]),
        "workbook_sha256": str(profile["workbook_sha256"]),
        "source_audit_sha256": str(source_audit["audit_sha256"]),
        "probe": probe,
        "label_inputs": [],
        "protected_data_inputs": [],
    }
    target = Path(output_text) / "shards" / shard_name(str(profile["unit_id"]))
    write_json_atomic(target, record)
    return str(profile["unit_id"])


def _validate_record(
    path: Path,
    profile: Mapping[str, str],
    source_audit: Mapping[str, object],
) -> dict[str, object]:
    payload = _load_json(path)
    if payload.get("protocol") != RUN_PROTOCOL:
        raise ValueError(f"unexpected repair-closure run protocol: {path.name}")
    if payload.get("unit_id") != profile["unit_id"]:
        raise ValueError(f"repair-closure unit differs: {path.name}")
    if payload.get("workbook_sha256") != profile["workbook_sha256"]:
        raise ValueError(f"repair-closure workbook hash differs: {path.name}")
    if payload.get("source_audit_sha256") != source_audit.get("audit_sha256"):
        raise ValueError(f"repair-closure source audit differs: {path.name}")
    if payload.get("label_inputs") != [] or payload.get("protected_data_inputs") != []:
        raise ValueError(f"repair-closure shard crossed the data boundary: {path.name}")
    probe = payload.get("probe")
    if not isinstance(probe, dict):
        raise ValueError(f"repair-closure probe is malformed: {path.name}")
    errors = validate_probe_output(probe)
    if errors:
        raise ValueError(f"invalid repair-closure output {path.name}: {'; '.join(errors)}")
    return payload


def _source_hashes() -> dict[str, str]:
    paths = (
        ROOT / "formulaguard/model_discovery.py",
        ROOT / "formulaguard/peer_repair_closure.py",
        ROOT / "scripts/extract_peer_repair_closure.py",
    )
    return {path.relative_to(ROOT).as_posix(): sha256(path) for path in paths}


def run(
    *,
    profiles_path: Path,
    v4_dir: Path,
    signal_dir: Path,
    output_dir: Path,
    workers: int,
    resume: bool,
) -> Path:
    for path in (profiles_path, v4_dir, signal_dir, output_dir):
        _reject_protected(path)
    profiles_path = profiles_path.resolve()
    profiles = read_profiles(profiles_path)
    v4, v4_complete = _load_sources(v4_dir.resolve(), profiles, kind="V4")
    signals, signal_complete = _load_sources(signal_dir.resolve(), profiles, kind="peer signals")
    if v4_complete.get("profiles_sha256") != sha256(profiles_path):
        raise ValueError("V4 profile hash differs from requested profiles")
    if signal_complete.get("profiles_sha256") != sha256(profiles_path):
        raise ValueError("peer-signal profile hash differs from requested profiles")
    output_dir = output_dir.resolve()
    shards_dir = output_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    metadata: dict[str, object] = {
        "protocol": RUN_PROTOCOL,
        "probe_protocol": PROTOCOL,
        "model_version": MODEL_VERSION,
        "candidate_policy": CANDIDATE_POLICY,
        "git_commit": _git_commit(),
        "profiles_path": _relative(profiles_path),
        "profiles_sha256": sha256(profiles_path),
        "profile_count": len(profiles),
        "v4_path": _relative(v4_dir),
        "v4_combined_shards_sha256": v4_complete["combined_shards_sha256"],
        "signal_path": _relative(signal_dir),
        "signal_combined_shards_sha256": signal_complete["combined_shards_sha256"],
        "source_hashes": _source_hashes(),
        "workers_requested": workers,
        "label_inputs": [],
        "protected_data_inputs": [],
        "persisted_content_exclusions": [
            "cell_addresses",
            "formula_text",
            "fingerprints",
            "roles",
            "workbook_text",
            "workbook_values",
            "revealed_labels",
        ],
    }
    metadata_path = output_dir / "metadata.json"
    if metadata_path.exists():
        existing = _load_json(metadata_path)
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("existing repair-closure metadata differs; use a new output directory")
        if not resume and (output_dir / "complete.json").exists():
            raise ValueError("repair-closure extraction is complete; choose a new output directory")
    else:
        write_json_atomic(metadata_path, metadata)

    profiles_by_id = {str(row["unit_id"]): row for row in profiles}
    pending: list[Mapping[str, str]] = []
    for profile in profiles:
        unit_id = str(profile["unit_id"])
        target = shards_dir / shard_name(unit_id)
        audit = signals[unit_id]["audit"]
        if not isinstance(audit, dict):
            raise ValueError(f"peer audit is malformed: {unit_id}")
        if target.exists():
            _validate_record(target, profile, audit)
        else:
            pending.append(profile)
    if pending:
        worker_count = min(max(1, workers), len(pending))
        payloads = []
        for profile in pending:
            unit_id = str(profile["unit_id"])
            ranking = v4[unit_id]["ranking"]
            if not isinstance(ranking, list):
                raise ValueError(f"V4 ranking is malformed: {unit_id}")
            v4_cells = [str(row["cell"]) for row in ranking if isinstance(row, Mapping)]
            audit = signals[unit_id]["audit"]
            if not isinstance(audit, dict):
                raise ValueError(f"peer audit is malformed: {unit_id}")
            payloads.append((profile, v4_cells, audit, str(output_dir)))
        print(
            f"peer repair closure scheduling: workers={worker_count}; "
            f"pending={len(pending)}; resumed={len(profiles) - len(pending)}",
            flush=True,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                if index % 10 == 0 or index == len(futures):
                    print(f"peer repair closure workbooks {index}/{len(futures)}", flush=True)

    paths = sorted(shards_dir.glob("*.json"), key=lambda path: path.name)
    if len(paths) != len(profiles):
        raise ValueError(f"expected {len(profiles)} repair-closure shards, found {len(paths)}")
    records: list[dict[str, object]] = []
    for path in paths:
        payload = _load_json(path)
        unit_id = str(payload.get("unit_id", ""))
        if unit_id not in profiles_by_id:
            raise ValueError(f"unexpected repair-closure unit: {unit_id}")
        audit = signals[unit_id]["audit"]
        if not isinstance(audit, dict):
            raise ValueError(f"peer audit is malformed: {unit_id}")
        records.append(_validate_record(path, profiles_by_id[unit_id], audit))
    reasons = Counter(str(record["probe"]["selection_reason"]) for record in records)  # type: ignore[index]
    completion: dict[str, object] = {
        "protocol": RUN_PROTOCOL,
        "complete": True,
        "profile_count": len(profiles),
        "shard_count": len(paths),
        "metadata_sha256": sha256(metadata_path),
        "profiles_sha256": sha256(profiles_path),
        "combined_shards_sha256": _combined_shards(paths),
        "selected_candidates": sum(record["probe"]["candidate_selected"] is True for record in records),  # type: ignore[index]
        "repairs_executed": sum(record["probe"]["repair_executed"] is True for record in records),  # type: ignore[index]
        "closures_without_new_anomaly": sum(
            bool(record["probe"]["closure"]["repair_closes_without_new_anomaly"])  # type: ignore[index]
            for record in records
            if record["probe"]["closure"] is not None  # type: ignore[index]
        ),
        "selection_reasons": dict(sorted(reasons.items())),
        "label_inputs": [],
        "protected_data_inputs": [],
        "revealed_label_files_read": [],
    }
    completion_path = output_dir / "complete.json"
    if completion_path.exists():
        if _load_json(completion_path) != completion:
            raise ValueError("completed repair-closure extraction would change; refusing overwrite")
    else:
        write_json_atomic(completion_path, completion)
    return completion_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    if args.workers < 1:
        parser.error("--workers must be positive")
    try:
        completion = run(
            profiles_path=args.profiles,
            v4_dir=args.v4,
            signal_dir=args.signals,
            output_dir=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except Exception as exc:
        raise SystemExit(f"peer repair closure extraction refused: {exc}") from exc
    print(completion)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
