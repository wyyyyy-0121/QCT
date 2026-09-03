#!/usr/bin/env python3
"""Run the preregistered VDEL U0 longevity-availability audit."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
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
    PROTOCOL,
    classify_window,
    evaluate_u0_gates,
    formula_signature,
    near_duplicate,
    profile_has_valid_formula_text,
    stable_id,
    transition_is_candidate,
    validate_private_manifest,
)
from formulaguard.venron import inspect_formula_workbook

SCHEMA_VERSION = 1
PROFILE_PROTOCOL = "formulaguard_vhrl_venron_profile_v0"
V0_PROTOCOL = "formulaguard_vhrl_venron_gate_v0"
DEFAULT_PROFILE = ROOT / "results/venron_profile_v0"
DEFAULT_V0 = ROOT / "results/venron_gate_v0"
DEFAULT_GROUPS = ROOT / "results/core_reset_b_phase0/scoring_groups.csv"
DEFAULT_OUTPUT = ROOT / "results/vdel_u0"
DEFAULT_COHORTS = (
    "enron",
    "public:info1",
    "public:integer_corpus",
    "public:modified_euses",
)
EXPECTED_PROFILE_RECEIPT_SHA256 = (
    "54b24336912fa0ce4d50f55ef1897bef4e7ed40e1d7313a9a17fff6fcba924e0"
)
EXPECTED_PROFILE_INDEX_SHA256 = (
    "f337ad4448aec142bb529a90b514dc1f8fe8235aae29414b20750cd8ab7b0cc3"
)
EXPECTED_V0_RESULT_SHA256 = (
    "4743f0a1fb929afc6d98f4ebbfa3ac9b74022fa272c98f84da2f95f8b91b723e"
)
EXPECTED_TRANSITIONS_SHA256 = (
    "8a8ff6e13fdebc44f28d4abb509357c9475c3badf00a679d8bbf33456cc9a5ee"
)
EXPECTED_GROUPS_SHA256 = (
    "6f5384990f8758258dba4c556bc1f119e498d850ab37c2d092ccaa82f6e88be7"
)
EXPECTED_PUBLIC_WORKBOOKS = 96
FIELDS_READ = (
    "cohort",
    "workbook",
    "workbook_sha256",
    "structure_cluster_id",
)
PROVENANCE_FIELDS_ALLOWED_BUT_NOT_READ = (
    "cohort_instance_id",
    "instance_id",
    "provenance_group_id",
    "outer_group_id",
)
ALLOWED_FIELDS = frozenset((*FIELDS_READ, *PROVENANCE_FIELDS_ALLOWED_BUT_NOT_READ))
FORBIDDEN_PREFIXES = (
    "data/external/v5_psl/revealed_trial",
    "data/external/v5_psl/custodian",
    "data/external/v5_psl/final_blind",
)
SOURCE_PATHS = (
    "formulaguard/vdel.py",
    "formulaguard/venron.py",
    "scripts/run_vdel_u0.py",
    "research/V5_VDEL_PREREGISTRATION.md",
    "research/V5_VDEL_AMENDMENT_1.md",
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
        raise ValueError("formal VDEL U0 requires clean tracked source files")
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
            raise ValueError("VDEL U0 source changed while the audit was running")


def _assert_no_symlink_components(path: Path, *, anchor: Path) -> None:
    current = path.absolute()
    boundary = anchor.absolute()
    while True:
        if current.is_symlink():
            raise ValueError(f"symlinked input path is not allowed: {path}")
        if current == boundary or current == current.parent:
            return
        current = current.parent


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or root.resolve() in resolved.parents for root in roots
    )


def _is_protected(path: Path, *, root: Path) -> bool:
    try:
        relative = path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return False
    return any(
        relative == prefix or relative.startswith(prefix + "/")
        for prefix in FORBIDDEN_PREFIXES
    )


def load_public_units(
    groups_path: Path,
    *,
    root: Path = ROOT,
    cohorts: Sequence[str] = DEFAULT_COHORTS,
    allowed_roots: Sequence[Path] | None = None,
    expected_groups_sha256: str = EXPECTED_GROUPS_SHA256,
    expected_workbooks: int = EXPECTED_PUBLIC_WORKBOOKS,
) -> list[dict[str, str]]:
    lexical = groups_path if groups_path.is_absolute() else root / groups_path
    _assert_no_symlink_components(lexical, anchor=root)
    resolved_groups = lexical.resolve()
    if not resolved_groups.is_file() or resolved_groups.suffix.lower() != ".csv":
        raise ValueError("VDEL scoring groups must be an existing CSV")
    if not _inside(resolved_groups, (root / "results/core_reset_b_phase0",)):
        raise ValueError("VDEL scoring groups path is outside the fixed allowlist")
    if sha256(resolved_groups) != expected_groups_sha256:
        raise ValueError("VDEL scoring groups changed after preregistration")

    raw = resolved_groups.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("VDEL scoring groups must be UTF-8") from exc
    with io.StringIO(text, newline="") as handle:
        reader = csv.DictReader(handle)
        field_list = tuple(reader.fieldnames or ())
        fields = set(field_list)
        if len(fields) != len(field_list):
            raise ValueError("VDEL scoring groups contain duplicate fields")
        if set(FIELDS_READ) - fields or fields - ALLOWED_FIELDS:
            raise ValueError("VDEL scoring groups do not match the label-free field allowlist")
        selected = []
        cohort_set = set(cohorts)
        for row_number, row in enumerate(reader, 2):
            if any(field not in fields for field in row):
                raise ValueError(f"VDEL scoring-groups row {row_number} has extra columns")
            if row["cohort"] in cohort_set:
                selected.append({field: row[field] for field in FIELDS_READ})
    if {row["cohort"] for row in selected} != set(cohorts):
        raise ValueError("VDEL scoring groups do not contain every fixed cohort")

    roots = tuple(allowed_roots or (root / "data", root / "results/v5_psl_pressure_inputs"))
    by_hash: dict[str, dict[str, str]] = {}
    for row in selected:
        declared = row["workbook_sha256"].lower()
        relative = Path(row["workbook"])
        if (
            not re.fullmatch(r"[0-9a-f]{64}", declared)
            or relative.is_absolute()
            or "\\" in row["workbook"]
            or any(part in {"", ".", ".."} for part in relative.parts)
            or relative.suffix.lower() != ".xlsx"
        ):
            raise ValueError("VDEL public workbook identity is invalid")
        lexical_workbook = root / relative
        _assert_no_symlink_components(lexical_workbook, anchor=root)
        workbook = lexical_workbook.resolve()
        if not _inside(workbook, roots):
            raise ValueError("VDEL public workbook path is outside the allowlist")
        if _is_protected(workbook, root=root):
            raise ValueError("VDEL public workbook path is protected")
        if not workbook.is_file() or sha256(workbook) != declared:
            raise ValueError("VDEL public workbook hash does not match its declaration")
        candidate = {**row, "_path": str(workbook)}
        prior = by_hash.get(declared)
        if prior is None:
            by_hash[declared] = candidate
        elif any(prior[field] != candidate[field] for field in ("cohort", "structure_cluster_id")):
            raise ValueError("VDEL duplicate public workbook has conflicting metadata")
    units = sorted(by_hash.values(), key=lambda row: row["workbook_sha256"])
    if len(units) != expected_workbooks:
        raise ValueError(f"VDEL expected {expected_workbooks} public workbooks, got {len(units)}")
    return units


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise TypeError(f"VDEL JSON input is not an object: {path}")
    return payload


def _verify_vdel_inputs(
    profile_dir: Path,
    v0_dir: Path,
    *,
    expected_hashes: Mapping[str, str] | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, str]]:
    expected = dict(expected_hashes or {
        "profile_receipt": EXPECTED_PROFILE_RECEIPT_SHA256,
        "profile_index": EXPECTED_PROFILE_INDEX_SHA256,
        "v0_result": EXPECTED_V0_RESULT_SHA256,
        "transitions": EXPECTED_TRANSITIONS_SHA256,
    })
    paths = {
        "profile_receipt": profile_dir / "profile_receipt.json",
        "profile_index": profile_dir / "profile_index.json",
        "v0_result": v0_dir / "gate_result.json",
        "transitions": v0_dir / "transition_manifest.json",
    }
    observed = {name: sha256(path) for name, path in paths.items()}
    if observed != expected:
        raise ValueError("VDEL source artifact hashes changed after preregistration")
    receipt = _load_json(paths["profile_receipt"])
    index = _load_json(paths["profile_index"])
    gate = _load_json(paths["v0_result"])
    transitions_payload = _load_json(paths["transitions"])
    if (
        receipt.get("protocol") != PROFILE_PROTOCOL
        or receipt.get("complete") is not True
        or receipt.get("profile_index_sha256") != observed["profile_index"]
        or receipt.get("protected_data_inputs") != []
        or index.get("protocol") != PROFILE_PROTOCOL
        or gate.get("protocol") != V0_PROTOCOL
        or gate.get("passed") is not True
        or gate.get("transition_manifest_sha256") != observed["transitions"]
        or gate.get("protected_data_inputs") != []
        or transitions_payload.get("protocol") != V0_PROTOCOL
    ):
        raise ValueError("VDEL source artifact receipts are invalid")
    profiles = index.get("profiles")
    transitions = transitions_payload.get("transitions")
    if not isinstance(profiles, list) or not isinstance(transitions, list):
        raise TypeError("VDEL source manifests are malformed")
    return profiles, transitions, observed


def _output_path(output: Path, *, inputs: Sequence[Path]) -> Path:
    lexical = output if output.is_absolute() else ROOT / output
    _assert_no_symlink_components(lexical, anchor=ROOT)
    resolved = lexical.resolve()
    partial = resolved.with_name(resolved.name + ".partial")
    for candidate in (resolved, partial):
        if any(
            candidate == source.resolve()
            or candidate in source.resolve().parents
            or source.resolve() in candidate.parents
            for source in inputs
        ):
            raise ValueError("VDEL output path overlaps an input")
    if resolved.exists() or partial.exists():
        raise ValueError("VDEL output or partial output already exists")
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
        profile_dir, v0_dir, expected_hashes=expected_hashes
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
            raise TypeError("VDEL profile-index row is malformed")
        key = (int(row["group_id"]), int(row["version_order"]))
        if key in profile_by_group_order:
            raise ValueError("VDEL profile-index group/order identity is duplicated")
        if row.get("status") not in {"parsed", "parsed_zero_formula"}:
            raise ValueError("VDEL profile index contains an unparsed workbook")
        profile_by_group_order[key] = row
    by_group: dict[int, list[int]] = defaultdict(list)
    for group_id, order in profile_by_group_order:
        by_group[group_id].append(order)
    group_order_verified = all(
        sorted(orders) == list(range(1, len(orders) + 1))
        for orders in by_group.values()
    )
    if len(profiles) != 7_294 or len(by_group) != 360 or not group_order_verified:
        raise ValueError("VDEL VEnron group/order inventory changed")

    @lru_cache(maxsize=64)
    def load_profile(group_id: int, order: int) -> dict[str, object]:
        index = profile_by_group_order[(group_id, order)]
        shard_name = str(index["profile_shard"])
        if Path(shard_name).name != shard_name or not shard_name.endswith(".json"):
            raise ValueError("VDEL profile shard path is unsafe")
        shard = profile_dir / "shards" / shard_name
        if sha256(shard) != index.get("profile_shard_sha256"):
            raise ValueError("VDEL profile shard changed after its receipt")
        payload = _load_json(shard)
        result = payload.get("result")
        if payload.get("protocol") != PROFILE_PROTOCOL or not isinstance(result, dict):
            raise ValueError("VDEL profile shard is malformed")
        if int(result.get("group_id", -1)) != group_id or int(
            result.get("version_order", -1)
        ) != order:
            raise ValueError("VDEL profile shard identity does not match its index")
        return result

    public_signatures = []
    for unit in public_units:
        path = Path(unit["_path"])
        before_hash = sha256(path)
        signature = formula_signature(inspect_formula_workbook(path))
        if sha256(path) != before_hash:
            raise ValueError("VDEL public workbook changed while being profiled")
        public_signatures.append((unit["cohort"], signature))

    transition_keys: set[tuple[int, int, int]] = set()
    candidates: list[dict[str, object]] = []
    for row in transitions:
        if not isinstance(row, dict):
            raise TypeError("VDEL transition row is malformed")
        key = (int(row["group_id"]), int(row["previous_order"]), int(row["current_order"]))
        if key in transition_keys or key[2] != key[1] + 1:
            raise ValueError("VDEL transition identity is duplicated or non-adjacent")
        transition_keys.add(key)
        if transition_is_candidate(row) and (key[0], key[2] + 1) in profile_by_group_order:
            candidates.append(row)
    expected_transition_keys = {
        (group_id, order, order + 1)
        for group_id, orders in by_group.items()
        for order in range(1, len(orders))
    }
    if transition_keys != expected_transition_keys:
        raise ValueError("VDEL transition manifest does not cover every adjacent pair")

    candidate_groups = sorted({int(row["group_id"]) for row in candidates})
    invalid_profile_groups: set[int] = set()
    for position, group_id in enumerate(candidate_groups, 1):
        if any(
            not profile_has_valid_formula_text(load_profile(group_id, order))
            for order in by_group[group_id]
        ):
            invalid_profile_groups.add(group_id)
        if position % 20 == 0 or position == len(candidate_groups):
            print(
                f"VDEL formula-text-audited groups {position}/{len(candidate_groups)}",
                flush=True,
            )

    valid_candidate_groups = [
        group_id
        for group_id in candidate_groups
        if group_id not in invalid_profile_groups
    ]
    overlap_excluded_groups: dict[int, set[str]] = {}
    for position, group_id in enumerate(valid_candidate_groups, 1):
        matched_cohorts: set[str] = set()
        for order in by_group[group_id]:
            signature = formula_signature(load_profile(group_id, order))
            for cohort, public_signature in public_signatures:
                if near_duplicate(signature, public_signature):
                    matched_cohorts.add(cohort)
            if matched_cohorts:
                break
        if matched_cohorts:
            overlap_excluded_groups[group_id] = matched_cohorts
        if position % 20 == 0 or position == len(valid_candidate_groups):
            print(
                f"VDEL overlap-audited groups {position}/{len(valid_candidate_groups)}",
                flush=True,
            )

    ranking_windows: list[dict[str, object]] = []
    controls: list[dict[str, object]] = []
    classifications: Counter[str] = Counter()
    for position, transition in enumerate(candidates, 1):
        group_id = int(transition["group_id"])
        if group_id in invalid_profile_groups:
            classifications["excluded_invalid_profile_group"] += 1
            continue
        if group_id in overlap_excluded_groups:
            classifications["excluded_overlap_group"] += 1
            continue
        current_order = int(transition["current_order"])
        classification, row = classify_window(
            group_id=group_id,
            current_order=current_order,
            transition=transition,
            previous=load_profile(group_id, current_order - 1),
            current=load_profile(group_id, current_order),
            future=load_profile(group_id, current_order + 1),
        )
        classifications[classification] += 1
        if classification == "ranking_window":
            ranking_windows.append(row)
        elif classification == "no_reedit_control":
            controls.append(row)
        if position % 100 == 0 or position == len(candidates):
            print(f"VDEL classified transitions {position}/{len(candidates)}", flush=True)

    ranking_windows.sort(key=lambda row: str(row["window_id"]))
    controls.sort(key=lambda row: str(row["window_id"]))
    private_manifest = {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "ranking_windows": ranking_windows,
        "no_reedit_controls": controls,
    }
    validate_private_manifest(private_manifest)

    fold_groups: dict[int, set[str]] = defaultdict(set)
    for row in ranking_windows:
        fold_groups[int(row["fold"])].add(str(row["group_id_hash"]))
    ranking_group_hashes = {str(row["group_id_hash"]) for row in ranking_windows}
    control_group_hashes = {str(row["group_id_hash"]) for row in controls}
    positive_count = sum(int(row["positive_count"]) for row in ranking_windows)
    negative_count = sum(int(row["negative_count"]) for row in ranking_windows)
    candidate_count = sum(int(row["available_candidate_count"]) for row in ranking_windows)
    overlap_excluded_hashes = sorted(
        stable_id("vdel-group", group_id) for group_id in overlap_excluded_groups
    )
    invalid_profile_hashes = sorted(
        stable_id("vdel-group", group_id) for group_id in invalid_profile_groups
    )
    overlap_excluded_from_rows = sum(
        str(row["group_id_hash"]) in set(overlap_excluded_hashes)
        for row in [*ranking_windows, *controls]
    )
    invalid_profile_from_rows = sum(
        str(row["group_id_hash"]) in set(invalid_profile_hashes)
        for row in [*ranking_windows, *controls]
    )
    overlap_by_cohort = Counter(
        cohort
        for cohorts_for_group in overlap_excluded_groups.values()
        for cohort in cohorts_for_group
    )
    summary = {
        "v0_profiles": len(profiles),
        "v0_groups": len(by_group),
        "v0_transitions": len(transitions),
        "potential_delta_transitions": len(candidates),
        "potential_delta_groups": len(candidate_groups),
        "public_workbooks_profiled": len(public_units),
        "profile_text_groups_audited": len(candidate_groups),
        "invalid_profile_groups": len(invalid_profile_groups),
        "invalid_profile_group_hashes": invalid_profile_hashes,
        "profile_text_validation_complete": True,
        "invalid_profile_group_rows": invalid_profile_from_rows,
        "overlap_candidate_groups_audited": len(valid_candidate_groups),
        "overlap_excluded_groups": len(overlap_excluded_groups),
        "overlap_excluded_group_hashes": overlap_excluded_hashes,
        "overlap_excluded_groups_by_public_cohort": dict(sorted(overlap_by_cohort.items())),
        "overlap_exclusion_complete": True,
        "excluded_group_rows": overlap_excluded_from_rows,
        "classifications": dict(sorted(classifications.items())),
        "ranking_windows": len(ranking_windows),
        "ranking_window_groups": len(ranking_group_hashes),
        "ranking_candidates": candidate_count,
        "re_edited_candidates": positive_count,
        "stable_candidates": negative_count,
        "no_reedit_controls": len(controls),
        "no_reedit_control_groups": len(control_group_hashes),
        "folds": {
            str(fold): {
                "ranking_windows": sum(int(row["fold"]) == fold for row in ranking_windows),
                "groups": len(fold_groups[fold]),
            }
            for fold in range(5)
        },
        "input_hashes_verified": True,
        "group_order_verified": group_order_verified,
        "candidate_accounting_verified": (
            candidate_count == positive_count + negative_count
            and all(
                int(row["available_candidate_count"])
                == int(row["positive_count"]) + int(row["negative_count"])
                for row in ranking_windows
            )
        ),
        "fold_isolation_verified": all(
            len({int(row["fold"]) for row in ranking_windows if row["group_id_hash"] == group})
            == 1
            for group in ranking_group_hashes
        ),
        "cached_value_inputs": [],
        "constant_inputs": [],
        "email_inputs": [],
        "fault_label_inputs": [],
        "public_label_inputs": [],
        "answer_workbook_inputs": [],
        "v4_inputs": [],
        "protected_data_inputs": [],
        "future_formula_state_used_for_scoring": True,
        "raw_formula_text_exported": False,
        "public_paths_exported": False,
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
            "preregistration_commit": "c0029b5",
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
        raise SystemExit(f"VDEL U0 refused: {exc}") from exc
    print(f"VDEL U0 receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
