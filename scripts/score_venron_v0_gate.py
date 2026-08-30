#!/usr/bin/env python3
"""Score the frozen VEnron V0 resource gate from formula-only profiles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from formulaguard.venron import compare_formula_profiles, stable_record_id


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_vhrl_venron_gate_v0"
PREPARE_PROTOCOL = "formulaguard_vhrl_venron_prepare_v0"
PROFILE_PROTOCOL = "formulaguard_vhrl_venron_profile_v0"
DEFAULT_PREPARE = ROOT / "results/venron_prepare_v0"
DEFAULT_PROFILE = ROOT / "results/venron_profile_v0"
DEFAULT_OUTPUT = ROOT / "results/venron_gate_v0"


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
        ("git", *command), cwd=ROOT, check=check, capture_output=True, text=True
    )


def require_clean_pushed_worktree() -> str:
    if _git(("status", "--porcelain", "--untracked-files=no")).stdout.strip():
        raise ValueError("tracked worktree must be clean before VEnron V0 scoring")
    commit = _git(("rev-parse", "HEAD")).stdout.strip()
    upstream = _git(
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    ).stdout.strip()
    if _git(("merge-base", "--is-ancestor", commit, upstream), check=False).returncode:
        raise ValueError("VEnron scoring implementation commit has not been pushed")
    return commit


def evaluate_gates(summary: Mapping[str, object]) -> dict[str, bool]:
    return {
        "at_least_300_groups_and_6000_workbooks": (
            int(summary["evolution_groups"]) >= 300
            and int(summary["source_workbooks"]) >= 6_000
        ),
        "direct_changes_in_1000_transitions_across_150_groups": (
            int(summary["direct_change_transitions"]) >= 1_000
            and int(summary["direct_change_groups"]) >= 150
        ),
        "nonbulk_multi_direct_100_transitions_across_30_groups": (
            int(summary["nonbulk_multi_direct_transitions"]) >= 100
            and int(summary["nonbulk_multi_direct_groups"]) >= 30
        ),
        "parse_coverage_at_least_80_percent": float(summary["parse_coverage"]) >= 0.80,
        "change_categories_reported_separately": all(
            key in summary
            for key in (
                "single_direct_transitions",
                "multi_direct_transitions",
                "bulk_direct_rewrite_transitions",
                "bulk_add_remove_transitions",
                "address_only_formula_move_transitions",
                "formula_addition_transitions",
                "formula_removal_transitions",
                "no_formula_text_change_transitions",
                "ineligible_adjacent_transitions",
            )
        ),
        "zero_forbidden_inputs": (
            summary.get("fault_label_inputs") == []
            and summary.get("protected_data_inputs") == []
            and summary.get("cached_value_difference_inputs") == []
            and summary.get("v4_inputs") == []
        ),
    }


def score(*, prepare_dir: Path, profile_dir: Path, output_dir: Path) -> Path:
    prepare_dir = prepare_dir.resolve()
    profile_dir = profile_dir.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise ValueError("completed or partial VEnron V0 score output already exists")
    commit = require_clean_pushed_worktree()
    version_manifest_path = prepare_dir / "version_manifest.json"
    prepare_receipt_path = prepare_dir / "prepare_receipt.json"
    profile_index_path = profile_dir / "profile_index.json"
    profile_receipt_path = profile_dir / "profile_receipt.json"
    versions_payload = json.loads(version_manifest_path.read_text(encoding="ascii"))
    prepare_receipt = json.loads(prepare_receipt_path.read_text(encoding="ascii"))
    index_payload = json.loads(profile_index_path.read_text(encoding="ascii"))
    profile_receipt = json.loads(profile_receipt_path.read_text(encoding="ascii"))
    if (
        prepare_receipt.get("protocol") != PREPARE_PROTOCOL
        or prepare_receipt.get("complete") is not True
        or prepare_receipt.get("protected_data_inputs") != []
        or prepare_receipt.get("version_manifest_sha256") != sha256(version_manifest_path)
        or versions_payload.get("protocol") != PREPARE_PROTOCOL
        or profile_receipt.get("protocol") != PROFILE_PROTOCOL
        or profile_receipt.get("complete") is not True
        or profile_receipt.get("protected_data_inputs") != []
        or profile_receipt.get("profile_index_sha256") != sha256(profile_index_path)
        or index_payload.get("protocol") != PROFILE_PROTOCOL
    ):
        raise ValueError("VEnron V0 score input receipt or manifest changed")
    versions = versions_payload.get("versions")
    profiles = index_payload.get("profiles")
    if not isinstance(versions, list) or not isinstance(profiles, list):
        raise ValueError("VEnron V0 score manifests are malformed")
    profile_by_source = {str(row["source_relative_path"]): row for row in profiles}
    if len(profile_by_source) != len(versions):
        raise ValueError("VEnron profile/version identity accounting differs")

    groups: dict[int, list[dict[str, object]]] = defaultdict(list)
    for version in versions:
        groups[int(version["group_id"])].append(version)
    transitions: list[dict[str, object]] = []
    direct_groups: set[int] = set()
    nonbulk_groups: set[int] = set()
    counts: Counter[str] = Counter()
    for group_id in sorted(groups):
        ordered = sorted(groups[group_id], key=lambda row: int(row["version_order"]))
        for previous, current in zip(ordered, ordered[1:]):
            previous_index = profile_by_source[str(previous["source_relative_path"])]
            current_index = profile_by_source[str(current["source_relative_path"])]
            transition_id = stable_record_id(
                "venron-transition",
                group_id,
                previous["version_order"],
                current["version_order"],
            )
            base = {
                "transition_id": transition_id,
                "group_id": group_id,
                "previous_order": previous["version_order"],
                "current_order": current["version_order"],
            }
            if previous_index["status"] not in {"parsed", "parsed_zero_formula"} or current_index[
                "status"
            ] not in {"parsed", "parsed_zero_formula"}:
                counts["ineligible"] += 1
                transitions.append({**base, "eligible": False, "reason": "unparsed_endpoint"})
                continue
            previous_shard = profile_dir / "shards" / str(previous_index["profile_shard"])
            current_shard = profile_dir / "shards" / str(current_index["profile_shard"])
            if (
                sha256(previous_shard) != previous_index.get("profile_shard_sha256")
                or sha256(current_shard) != current_index.get("profile_shard_sha256")
            ):
                raise ValueError("VEnron formula profile shard changed after receipt")
            previous_result = json.loads(previous_shard.read_text(encoding="ascii"))["result"]
            current_result = json.loads(current_shard.read_text(encoding="ascii"))["result"]
            comparison = compare_formula_profiles(previous_result, current_result)
            transitions.append({**base, "eligible": True, **comparison})
            counts["eligible"] += 1
            for key in (
                "has_direct_formula_text_change",
                "single_direct",
                "multi_direct",
                "bulk_direct_rewrite",
                "bulk_add_remove",
                "address_only_formula_move",
                "no_formula_text_change",
                "nonbulk_multi_direct",
            ):
                if comparison[key]:
                    counts[key] += 1
            if int(comparison["formula_additions"]) > 0:
                counts["formula_addition"] += 1
            if int(comparison["formula_removals"]) > 0:
                counts["formula_removal"] += 1
            if comparison["has_direct_formula_text_change"]:
                direct_groups.add(group_id)
            if comparison["nonbulk_multi_direct"]:
                nonbulk_groups.add(group_id)

    summary = {
        "evolution_groups": len(groups),
        "source_workbooks": len(versions),
        "total_adjacent_transitions": len(versions) - len(groups),
        "eligible_adjacent_transitions": counts["eligible"],
        "ineligible_adjacent_transitions": counts["ineligible"],
        "direct_change_transitions": counts["has_direct_formula_text_change"],
        "direct_change_groups": len(direct_groups),
        "single_direct_transitions": counts["single_direct"],
        "multi_direct_transitions": counts["multi_direct"],
        "nonbulk_multi_direct_transitions": counts["nonbulk_multi_direct"],
        "nonbulk_multi_direct_groups": len(nonbulk_groups),
        "bulk_direct_rewrite_transitions": counts["bulk_direct_rewrite"],
        "bulk_add_remove_transitions": counts["bulk_add_remove"],
        "address_only_formula_move_transitions": counts["address_only_formula_move"],
        "formula_addition_transitions": counts["formula_addition"],
        "formula_removal_transitions": counts["formula_removal"],
        "no_formula_text_change_transitions": counts["no_formula_text_change"],
        "zero_formula_workbooks": int(profile_receipt.get("statuses", {}).get("parsed_zero_formula", 0)),
        "failed_workbooks": int(
            profile_receipt.get("statuses", {}).get("conversion_or_parse_failure", 0)
        ),
        "parse_coverage": profile_receipt["parse_coverage"],
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "cached_value_difference_inputs": [],
        "v4_inputs": [],
    }
    gates = evaluate_gates(summary)
    output_dir.mkdir(parents=True)
    transition_path = output_dir / "transition_manifest.json"
    _write_json(transition_path, {"protocol": PROTOCOL, "transitions": transitions})
    result = {
        "protocol": PROTOCOL,
        "implementation_commit": commit,
        "prepare_receipt_sha256": sha256(prepare_receipt_path),
        "profile_receipt_sha256": sha256(profile_receipt_path),
        "transition_manifest_sha256": sha256(transition_path),
        "summary": summary,
        "gates": gates,
        "passed": all(gates.values()),
        "protected_data_inputs": [],
        "complete": True,
    }
    result_path = output_dir / "gate_result.json"
    _write_json(result_path, result)
    return result_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", type=Path, default=DEFAULT_PREPARE)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        result = score(
            prepare_dir=args.prepare,
            profile_dir=args.profile,
            output_dir=args.output,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"VEnron V0 scoring refused: {exc}") from exc
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
