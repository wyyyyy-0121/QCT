"""Audit revealed-corpus pressure results before a V5-PSL candidate freeze."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import os
import statistics
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl import v5_psl_default_parameters
from formulaguard.v5_psl_corpora import (
    CORPUS_IDS,
    INVENTORY_FIELDS,
    adapt_corpus,
    load_registry,
)
from formulaguard.v5_psl_protocol import (
    DEFAULT_WORKERS,
    canonical_json_sha256,
    combined_shards_sha256,
    sha256,
)
from scripts.run_v5_psl_public_pressure import (
    PRESSURE_EVENT_FIELDS,
    PRESSURE_METHODS,
    audit_shard,
    build_events,
    development_signatures,
    read_manifest,
)
from scripts.freeze_v5_psl_candidate import _git, candidate_source_files
from scripts.tune_v5_psl_parameters import FOLD_COUNT, assign_group_folds


def _mean(values: Iterable[float | int]) -> float:
    rows = list(values)
    return statistics.fmean(rows) if rows else 0.0


def _read_events(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PRESSURE_EVENT_FIELDS:
            raise ValueError("Public pressure event fields are invalid")
        rows = list(reader)
    if not rows:
        raise ValueError("Public pressure events are empty")
    return rows


def _csv_strings(rows: Sequence[Mapping[str, object]]) -> list[dict[str, str]]:
    return [
        {field: str(row[field]) for field in PRESSURE_EVENT_FIELDS}
        for row in rows
    ]


def _read_signatures(path: Path) -> list[str]:
    signatures = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = line.strip().lower()
        if not value or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"Invalid development signature at line {line_number}")
        signatures.append(value)
    if not signatures or signatures != sorted(set(signatures)):
        raise ValueError("Development signatures must be non-empty, sorted, and unique")
    return signatures


def _audit_pressure_run(
    manifest_path: Path,
    run: Path,
    *,
    workers: int = DEFAULT_WORKERS,
) -> tuple[
    dict[str, object], dict[str, object], list[dict[str, str]], list[dict[str, str]]
]:
    rows = read_manifest(manifest_path)
    included = [row for row in rows if row["include"] == "1"]
    if not included:
        raise ValueError("Public pressure manifest contains no included cases")
    metadata_path = run / "public_pressure_metadata.json"
    completion_path = run / "public_pressure_complete.json"
    events_path = run / "public_pressure_events.csv"
    signatures_path = run / "development_formula_change_signatures.txt"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    events = _read_events(events_path)

    if metadata.get("protocol") != "v5_psl_public_pressure_run_v1":
        raise ValueError("Public pressure metadata protocol is invalid")
    if metadata.get("manifest_sha256") != sha256(manifest_path):
        raise ValueError("Public pressure metadata does not bind the supplied manifest")
    if metadata.get("included_cases") != len(included) or metadata.get("excluded_cases") != len(rows) - len(included):
        raise ValueError("Public pressure metadata case accounting changed")
    if metadata.get("git_commit") != _git("rev-parse", "HEAD"):
        raise ValueError("Public pressure Git commit differs from the audited checkout")
    if metadata.get("clean_git_worktree_before_prediction") is not True:
        raise ValueError("Public pressure did not start from a clean Git worktree")
    source_hashes = metadata.get("source_sha256")
    expected_sources = set(candidate_source_files())
    if not isinstance(source_hashes, dict) or set(source_hashes) != expected_sources:
        raise ValueError("Public pressure candidate source inventory is incomplete")
    for relative, expected in source_hashes.items():
        if sha256(ROOT / relative) != expected:
            raise ValueError(f"Public pressure candidate source changed: {relative}")
    if canonical_json_sha256(metadata.get("parameters")) != canonical_json_sha256(
        v5_psl_default_parameters()
    ):
        raise ValueError("Public pressure parameters differ from the implementation defaults")
    if metadata.get("methods") != list(PRESSURE_METHODS):
        raise ValueError("Public pressure method list is incomplete")
    if metadata.get("label_inputs_to_model") != []:
        raise ValueError("Public pressure labels reached the diagnostic model")
    if metadata.get("third_party_confirmation_files_read") != []:
        raise ValueError("Public pressure run touched third-party confirmation files")

    if completion.get("protocol") != "v5_psl_public_pressure_completion_v1":
        raise ValueError("Public pressure completion protocol is invalid")
    if completion.get("complete") is not True or completion.get("full_ranking_audit_passed") is not True:
        raise ValueError("Public pressure run or full-ranking audit is incomplete")
    if completion.get("methods") != list(PRESSURE_METHODS):
        raise ValueError("Public pressure completion lacks an ablation")
    if completion.get("manifest_sha256") != sha256(manifest_path):
        raise ValueError("Public pressure completion does not bind the supplied manifest")
    if completion.get("metadata_sha256") != sha256(metadata_path):
        raise ValueError("Public pressure metadata changed after completion")

    rows_by_id = {row["instance_id"]: row for row in included}
    shard_paths = sorted((run / "shards").glob("*.json"))
    if len(shard_paths) != len(rows_by_id) or {path.stem for path in shard_paths} != set(rows_by_id):
        raise ValueError("Public pressure shards do not cover the supplied manifest exactly")
    expected_files = {
        "public_pressure_metadata.json",
        "public_pressure_complete.json",
        "public_pressure_events.csv",
        "development_formula_change_signatures.txt",
        *(f"shards/{instance_id}.json" for instance_id in rows_by_id),
    }
    observed_files = {
        path.relative_to(run).as_posix()
        for path in run.rglob("*") if path.is_file() or path.is_symlink()
    }
    symlinks = sorted(
        path.relative_to(run).as_posix()
        for path in run.rglob("*") if path.is_symlink()
    )
    if symlinks:
        raise ValueError(f"Public pressure run contains symbolic links: {symlinks}")
    if observed_files != expected_files:
        raise ValueError(
            "Public pressure run file inventory differs: "
            f"missing={sorted(expected_files - observed_files)}, "
            f"extra={sorted(observed_files - expected_files)}"
        )
    for path in shard_paths:
        if path.is_symlink():
            raise ValueError(f"Public pressure shard must not be a symlink: {path.name}")
        audit_shard(path, rows_by_id[path.stem], manifest_path.parent)
    if workers < 1:
        raise ValueError("Public pressure audit workers must be positive")
    recomputation_tasks = [
        (str(path), dict(rows_by_id[path.stem]), str(manifest_path.parent))
        for path in shard_paths
    ]
    if len(recomputation_tasks) == 1 or workers == 1:
        for task in recomputation_tasks:
            _recompute_pressure_shard(task)
    else:
        print(
            f"V5-PSL audit scheduling: workers={min(workers, len(recomputation_tasks))}; "
            f"shards={len(recomputation_tasks)}",
            flush=True,
        )
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(workers, len(recomputation_tasks)),
        ) as executor:
            list(executor.map(_recompute_pressure_shard, recomputation_tasks))
    combined = combined_shards_sha256(shard_paths)
    if completion.get("combined_shards_sha256") != combined:
        raise ValueError("Public pressure shard aggregate changed after completion")
    if completion.get("cases") != len(included):
        raise ValueError("Public pressure completion case count is invalid")

    expected_events = _csv_strings(build_events(run, included))
    if events != expected_events:
        raise ValueError("Public pressure events do not reproduce from the manifest and shards")
    if completion.get("events_sha256") != sha256(events_path):
        raise ValueError("Public pressure events changed after completion")
    if completion.get("method_events") != len(expected_events):
        raise ValueError("Public pressure completion event count is invalid")

    expected_signatures = development_signatures(manifest_path, included)
    if _read_signatures(signatures_path) != expected_signatures:
        raise ValueError("Development signatures do not reproduce from the workbook pairs")
    if completion.get("development_signatures") != len(expected_signatures):
        raise ValueError("Development signature count is invalid")
    if completion.get("development_signatures_sha256") != sha256(signatures_path):
        raise ValueError("Development formula-change signatures changed")
    return metadata, completion, events, included


def _recompute_pressure_shard(payload: tuple[str, dict[str, str], str]) -> str:
    path_text, row, root_text = payload
    path = Path(path_text)
    audit_shard(path, row, Path(root_text), recompute=True)
    return path.name


def _summarize(rows: Sequence[Mapping[str, str]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    identifiable = [row for row in errors if row["identifiability"] == "identifiable"]
    localized = [row for row in identifiable if row["state"] == "localized"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    inspected = sum(int(row["inspected_cells"]) for row in rows)
    found = sum(int(row["action_hit"]) for row in errors)
    states = Counter(row["state"] for row in rows)
    return {
        "cases": len(rows),
        "errors": len(errors),
        "controls": len(controls),
        "state_counts": dict(sorted(states.items())),
        "supported_rate": _mean(int(row["state"] != "unsupported") for row in rows),
        "error_top1": _mean(int(row["top1"]) for row in errors),
        "error_top5": _mean(int(row["top5"]) for row in errors),
        "error_mrr": _mean(float(row["mrr"]) for row in errors),
        "localized_coverage": len(localized) / max(1, len(identifiable)),
        "localized_top1": _mean(int(row["top1"]) for row in localized),
        "localized_top5": _mean(int(row["top5"]) for row in localized),
        "control_actionable_rate": _mean(int(row["actionable"]) for row in controls),
        "control_localized_rate": _mean(
            int(row["state"] == "localized") for row in controls
        ),
        "inspected_cells": inspected,
        "source_cases_found": found,
        "review_efficiency_per_100_cells": 100 * found / inspected if inspected else 0.0,
    }


def _revision_gates(
    summary: Mapping[str, object],
    fold_summaries: Sequence[Mapping[str, object]],
) -> dict[str, bool]:
    stable_folds = sum(
        float(row["error_top5"]) >= 0.50
        and float(row["control_actionable_rate"]) <= 0.25
        for row in fold_summaries
    )
    return {
        "revision_localized_coverage_at_least_30_percent": float(summary["localized_coverage"]) >= 0.30,
        "revision_localized_top1_at_least_75_percent": float(summary["localized_top1"]) >= 0.75,
        "revision_localized_top5_at_least_95_percent": float(summary["localized_top5"]) >= 0.95,
        "revision_localized_control_rate_at_most_5_percent": float(summary["control_localized_rate"]) <= 0.05,
        "revision_at_least_four_stable_folds": stable_folds >= 4,
    }


def _audit_inventories(
    paths: Sequence[Path],
    registry: Mapping[str, Mapping[str, object]],
    *,
    require_source_reopen: bool = False,
) -> dict[str, dict[str, object]]:
    result = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("protocol") != "v5_psl_public_corpus_inventory_v1":
            raise ValueError(f"Invalid corpus inventory audit: {path}")
        corpus_id = str(payload.get("corpus_id", ""))
        if corpus_id in result or corpus_id not in CORPUS_IDS:
            raise ValueError(f"Duplicate or unknown corpus inventory: {corpus_id}")
        inventory = path.parent / "inventory.csv"
        if not inventory.is_file() or payload.get("inventory_file_sha256") != sha256(inventory):
            raise ValueError(f"Corpus inventory hash failed: {corpus_id}")
        with inventory.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != INVENTORY_FIELDS:
                raise ValueError(f"Corpus inventory fields failed: {corpus_id}")
            rows = list(reader)
        if len(rows) != payload.get("items") or not rows:
            raise ValueError(f"Corpus inventory count failed: {corpus_id}")
        if any(row["corpus_id"] != corpus_id for row in rows):
            raise ValueError(f"Corpus inventory row identity failed: {corpus_id}")
        if len({row["item_id"] for row in rows}) != len(rows):
            raise ValueError(f"Corpus inventory item identifiers are not unique: {corpus_id}")
        if any(row["include_for_localization"] not in {"0", "1"} for row in rows):
            raise ValueError(f"Corpus inventory inclusion values failed: {corpus_id}")
        if any(
            row["include_for_localization"] == "0" and not row["exclusion_reason"]
            for row in rows
        ):
            raise ValueError(f"Corpus inventory exclusions lack reasons: {corpus_id}")
        spec = registry[corpus_id]
        if payload.get("task_scope") != spec.get("task_scope") or any(
            row["task_scope"] != spec.get("task_scope") for row in rows
        ):
            raise ValueError(f"Corpus inventory task scope failed: {corpus_id}")
        if payload.get("license") != spec.get("license"):
            raise ValueError(f"Corpus inventory license record failed: {corpus_id}")
        if payload.get("inventory_sha256") != canonical_json_sha256(rows):
            raise ValueError(f"Corpus inventory canonical hash failed: {corpus_id}")
        included = sum(row["include_for_localization"] == "1" for row in rows)
        if (
            payload.get("included_for_localization") != included
            or payload.get("excluded_or_pending") != len(rows) - included
        ):
            raise ValueError(f"Corpus inventory inclusion accounting failed: {corpus_id}")
        if corpus_id not in {"modified_euses", "info1", "integer_corpus", "enron_error"} and included:
            raise ValueError(f"Supplemental corpus entered localization inventory: {corpus_id}")
        if payload.get("raw_data_redistributed") is not False:
            raise ValueError(f"Raw redistribution boundary failed: {corpus_id}")
        if require_source_reopen:
            source = Path(str(payload.get("source_root", "")))
            if not source.is_absolute() or not source.is_dir() or source.is_symlink():
                raise ValueError(f"Corpus source root cannot be reopened safely: {corpus_id}")
            expected_rows, expected_audit = adapt_corpus(corpus_id, source, spec)
            expected_csv_rows = [
                {field: str(row[field]) for field in INVENTORY_FIELDS}
                for row in expected_rows
            ]
            if rows != expected_csv_rows:
                raise ValueError(f"Corpus inventory does not reproduce from source: {corpus_id}")
            for field in (
                "items", "task_scope", "included_for_localization",
                "excluded_or_pending", "license", "raw_data_redistributed",
                "inventory_sha256",
            ):
                if payload.get(field) != expected_audit.get(field):
                    raise ValueError(f"Corpus source audit differs for {corpus_id}: {field}")
            payload = dict(payload)
            payload["_acquisition_receipt_sha256"] = _verify_acquisition(
                corpus_id, source, spec,
            )
            payload["_source_reopened"] = True
        result[corpus_id] = payload
    if set(result) != set(CORPUS_IDS):
        raise ValueError(f"Six-corpus inventory is incomplete: {sorted(set(CORPUS_IDS) - set(result))}")
    return result


def _verify_zip_extraction(archive_path: Path, extracted: Path) -> None:
    expected: dict[str, str] = {}
    with zipfile.ZipFile(archive_path) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            name = Path(item.filename).as_posix()
            if name in expected:
                raise ValueError(f"Downloaded corpus ZIP contains duplicate member: {name}")
            with archive.open(item) as handle:
                digest = hashlib.sha256()
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            expected[name] = digest.hexdigest()
    observed_paths = [path for path in extracted.rglob("*") if path.is_file()]
    if any(path.is_symlink() for path in extracted.rglob("*")):
        raise ValueError("Extracted corpus contains a symbolic link")
    observed = {
        path.relative_to(extracted).as_posix(): sha256(path)
        for path in observed_paths
    }
    if observed != expected:
        raise ValueError("Extracted corpus files differ from the pinned archive")


def _verify_acquisition(
    corpus_id: str,
    source: Path,
    spec: Mapping[str, object],
) -> str:
    receipt_path = source.parent / "acquisition_receipt.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    recorded_hash = receipt.get("receipt_sha256")
    unsigned = dict(receipt)
    unsigned.pop("receipt_sha256", None)
    if (
        receipt.get("protocol") != "v5_psl_public_corpus_acquisition_v1"
        or receipt.get("corpus_id") != corpus_id
        or receipt.get("terms_acknowledged") is not True
        or receipt.get("raw_redistribution_authorized_by_project") is not False
        or receipt.get("license_status") != spec.get("license")
        or recorded_hash != canonical_json_sha256(unsigned)
    ):
        raise ValueError(f"Corpus acquisition receipt is invalid: {corpus_id}")
    acquisition = spec.get("acquisition")
    if not isinstance(acquisition, Mapping) or receipt.get("source_url") != acquisition.get("url"):
        raise ValueError(f"Corpus acquisition source differs from registry: {corpus_id}")
    if acquisition.get("kind") == "http_zip":
        archive = source.parent / "source.zip"
        expected_size = int(acquisition.get("size_bytes", -1))
        if (
            not archive.is_file()
            or sha256(archive) != acquisition.get("sha256")
            or archive.stat().st_size != expected_size
            or receipt.get("archive_sha256") != acquisition.get("sha256")
            or receipt.get("archive_size_bytes") != expected_size
        ):
            raise ValueError(f"Pinned HTTP corpus acquisition differs: {corpus_id}")
        _verify_zip_extraction(archive, source)
        extracted_files = sum(path.is_file() for path in source.rglob("*"))
        if receipt.get("files_extracted") != extracted_files:
            raise ValueError(f"Corpus extraction count differs from receipt: {corpus_id}")
    elif acquisition.get("kind") == "git":
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=source, text=True,
            capture_output=True, check=False,
        )
        if (
            completed.returncode
            or completed.stdout.strip() != acquisition.get("commit")
            or receipt.get("git_commit") != acquisition.get("commit")
        ):
            raise ValueError(f"Pinned Git corpus commit differs: {corpus_id}")
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=source,
            text=True, capture_output=True, check=False,
        )
        if dirty.returncode or dirty.stdout.strip():
            raise ValueError(f"Pinned Git corpus checkout is dirty: {corpus_id}")
        for relative, expected in dict(spec.get("content_hashes", {})).items():
            path = source / relative
            if not path.is_file() or sha256(path) != expected:
                raise ValueError(f"Pinned Git corpus content differs: {corpus_id}:{relative}")
        if receipt.get("content_hashes_verified") != dict(spec.get("content_hashes", {})):
            raise ValueError(f"Pinned Git corpus receipt content differs: {corpus_id}")
    else:
        raise ValueError(f"Unsupported acquisition kind in audit: {corpus_id}")
    return sha256(receipt_path)


def _revision_count(path: Path) -> int:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != "v5_psl_mechanism_revision_log_v1":
        raise ValueError("V5-PSL mechanism revision log protocol is invalid")
    revisions = payload.get("revisions")
    if not isinstance(revisions, list):
        raise ValueError("V5-PSL mechanism revision log must contain a list")
    for index, row in enumerate(revisions, 1):
        if not isinstance(row, dict) or not {
            "revision_id", "root_cause", "evidence_sha256", "source_commit",
        } <= set(row):
            raise ValueError(f"Mechanism revision {index} lacks audit fields")
    return len(revisions)


def _audit_supplemental_roles(paths: Sequence[Path]) -> dict[str, dict[str, object]]:
    result = {}
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("protocol") != "v5_psl_supplemental_corpus_role_audit_v1":
            raise ValueError(f"Invalid supplemental role audit: {path}")
        corpus_id = str(payload.get("corpus_id", ""))
        if corpus_id not in {"forepbench", "spreadsheetbench"} or corpus_id in result:
            raise ValueError(f"Duplicate or unknown supplemental role audit: {corpus_id}")
        events = path.parent / "events.csv"
        if not events.is_file() or payload.get("events_sha256") != sha256(events):
            raise ValueError(f"Supplemental role events hash failed: {corpus_id}")
        with events.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            event_rows = list(reader)
        if not event_rows or len({row.get("item_id") for row in event_rows}) != len(event_rows):
            raise ValueError(f"Supplemental role event inventory failed: {corpus_id}")
        expected_scope = "repair_only" if corpus_id == "forepbench" else "parser_stress_only"
        if payload.get("task_scope") != expected_scope or any(
            row.get("task_scope") != expected_scope for row in event_rows
        ):
            raise ValueError(f"Supplemental task scope changed: {corpus_id}")
        if payload.get("localization_accuracy_events") != 0 or any(
            row.get("localization_accuracy_eligible") != "0" for row in event_rows
        ):
            raise ValueError(f"Supplemental corpus leaked into localization accuracy: {corpus_id}")
        if payload.get("raw_data_redistributed") is not False or payload.get("complete") is not True:
            raise ValueError(f"Supplemental role audit is incomplete: {corpus_id}")
        if corpus_id == "forepbench":
            if payload.get("items") != 618 or len(event_rows) != 618:
                raise ValueError("FoRepBench role audit must retain all 618 items")
            integer_fields = (
                "formula_pair_present", "formula_pair_distinct",
                "faulty_formula_parseable", "correct_formula_parseable",
            )
            try:
                totals = {
                    field: sum(int(row[field]) for row in event_rows)
                    for field in integer_fields
                }
            except (KeyError, ValueError) as exc:
                raise ValueError("FoRepBench role event fields are invalid") from exc
            if (
                payload.get("formula_pairs_present") != totals["formula_pair_present"]
                or payload.get("distinct_formula_pairs") != totals["formula_pair_distinct"]
                or payload.get("faulty_formula_parse_coverage")
                != totals["faulty_formula_parseable"] / 618
                or payload.get("correct_formula_parse_coverage")
                != totals["correct_formula_parseable"] / 618
            ):
                raise ValueError("FoRepBench role event accounting failed")
        if corpus_id == "spreadsheetbench":
            try:
                parsed = sum(row["parse_status"] == "parsed" for row in event_rows)
                excluded = sum(row["parse_status"] == "excluded" for row in event_rows)
                formula_workbooks_observed = sum(
                    row["parse_status"] == "parsed" and int(row["formula_count"]) > 0
                    for row in event_rows
                )
                diagnosed = sum(
                    row["diagnostic_state"] not in {"not_run", "safe_skip"}
                    for row in event_rows
                )
                diagnostic_failures = sum(
                    row["parse_status"] == "parsed" and row["diagnostic_state"] == "safe_skip"
                    for row in event_rows
                )
            except (KeyError, ValueError) as exc:
                raise ValueError("SpreadsheetBench role event fields are invalid") from exc
            formula_workbooks = payload.get("formula_workbooks")
            diagnosis_target = payload.get("diagnosis_target")
            if (
                not isinstance(formula_workbooks, int) or formula_workbooks < 1
                or not isinstance(diagnosis_target, int) or diagnosis_target < 1
                or payload.get("limited") is not False
                or payload.get("unhandled_crashes") != 0
                or payload.get("accounting_complete") is not True
                or payload.get("diagnostic_failures") != 0
                or diagnosis_target != min(25, formula_workbooks)
                or payload.get("diagnosis_attempts") != diagnosis_target
                or payload.get("diagnosed_without_labels") != diagnosis_target
                or payload.get("workbooks_attempted") != len(event_rows)
                or payload.get("parsed") != parsed
                or payload.get("safe_skip_exclusions") != excluded
                or formula_workbooks != formula_workbooks_observed
                or diagnosed != diagnosis_target
                or diagnostic_failures != 0
            ):
                raise ValueError("SpreadsheetBench formal parser-stress accounting failed")
        result[corpus_id] = payload
    if set(result) != {"forepbench", "spreadsheetbench"}:
        raise ValueError("Both supplemental corpus role audits are required")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit V5-PSL public pressure evidence")
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--inventory-audits", nargs="+", type=Path, required=True)
    parser.add_argument("--role-audits", nargs="+", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--revision-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=min(DEFAULT_WORKERS, os.cpu_count() or 1),
    )
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    run = args.run.resolve()
    manifest_path = args.manifest.resolve()
    completion_path = run / "public_pressure_complete.json"
    events_path = run / "public_pressure_events.csv"
    signatures_path = run / "development_formula_change_signatures.txt"
    try:
        registry = load_registry(args.registry.resolve())
        inventories = _audit_inventories(
            [path.resolve() for path in args.inventory_audits], registry,
            require_source_reopen=True,
        )
        roles = _audit_supplemental_roles([path.resolve() for path in args.role_audits])
        revision_count = _revision_count(args.revision_log.resolve())
        metadata, completion, events, included = _audit_pressure_run(
            manifest_path, run, workers=args.workers,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5-PSL public pressure audit refused: {exc}") from exc

    case_methods: dict[str, set[str]] = {}
    for row in events:
        case_methods.setdefault(row["instance_id"], set()).add(row["method"])
    expected_methods = set(PRESSURE_METHODS)
    ablations_complete = (
        all(methods == expected_methods for methods in case_methods.values())
        and len(events) == len(case_methods) * len(PRESSURE_METHODS)
        and completion.get("method_events") == len(events)
    )
    summary = {
        method: _summarize([row for row in events if row["method"] == method])
        for method in PRESSURE_METHODS
    }
    full = summary["full"]
    no_perturbation = summary["no_perturbation"]
    no_gate = summary["no_identifiability_gate"]
    full_rows = [row for row in events if row["method"] == "full"]
    error_count = sum(row["case_kind"] == "error" for row in full_rows)
    control_count = sum(row["case_kind"] == "control" for row in full_rows)
    localization_corpora = sorted({row["corpus_id"] for row in full_rows})
    _groups, fold_by_instance = assign_group_folds(included, manifest_path.parent)
    fold_summaries = [
        _summarize([
            row for row in full_rows
            if fold_by_instance[row["instance_id"]] == fold
        ])
        for fold in range(FOLD_COUNT)
    ]
    stable_folds = sum(
        float(row["error_top5"]) >= 0.50
        and float(row["control_actionable_rate"]) <= 0.25
        for row in fold_summaries
    )
    revision_run = (
        metadata.get("parameters", {}).get("model_version") == "v5-psl-dev1-rev1"
    )
    gates = {
        "six_corpus_inventories_complete": set(inventories) == set(CORPUS_IDS),
        "six_pinned_acquisitions_reopened": all(
            row.get("_source_reopened") is True
            and isinstance(row.get("_acquisition_receipt_sha256"), str)
            for row in inventories.values()
        ),
        "supplemental_roles_audited_without_metric_mixing": set(roles) == {
            "forepbench", "spreadsheetbench",
        },
        "at_least_60_revealed_errors": error_count >= 60,
        "at_least_30_revealed_controls": control_count >= 30,
        "at_least_3_localization_corpora": len(localization_corpora) >= 3,
        "all_four_ablations_complete": ablations_complete,
        "default_supported_rate_at_least_80_percent": float(full["supported_rate"]) >= 0.80,
        "default_error_top5_at_least_60_percent": float(full["error_top5"]) >= 0.60,
        "default_control_actionable_rate_at_most_15_percent": float(full["control_actionable_rate"]) <= 0.15,
        "default_efficiency_not_below_no_perturbation": float(full["review_efficiency_per_100_cells"]) >= float(no_perturbation["review_efficiency_per_100_cells"]),
        "identifiability_gate_does_not_increase_control_actions": float(full["control_actionable_rate"]) <= float(no_gate["control_actionable_rate"]),
        "mechanism_revision_count_at_most_one": revision_count <= 1,
        "revision_one_recorded_for_rev1_output": not revision_run or revision_count == 1,
        "third_party_confirmation_files_untouched": metadata.get("third_party_confirmation_files_read") == [],
    }
    if revision_run:
        gates.update(_revision_gates(full, fold_summaries))
    payload = {
        "protocol": "v5_psl_public_pressure_audit_v1",
        "audit_worker_processes_requested": args.workers,
        "hard_gate_passed": all(gates.values()),
        "gates": gates,
        "corpora_audited": list(CORPUS_IDS),
        "localization_corpora_in_pressure_run": localization_corpora,
        "manifest_sha256": sha256(manifest_path),
        "git_commit": metadata["git_commit"],
        "source_sha256": metadata["source_sha256"],
        "registry_sha256": sha256(args.registry.resolve()),
        "inventory_audit_sha256": {
            corpus_id: sha256(next(
                path.resolve() for path in args.inventory_audits
                if json.loads(path.read_text(encoding="utf-8"))["corpus_id"] == corpus_id
            ))
            for corpus_id in CORPUS_IDS
        },
        "acquisition_receipt_sha256": {
            corpus_id: inventories[corpus_id]["_acquisition_receipt_sha256"]
            for corpus_id in CORPUS_IDS
        },
        "supplemental_role_audit_sha256": {
            corpus_id: sha256(next(
                path.resolve() for path in args.role_audits
                if json.loads(path.read_text(encoding="utf-8"))["corpus_id"] == corpus_id
            ))
            for corpus_id in ("forepbench", "spreadsheetbench")
        },
        "run_completion_sha256": sha256(completion_path),
        "events_sha256": sha256(events_path),
        "development_signatures_sha256": sha256(signatures_path),
        "summary": summary,
        "ablation_deltas_full_minus_ablation": {
            method: {
                "error_mrr": float(full["error_mrr"]) - float(summary[method]["error_mrr"]),
                "control_actionable_rate": float(full["control_actionable_rate"]) - float(summary[method]["control_actionable_rate"]),
                "review_efficiency_per_100_cells": float(full["review_efficiency_per_100_cells"]) - float(summary[method]["review_efficiency_per_100_cells"]),
            }
            for method in PRESSURE_METHODS[1:]
        },
        "ablations_complete": ablations_complete,
        "mechanism_revision_count": revision_count,
        "revision_fold_summaries": fold_summaries if revision_run else [],
        "revision_stable_folds": stable_folds if revision_run else None,
        "third_party_confirmation_files_read": [],
        "data_are_revealed_public_development_evidence": True,
        "independent_or_blind_claim_forbidden": True,
    }
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite public pressure audit: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    if not payload["hard_gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
