#!/usr/bin/env python3
"""Run deterministic, label-free header-partition predictions."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.header_partition import analyze_header_partitions
from formulaguard.workbook import WorkbookModel

PROTOCOL = "formulaguard_header_partition_predictions_v2"
SCHEMA_VERSION = 2
DEFAULT_GROUPS = ROOT / "results/core_reset_b_phase0/scoring_groups.csv"
DEFAULT_OUTPUT = ROOT / "results/header_partition_predictions"
DEFAULT_COHORTS = (
    "enron",
    "public:info1",
    "public:integer_corpus",
    "public:modified_euses",
)
MAX_WORKERS = 24
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
    "formulaguard/a1.py",
    "formulaguard/formula.py",
    "formulaguard/header_partition.py",
    "formulaguard/workbook.py",
    "scripts/run_header_partition_predictions.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_hash(payload: object) -> str:
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def git_commit(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=root, text=True
    ).strip()


def _git_source_status(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--", *SOURCE_PATHS),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def capture_source_state(
    source_root: Path = ROOT,
    *,
    allow_dirty: bool = False,
) -> dict[str, object]:
    source_root = source_root.resolve()
    state = {
        "git_commit": git_commit(source_root),
        "source_sha256": {
            relative: sha256(source_root / relative) for relative in SOURCE_PATHS
        },
        "source_status": list(_git_source_status(source_root)),
    }
    dirty = bool(state["source_status"])
    if dirty and not allow_dirty:
        raise ValueError(
            "formal prediction run requires clean tracked source files; "
            "use allow_dirty only for non-formal development checks"
        )
    state["source_tree_dirty"] = dirty
    state["formal_evidence"] = not dirty
    return state


def verify_source_state(
    expected: Mapping[str, object], source_root: Path = ROOT
) -> None:
    observed = capture_source_state(source_root, allow_dirty=True)
    comparable = ("git_commit", "source_sha256", "source_status")
    if any(observed[key] != expected[key] for key in comparable):
        raise ValueError("prediction source changed while the scan was running")


def _assert_no_symlink_components(path: Path, *, anchor: Path) -> None:
    lexical = path.absolute()
    boundary = anchor.absolute()
    current = lexical
    while True:
        if current.is_symlink():
            raise ValueError(f"symlinked input path is not allowed: {path}")
        if current == boundary:
            return
        if current == current.parent:
            return
        current = current.parent


def _inside(path: Path, roots: Sequence[Path]) -> bool:
    resolved = path.resolve()
    return any(
        resolved == root.resolve() or root.resolve() in resolved.parents
        for root in roots
    )


def _is_protected(path: Path, *, root: Path) -> bool:
    resolved_root = root.resolve()
    resolved = path.resolve()
    try:
        normalized = resolved.relative_to(resolved_root).as_posix()
    except ValueError:
        return False
    return any(
        normalized == prefix or normalized.startswith(prefix + "/")
        for prefix in FORBIDDEN_PREFIXES
    )


def _read_groups_snapshot(
    groups_path: Path,
    *,
    root: Path,
    allowed_group_roots: Sequence[Path],
) -> tuple[Path, bytes]:
    lexical = groups_path if groups_path.is_absolute() else root / groups_path
    _assert_no_symlink_components(lexical, anchor=root)
    candidate = lexical.resolve()
    if candidate.suffix.lower() != ".csv":
        raise ValueError("scoring groups must be a .csv file")
    if not _inside(candidate, allowed_group_roots):
        raise ValueError("scoring groups path is outside the explicit allowlist")
    if _is_protected(candidate, root=root):
        raise ValueError("scoring groups path is protected")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate, candidate.read_bytes()


def _safe_workbook(
    relative: str,
    *,
    root: Path,
    allowed_roots: Sequence[Path],
) -> Path:
    relative_path = Path(relative)
    if (
        not relative
        or "\\" in relative
        or relative_path.is_absolute()
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise ValueError(f"invalid workbook path: {relative!r}")
    if relative_path.suffix.lower() != ".xlsx":
        raise ValueError(f"workbook path must end in .xlsx: {relative!r}")
    lexical = root / relative_path
    _assert_no_symlink_components(lexical, anchor=root)
    candidate = lexical.resolve()
    if not _inside(candidate, allowed_roots):
        raise ValueError(f"workbook path is outside the allowlist: {relative!r}")
    if _is_protected(candidate, root=root):
        raise ValueError(f"workbook path is protected: {relative!r}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def load_units(
    groups_path: Path,
    *,
    cohorts: Sequence[str] = DEFAULT_COHORTS,
    root: Path = ROOT,
    allowed_roots: Sequence[Path] | None = None,
    allowed_group_roots: Sequence[Path] | None = None,
    snapshot_root: Path | None = None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Read only label-free group fields and deduplicate observed workbooks."""

    selected_cohorts = tuple(dict.fromkeys(cohorts))
    if not selected_cohorts or any(not cohort for cohort in selected_cohorts):
        raise ValueError("at least one non-empty cohort is required")
    group_roots = tuple(
        allowed_group_roots or (root / "results/core_reset_b_phase0",)
    )
    safe_groups_path, groups_bytes = _read_groups_snapshot(
        groups_path,
        root=root,
        allowed_group_roots=group_roots,
    )
    try:
        groups_text = groups_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("scoring groups must be valid UTF-8 CSV") from exc
    with io.StringIO(groups_text, newline="") as handle:
        reader = csv.DictReader(handle)
        field_list = tuple(reader.fieldnames or ())
        fields = set(field_list)
        if len(field_list) != len(fields):
            raise ValueError("scoring groups contain duplicate field names")
        missing = set(FIELDS_READ) - fields
        unexpected = fields - ALLOWED_FIELDS
        if missing:
            raise ValueError(f"scoring groups missing fields: {sorted(missing)}")
        if unexpected:
            raise ValueError(
                "scoring groups unexpectedly contain undeclared fields "
                f"(including possible labels): {sorted(unexpected)}"
            )
        rows = []
        for row_number, row in enumerate(reader, start=2):
            extra_fields = [field for field in row if field not in fields]
            if extra_fields:
                raise ValueError(
                    f"scoring groups row {row_number} contains extra columns: "
                    f"{extra_fields!r}"
                )
            if row["cohort"] in selected_cohorts:
                rows.append({field: row[field] for field in FIELDS_READ})
    observed_cohorts = {row["cohort"] for row in rows}
    missing_cohorts = set(selected_cohorts) - observed_cohorts
    if missing_cohorts:
        raise ValueError(f"requested cohorts are absent: {sorted(missing_cohorts)}")
    if not rows:
        raise ValueError("no scoring-group rows were selected")

    roots = tuple(
        allowed_roots or (root / "data", root / "results/v5_psl_pressure_inputs")
    )
    if snapshot_root is not None:
        snapshot_root.mkdir(parents=True, exist_ok=False)
    by_hash: dict[str, dict[str, str]] = {}
    for row in rows:
        declared_hash = row["workbook_sha256"].lower()
        if not re.fullmatch(r"[0-9a-f]{64}", declared_hash):
            raise ValueError(f"invalid workbook hash for {row['workbook']!r}")
        path = _safe_workbook(row["workbook"], root=root, allowed_roots=roots)
        workbook_bytes = path.read_bytes()
        actual_hash = sha256_bytes(workbook_bytes)
        if actual_hash != declared_hash:
            raise ValueError(
                f"workbook hash mismatch for {row['workbook']!r}: "
                f"declared {declared_hash}, observed {actual_hash}"
            )
        candidate = {
            "unit_id": "observed-workbook:" + actual_hash,
            "cohort": row["cohort"],
            "structure_cluster_id": row["structure_cluster_id"],
            "workbook": path.relative_to(root.resolve()).as_posix(),
            "workbook_sha256": actual_hash,
        }
        if snapshot_root is not None:
            snapshot_path = snapshot_root / f"{actual_hash}.xlsx"
            if not snapshot_path.exists():
                with snapshot_path.open("xb") as handle:
                    handle.write(workbook_bytes)
            elif sha256(snapshot_path) != actual_hash:
                raise ValueError("conflicting bytes for a staged workbook snapshot")
            candidate["_snapshot_path"] = str(snapshot_path)
        existing = by_hash.get(actual_hash)
        if existing is None:
            by_hash[actual_hash] = candidate
            continue
        for field in ("cohort", "structure_cluster_id"):
            if existing[field] != candidate[field]:
                raise ValueError(
                    f"observed hash {actual_hash} has conflicting {field}"
                )
        existing["workbook"] = min(existing["workbook"], candidate["workbook"])

    units = sorted(by_hash.values(), key=lambda item: item["unit_id"])
    inventory = [
        {field: value for field, value in unit.items() if not field.startswith("_")}
        for unit in units
    ]
    audit = {
        "scoring_groups": safe_groups_path.relative_to(root.resolve()).as_posix()
        if root.resolve() in safe_groups_path.parents
        else safe_groups_path.as_posix(),
        "scoring_groups_sha256": sha256_bytes(groups_bytes),
        "fields_read_from_scoring_groups": list(FIELDS_READ),
        "strict_scoring_group_field_allowlist": sorted(ALLOWED_FIELDS),
        "selected_cohorts": list(selected_cohorts),
        "selected_identity_rows": len(rows),
        "unique_observed_workbooks": len(units),
        "input_inventory_sha256": stable_hash(inventory),
        "label_inputs": [],
        "protected_data_inputs": [],
    }
    return units, audit


