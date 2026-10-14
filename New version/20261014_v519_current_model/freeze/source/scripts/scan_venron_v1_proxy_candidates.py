#!/usr/bin/env python3
"""Scan frozen VEnron V1 candidates for errors and exact reversions."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath

from formulaguard.venron import stable_record_id
from formulaguard.venron_proxy import (
    direct_formula_edits,
    error_key_hash,
    error_key_set,
    exact_reversions,
    explicit_formula_errors,
)

ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_vhrl_venron_v1_scan_v1"
V0_PROTOCOL = "formulaguard_vhrl_venron_gate_v0"
PREPARE_PROTOCOL = "formulaguard_vhrl_venron_prepare_v0"
PROFILE_PROTOCOL = "formulaguard_vhrl_venron_profile_v0"
DEFAULT_PREPARE = ROOT / "results/venron_prepare_v0"
DEFAULT_PROFILE = ROOT / "results/venron_profile_v0"
DEFAULT_V0 = ROOT / "results/venron_gate_v0"
DEFAULT_CONVERTED = ROOT / "data/external/model_discovery/converted/venron_v0"
DEFAULT_OUTPUT = ROOT / "results/venron_v1_scan_v1"
MAX_WORKERS = 24


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
        raise ValueError("tracked worktree must be clean before VEnron V1 scan")
    commit = _git(("rev-parse", "HEAD")).stdout.strip()
    upstream = _git(
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ).stdout.strip()
    if _git(("merge-base", "--is-ancestor", commit, upstream), check=False).returncode:
        raise ValueError("VEnron V1 scan implementation commit has not been pushed")
    return commit


def _load_profile(profile_dir: Path, index: Mapping[str, object]) -> dict[str, object]:
    shard = profile_dir / "shards" / str(index["profile_shard"])
    if sha256(shard) != index.get("profile_shard_sha256"):
        raise ValueError("VEnron formula profile shard changed before V1 scan")
    payload = json.loads(shard.read_text(encoding="ascii"))
    if payload.get("protocol") != PROFILE_PROTOCOL or not isinstance(payload.get("result"), dict):
        raise ValueError("VEnron formula profile shard is malformed")
    return payload["result"]


def _error_worker(
    payload: tuple[dict[str, object], str, str]
) -> tuple[str, list[dict[str, str]], str]:
    index, profile_dir_text, converted_root_text = payload
    profile_dir = Path(profile_dir_text)
    converted_root = Path(converted_root_text)
    result = _load_profile(profile_dir, index)
    relative = PurePosixPath(str(result["converted_relative_path"]))
    converted = converted_root.joinpath(*relative.parts)
    if not converted.is_file() or sha256(converted) != result.get("converted_sha256"):
        raise ValueError("VEnron converted workbook changed before V1 scan")
    errors = explicit_formula_errors(converted, result)
    source = str(result["source_relative_path"])
    return source, errors, error_key_hash(errors)


def scan(
    *,
    prepare_dir: Path,
    profile_dir: Path,
    v0_dir: Path,
    converted_root: Path,
    output_dir: Path,
    workers: int,
) -> Path:
    prepare_dir = prepare_dir.resolve()
    profile_dir = profile_dir.resolve()
    v0_dir = v0_dir.resolve()
    converted_root = converted_root.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if output_dir.exists():
        raise ValueError("completed or partial VEnron V1 scan output already exists")
    commit = require_clean_pushed_worktree()

    version_manifest_path = prepare_dir / "version_manifest.json"
    prepare_receipt_path = prepare_dir / "prepare_receipt.json"
    profile_index_path = profile_dir / "profile_index.json"
    profile_receipt_path = profile_dir / "profile_receipt.json"
    transition_manifest_path = v0_dir / "transition_manifest.json"
    gate_result_path = v0_dir / "gate_result.json"
    versions_payload = json.loads(version_manifest_path.read_text(encoding="ascii"))
    prepare_receipt = json.loads(prepare_receipt_path.read_text(encoding="ascii"))
    index_payload = json.loads(profile_index_path.read_text(encoding="ascii"))
    profile_receipt = json.loads(profile_receipt_path.read_text(encoding="ascii"))
    transitions_payload = json.loads(transition_manifest_path.read_text(encoding="ascii"))
    gate_result = json.loads(gate_result_path.read_text(encoding="ascii"))
    if (
        prepare_receipt.get("protocol") != PREPARE_PROTOCOL
        or prepare_receipt.get("complete") is not True
        or prepare_receipt.get("protected_data_inputs") != []
        or prepare_receipt.get("version_manifest_sha256") != sha256(version_manifest_path)
        or profile_receipt.get("protocol") != PROFILE_PROTOCOL
        or profile_receipt.get("complete") is not True
        or profile_receipt.get("protected_data_inputs") != []
        or profile_receipt.get("profile_index_sha256") != sha256(profile_index_path)
        or gate_result.get("protocol") != V0_PROTOCOL
        or gate_result.get("passed") is not True
        or gate_result.get("protected_data_inputs") != []
        or gate_result.get("transition_manifest_sha256") != sha256(transition_manifest_path)
        or transitions_payload.get("protocol") != V0_PROTOCOL
    ):
        raise ValueError("VEnron V1 scan input evidence changed or did not pass V0")
    versions = versions_payload.get("versions")
    profiles = index_payload.get("profiles")
    transitions = transitions_payload.get("transitions")
    if not isinstance(versions, list) or not isinstance(profiles, list) or not isinstance(
        transitions, list
    ):
        raise ValueError("VEnron V1 scan manifests are malformed")  # noqa: TRY004 intentional compatibility or fallback boundary; preserve runtime behavior
    profile_by_source = {str(row["source_relative_path"]): row for row in profiles}
    versions_by_group_order = {
        (int(row["group_id"]), int(row["version_order"])): row for row in versions
    }
    candidates = [row for row in transitions if row.get("nonbulk_multi_direct") is True]
    if len(candidates) != 423:
        raise ValueError(f"frozen VEnron V1 candidate count changed: {len(candidates)}")

    endpoint_sources: set[str] = set()
    for candidate in candidates:
        group_id = int(candidate["group_id"])
        previous = versions_by_group_order[(group_id, int(candidate["previous_order"]))]
        current = versions_by_group_order[(group_id, int(candidate["current_order"]))]
        endpoint_sources.update((
            str(previous["source_relative_path"]),
            str(current["source_relative_path"]),
        ))
    payloads = [
        (profile_by_source[source], str(profile_dir), str(converted_root))
        for source in sorted(endpoint_sources)
    ]
    error_profiles: dict[str, dict[str, object]] = {}
    print(
        f"VEnron V1 explicit-error scan: workers={min(workers, len(payloads))}; "
        f"workbooks={len(payloads)}",
        flush=True,
    )
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_error_worker, payload) for payload in payloads]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            source, errors, key_hash = future.result()
            error_profiles[source] = {
                "source_relative_path": source,
                "explicit_errors": errors,
                "explicit_error_key_hash": key_hash,
            }
            if index % 100 == 0 or index == len(payloads):
                print(f"VEnron V1 error-profiled {index}/{len(payloads)}", flush=True)

    detailed: list[dict[str, object]] = []
    reversion_groups: set[int] = set()
    new_error_groups: set[int] = set()
    union_groups: set[int] = set()
    reversion_keys = 0
    for position, candidate in enumerate(candidates, 1):
        group_id = int(candidate["group_id"])
        previous_order = int(candidate["previous_order"])
        current_order = int(candidate["current_order"])
        previous_version = versions_by_group_order[(group_id, previous_order)]
        current_version = versions_by_group_order[(group_id, current_order)]
        previous_source = str(previous_version["source_relative_path"])
        current_source = str(current_version["source_relative_path"])
        previous_profile = _load_profile(profile_dir, profile_by_source[previous_source])
        current_profile = _load_profile(profile_dir, profile_by_source[current_source])
        edits = direct_formula_edits(previous_profile, current_profile)
        if len(edits) != int(candidate["direct_formula_text_changes"]):
            raise ValueError("VEnron V1 direct-edit identity differs from V0")
        future_profiles: list[dict[str, object]] = []
        for horizon in range(1, 4):
            future_version = versions_by_group_order.get((group_id, current_order + horizon))
            if future_version is None:
                break
            source = str(future_version["source_relative_path"])
            future_profiles.append(_load_profile(profile_dir, profile_by_source[source]))
        reversions = exact_reversions(previous_profile, current_profile, future_profiles)
        previous_errors = error_key_set(error_profiles[previous_source]["explicit_errors"])
        current_errors = error_key_set(error_profiles[current_source]["explicit_errors"])
        new_errors = sorted(current_errors - previous_errors)
        new_error_rows = [
            {"sheet": sheet, "address": address} for sheet, address in new_errors
        ]
        if reversions:
            reversion_groups.add(group_id)
            reversion_keys += len(reversions)
        if new_errors:
            new_error_groups.add(group_id)
        if reversions or new_errors:
            union_groups.add(group_id)
        detailed.append({
            "transition_id": candidate["transition_id"],
            "group_id": group_id,
            "previous_order": previous_order,
            "current_order": current_order,
            "previous_source": previous_source,
            "current_source": current_source,
            "direct_edit_count": len(edits),
            "direct_edits": edits,
            "formula_additions": candidate["formula_additions"],
            "formula_removals": candidate["formula_removals"],
            "current_formula_count": candidate["current_formula_count"],
            "current_formula_count_log2_bin": math.floor(
                math.log2(1 + int(candidate["current_formula_count"]))
            ),
            "previous_error_key_hash": error_profiles[previous_source][
                "explicit_error_key_hash"
            ],
            "current_error_key_hash": error_profiles[current_source][
                "explicit_error_key_hash"
            ],
            "new_explicit_errors": new_error_rows,
            "new_explicit_error_count": len(new_error_rows),
            "exact_reversions": reversions,
            "exact_reversion_count": len(reversions),
            "isolated_rollback_eligible": bool(new_errors) and 2 <= len(edits) <= 12,
            "joint_rollback_eligible": bool(new_errors) and 2 <= len(edits) <= 8,
        })
        if position % 50 == 0 or position == len(candidates):
            print(f"VEnron V1 candidates analyzed {position}/{len(candidates)}", flush=True)

    output_dir.mkdir(parents=True)
    candidate_path = output_dir / "candidate_manifest.json"
    write_json_atomic(candidate_path, {"protocol": PROTOCOL, "candidates": detailed})
    error_index = [
        {
            "source_id": stable_record_id(source),
            "explicit_error_count": len(row["explicit_errors"]),
            "explicit_error_key_hash": row["explicit_error_key_hash"],
        }
        for source, row in sorted(error_profiles.items())
    ]
    error_index_path = output_dir / "error_profile_index.json"
    write_json_atomic(error_index_path, {"protocol": PROTOCOL, "profiles": error_index})
    reversion_transitions = sum(bool(row["exact_reversions"]) for row in detailed)
    new_error_transitions = sum(bool(row["new_explicit_errors"]) for row in detailed)
    union_transitions = sum(
        bool(row["exact_reversions"] or row["new_explicit_errors"]) for row in detailed
    )
    receipt = {
        "protocol": PROTOCOL,
        "implementation_commit": commit,
        "prepare_receipt_sha256": sha256(prepare_receipt_path),
        "profile_receipt_sha256": sha256(profile_receipt_path),
        "v0_gate_result_sha256": sha256(gate_result_path),
        "v0_transition_manifest_sha256": sha256(transition_manifest_path),
        "candidate_manifest_sha256": sha256(candidate_path),
        "error_profile_index_sha256": sha256(error_index_path),
        "candidate_transitions": len(detailed),
        "error_profiled_workbooks": len(error_profiles),
        "new_error_transitions_before_rollback": new_error_transitions,
        "new_error_groups_before_rollback": len(new_error_groups),
        "isolated_rollback_eligible_transitions": sum(
            bool(row["isolated_rollback_eligible"]) for row in detailed
        ),
        "joint_rollback_eligible_transitions": sum(
            bool(row["joint_rollback_eligible"]) for row in detailed
        ),
        "exact_reversion_transitions": reversion_transitions,
        "exact_reversion_groups": len(reversion_groups),
        "exact_reversion_keys": reversion_keys,
        "union_screen_transitions": union_transitions,
        "union_screen_groups": len(union_groups),
        "rollback_labels_materialized": 0,
        "cached_non_error_values_exported": False,
        "constant_values_exported": False,
        "email_fields_exported": False,
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "complete": True,
    }
    receipt_path = output_dir / "scan_receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", type=Path, default=DEFAULT_PREPARE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--v0", type=Path, default=DEFAULT_V0)
    parser.add_argument("--converted", type=Path, default=DEFAULT_CONVERTED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    try:
        receipt = scan(
            prepare_dir=args.prepare,
            profile_dir=args.profile,
            v0_dir=args.v0,
            converted_root=args.converted,
            output_dir=args.output,
            workers=args.workers,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"VEnron V1 scan refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
