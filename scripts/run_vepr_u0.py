#!/usr/bin/env python3
"""Run the preregistered VEPR U0 natural-edit availability audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.vdel import (
    COORDINATE_CONTAINMENT_THRESHOLD,
    COORDINATE_FORMULA_AGREEMENT_THRESHOLD,
    EXACT_CONTAINMENT_THRESHOLD,
    MIN_FORMULAS_FOR_OVERLAP,
    formula_signature,
    near_duplicate,
    profile_has_valid_formula_text,
)
from formulaguard.venron import inspect_formula_workbook
from formulaguard.vepr import (
    MAX_ADDITIONS_REMOVALS,
    MAX_CURRENT_FORMULAS,
    MAX_DIRECT_EDITS,
    MIN_CURRENT_FORMULAS,
    MIN_DIRECT_EDITS,
    MIN_STABLE_CANDIDATES,
    PROTOCOL,
    build_control,
    classify_ranking_transition,
    evaluate_u0_gates,
    stable_id,
    transition_is_control_candidate,
    transition_is_ranking_candidate,
    validate_private_manifest,
)
from scripts.run_vdel_u0 import (
    DEFAULT_COHORTS,
    EXPECTED_GROUPS_SHA256,
    EXPECTED_PROFILE_INDEX_SHA256,
    EXPECTED_PROFILE_RECEIPT_SHA256,
    EXPECTED_PUBLIC_WORKBOOKS,
    EXPECTED_TRANSITIONS_SHA256,
    EXPECTED_V0_RESULT_SHA256,
    _verify_vdel_inputs,
    load_public_units,
)

SCHEMA_VERSION = 1
PROFILE_PROTOCOL = "formulaguard_vhrl_venron_profile_v0"
DEFAULT_PROFILE = ROOT / "results/venron_profile_v0"
DEFAULT_V0 = ROOT / "results/venron_gate_v0"
DEFAULT_GROUPS = ROOT / "results/core_reset_b_phase0/scoring_groups.csv"
DEFAULT_OUTPUT = ROOT / "results/vepr_u0"
SOURCE_PATHS = (
    "formulaguard/vepr.py",
    "formulaguard/vdel.py",
    "formulaguard/venron.py",
    "scripts/run_vepr_u0.py",
    "scripts/run_vdel_u0.py",
    "research/V5_VEPR_PREREGISTRATION.md",
    "research/V5_VEPR_PREREGISTRATION.json",
    "research/V5_VEPR_AMENDMENT_1.md",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def stable_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def _git(command: Sequence[str]) -> str:
    return subprocess.run(
        ("git", *command),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def capture_source_state(*, allow_dirty: bool = False) -> dict[str, object]:
    status = tuple(
        line
        for line in _git(("status", "--porcelain", "--", *SOURCE_PATHS)).splitlines()
        if line
    )
    if status and not allow_dirty:
        raise ValueError("formal VEPR U0 requires clean tracked source files")
    return {
        "git_commit": _git(("rev-parse", "HEAD")),
        "source_sha256": {relative: sha256(ROOT / relative) for relative in SOURCE_PATHS},
        "source_status": list(status),
        "source_tree_dirty": bool(status),
        "formal_evidence": not status,
    }


def verify_source_state(expected: Mapping[str, object]) -> None:
    observed = capture_source_state(allow_dirty=True)
    for field in ("git_commit", "source_sha256", "source_status"):
        if observed[field] != expected[field]:
            raise ValueError("VEPR U0 source changed while the audit was running")


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise TypeError(f"VEPR JSON input is not an object: {path}")
    return payload


def _output_path(output: Path, *, inputs: Sequence[Path]) -> Path:
    resolved = (output if output.is_absolute() else ROOT / output).resolve()
    partial = resolved.with_name(resolved.name + ".partial")
    for candidate in (resolved, partial):
        if any(
            candidate == source.resolve()
            or candidate in source.resolve().parents
            or source.resolve() in candidate.parents
            for source in inputs
        ):
            raise ValueError("VEPR output path overlaps an input")
    if resolved.exists() or partial.exists():
        raise ValueError("VEPR output or partial output already exists")
    return resolved


def run(
    *,
    profile_dir: Path = DEFAULT_PROFILE,
    v0_dir: Path = DEFAULT_V0,
    groups_path: Path = DEFAULT_GROUPS,
    output: Path = DEFAULT_OUTPUT,
    root: Path = ROOT,
    cohorts: Sequence[str] = DEFAULT_COHORTS,
    allowed_roots: Sequence[Path] | None = None,
    expected_hashes: Mapping[str, str] | None = None,
    expected_groups_sha256: str = EXPECTED_GROUPS_SHA256,
    expected_public_workbooks: int = EXPECTED_PUBLIC_WORKBOOKS,
    allow_dirty: bool = False,
) -> Path:
    source_state = capture_source_state(allow_dirty=allow_dirty)
    profile_dir = profile_dir.resolve()
    v0_dir = v0_dir.resolve()
    groups_path = groups_path.resolve()
    profiles, transitions, input_hashes = _verify_vdel_inputs(
        profile_dir,
        v0_dir,
        expected_hashes=expected_hashes
        or {
            "profile_receipt": EXPECTED_PROFILE_RECEIPT_SHA256,
            "profile_index": EXPECTED_PROFILE_INDEX_SHA256,
            "v0_result": EXPECTED_V0_RESULT_SHA256,
            "transitions": EXPECTED_TRANSITIONS_SHA256,
        },
    )
    public_units = load_public_units(
        groups_path,
        root=root,
        cohorts=cohorts,
        allowed_roots=allowed_roots,
        expected_groups_sha256=expected_groups_sha256,
        expected_workbooks=expected_public_workbooks,
    )
    output = _output_path(
        output,
        inputs=(profile_dir, v0_dir, groups_path, *(Path(row["_path"]) for row in public_units)),
    )

    profile_by_group_order: dict[tuple[int, int], dict[str, object]] = {}
    for row in profiles:
        if not isinstance(row, dict):
            raise TypeError("VEPR profile-index row is malformed")
        key = (int(row["group_id"]), int(row["version_order"]))
        if key in profile_by_group_order:
            raise ValueError("VEPR profile-index group/order identity is duplicated")
        if row.get("status") not in {"parsed", "parsed_zero_formula"}:
            raise ValueError("VEPR profile index contains an unparsed workbook")
        profile_by_group_order[key] = row

    by_group: dict[int, list[int]] = defaultdict(list)
    for group_id, order in profile_by_group_order:
        by_group[group_id].append(order)
    group_order_verified = all(
        sorted(orders) == list(range(1, len(orders) + 1))
        for orders in by_group.values()
    )
    if len(profiles) != 7_294 or len(by_group) != 360 or not group_order_verified:
        raise ValueError("VEPR VEnron group/order inventory changed")

    @lru_cache(maxsize=96)
    def load_profile(group_id: int, order: int) -> dict[str, object]:
        index = profile_by_group_order[(group_id, order)]
        shard_name = str(index["profile_shard"])
        if Path(shard_name).name != shard_name or not shard_name.endswith(".json"):
            raise ValueError("VEPR profile shard path is unsafe")
        shard = profile_dir / "shards" / shard_name
        if sha256(shard) != index.get("profile_shard_sha256"):
            raise ValueError("VEPR profile shard changed after its receipt")
        payload = _load_json(shard)
        result = payload.get("result")
        if payload.get("protocol") != PROFILE_PROTOCOL or not isinstance(result, dict):
            raise ValueError("VEPR profile shard is malformed")
        if int(result.get("group_id", -1)) != group_id or int(
            result.get("version_order", -1)
        ) != order:
            raise ValueError("VEPR profile shard identity does not match its index")
        return result

    transition_keys: set[tuple[int, int, int]] = set()
    ranking_candidates: list[dict[str, object]] = []
    control_candidates: list[dict[str, object]] = []
    for row in transitions:
        if not isinstance(row, dict):
            raise TypeError("VEPR transition row is malformed")
        key = (int(row["group_id"]), int(row["previous_order"]), int(row["current_order"]))
        if key in transition_keys or key[2] != key[1] + 1:
            raise ValueError("VEPR transition identity is duplicated or non-adjacent")
        transition_keys.add(key)
        if transition_is_ranking_candidate(row):
            ranking_candidates.append(row)
        if transition_is_control_candidate(row):
            control_candidates.append(row)
    expected_transition_keys = {
        (group_id, order, order + 1)
        for group_id, orders in by_group.items()
        for order in range(1, len(orders))
    }
    if transition_keys != expected_transition_keys:
        raise ValueError("VEPR transition manifest does not cover every adjacent pair")

    invalid_profile_groups: set[int] = set()
    audited_profiles = 0
    for position, group_id in enumerate(sorted(by_group), 1):
        invalid = False
        for order in by_group[group_id]:
            audited_profiles += 1
            if not profile_has_valid_formula_text(load_profile(group_id, order)):
                invalid = True
        if invalid:
            invalid_profile_groups.add(group_id)
        if position % 20 == 0 or position == len(by_group):
            print(f"VEPR formula-text-audited groups {position}/{len(by_group)}", flush=True)

    public_signatures = []
    for unit in public_units:
        path = Path(unit["_path"])
        before_hash = sha256(path)
        signature = formula_signature(inspect_formula_workbook(path))
        if sha256(path) != before_hash:
            raise ValueError("VEPR public workbook changed while being profiled")
        public_signatures.append((unit["cohort"], signature))

    row_groups = {
        int(row["group_id"]) for row in [*ranking_candidates, *control_candidates]
    }
    overlap_audit_groups = sorted(row_groups - invalid_profile_groups)
    overlap_excluded_groups: dict[int, set[str]] = {}
    for position, group_id in enumerate(overlap_audit_groups, 1):
        matched_cohorts: set[str] = set()
        for order in by_group[group_id]:
            signature = formula_signature(load_profile(group_id, order))
            for cohort, public_signature in public_signatures:
                if near_duplicate(signature, public_signature):
                    matched_cohorts.add(str(cohort))
            if matched_cohorts:
                break
        if matched_cohorts:
            overlap_excluded_groups[group_id] = matched_cohorts
        if position % 20 == 0 or position == len(overlap_audit_groups):
            print(
                f"VEPR overlap-audited groups {position}/{len(overlap_audit_groups)}",
                flush=True,
            )

    ranking_rows: list[dict[str, object]] = []
    ranking_exclusions: Counter[str] = Counter()
    for position, transition in enumerate(ranking_candidates, 1):
        group_id = int(transition["group_id"])
        if group_id in invalid_profile_groups:
            ranking_exclusions["invalid_profile_group"] += 1
            continue
        if group_id in overlap_excluded_groups:
            ranking_exclusions["public_overlap_group"] += 1
            continue
        current_order = int(transition["previous_order"])
        ranking_rows.append(
            classify_ranking_transition(
                group_id=group_id,
                current_order=current_order,
                transition=transition,
                current=load_profile(group_id, current_order),
                future=load_profile(group_id, current_order + 1),
            )
        )
        if position % 100 == 0 or position == len(ranking_candidates):
            print(
                f"VEPR classified ranking transitions {position}/{len(ranking_candidates)}",
                flush=True,
            )

    control_rows: list[dict[str, object]] = []
    control_exclusions: Counter[str] = Counter()
    seen_control_layouts: set[tuple[int, str]] = set()
    for transition in sorted(
        control_candidates,
        key=lambda row: (int(row["group_id"]), int(row["previous_order"])),
    ):
        group_id = int(transition["group_id"])
        if group_id in invalid_profile_groups:
            control_exclusions["invalid_profile_group"] += 1
            continue
        if group_id in overlap_excluded_groups:
            control_exclusions["public_overlap_group"] += 1
            continue
        current_order = int(transition["previous_order"])
        row = build_control(
            group_id=group_id,
            current_order=current_order,
            transition=transition,
            current=load_profile(group_id, current_order),
        )
        identity = (group_id, str(row["layout_sha256"]))
        if identity in seen_control_layouts:
            control_exclusions["duplicate_group_layout"] += 1
            continue
        seen_control_layouts.add(identity)
        control_rows.append(row)

    ranking_rows.sort(key=lambda row: str(row["ranking_id"]))
    control_rows.sort(key=lambda row: str(row["control_id"]))
    private_manifest = {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "ranking_transitions": ranking_rows,
        "unchanged_controls": control_rows,
    }
    validate_private_manifest(private_manifest)

    ranking_group_hashes = {str(row["group_id_hash"]) for row in ranking_rows}
    control_group_hashes = {str(row["group_id_hash"]) for row in control_rows}
    overlap_hashes = {
        stable_id("vepr-group", group_id) for group_id in overlap_excluded_groups
    }
    invalid_hashes = {
        stable_id("vepr-group", group_id) for group_id in invalid_profile_groups
    }
    all_rows = [*ranking_rows, *control_rows]
    overlap_by_cohort = Counter(
        cohort
        for cohorts_for_group in overlap_excluded_groups.values()
        for cohort in cohorts_for_group
    )

    folds: dict[str, object] = {}
    for fold in range(5):
        fold_rankings = [row for row in ranking_rows if int(row["fold"]) == fold]
        fold_controls = [row for row in control_rows if int(row["fold"]) == fold]
        folds[str(fold)] = {
            "ranking_transitions": len(fold_rankings),
            "ranking_groups": len({str(row["group_id_hash"]) for row in fold_rankings}),
            "positive_rows": sum(int(row["positive_count"]) for row in fold_rankings),
            "stable_rows": sum(int(row["stable_count"]) for row in fold_rankings),
            "controls": len(fold_controls),
            "control_groups": len({str(row["group_id_hash"]) for row in fold_controls}),
        }

    positive_rows = sum(int(row["positive_count"]) for row in ranking_rows)
    stable_rows = sum(int(row["stable_count"]) for row in ranking_rows)
    summary = {
        "v0_profiles": len(profiles),
        "v0_groups": len(by_group),
        "v0_transitions": len(transitions),
        "potential_ranking_transitions": len(ranking_candidates),
        "potential_control_transitions": len(control_candidates),
        "candidate_groups_before_exclusion": len(row_groups),
        "public_workbooks_profiled": len(public_units),
        "profile_text_profiles_audited": audited_profiles,
        "profile_text_groups_audited": len(by_group),
        "invalid_profile_groups": len(invalid_profile_groups),
        "invalid_profile_group_hashes": sorted(invalid_hashes),
        "profile_text_validation_complete": audited_profiles == len(profiles),
        "invalid_profile_rows": sum(
            str(row["group_id_hash"]) in invalid_hashes for row in all_rows
        ),
        "overlap_candidate_groups_audited": len(overlap_audit_groups),
        "overlap_excluded_groups": len(overlap_excluded_groups),
        "overlap_excluded_group_hashes": sorted(overlap_hashes),
        "overlap_excluded_groups_by_public_cohort": dict(sorted(overlap_by_cohort.items())),
        "overlap_exclusion_complete": True,
        "overlap_excluded_rows": sum(
            str(row["group_id_hash"]) in overlap_hashes for row in all_rows
        ),
        "ranking_exclusions": dict(sorted(ranking_exclusions.items())),
        "control_exclusions": dict(sorted(control_exclusions.items())),
        "ranking_transitions": len(ranking_rows),
        "ranking_groups": len(ranking_group_hashes),
        "positive_rows": positive_rows,
        "stable_rows": stable_rows,
        "candidate_rows": positive_rows + stable_rows,
        "controls": len(control_rows),
        "control_groups": len(control_group_hashes),
        "folds": folds,
        "eligibility": {
            "minimum_current_formulas": MIN_CURRENT_FORMULAS,
            "maximum_current_formulas": MAX_CURRENT_FORMULAS,
            "minimum_direct_edits": MIN_DIRECT_EDITS,
            "maximum_direct_edits": MAX_DIRECT_EDITS,
            "maximum_additions_plus_removals": MAX_ADDITIONS_REMOVALS,
            "minimum_stable_candidates": MIN_STABLE_CANDIDATES,
        },
        "input_hashes_verified": True,
        "group_order_verified": group_order_verified,
        "candidate_accounting_verified": all(
            int(row["candidate_count"])
            == int(row["positive_count"]) + int(row["stable_count"])
            for row in ranking_rows
        ),
        "snapshot_before_label_verified": all(
            len(str(row["current_snapshot_sha256"])) == 64 for row in ranking_rows
        ),
        "fold_isolation_verified": all(
            len({int(row["fold"]) for row in all_rows if row["group_id_hash"] == group})
            == 1
            for group in ranking_group_hashes | control_group_hashes
        ),
        "cached_value_inputs": [],
        "constant_inputs": [],
        "cell_text_inputs": [],
        "email_inputs": [],
        "fault_label_inputs": [],
        "expected_output_inputs": [],
        "correct_workbook_inputs": [],
        "public_source_cell_inputs": [],
        "v4_inputs": [],
        "protected_data_inputs": [],
        "next_formula_state_used_for_labels": True,
        "raw_formula_text_exported": False,
        "public_paths_exported": False,
        "raw_sheet_or_address_exported": False,
    }
    gates = evaluate_u0_gates(summary)
    verify_source_state(source_state)

    partial = output.with_name(output.name + ".partial")
    partial.mkdir(parents=True)
    try:
        manifest_path = partial / "private_manifest.json"
        manifest_path.write_text(
            json.dumps(private_manifest, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        receipt = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            **source_state,
            "preregistration_commits": ["20fcf0b", "68535f7"],
            "profile_receipt_sha256": input_hashes["profile_receipt"],
            "profile_index_sha256": input_hashes["profile_index"],
            "v0_gate_result_sha256": input_hashes["v0_result"],
            "v0_transition_manifest_sha256": input_hashes["transitions"],
            "scoring_groups_sha256": expected_groups_sha256,
            "private_manifest_sha256": sha256(manifest_path),
            "private_record_set_sha256": stable_hash(private_manifest),
            "overlap_thresholds": {
                "minimum_formulas": MIN_FORMULAS_FOR_OVERLAP,
                "exact_containment": EXACT_CONTAINMENT_THRESHOLD,
                "coordinate_containment": COORDINATE_CONTAINMENT_THRESHOLD,
                "coordinate_formula_agreement": COORDINATE_FORMULA_AGREEMENT_THRESHOLD,
            },
            "summary": summary,
            "gates": gates,
            "single_run_gates_passed": all(gates.values()),
            "second_identical_run_required_for_u0_pass": True,
            "label_inputs": ["venron_immediate_next_formula_state"],
            "protected_data_inputs": [],
        }
        (partial / "u0_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        os.replace(partial, output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return output / "u0_receipt.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument("--v0", type=Path, default=DEFAULT_V0)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = run(
            profile_dir=args.profile,
            v0_dir=args.v0,
            groups_path=args.groups,
            output=args.output,
            allow_dirty=args.allow_dirty,
        )
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"VEPR U0 refused: {exc}") from exc
    print(f"VEPR U0 receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
