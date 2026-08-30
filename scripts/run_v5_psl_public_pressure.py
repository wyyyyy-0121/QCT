"""Run V5-PSL and its four ablations on revealed public development cases."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl import ABLATIONS, diagnose_v5_psl, v5_psl_default_parameters
from formulaguard.v5_psl_corpora import LOCALIZATION_CORPORA
from formulaguard.v5_psl_protocol import (
    DEFAULT_WORKERS,
    DIAGNOSTIC_STATES,
    canonical_cell,
    combined_shards_sha256,
    model_output_projection,
    parse_source_cells,
    safe_path,
    sha256,
    source_rank,
    validate_complete_ranking,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_v5_psl_third_party_pack import validate_case_pair
from scripts.freeze_v5_psl_candidate import _git, candidate_source_files


PRESSURE_FIELDS = (
    "instance_id", "corpus_id", "workbook", "original_workbook", "case_kind",
    "source_cells", "identifiability", "control_subtype", "include",
    "exclusion_reason", "license_id",
)
PRESSURE_METHODS = ("full", *ABLATIONS)
PRESSURE_EVENT_FIELDS = (
    "instance_id", "corpus_id", "method", "case_kind", "identifiability",
    "control_subtype", "state", "formula_count", "inspected_cells",
    "actionable", "action_hit", "source_rank", "top1", "top5", "mrr",
)


def read_manifest(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != PRESSURE_FIELDS:
            raise ValueError("Public pressure manifest fields are invalid")
        rows = list(reader)
    identifiers = [row["instance_id"] for row in rows]
    if (
        not rows or len(identifiers) != len(set(identifiers))
        or any(not re.fullmatch(r"[A-Za-z0-9._-]+", identifier) for identifier in identifiers)
    ):
        raise ValueError("Public pressure manifest requires unique non-empty instances")
    included_workbooks = [row["workbook"] for row in rows if row["include"] == "1"]
    if len(included_workbooks) != len(set(included_workbooks)):
        raise ValueError("Included public pressure workbook paths must be unique")
    for row in rows:
        if row["corpus_id"] not in LOCALIZATION_CORPORA:
            raise ValueError(f"Invalid localization corpus: {row['corpus_id']}")
        if row["include"] not in {"0", "1"}:
            raise ValueError(f"include must be 0 or 1: {row['instance_id']}")
        if row["include"] == "0" and not row["exclusion_reason"]:
            raise ValueError(f"Excluded case requires a reason: {row['instance_id']}")
        if row["case_kind"] not in {"error", "control"}:
            raise ValueError(f"Invalid case_kind: {row['instance_id']}")
        sources = parse_source_cells(row["source_cells"])
        if row["case_kind"] == "error" and not sources:
            raise ValueError(f"Error case requires source cells: {row['instance_id']}")
        if row["case_kind"] == "control" and sources:
            raise ValueError(f"Control must not contain source cells: {row['instance_id']}")
        if row["include"] == "1":
            if not row["license_id"].strip():
                raise ValueError(f"Included case requires a reviewed license identifier: {row['instance_id']}")
            if row["case_kind"] == "error":
                if row["identifiability"] not in {"identifiable", "ambiguous"}:
                    raise ValueError(f"Included error requires an identifiability review: {row['instance_id']}")
                if row["identifiability"] == "identifiable" and len(sources) != 1:
                    raise ValueError(f"Identifiable pressure error requires one source: {row['instance_id']}")
                if row["control_subtype"]:
                    raise ValueError(f"Error case must not declare a control subtype: {row['instance_id']}")
            else:
                if row["identifiability"]:
                    raise ValueError(f"Control must not declare identifiability: {row['instance_id']}")
                if row["control_subtype"] not in {"regular", "legal_exception"}:
                    raise ValueError(f"Included control requires a reviewed subtype: {row['instance_id']}")
            workbook = safe_path(path.parent, row["workbook"])
            if workbook.suffix.lower() != ".xlsx":
                raise ValueError(f"Included pressure workbook must be .xlsx: {row['instance_id']}")
            original = safe_path(path.parent, row["original_workbook"])
            if original.suffix.lower() != ".xlsx":
                raise ValueError(f"Included pressure original must be .xlsx: {row['instance_id']}")
    return rows


def _predict(path: Path, instance_id: str, workbook_label: str) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(path)
    methods = {}
    for method in PRESSURE_METHODS:
        started = time.perf_counter()
        report = diagnose_v5_psl(model, ablation=None if method == "full" else method)
        payload = report.as_dict()
        payload["action_cells"] = payload.pop("review_cells")
        payload["runtime_seconds"] = time.perf_counter() - started
        methods[method] = payload
    return {
        "protocol": "v5_psl_public_pressure_shard_v1",
        "instance_id": instance_id,
        "workbook": workbook_label,
        "workbook_sha256": sha256(path),
        "formula_count": len(model.formulas),
        "methods": methods,
        "label_inputs_to_model": [],
    }


def _task(payload: tuple[str, str, str, str]) -> str:
    root_text, output_text, instance_id, workbook_label = payload
    root, output = Path(root_text), Path(output_text)
    workbook = safe_path(root, workbook_label)
    record = _predict(workbook, instance_id, workbook_label)
    shard = output / "shards" / f"{instance_id}.json"
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, shard)
    return instance_id


def audit_shard(
    path: Path,
    row: Mapping[str, str],
    root: Path,
    *,
    recompute: bool = False,
) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("protocol") != "v5_psl_public_pressure_shard_v1":
        raise ValueError(f"Invalid public pressure shard protocol: {path.name}")
    if record.get("instance_id") != row["instance_id"] or record.get("workbook") != row["workbook"]:
        raise ValueError(f"Public pressure shard identity changed: {path.name}")
    workbook = safe_path(root, row["workbook"])
    if record.get("workbook_sha256") != sha256(workbook):
        raise ValueError(f"Public pressure workbook hash changed: {path.name}")
    model = WorkbookModel.from_xlsx(workbook)
    formula_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    if record.get("formula_count") != len(formula_cells):
        raise ValueError(f"Public pressure formula count changed: {path.name}")
    methods = record.get("methods")
    if not isinstance(methods, dict) or tuple(methods) != PRESSURE_METHODS:
        raise ValueError(f"Public pressure ablation inventory is incomplete: {path.name}")
    canonical_formulas = {canonical_cell(value) for value in formula_cells}
    fixed_count = min(5, len(formula_cells))
    for method, result in methods.items():
        if not isinstance(result, dict) or not isinstance(result.get("ranking"), list):
            raise ValueError(f"Invalid public pressure result for {method}: {path.name}")
        validate_complete_ranking(result["ranking"], formula_cells)
        actions = result.get("action_cells")
        if not isinstance(actions, list):
            raise ValueError(f"Invalid action set for {method}: {path.name}")
        canonical_actions = [canonical_cell(value) for value in actions]
        if (
            len(canonical_actions) != len(set(canonical_actions))
            or not set(canonical_actions) <= canonical_formulas
        ):
            raise ValueError(f"Invalid action set for {method}: {path.name}")
        state = result.get("state")
        if state not in DIAGNOSTIC_STATES:
            raise ValueError(f"Invalid diagnostic state for {method}: {path.name}")
        expected_actions = {"localized": 1, "review": fixed_count}.get(str(state), 0)
        if len(canonical_actions) != expected_actions:
            raise ValueError(f"Invalid selective action budget for {method}: {path.name}")
        ranked = [canonical_cell(item["cell"]) for item in result["ranking"]]
        if canonical_actions != ranked[:expected_actions]:
            raise ValueError(f"Action cells differ from ranking for {method}: {path.name}")
    if record.get("label_inputs_to_model") != []:
        raise ValueError(f"Labels reached the diagnostic model: {path.name}")
    if recompute:
        expected = _predict(workbook, row["instance_id"], row["workbook"])
        if model_output_projection(record) != model_output_projection(expected):
            raise ValueError(f"Public pressure shard does not reproduce: {path.name}")
    return record


def build_events(
    output: Path,
    included: Sequence[Mapping[str, str]],
) -> list[dict[str, object]]:
    events = []
    for row in included:
        record = json.loads((output / "shards" / f"{row['instance_id']}.json").read_text(encoding="utf-8"))
        sources = set(parse_source_cells(row["source_cells"]))
        for method in PRESSURE_METHODS:
            result = record["methods"][method]
            rank = source_rank(result["ranking"], sources) if sources else None
            actions = {canonical_cell(value) for value in result["action_cells"]}
            events.append({
                "instance_id": row["instance_id"],
                "corpus_id": row["corpus_id"],
                "method": method,
                "case_kind": row["case_kind"],
                "identifiability": row["identifiability"],
                "control_subtype": row["control_subtype"],
                "state": result["state"],
                "formula_count": record["formula_count"],
                "inspected_cells": len(actions),
                "actionable": int(bool(actions)),
                "action_hit": int(bool(actions & sources)),
                "source_rank": rank if rank is not None else "",
                "top1": int(rank is not None and rank <= 1) if sources else "",
                "top5": int(rank is not None and rank <= 5) if sources else "",
                "mrr": 1 / rank if rank is not None else "",
            })
    return events


def _write_events(
    output: Path,
    included: Sequence[Mapping[str, str]],
) -> list[dict[str, object]]:
    events = build_events(output, included)
    with (output / "public_pressure_events.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRESSURE_EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(events)
    return events


def development_signatures(
    manifest_path: Path,
    included: Sequence[Mapping[str, str]],
) -> list[str]:
    signatures = set()
    for row in included:
        evidence = validate_case_pair(
            row, manifest_path.parent, development_signatures=set(),
        )
        signature = str(evidence["formula_change_signature"])
        if row["case_kind"] == "error":
            if not signature:
                raise ValueError(f"Development error pair has no formula signature: {row['instance_id']}")
            signatures.add(signature)
    if not signatures:
        raise ValueError("At least one reviewed original/error pair is required for leakage signatures")
    return sorted(signatures)


def _write_development_signatures(
    manifest_path: Path,
    included: Sequence[Mapping[str, str]],
    output: Path,
) -> list[str]:
    ordered = development_signatures(manifest_path, included)
    (output / "development_formula_change_signatures.txt").write_text(
        "".join(f"{value}\n" for value in ordered), encoding="utf-8",
    )
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="Run V5-PSL public pressure and ablations")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=min(DEFAULT_WORKERS, os.cpu_count() or 1),
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    manifest_path = args.manifest.resolve()
    root = manifest_path.parent
    output = args.output.resolve()
    try:
        if _git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Formal public pressure requires a clean Git worktree")
        git_commit = _git("rev-parse", "HEAD")
        source_sha256 = {
            relative: sha256(ROOT / relative)
            for relative in candidate_source_files()
        }
        rows = read_manifest(manifest_path)
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"V5-PSL public pressure refused: {exc}") from exc
    included = [row for row in rows if row["include"] == "1"]
    if not included:
        raise SystemExit("V5-PSL public pressure has no included cases")
    output.mkdir(parents=True, exist_ok=True)
    (output / "shards").mkdir(exist_ok=True)
    metadata = {
        "protocol": "v5_psl_public_pressure_run_v1",
        "manifest_sha256": sha256(manifest_path),
        "included_cases": len(included),
        "excluded_cases": len(rows) - len(included),
        "git_commit": git_commit,
        "source_sha256": source_sha256,
        "worker_processes_requested": args.workers,
        "clean_git_worktree_before_prediction": True,
        "methods": list(PRESSURE_METHODS),
        "parameters": json.loads(json.dumps(v5_psl_default_parameters())),
        "label_inputs_to_model": [],
        "labels_used_after_prediction_for_development_scoring": [
            "case_kind", "source_cells", "identifiability", "control_subtype",
        ],
        "third_party_confirmation_files_read": [],
    }
    metadata_path = output / "public_pressure_metadata.json"
    if metadata_path.exists():
        previous = json.loads(metadata_path.read_text(encoding="utf-8"))
        if previous != metadata:
            raise SystemExit("Public pressure resume refused: manifest or parameters changed")
        if not args.resume:
            raise SystemExit("Public pressure output exists; pass --resume")
    else:
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    pending = []
    for row in included:
        shard = output / "shards" / f"{row['instance_id']}.json"
        if shard.exists():
            try:
                audit_shard(shard, row, root, recompute=True)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                raise SystemExit(f"Public pressure resume refused: {exc}") from exc
        else:
            pending.append(row)
    workers = min(args.workers, max(1, len(pending)))
    print(
        f"V5-PSL public pressure scheduling: workers={workers}; "
        f"pending={len(pending)}; resumed={len(included) - len(pending)}",
        flush=True,
    )
    payloads = [(str(root), str(output), row["instance_id"], row["workbook"]) for row in pending]
    if workers == 1:
        for index, payload in enumerate(payloads, 1):
            print(f"[{index}/{len(payloads)}] {_task(payload)}", flush=True)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_task, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(payloads)}] {future.result()}", flush=True)
    by_id = {row["instance_id"]: row for row in included}
    shards = sorted((output / "shards").glob("*.json"))
    if {path.stem for path in shards} != set(by_id):
        raise SystemExit("Public pressure completion refused: incomplete shard set")
    try:
        for path in shards:
            audit_shard(path, by_id[path.stem], root)
        events = _write_events(output, included)
        signatures = _write_development_signatures(manifest_path, included, output)
        if _git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Git worktree changed during public pressure prediction")
        if _git("rev-parse", "HEAD") != git_commit:
            raise ValueError("Git commit changed during public pressure prediction")
        for relative, expected in source_sha256.items():
            if sha256(ROOT / relative) != expected:
                raise ValueError(f"Candidate source changed during public pressure: {relative}")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Public pressure completion refused: {exc}") from exc
    completion = {
        "protocol": "v5_psl_public_pressure_completion_v1",
        "complete": True,
        "cases": len(included),
        "method_events": len(events),
        "methods": list(PRESSURE_METHODS),
        "combined_shards_sha256": combined_shards_sha256(shards),
        "events_sha256": sha256(output / "public_pressure_events.csv"),
        "development_signatures": len(signatures),
        "development_signatures_sha256": sha256(
            output / "development_formula_change_signatures.txt"
        ),
        "manifest_sha256": sha256(manifest_path),
        "metadata_sha256": sha256(metadata_path),
        "full_ranking_audit_passed": True,
        "third_party_confirmation_files_read": [],
    }
    completion_path = output / "public_pressure_complete.json"
    completion_path.write_text(json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(completion_path)


if __name__ == "__main__":
    main()