def predict_unit(payload: tuple[Mapping[str, str], str]) -> dict[str, object]:
    unit, snapshot_text = payload
    snapshot = Path(snapshot_text)
    expected_hash = unit["workbook_sha256"]
    if sha256(snapshot) != expected_hash:
        raise ValueError("staged workbook hash changed before parsing")
    model = WorkbookModel.from_xlsx(snapshot)
    if sha256(snapshot) != expected_hash:
        raise ValueError("staged workbook hash changed while parsing")
    result = analyze_header_partitions(model)
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        **{key: value for key, value in unit.items() if not key.startswith("_")},
        "formula_count": len(model.formulas),
        "metadata_complete": model.header_partition_metadata_complete,
        "certificate_count": len(result.certificates),
        "observation_count": len(result.observations),
        "qualified_block_count": len(result.qualified_blocks),
        "abstain_reason": result.abstain_reason,
        "result": asdict(result),
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def build_summary(
    records: Sequence[Mapping[str, object]],
    *,
    input_audit: Mapping[str, object],
    workers: int,
    source_state: Mapping[str, object],
) -> dict[str, object]:
    block_reviews: list[dict[str, object]] = []
    by_cohort: dict[str, Counter[str]] = defaultdict(Counter)
    abstentions: Counter[str] = Counter()
    metadata_incomplete: list[str] = []
    multiple_blocks: list[str] = []
    for record in records:
        cohort = str(record["cohort"])
        by_cohort[cohort]["unique_observed_workbooks"] += 1
        reason = record.get("abstain_reason")
        abstentions[str(reason or "block_review_candidate")] += 1
        if record.get("metadata_complete") is not True:
            metadata_incomplete.append(str(record["workbook"]))
        if reason == "multiple_qualified_blocks":
            multiple_blocks.append(str(record["workbook"]))
        result = record["result"]
        if not isinstance(result, Mapping):
            raise TypeError("prediction result is malformed")
        blocks = result.get("qualified_blocks")
        if not isinstance(blocks, (list, tuple)):
            raise TypeError("qualified blocks are malformed")
        if reason is not None or not blocks:
            continue
        if len(blocks) != 1:
            raise ValueError("unambiguous review requires exactly one qualified block")
        block = blocks[0]
        if not isinstance(block, Mapping):
            raise TypeError("qualified block is malformed")
        if block.get("within_block_ranking_supported") is not False:
            raise ValueError("header partition does not support within-block ranking")
        if block.get("selection_basis") != "coordinate_canonicalization_only":
            raise ValueError("unexpected block selection semantics")
        certificate = block.get("certificate")
        if not isinstance(certificate, Mapping):
            raise TypeError("qualified-block certificate is malformed")
        cells = block.get("cells")
        if not isinstance(cells, (list, tuple)) or not cells:
            raise ValueError("qualified block must contain review cells")
        review_cells: list[dict[str, object]] = []
        disagreement_cells = 0
        for comparison in cells:
            if not isinstance(comparison, Mapping):
                raise TypeError("qualified-block comparison is malformed")
            actionable = comparison["actionable_schema_disagreement"]
            disagreement_cells += int(actionable is True)
            review_cells.append(
                {
                    "cell": comparison["target"],
                    "candidate_formula": comparison["candidate_formula"],
                    "edit_kind": comparison["edit_kind"],
                    "missing_columns": comparison["missing_columns"],
                    "extra_columns": comparison["extra_columns"],
                    "comparison_supported": comparison["comparison_supported"],
                    "observed_disagrees": comparison["observed_disagrees"],
                    "actionable_schema_disagreement": actionable,
                    "candidate_derived_without_observed_target": comparison[
                        "candidate_derived_without_observed_target"
                    ],
                    "observed_target_used_for_comparison": comparison[
                        "observed_target_used_for_comparison"
                    ],
                }
            )
        if disagreement_cells < 1:
            raise ValueError("qualified block has no actionable schema disagreement")
        by_cohort[cohort]["review_candidate_workbooks"] += 1
        by_cohort[cohort]["schema_disagreement_formula_cells"] += disagreement_cells
        by_cohort[cohort]["formula_cell_review_cost"] += len(review_cells)
        block_reviews.append(
            {
                "workbook": record["workbook"],
                "workbook_sha256": record["workbook_sha256"],
                "cohort": cohort,
                "sheet": certificate["sheet"],
                "block_row_start": certificate["row_start"],
                "block_row_end": certificate["row_end"],
                "block_formula_cells": len(review_cells),
                "schema_disagreement_formula_cells": disagreement_cells,
                "formula_cell_review_cost": len(review_cells),
                "schema_block_review_cost": 1,
                "review_cells": review_cells,
                "selection_basis": block["selection_basis"],
                "within_block_ranking_supported": False,
                "automatic_edit_supported": False,
                "candidate_identified": certificate["candidate_identified"],
                "candidate_derived_without_observed_target": certificate[
                    "candidate_derived_without_observed_target"
                ],
                "observed_target_used_for_comparison": True,
                "can_identify_formula_error": certificate[
                    "can_identify_formula_error"
                ],
            }
        )
    block_reviews.sort(key=lambda item: str(item["workbook_sha256"]))
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "complete": True,
        **dict(input_audit),
        **dict(source_state),
        "workers_requested": workers,
        "global": {
            "completed_workbooks": len(records),
            "action_workbooks": 0,
            "review_candidate_workbooks": len(block_reviews),
            "review_candidate_formula_cells": sum(
                int(item["schema_disagreement_formula_cells"])
                for item in block_reviews
            ),
            "formula_cell_review_cost": sum(
                int(item["formula_cell_review_cost"]) for item in block_reviews
            ),
            "certificate_workbooks": sum(
                int(record["certificate_count"]) > 0 for record in records
            ),
            "qualified_block_workbooks": sum(
                int(record["qualified_block_count"]) > 0 for record in records
            ),
            "metadata_incomplete_workbooks": len(metadata_incomplete),
            "abstain_reasons": dict(sorted(abstentions.items())),
        },
        "by_cohort": {
            cohort: dict(sorted(counts.items()))
            for cohort, counts in sorted(by_cohort.items())
        },
        "actions": [],
        "block_reviews": block_reviews,
        "anomalies": {
            "metadata_incomplete": sorted(metadata_incomplete),
            "multiple_qualified_blocks": sorted(multiple_blocks),
        },
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def validate_outputs(
    records: Sequence[Mapping[str, object]], summary: Mapping[str, object]
) -> None:
    if summary.get("protocol") != PROTOCOL or summary.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("summary protocol/schema mismatch")
    global_counts = summary.get("global")
    if not isinstance(global_counts, Mapping):
        raise TypeError("summary global counts are malformed")
    if global_counts.get("completed_workbooks") != len(records):
        raise ValueError("summary completion count does not match records")
    if global_counts.get("action_workbooks") != 0 or summary.get("actions") != []:
        raise ValueError("coordinate-only candidates cannot be emitted as actions")
    reviews = summary.get("block_reviews")
    if not isinstance(reviews, list):
        raise TypeError("summary block reviews are malformed")
    if global_counts.get("review_candidate_workbooks") != len(reviews):
        raise ValueError("summary review count does not match review blocks")
    for record in records:
        if record.get("protocol") != PROTOCOL or record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("prediction record protocol/schema mismatch")
        if record.get("label_inputs") != [] or record.get("protected_data_inputs") != []:
            raise ValueError("prediction record declares forbidden inputs")
    for review in reviews:
        if not isinstance(review, Mapping):
            raise TypeError("block review is malformed")
        if review.get("within_block_ranking_supported") is not False:
            raise ValueError("block review incorrectly claims a cell ranking")
        if review.get("automatic_edit_supported") is not False:
            raise ValueError("block review incorrectly claims an automatic edit")
        if review.get("can_identify_formula_error") is not False:
            raise ValueError("block review incorrectly claims confirmed error identity")
        cells = review.get("review_cells")
        if not isinstance(cells, list) or not cells:
            raise ValueError("block review has no review cells")
        actionable = 0
        for cell in cells:
            if not isinstance(cell, Mapping):
                raise TypeError("block review cell is malformed")
            if cell.get("candidate_derived_without_observed_target") is not True:
                raise ValueError("candidate derivation used observed target content")
            if cell.get("observed_target_used_for_comparison") is not True:
                raise ValueError("target comparison provenance is missing")
            actionable += int(cell.get("actionable_schema_disagreement") is True)
        if actionable != review.get("schema_disagreement_formula_cells"):
            raise ValueError("block disagreement count is inconsistent")
        if len(cells) != review.get("formula_cell_review_cost"):
            raise ValueError("block review cost is inconsistent")


