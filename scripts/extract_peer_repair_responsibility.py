"""Extract label-free output-coupled Peer repair responsibility features."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.peer_repair_responsibility import (  # noqa: E402
    ACTION_RULE,
    MODEL_VERSION,
    PROTOCOL,
    probe_repair_responsibility,
    validate_responsibility_output,
)
from formulaguard.workbook import WorkbookModel  # noqa: E402
from scripts.extract_peer_repair_closure import (  # noqa: E402
    DEFAULT_PROFILES,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    _combined_shards,
    _load_json,
    _load_sources,
    _reject_protected,
    _relative,
)
from scripts.run_model_discovery_signals import (  # noqa: E402
    read_profiles,
    safe_input_path,
    sha256,
    shard_name,
    write_json_atomic,
)


RUN_PROTOCOL = "formulaguard_peer_repair_responsibility_run_v1"
DEFAULT_OUTPUT = ROOT / "results/peer_repair_responsibility_v1"


def _git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _worker(
    payload: tuple[Mapping[str, str], Sequence[str], Mapping[str, object], str],
) -> str:
    profile, v4_cells, source_audit, output_text = payload
    workbook = safe_input_path(str(profile["path"]))
    if sha256(workbook) != str(profile["workbook_sha256"]):
        raise ValueError(f"workbook changed while probing {profile['unit_id']}")
    model = WorkbookModel.from_xlsx(workbook)
    probe = probe_repair_responsibility(model, v4_cells, source_audit)
    errors = validate_responsibility_output(probe)
    if errors:
        raise ValueError(f"invalid repair responsibility for {profile['unit_id']}: {'; '.join(errors)}")
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
        raise ValueError(f"unexpected repair-responsibility run protocol: {path.name}")
    if payload.get("unit_id") != profile["unit_id"]:
        raise ValueError(f"repair-responsibility unit differs: {path.name}")
    if payload.get("workbook_sha256") != profile["workbook_sha256"]:
        raise ValueError(f"repair-responsibility workbook hash differs: {path.name}")
    if payload.get("source_audit_sha256") != source_audit.get("audit_sha256"):
        raise ValueError(f"repair-responsibility source audit differs: {path.name}")
    if payload.get("label_inputs") != [] or payload.get("protected_data_inputs") != []:
        raise ValueError(f"repair-responsibility shard crossed the data boundary: {path.name}")
    probe = payload.get("probe")
    if not isinstance(probe, dict):
        raise ValueError(f"repair-responsibility probe is malformed: {path.name}")
    errors = validate_responsibility_output(probe)
    if errors:
        raise ValueError(f"invalid repair-responsibility output {path.name}: {'; '.join(errors)}")
    return payload


def _source_hashes() -> dict[str, str]:
    paths = (
        ROOT / "formulaguard/localize.py",
        ROOT / "formulaguard/workbook.py",
        ROOT / "formulaguard/peer_repair_responsibility.py",
        ROOT / "scripts/extract_peer_repair_responsibility.py",
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
        "action_rule": ACTION_RULE,
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
            raise ValueError("existing responsibility metadata differs; use a new output directory")
        if not resume and (output_dir / "complete.json").exists():
            raise ValueError("responsibility extraction is complete; choose a new output directory")
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
            audit = signals[unit_id]["audit"]
            if not isinstance(ranking, list) or not isinstance(audit, dict):
                raise ValueError(f"V4 or peer source is malformed: {unit_id}")
            v4_cells = [str(row["cell"]) for row in ranking if isinstance(row, Mapping)]
            payloads.append((profile, v4_cells, audit, str(output_dir)))
        print(
            f"peer repair responsibility scheduling: workers={worker_count}; "
            f"pending={len(pending)}; resumed={len(profiles) - len(pending)}",
            flush=True,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [executor.submit(_worker, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                future.result()
                if index % 10 == 0 or index == len(futures):
                    print(f"peer repair responsibility workbooks {index}/{len(futures)}", flush=True)

    paths = sorted(shards_dir.glob("*.json"), key=lambda path: path.name)
    if len(paths) != len(profiles):
        raise ValueError(f"expected {len(profiles)} responsibility shards, found {len(paths)}")
    records: list[dict[str, object]] = []
    for path in paths:
        payload = _load_json(path)
        unit_id = str(payload.get("unit_id", ""))
        if unit_id not in profiles_by_id:
            raise ValueError(f"unexpected responsibility unit: {unit_id}")
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
        "responsibilities_evaluated": sum(record["probe"]["responsibility_evaluated"] is True for record in records),  # type: ignore[index]
        "responsibility_passes": sum(
            bool(record["probe"]["responsibility"]["responsibility_pass"])  # type: ignore[index]
            for record in records
            if record["probe"]["responsibility"] is not None  # type: ignore[index]
        ),
        "selection_reasons": dict(sorted(reasons.items())),
        "label_inputs": [],
        "protected_data_inputs": [],
        "revealed_label_files_read": [],
    }
    completion_path = output_dir / "complete.json"
    if completion_path.exists():
        if _load_json(completion_path) != completion:
            raise ValueError("completed responsibility extraction would change; refusing overwrite")
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
        raise SystemExit(f"peer repair responsibility extraction refused: {exc}") from exc
    print(completion)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
