#!/usr/bin/env python3
"""Audit counterfactual behavior on the frozen public input-only corpus.

The injected edit and target are selected before any detector is evaluated.
The original formula is then used only as the known reverse edit for measuring
candidate recovery; neither formula text nor workbook values are serialized.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.a1 import parse_address
from formulaguard.behavioral_consistency import (
    BehavioralConsistencyConfig,
    audit_behavioral_consistency,
    rank_behavioral_candidates,
)
from formulaguard.candidate_pool import (
    AST_SOURCE,
    PEER_SOURCE,
    CandidatePoolConfig,
    build_candidate_pool,
)
from formulaguard.counterfactual_candidates import (
    NUMERIC_CONSTANT,
    OPERATOR_REPLACEMENT,
    RANGE_BOUNDARY,
    REFERENCE_OFFSET,
    CounterfactualCandidate,
    generate_counterfactual_candidates,
)
from formulaguard.counterfactual_response import (
    CounterfactualResponseConfig,
)
from formulaguard.formula import (
    Binary,
    FormulaSyntaxError,
    Func,
    Number,
    Range,
    Ref,
    Unary,
    parse_formula,
    render,
)
from formulaguard.localize import formula_anomaly_scores
from formulaguard.metamorphic_oracles import (
    MetamorphicOracleConfig,
    audit_metamorphic_oracles,
)
from formulaguard.workbook import CellKey, WorkbookModel

PROTOCOL = "formulaguard_counterfactual_behavior_input_only_audit_v2"
DRFV_MANIFEST_SHA256 = "0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed"
INTAKE_MANIFEST_SHA256 = "bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d"
EXPECTED_WORKBOOK_SPLITS = {"train": 421, "calibration": 95, "internal_test": 91}
EXPECTED_GROUP_SPLITS = {"train": 153, "calibration": 33, "internal_test": 33}
EXPECTED_WORKBOOKS = 607
EXPECTED_GROUPS = 219
MAX_WORKERS = 24
CANDIDATE_BUDGET = 64
REPAIR_POOL_CONFIG = CandidatePoolConfig(
    ast_budget=24,
    peer_budget=8,
    peer_radius=8,
    minimum_peer_votes=2,
)

BEHAVIOR_CONFIG = BehavioralConsistencyConfig(
    axis_radius=8,
    min_peers=3,
    max_peers=8,
    max_peer_coherence=0.35,
    minimum_excess=0.01,
    response_config=CounterfactualResponseConfig(
        relative_step=0.05,
        half_step_ratio=0.5,
        normalization_floor=1.0,
        minimum_step=1e-6,
        response_tolerance=1e-9,
        max_inputs=8,
        max_downstream=0,
    ),
)
ORACLE_CONFIG = MetamorphicOracleConfig(
    scale_factor=2.0,
    step_fraction=0.125,
    minimum_step=1.0,
    relative_tolerance=1e-9,
    absolute_tolerance=1e-9,
    max_input_cells=32,
    max_aggregate_cells=32,
    max_redundant_path_mismatches=1,
)

EDIT_KINDS = (
    OPERATOR_REPLACEMENT,
    REFERENCE_OFFSET,
    RANGE_BOUNDARY,
    NUMERIC_CONSTANT,
)
FORBIDDEN_INPUT_KEY = re.compile(
    r"(?:^|_)(?:fault|answer|v4|protected|labels?)(?:_|$)"
    r"|(?:^|_)(?:ground_truth|correct_formula|expected_formula|repair_formula)(?:_|$)",
    re.IGNORECASE,
)
FORBIDDEN_PATH_TEXT = re.compile(
    r"(?:^|[/_.-])(?:fault|answer|v4|protected|labels?)(?:[/_.-]|$)",
    re.IGNORECASE,
)
EXPECTED_DATA_ERRORS = (OSError, ValueError, KeyError, zipfile.BadZipFile, ET.ParseError)

DEFAULT_CORPUS_MANIFEST = ROOT / "results/drfv_corpus_v1/corpus_manifest.json"
DEFAULT_INTAKE_MANIFEST = ROOT / "results/drfv_spreadsheetbench_v1_intake/input_manifest.json"
DEFAULT_INPUT_ROOT = ROOT / "data/external/model_discovery/corpus/drfv_spreadsheetbench_v1_inputs"
DEFAULT_OUTPUT = ROOT / "results/counterfactual_behavior_input_only_audit.json"
AUDIT_SOURCE_PATHS = (
    Path(__file__).resolve(),
    ROOT / "formulaguard/behavioral_consistency.py",
    ROOT / "formulaguard/candidate_pool.py",
    ROOT / "formulaguard/counterfactual_response.py",
    ROOT / "formulaguard/counterfactual_candidates.py",
    ROOT / "formulaguard/metamorphic_oracles.py",
    ROOT / "formulaguard/localize.py",
    ROOT / "formulaguard/formula.py",
    ROOT / "formulaguard/workbook.py",
    ROOT / "formulaguard/a1.py",
)


class _FormulaCandidate(Protocol):
    formula: str


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def _read_input_json(path: Path) -> Mapping[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise TypeError("input-only manifest must be a JSON object")
    _reject_forbidden_fields(payload)
    return payload


def _reject_forbidden_fields(value: object, location: str = "root") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            if FORBIDDEN_INPUT_KEY.search(key_text):
                raise ValueError(f"forbidden label/protected field at {location}.{key_text}")
            _reject_forbidden_fields(child, f"{location}.{key_text}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden_fields(child, f"{location}[{index}]")


def _ensure_no_symlink_components(path: Path, label: str) -> None:
    absolute = path.absolute()
    cursor = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError(f"{label} contains a symlink component")


def _validate_input_relative_text(relative_text: str) -> None:
    if (
        not relative_text
        or "\\" in relative_text
        or "\0" in relative_text
        or FORBIDDEN_PATH_TEXT.search(relative_text)
        or not relative_text.lower().endswith("_input.xlsx")
    ):
        raise ValueError("path is not a public input-only workbook")


def _safe_input_path(root: Path, relative_text: str) -> Path:
    _validate_input_relative_text(relative_text)
    _ensure_no_symlink_components(root, "input root")
    resolved_root = root.resolve()
    unresolved = resolved_root / relative_text
    _ensure_no_symlink_components(unresolved, "input-only workbook")
    candidate = unresolved.resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("input-only workbook escapes source root") from exc
    if not candidate.is_file():
        raise ValueError("input-only workbook is missing")
    return candidate


def _check_cli_input_path(path: Path, label: str) -> None:
    if FORBIDDEN_PATH_TEXT.search(str(path)):
        raise ValueError(f"{label} path contains a forbidden input class")
    _ensure_no_symlink_components(path, label)


def _required_text(row: Mapping[str, object], key: str, label: str) -> str:
    value = row.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{label} {key} must be text")
    if not value:
        raise ValueError(f"{label} {key} must not be empty")
    return value


def _source_attestation(
    *,
    corpus_sha256: str,
    intake_sha256: str,
    workbook_id: str,
    source_sha256: str,
    relative_path: str,
    split: str,
    structure_group: str,
) -> str:
    return stable_hash(
        [
            "input-only-source-v1",
            corpus_sha256,
            intake_sha256,
            workbook_id,
            source_sha256,
            relative_path,
            split,
            structure_group,
        ]
    )


def load_group_sources(
    corpus_manifest: Path,
    intake_manifest: Path,
    input_root: Path,
    *,
    expected_corpus_sha256: str = DRFV_MANIFEST_SHA256,
    expected_intake_sha256: str = INTAKE_MANIFEST_SHA256,
    expected_workbooks: int = EXPECTED_WORKBOOKS,
    expected_groups: int = EXPECTED_GROUPS,
    expected_workbook_splits: Mapping[str, int] = EXPECTED_WORKBOOK_SPLITS,
    expected_group_splits: Mapping[str, int] = EXPECTED_GROUP_SPLITS,
) -> list[dict[str, object]]:
    """Validate the two frozen manifests and select one workbook per group."""

    for path, label in (
        (corpus_manifest, "corpus manifest"),
        (intake_manifest, "intake manifest"),
        (input_root, "input root"),
    ):
        _check_cli_input_path(path, label)
    if sha256_file(corpus_manifest) != expected_corpus_sha256:
        raise ValueError("DRFV corpus manifest hash mismatch")
    if sha256_file(intake_manifest) != expected_intake_sha256:
        raise ValueError("SpreadsheetBench input manifest hash mismatch")

    corpus = _read_input_json(corpus_manifest)
    intake = _read_input_json(intake_manifest)
    if corpus.get("protocol") != "formulaguard_drfv_corpus_build_v1":
        raise ValueError("unexpected DRFV corpus protocol")
    if intake.get("protocol") != "formulaguard_drfv_spreadsheetbench_v1_intake_v1":
        raise ValueError("unexpected SpreadsheetBench intake protocol")
    corpus_rows = corpus.get("workbooks")
    intake_rows = intake.get("workbooks")
    if not isinstance(corpus_rows, list) or not isinstance(intake_rows, list):
        raise TypeError("input-only manifests must contain workbook lists")

    intake_by_id: dict[str, Mapping[str, object]] = {}
    for row in intake_rows:
        if not isinstance(row, Mapping):
            raise TypeError("invalid intake workbook row")
        workbook_id = _required_text(row, "workbook_id", "intake workbook")
        relative_text = _required_text(row, "relative_path", "intake workbook")
        digest = _required_text(row, "sha256", "intake workbook")
        _validate_input_relative_text(relative_text)
        if FORBIDDEN_PATH_TEXT.search(workbook_id):
            raise ValueError("intake workbook id contains a forbidden input class")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid intake workbook hash")
        if workbook_id in intake_by_id:
            raise ValueError("duplicate intake workbook id")
        intake_by_id[workbook_id] = row

    retained = [
        row
        for row in corpus_rows
        if isinstance(row, Mapping)
        and row.get("status") == "eligible"
        and row.get("byte_representative") is True
        and row.get("excluded_known_overlap_component") is False
    ]
    if len(retained) != expected_workbooks:
        raise ValueError("retained input-only workbook count changed")

    workbook_splits: Counter[str] = Counter()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    group_splits: dict[str, set[str]] = defaultdict(set)
    seen_digests: set[str] = set()
    for row in retained:
        workbook_id = _required_text(row, "workbook_id", "corpus workbook")
        source = intake_by_id.get(workbook_id)
        if source is None:
            raise ValueError("retained workbook is absent from input-only intake")
        digest = _required_text(row, "workbook_sha256", "corpus workbook")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("invalid retained workbook hash")
        if source.get("sha256") != digest:
            raise ValueError("corpus workbook is not bound to input-only intake")
        if digest in seen_digests:
            raise ValueError("byte-identical retained workbook repeated")
        seen_digests.add(digest)
        split = _required_text(row, "split", "corpus workbook")
        group = _required_text(row, "template_group_id", "corpus workbook")
        if split not in expected_workbook_splits:
            raise ValueError("invalid retained split or structure group")
        path = _safe_input_path(
            input_root,
            _required_text(source, "relative_path", "intake workbook"),
        )
        relative_path = _required_text(source, "relative_path", "intake workbook")
        if sha256_file(path) != digest:
            raise ValueError("retained input-only workbook hash mismatch")
        workbook_splits[split] += 1
        group_splits[group].add(split)
        groups[group].append(
            {
                "workbook_id": workbook_id,
                "source_sha256": digest,
                "path": str(path),
                "relative_path": relative_path,
                "split": split,
                "structure_group": group,
                "corpus_manifest_sha256": expected_corpus_sha256,
                "intake_manifest_sha256": expected_intake_sha256,
                "input_only_attestation": _source_attestation(
                    corpus_sha256=expected_corpus_sha256,
                    intake_sha256=expected_intake_sha256,
                    workbook_id=workbook_id,
                    source_sha256=digest,
                    relative_path=relative_path,
                    split=split,
                    structure_group=group,
                ),
            }
        )

    if dict(workbook_splits) != dict(expected_workbook_splits):
        raise ValueError("input-only workbook split counts changed")
    if len(groups) != expected_groups or any(len(value) != 1 for value in group_splits.values()):
        raise ValueError("structure groups changed or cross splits")
    actual_group_splits = Counter(next(iter(group_splits[group])) for group in groups)
    if dict(actual_group_splits) != dict(expected_group_splits):
        raise ValueError("structure-group split counts changed")

    selected: list[dict[str, object]] = []
    for group, rows in groups.items():
        chosen = min(
            rows,
            key=lambda row: stable_hash(
                [group, row["source_sha256"], row["workbook_id"]]
            ),
        )
        selected.append(chosen)
    return sorted(selected, key=lambda row: stable_hash(row["structure_group"]))


def expected_edit_kind(structure_group: str) -> str:
    return EDIT_KINDS[int(stable_hash(structure_group)[:16], 16) % len(EDIT_KINDS)]


def _target_id(source_sha256: str, sheet_index: int, address: str) -> str:
    return "target:" + stable_hash([source_sha256, sheet_index, address.upper()])


def _candidate_id(target_id: str, candidate: CounterfactualCandidate) -> str:
    return "candidate:" + stable_hash([target_id, _formula_identity(candidate.formula)])


def _formula_identity(formula: str) -> str:
    """Canonical AST identity, insensitive to renderer-added parentheses."""

    return render(parse_formula(formula))


def _node_supports_edit_kind(node: object, edit_kind: str) -> bool:
    if edit_kind == NUMERIC_CONSTANT and isinstance(node, Number):
        return True
    if edit_kind == REFERENCE_OFFSET and isinstance(node, Ref):
        return True
    if edit_kind == RANGE_BOUNDARY and isinstance(node, Range):
        return True
    if edit_kind == OPERATOR_REPLACEMENT and isinstance(node, (Unary, Binary)):
        return True
    if isinstance(node, Unary):
        return _node_supports_edit_kind(node.value, edit_kind)
    if isinstance(node, Binary):
        return _node_supports_edit_kind(node.left, edit_kind) or _node_supports_edit_kind(
            node.right, edit_kind
        )
    if isinstance(node, Func):
        return any(_node_supports_edit_kind(argument, edit_kind) for argument in node.args)
    return False


def select_injection(
    model: WorkbookModel,
    source_sha256: str,
    edit_kind: str,
    *,
    candidate_budget: int = CANDIDATE_BUDGET,
) -> tuple[CellKey, str, CounterfactualCandidate, str] | None:
    """Select a target and edit solely by stable hashes and edit availability."""

    selected, _ = _select_injection(
        model,
        source_sha256,
        edit_kind,
        candidate_budget=candidate_budget,
    )
    return selected


def _select_injection(
    model: WorkbookModel,
    source_sha256: str,
    edit_kind: str,
    *,
    candidate_budget: int,
) -> tuple[tuple[CellKey, str, CounterfactualCandidate, str] | None, str]:
    """Return the first hash-ordered edit-available pair and a funnel reason."""

    if edit_kind not in EDIT_KINDS:
        raise ValueError("unknown edit kind")
    sheet_index = {sheet: index for index, sheet in enumerate(model.sheet_visibility)}
    targets = []
    for key in model.formula_cells:
        if not model.is_visible(key):
            continue
        try:
            node = model.ast(model.formulas[key])
        except (FormulaSyntaxError, ValueError, OverflowError):
            continue
        if _node_supports_edit_kind(node, edit_kind):
            targets.append(
                (_target_id(source_sha256, sheet_index.get(key[0], 0), key[1]), key)
            )
    for opaque_target, target in sorted(targets):
        candidates = sorted(
            [
            candidate
            for candidate in generate_counterfactual_candidates(
                model, target, budget=candidate_budget
            )
            if candidate.edit_kind == edit_kind
            ],
            key=lambda item: _candidate_id(opaque_target, item),
        )
        if not candidates:
            continue
        chosen = candidates[0]
        return (
            target,
            opaque_target,
            chosen,
            _candidate_id(opaque_target, chosen),
        ), "selected"
    return None, "expected_edit_kind_unavailable"


def _clone_with_formula(model: WorkbookModel, target: CellKey, formula: str) -> WorkbookModel:
    formulas = dict(model.formulas)
    formulas[target] = formula
    return WorkbookModel(
        model.cells,
        formulas,
        source="",
        cell_visibility=model.cell_visibility,
        number_formats=model.number_formats,
        sheet_visibility=model.sheet_visibility,
    )


def _local_behavior_model(
    model: WorkbookModel, target: CellKey, target_formula: str
) -> WorkbookModel:
    target_address = parse_address(target[1])
    formulas: dict[CellKey, str] = {}
    for key, formula in model.formulas.items():
        if key[0] != target[0]:
            continue
        address = parse_address(key[1])
        same_column = address.col == target_address.col and abs(address.row - target_address.row) <= 8
        same_row = address.row == target_address.row and abs(address.col - target_address.col) <= 8
        if same_column or same_row:
            formulas[key] = formula
    formulas[target] = target_formula
    return WorkbookModel(
        model.cells,
        formulas,
        source="",
        cell_visibility=model.cell_visibility,
        number_formats=model.number_formats,
        sheet_visibility=model.sheet_visibility,
    )


def _target_behavior(model: WorkbookModel, target: CellKey) -> Mapping[str, object]:
    return audit_behavioral_consistency(
        model,
        targets=[target],
        config=BEHAVIOR_CONFIG,
    )["records"][0]


def _oracle_target_summary(
    model: WorkbookModel, target: CellKey, formula: str
) -> dict[str, object]:
    # Cached upstream outputs remain ordinary cells in this target-local audit.
    local = WorkbookModel(
        model.cells,
        {target: formula},
        source="",
        cell_visibility=model.cell_visibility,
        number_formats=model.number_formats,
        sheet_visibility=model.sheet_visibility,
    )
    row = audit_metamorphic_oracles(local, ORACLE_CONFIG)["records"][0]
    return {
        "status": row["status"],
        "applicable_relations": int(row["applicable_relations"]),
        "relation_holds_count": int(row["relation_holds_count"]),
        "ambiguity_count": int(row["ambiguity_count"]),
        "violation_count": int(row["violation_count"]),
    }


def _behavior_top1(
    model: WorkbookModel,
    target: CellKey,
    candidates: Sequence[_FormulaCandidate],
) -> tuple[_FormulaCandidate | None, bool]:
    ranked = rank_behavioral_candidates(
        model,
        target,
        candidates,
        config=BEHAVIOR_CONFIG,
    )
    by_formula = {candidate.formula: candidate for candidate in candidates}
    rows = list(ranked["candidates"])
    rows.sort(
        key=lambda row: (
            not bool(row["applicable"]),
            -float(row["improvement"]) if row["improvement"] is not None else 0.0,
            float(row["candidate_score"]),
            stable_hash(_formula_identity(str(row["formula"]))),
        )
    )
    if not rows or not rows[0]["applicable"]:
        return None, False
    return by_formula[str(rows[0]["formula"])], True


def _formula_baseline_top1(
    model: WorkbookModel,
    target: CellKey,
    candidates: Sequence[_FormulaCandidate],
) -> _FormulaCandidate | None:
    ranked: list[tuple[float, str, _FormulaCandidate]] = []
    for candidate in candidates:
        formula = candidate.formula
        score = float(formula_anomaly_scores(model, {target: formula})[target])
        ranked.append((score, stable_hash(_formula_identity(formula)), candidate))
    return min(ranked, default=None, key=lambda item: (item[0], item[1]))[2] if ranked else None


def audit_source(source: Mapping[str, object]) -> dict[str, object]:
    """Run one pre-run-frozen group experiment and return only opaque evidence."""

    group = _required_text(source, "structure_group", "worker source")
    workbook_id = _required_text(source, "workbook_id", "worker source")
    source_sha256 = _required_text(source, "source_sha256", "worker source")
    relative_path = _required_text(source, "relative_path", "worker source")
    split = _required_text(source, "split", "worker source")
    corpus_sha256 = _required_text(
        source, "corpus_manifest_sha256", "worker source"
    )
    intake_sha256 = _required_text(
        source, "intake_manifest_sha256", "worker source"
    )
    attestation = _required_text(source, "input_only_attestation", "worker source")
    if attestation != _source_attestation(
        corpus_sha256=corpus_sha256,
        intake_sha256=intake_sha256,
        workbook_id=workbook_id,
        source_sha256=source_sha256,
        relative_path=relative_path,
        split=split,
        structure_group=group,
    ):
        raise ValueError("worker source lacks a valid input-only attestation")
    _validate_input_relative_text(relative_path)
    path = Path(_required_text(source, "path", "worker source"))
    _check_cli_input_path(path, "worker input workbook")
    if path.name != Path(relative_path).name or sha256_file(path) != source_sha256:
        raise ValueError("worker source is not the attested input-only workbook")

    edit_kind = expected_edit_kind(group)
    base = {
        "group_id": "group:" + stable_hash(group),
        "workbook_id": "workbook:" + stable_hash(workbook_id),
        "source_sha256": source_sha256,
        "split": split,
        "expected_edit_kind": edit_kind,
    }
    try:
        model = WorkbookModel.from_xlsx(path)
    except EXPECTED_DATA_ERRORS:
        return {**base, "status": "rejected", "rejection_reason": "workbook_load_error"}
    if not model.formula_cells:
        return {**base, "status": "rejected", "rejection_reason": "no_formula_targets"}

    try:
        injection, selection_reason = _select_injection(
            model,
            source_sha256,
            edit_kind,
            candidate_budget=CANDIDATE_BUDGET,
        )
    except EXPECTED_DATA_ERRORS:
        return {**base, "status": "rejected", "rejection_reason": "selection_error"}
    if injection is None:
        return {
            **base,
            "status": "rejected",
            "rejection_reason": selection_reason,
        }
    target, opaque_target, injected, injected_id = injection
    original = model.formulas[target]
    local_original = _local_behavior_model(model, target, original)
    mutant = _clone_with_formula(local_original, target, injected.formula)
    try:
        original_behavior = _target_behavior(local_original, target)
        mutant_behavior = _target_behavior(mutant, target)
        original_formula_score = float(formula_anomaly_scores(local_original)[target])
        mutant_formula_score = float(formula_anomaly_scores(mutant)[target])
        original_oracle = _oracle_target_summary(model, target, original)
        mutant_oracle = _oracle_target_summary(model, target, injected.formula)
        reverse_pool = build_candidate_pool(
            _clone_with_formula(model, target, injected.formula),
            target,
            config=REPAIR_POOL_CONFIG,
        )
        reverse = reverse_pool.candidates
        original_normalized = _formula_identity(original)
        reverse_original = [
            item for item in reverse if _formula_identity(item.formula) == original_normalized
        ]
        reverse_available = bool(reverse_original)
        reverse_original_sources = sorted(
            {
                source_name
                for item in reverse_original
                for source_name in item.sources
            }
        )
        behavior_choice, behavior_evaluable = _behavior_top1(mutant, target, reverse)
        formula_choice = _formula_baseline_top1(mutant, target, reverse)
    except EXPECTED_DATA_ERRORS:
        return {**base, "status": "rejected", "rejection_reason": "mechanism_evaluation_error"}

    original_eligible = original_behavior["status"] != "abstained"
    mutant_eligible = mutant_behavior["status"] != "abstained"
    pair_eligible = original_eligible and mutant_eligible
    behavior_exact = bool(
        reverse_available
        and behavior_choice is not None
        and _formula_identity(behavior_choice.formula) == original_normalized
    )
    formula_exact = bool(
        reverse_available
        and formula_choice is not None
        and _formula_identity(formula_choice.formula) == original_normalized
    )
    return {
        **base,
        "status": "evaluated",
        "rejection_reason": None,
        "target_id": opaque_target,
        "injected_candidate_id": injected_id,
        "reverse_candidate_count": len(reverse),
        "reverse_ast_candidates": reverse_pool.audit.ast_selected,
        "reverse_peer_consensus_available": reverse_pool.audit.peer_consensus_available,
        "reverse_peer_candidates": reverse_pool.audit.peer_selected,
        "reverse_original_available": reverse_available,
        "reverse_original_sources": reverse_original_sources,
        "original_behavior_eligible": original_eligible,
        "original_behavior_outlier": original_behavior["status"] == "behavioral_outlier",
        "original_behavior_score": round(float(original_behavior["score"]), 12),
        "mutant_behavior_eligible": mutant_eligible,
        "mutant_behavior_outlier": mutant_behavior["status"] == "behavioral_outlier",
        "mutant_behavior_score": round(float(mutant_behavior["score"]), 12),
        "behavior_pair_eligible": pair_eligible,
        "mutant_pairwise_score_increase": bool(
            pair_eligible
            and float(mutant_behavior["score"]) > float(original_behavior["score"])
        ),
        "original_formula_baseline_outlier": original_formula_score > 0.0,
        "original_formula_baseline_score": round(original_formula_score, 12),
        "mutant_formula_baseline_outlier": mutant_formula_score > 0.0,
        "mutant_formula_baseline_score": round(mutant_formula_score, 12),
        "mutant_formula_baseline_score_increase": mutant_formula_score
        > original_formula_score,
        "behavior_ranking_evaluable": behavior_evaluable,
        "behavior_exact_top1": behavior_exact,
        "formula_baseline_exact_top1": formula_exact,
        "behavior_only_win": behavior_exact and not formula_exact,
        "formula_only_win": formula_exact and not behavior_exact,
        "original_oracle": original_oracle,
        "mutant_oracle": mutant_oracle,
    }


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 12) if denominator else 0.0


def summarize(records: Sequence[Mapping[str, object]], total_groups: int) -> dict[str, object]:
    evaluated = [row for row in records if row.get("status") == "evaluated"]
    eligible = [
        row
        for row in evaluated
        if row.get("behavior_pair_eligible") is True
        and row.get("reverse_original_available") is True
        and row.get("behavior_ranking_evaluable") is True
    ]
    pairwise = [row for row in evaluated if row.get("behavior_pair_eligible") is True]
    reverse_available = [
        row for row in evaluated if row.get("reverse_original_available") is True
    ]
    reverse_source_counts = Counter(
        str(source_name)
        for row in reverse_available
        for source_name in row.get("reverse_original_sources", ())
        if source_name in {AST_SOURCE, PEER_SOURCE}
    )
    kind_counts = Counter(str(row["expected_edit_kind"]) for row in eligible)
    clean_outliers = sum(row.get("original_behavior_outlier") is True for row in pairwise)
    increases = sum(row.get("mutant_pairwise_score_increase") is True for row in pairwise)
    mutant_outliers = sum(row.get("mutant_behavior_outlier") is True for row in pairwise)
    behavior_hits = sum(row.get("behavior_exact_top1") is True for row in eligible)
    formula_hits = sum(
        row.get("formula_baseline_exact_top1") is True for row in eligible
    )
    behavior_only = sum(row.get("behavior_only_win") is True for row in eligible)
    formula_only = sum(row.get("formula_only_win") is True for row in eligible)
    formula_clean_outliers = sum(
        row.get("original_formula_baseline_outlier") is True for row in pairwise
    )
    formula_increases = sum(
        row.get("mutant_formula_baseline_score_increase") is True for row in pairwise
    )
    formula_mutant_outliers = sum(
        row.get("mutant_formula_baseline_outlier") is True for row in pairwise
    )
    behavior_rate = _rate(behavior_hits, len(eligible))
    formula_rate = _rate(formula_hits, len(eligible))
    return {
        "groups_selected": total_groups,
        "groups_evaluated": len(evaluated),
        "eligible_groups": len(eligible),
        "eligible_edit_kind_counts": dict(sorted(kind_counts.items())),
        "behavior_pairwise_groups": len(pairwise),
        "reverse_original_available_groups": len(reverse_available),
        "reverse_original_source_counts": dict(sorted(reverse_source_counts.items())),
        "top1_comparison_groups": len(eligible),
        "clean_behavior_outliers": clean_outliers,
        "clean_behavior_outlier_rate": _rate(clean_outliers, len(pairwise)),
        "mutant_pairwise_score_increases": increases,
        "mutant_pairwise_score_increase_rate": _rate(increases, len(pairwise)),
        "mutant_behavior_outliers": mutant_outliers,
        "mutant_behavior_outlier_rate": _rate(mutant_outliers, len(pairwise)),
        "behavior_exact_top1": behavior_hits,
        "behavior_exact_top1_rate": behavior_rate,
        "formula_baseline_exact_top1": formula_hits,
        "formula_baseline_exact_top1_rate": formula_rate,
        "formula_baseline_clean_outlier_rate": _rate(
            formula_clean_outliers, len(pairwise)
        ),
        "formula_baseline_mutant_score_increase_rate": _rate(
            formula_increases, len(pairwise)
        ),
        "formula_baseline_mutant_outlier_rate": _rate(
            formula_mutant_outliers, len(pairwise)
        ),
        "behavior_minus_formula_baseline_pp": round(100.0 * (behavior_rate - formula_rate), 12),
        "behavior_only_wins": behavior_only,
        "formula_only_wins": formula_only,
    }


def public_gates(summary: Mapping[str, object]) -> dict[str, bool]:
    kind_counts = summary.get("eligible_edit_kind_counts", {})
    qualifying_kinds = (
        sum(int(value) >= 15 for value in kind_counts.values())
        if isinstance(kind_counts, Mapping)
        else 0
    )
    complement = (
        float(summary["behavior_minus_formula_baseline_pp"]) >= 3.0
        or (
            int(summary["behavior_only_wins"]) >= 10
            and int(summary["formula_only_wins"]) <= 5
        )
    )
    return {
        "eligible_groups_at_least_80": int(summary["eligible_groups"]) >= 80,
        "at_least_3_edit_kinds_with_15_groups": qualifying_kinds >= 3,
        "clean_outlier_rate_at_most_10_percent": float(summary["clean_behavior_outlier_rate"]) <= 0.10,
        "mutant_pairwise_increase_at_least_65_percent": float(summary["mutant_pairwise_score_increase_rate"]) >= 0.65,
        "mutant_outlier_rate_at_least_50_percent": float(summary["mutant_behavior_outlier_rate"]) >= 0.50,
        "behavior_exact_top1_at_least_60_percent": float(summary["behavior_exact_top1_rate"]) >= 0.60,
        "formula_baseline_complementarity": complement,
    }


def selection_funnel(records: Sequence[Mapping[str, object]], total_groups: int) -> dict[str, object]:
    reasons = Counter(
        str(row.get("rejection_reason"))
        for row in records
        if row.get("status") == "rejected"
    )
    evaluated = [row for row in records if row.get("status") == "evaluated"]
    return {
        "structure_groups": total_groups,
        "workbooks_loaded": total_groups - reasons["workbook_load_error"],
        "formula_targets_present": total_groups
        - reasons["workbook_load_error"]
        - reasons["no_formula_targets"],
        "expected_edit_candidate_available": len(evaluated)
        + reasons["mechanism_evaluation_error"],
        "original_behavior_applicable": sum(
            row.get("original_behavior_eligible") is True for row in evaluated
        ),
        "mutant_behavior_applicable": sum(
            row.get("mutant_behavior_eligible") is True for row in evaluated
        ),
        "mechanisms_evaluated": len(evaluated),
        "behavior_pair_eligible": sum(
            row.get("behavior_pair_eligible") is True for row in evaluated
        ),
        "reverse_original_available": sum(
            row.get("reverse_original_available") is True for row in evaluated
        ),
        "behavior_ranking_evaluable": sum(
            row.get("behavior_ranking_evaluable") is True for row in evaluated
        ),
        "rejection_counts": dict(sorted(reasons.items())),
    }


def _assert_public_output(payload: object) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            lowered = str(key).lower()
            if lowered in {"formula", "cell_value", "raw_value", "workbook_path"}:
                raise ValueError("public output contains formula text, a cell value, or a path")
            _assert_public_output(value)
    elif isinstance(payload, list):
        for value in payload:
            _assert_public_output(value)
    elif isinstance(payload, str) and payload.lstrip().startswith("="):
        raise ValueError("public output contains formula text")


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    _assert_public_output(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="ascii") as handle:
            json.dump(payload, handle, sort_keys=True, indent=2, ensure_ascii=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _git_commit() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _source_hashes() -> dict[str, str]:
    return {
        str(path.relative_to(ROOT)): sha256_file(path) for path in AUDIT_SOURCE_PATHS
    }


def require_clean_audit_sources() -> None:
    relative_paths = [str(path.relative_to(ROOT)) for path in AUDIT_SOURCE_PATHS]
    completed = subprocess.run(
        (
            "git",
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            *relative_paths,
        ),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("full audit requires clean tracked audit source files")


def run_audit(
    *,
    corpus_manifest: Path,
    intake_manifest: Path,
    input_root: Path,
    output: Path,
    workers: int = MAX_WORKERS,
    max_groups: int | None = None,
) -> Mapping[str, object]:
    if isinstance(workers, bool) or not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    if max_groups is not None and (isinstance(max_groups, bool) or max_groups < 1):
        raise ValueError("max_groups must be a positive integer")
    if output.exists() or output.is_symlink():
        raise ValueError("audit output already exists")
    if max_groups is None:
        require_clean_audit_sources()
    initial_source_hashes = _source_hashes()
    initial_manifest_hashes = {
        "corpus_manifest_sha256": sha256_file(corpus_manifest),
        "intake_manifest_sha256": sha256_file(intake_manifest),
    }
    sources = load_group_sources(corpus_manifest, intake_manifest, input_root)
    selected = sources[:max_groups] if max_groups is not None else sources
    if workers == 1:
        records = [audit_source(source) for source in selected]
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            records = list(executor.map(audit_source, selected))
    records.sort(key=lambda row: str(row["group_id"]))
    final_source_hashes = _source_hashes()
    final_manifest_hashes = {
        "corpus_manifest_sha256": sha256_file(corpus_manifest),
        "intake_manifest_sha256": sha256_file(intake_manifest),
    }
    if final_source_hashes != initial_source_hashes:
        raise RuntimeError("audit source files changed during execution")
    if final_manifest_hashes != initial_manifest_hashes:
        raise RuntimeError("input manifests changed during execution")
    if any(
        sha256_file(Path(str(source["path"]))) != source["source_sha256"]
        for source in selected
    ):
        raise RuntimeError("selected input workbook changed during execution")
    summary = summarize(records, len(selected))
    gates = public_gates(summary)
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "input_only": True,
        "label_inputs": [],
        "answer_inputs": [],
        "v4_inputs": [],
        "protected_inputs": [],
        "selection_policy": {
            "one_workbook_per_structure_group": True,
            "edit_kind_assigned_by_group_hash": True,
            "target_selected_by_stable_hash": True,
            "injected_candidate_selected_by_stable_hash": True,
            "behavior_applicability_used_for_selection": False,
            "reverse_original_availability_used_for_selection": False,
            "detector_scores_used_for_injection_selection": False,
            "injection_candidate_budget": CANDIDATE_BUDGET,
            "repair_candidate_pool_is_label_free": True,
        },
        "frozen_config": {
            "behavioral_consistency": BEHAVIOR_CONFIG.as_dict(),
            "metamorphic_oracles": ORACLE_CONFIG.as_dict(),
            "injection_candidate_budget": CANDIDATE_BUDGET,
            "repair_candidate_pool": {
                "ast_budget": REPAIR_POOL_CONFIG.ast_budget,
                "peer_budget": REPAIR_POOL_CONFIG.peer_budget,
                "peer_radius": REPAIR_POOL_CONFIG.peer_radius,
                "minimum_peer_votes": REPAIR_POOL_CONFIG.minimum_peer_votes,
            },
        },
        "execution": {
            "workers": workers,
            "max_groups": max_groups,
            "smoke": max_groups is not None,
            "full_run_clean_source_gate_enforced": max_groups is None,
            "git_commit": _git_commit(),
        },
        "input_hashes": {
            **initial_manifest_hashes,
            "selected_workbook_set_sha256": stable_hash(
                sorted(str(source["source_sha256"]) for source in selected)
            ),
        },
        "source_hashes": initial_source_hashes,
        "frozen_expected_counts": {
            "workbooks": EXPECTED_WORKBOOKS,
            "structure_groups": EXPECTED_GROUPS,
            "workbook_splits": EXPECTED_WORKBOOK_SPLITS,
            "structure_group_splits": EXPECTED_GROUP_SPLITS,
        },
        "selection_funnel": selection_funnel(records, len(selected)),
        "summary": summary,
        "public_gates": gates,
        "all_public_gates_passed": all(gates.values()),
        "records": records,
    }
    write_json_atomic(output, payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS_MANIFEST)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--max-groups", type=int)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = run_audit(
        corpus_manifest=args.corpus_manifest,
        intake_manifest=args.intake_manifest,
        input_root=args.input_root,
        output=args.output,
        workers=args.workers,
        max_groups=args.max_groups,
    )
    print(json.dumps({"output": str(args.output), "summary": payload["summary"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