def _paths_overlap(first: Path, second: Path) -> bool:
    first = first.resolve()
    second = second.resolve()
    return first == second or first in second.parents or second in first.parents


def validate_output_path(
    output: Path,
    *,
    root: Path,
    input_paths: Sequence[Path],
) -> Path:
    lexical = output if output.is_absolute() else root / output
    _assert_no_symlink_components(lexical, anchor=root)
    resolved = lexical.resolve()
    partial = resolved.with_name(resolved.name + ".partial")
    if any(_paths_overlap(resolved, path) for path in input_paths):
        raise ValueError("output path overlaps a prediction input")
    if any(_paths_overlap(partial, path) for path in input_paths):
        raise ValueError("partial output path overlaps a prediction input")
    return resolved


def write_predictions(
    output: Path,
    records: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> Path:
    validate_outputs(records, summary)
    output = output.resolve()
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise ValueError("output or partial output already exists")
    partial.mkdir(parents=True)
    try:
        records_path = partial / "predictions.jsonl"
        with records_path.open("w", encoding="ascii", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
        summary_payload = dict(summary)
        summary_payload["predictions_sha256"] = sha256(records_path)
        summary_payload["prediction_records"] = len(records)
        summary_path = partial / "scan_summary.json"
        summary_path.write_text(
            json.dumps(summary_payload, ensure_ascii=True, indent=2, sort_keys=True)
            + "\n",
            encoding="ascii",
        )
        receipt = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            "formal_evidence": summary["formal_evidence"],
            "git_commit": summary["git_commit"],
            "source_sha256": summary["source_sha256"],
            "predictions_sha256": sha256(records_path),
            "scan_summary_sha256": sha256(summary_path),
            "record_set_sha256": stable_hash(records),
            "label_inputs": [],
            "protected_data_inputs": [],
        }
        (partial / "completion_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        os.replace(partial, output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return output / "completion_receipt.json"


def run(
    *,
    groups: Path,
    output: Path,
    cohorts: Sequence[str],
    workers: int,
    root: Path = ROOT,
    allowed_roots: Sequence[Path] | None = None,
    allowed_group_roots: Sequence[Path] | None = None,
    source_root: Path = ROOT,
    allow_dirty: bool = False,
) -> Path:
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    source_state = capture_source_state(source_root, allow_dirty=allow_dirty)
    with tempfile.TemporaryDirectory(prefix="formulaguard-header-partition-") as temp:
        units, input_audit = load_units(
            groups,
            cohorts=cohorts,
            root=root,
            allowed_roots=allowed_roots,
            allowed_group_roots=allowed_group_roots,
            snapshot_root=Path(temp) / "workbooks",
        )
        input_paths = [groups.resolve()]
        input_paths.extend(root / unit["workbook"] for unit in units)
        safe_output = validate_output_path(
            output,
            root=root,
            input_paths=input_paths,
        )
        payloads = [
            (
                {key: value for key, value in unit.items() if not key.startswith("_")},
                unit["_snapshot_path"],
            )
            for unit in units
        ]
        worker_count = min(workers, len(payloads))
        print(
            f"Header-partition scan: workers={worker_count}; workbooks={len(payloads)}",
            flush=True,
        )
        if worker_count == 1:
            records = [predict_unit(payload) for payload in payloads]
        else:
            records = []
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=worker_count
            ) as executor:
                futures = [executor.submit(predict_unit, payload) for payload in payloads]
                for index, future in enumerate(
                    concurrent.futures.as_completed(futures), 1
                ):
                    records.append(future.result())
                    if index % 20 == 0 or index == len(futures):
                        print(
                            f"Header-partition scanned {index}/{len(futures)}",
                            flush=True,
                        )
        records.sort(key=lambda item: str(item["unit_id"]))
        verify_source_state(source_state, source_root)
        summary = build_summary(
            records,
            input_audit=input_audit,
            workers=workers,
            source_state=source_state,
        )
        return write_predictions(safe_output, records, summary)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cohort", action="append", dest="cohorts")
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="permit a non-formal development scan from modified source files",
    )
    args = parser.parse_args(argv)
    try:
        receipt = run(
            groups=args.groups.resolve(),
            output=args.output,
            cohorts=tuple(args.cohorts or DEFAULT_COHORTS),
            workers=args.workers,
            allow_dirty=args.allow_dirty,
        )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"header-partition prediction refused: {exc}") from exc
    print(f"Header-partition receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
