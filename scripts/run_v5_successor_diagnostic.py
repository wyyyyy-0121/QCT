"""Compare fixed successor signals on revealed public-development cases."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl_protocol import (
    DEFAULT_WORKERS,
    combined_shards_sha256,
    parse_source_cells,
    safe_path,
    sha256,
    source_rank,
)
from formulaguard.workbook import WorkbookModel
from scripts.freeze_v5_psl_candidate import _git
from scripts.run_v5_psl_predictions import audit_prediction_shard, predict_workbook
from scripts.run_v5_psl_public_pressure import read_manifest
from scripts.tune_v5_psl_parameters import FOLD_COUNT, assign_group_folds

PROTOCOL = "v5_successor_baseline_diagnostic_v1"
RANKING_METHODS = ("v4_r1", "v4_3_semantic_c", "v5_psl_dev1")
POLICY_IDS = (
    "v4_fixed_top5",
    "v42_review_set",
    "psl_revision_action",
    "v4_top1_strong",
    "v4_unique_strong_top5",
    "v4_unique_counterfactual_top5",
    "v4_unique_peer_strong_top5",
)
SUCCESSOR_POLICY_IDS = POLICY_IDS[3:]
SOURCE_FILES = (
    "formulaguard/localize.py",
    "formulaguard/v4x.py",
    "formulaguard/v52.py",
    "formulaguard/v5_psl.py",
    "scripts/run_v5_psl_predictions.py",
    "scripts/run_v5_successor_diagnostic.py",
    "research/V5_SUCCESSOR_BASELINE_DIAGNOSTIC.md",
)
EVENT_FIELDS = (
    "policy_id", "instance_id", "corpus_id", "group_sha256", "fold",
    "case_kind", "action_count", "actionable", "action_hit",
)


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _task(payload: tuple[str, str, str, str]) -> str:
    root_text, output_text, instance_id, workbook_label = payload
    root, output = Path(root_text), Path(output_text)
    record = predict_workbook(
        safe_path(root, workbook_label), instance_id, workbook_label,
    )
    _write_json_atomic(output / "shards" / f"{instance_id}.json", record)
    return instance_id


def _v4_candidates(
    methods: Mapping[str, object],
    statuses: set[str],
    *,
    peer_supported: bool = False,
) -> list[str]:
    ranking = methods["v4_r1"]["ranking"][:5]  # type: ignore[index]
    candidates = []
    for row in ranking:
        evidence = row["evidence"]
        sources = set(filter(None, str(evidence.get("candidate_source", "")).split(",")))
        if evidence.get("diagnostic_status") not in statuses:
            continue
        if peer_supported and (
            int(evidence.get("candidate_support", 0)) < 2
            or "peer_translation" not in sources
        ):
            continue
        candidates.append(str(row["cell"]))
    return candidates


def policy_actions(methods: Mapping[str, object], policy_id: str) -> list[str]:
    if policy_id == "v4_fixed_top5":
        return list(methods["v4_r1"]["action_cells"])  # type: ignore[index]
    if policy_id == "v42_review_set":
        return list(methods["v4_2_review_b"]["action_cells"])  # type: ignore[index]
    if policy_id == "psl_revision_action":
        return list(methods["v5_psl_dev1"]["action_cells"])  # type: ignore[index]
    if policy_id == "v4_top1_strong":
        ranking = methods["v4_r1"]["ranking"]  # type: ignore[index]
        if ranking[0]["evidence"].get("diagnostic_status") == "strong_counterfactual":
            return [str(ranking[0]["cell"])]
        return []
    if policy_id == "v4_unique_strong_top5":
        candidates = _v4_candidates(methods, {"strong_counterfactual"})
    elif policy_id == "v4_unique_counterfactual_top5":
        candidates = _v4_candidates(
            methods, {"strong_counterfactual", "moderate_counterfactual"},
        )
    elif policy_id == "v4_unique_peer_strong_top5":
        candidates = _v4_candidates(
            methods, {"strong_counterfactual"}, peer_supported=True,
        )
    else:
        raise ValueError(f"Unknown successor policy: {policy_id}")
    return candidates if len(candidates) == 1 else []


def summarize_policy(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    acted_errors = sum(int(row["actionable"]) for row in errors)
    hits = sum(int(row["action_hit"]) for row in errors)
    inspected = sum(int(row["action_count"]) for row in rows)
    return {
        "cases": len(rows),
        "errors": len(errors),
        "controls": len(controls),
        "error_action_coverage": acted_errors / max(1, len(errors)),
        "error_source_hit_rate": hits / max(1, len(errors)),
        "acted_error_case_precision": hits / max(1, acted_errors),
        "control_actionable_rate": sum(
            int(row["actionable"]) for row in controls
        ) / max(1, len(controls)),
        "inspected_cells": inspected,
        "source_cases_found": hits,
        "review_efficiency_per_100_cells": 100 * hits / inspected if inspected else 0.0,
    }


def evaluate_successor_policies(
    summaries: Mapping[str, Mapping[str, object]],
    folds: Mapping[str, Sequence[Mapping[str, object]]],
) -> dict[str, dict[str, object]]:
    baseline_efficiency = float(
        summaries["v4_fixed_top5"]["review_efficiency_per_100_cells"]
    )
    decisions = {}
    for policy_id in SUCCESSOR_POLICY_IDS:
        summary = summaries[policy_id]
        stable_folds = sum(
            float(row["error_source_hit_rate"]) >= 0.20
            and float(row["acted_error_case_precision"]) >= 0.60
            and float(row["control_actionable_rate"]) <= 0.25
            for row in folds[policy_id]
        )
        gates = {
            "error_source_hit_rate_at_least_30_percent": float(
                summary["error_source_hit_rate"]
            ) >= 0.30,
            "acted_error_case_precision_at_least_75_percent": float(
                summary["acted_error_case_precision"]
            ) >= 0.75,
            "control_actionable_rate_at_most_15_percent": float(
                summary["control_actionable_rate"]
            ) <= 0.15,
            "efficiency_not_below_v4_fixed_top5": float(
                summary["review_efficiency_per_100_cells"]
            ) >= baseline_efficiency,
            "at_least_four_stable_folds": stable_folds >= 4,
        }
        decisions[policy_id] = {
            "eligible_for_new_architecture_preregistration": all(gates.values()),
            "gates": gates,
            "stable_folds": stable_folds,
        }
    return decisions


def _ranking_summary(
    records: Mapping[str, Mapping[str, object]],
    rows: Sequence[Mapping[str, str]],
) -> dict[str, dict[str, float | int]]:
    result = {}
    for method in RANKING_METHODS:
        ranks = []
        for row in rows:
            if row["case_kind"] != "error":
                continue
            ranking = records[row["instance_id"]]["methods"][method]["ranking"]  # type: ignore[index]
            rank = source_rank(ranking, set(parse_source_cells(row["source_cells"])))
            if rank is not None:
                ranks.append(rank)
        result[method] = {
            "errors": len(ranks),
            "top1": sum(rank <= 1 for rank in ranks) / max(1, len(ranks)),
            "top5": sum(rank <= 5 for rank in ranks) / max(1, len(ranks)),
            "mrr": statistics.fmean(1 / rank for rank in ranks) if ranks else 0.0,
        }
    return result


def _source_candidate_audit(
    records: Mapping[str, Mapping[str, object]],
    rows: Sequence[Mapping[str, str]],
    root: Path,
) -> dict[str, object]:
    counts = Counter()
    statuses = Counter()
    for row in rows:
        if row["case_kind"] != "error":
            continue
        sources = set(parse_source_cells(row["source_cells"]))
        ranking = records[row["instance_id"]]["methods"]["v4_r1"]["ranking"]  # type: ignore[index]
        lookup = {str(item["cell"]): item for item in ranking}
        original = None
        case_available = case_exact = False
        for source in sources:
            item = lookup.get(source)
            if item is None:
                continue
            statuses[str(item["evidence"].get("diagnostic_status", "missing"))] += 1
            candidate = item.get("candidate_formula")
            if not candidate:
                continue
            case_available = True
            if original is None:
                original = WorkbookModel.from_xlsx(safe_path(root, row["original_workbook"]))
            sheet, address = source.split("!", 1)
            if candidate == original.formulas.get((sheet, address)):
                case_exact = True
        counts["source_candidate_available"] += int(case_available)
        counts["source_selected_candidate_exact_original"] += int(case_exact)
    return {
        "error_cases": sum(row["case_kind"] == "error" for row in rows),
        **dict(counts),
        "source_diagnostic_status_counts": dict(sorted(statuses.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run fixed V5 successor baseline diagnostics on revealed data",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=min(DEFAULT_WORKERS, os.cpu_count() or 1),
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    manifest, output = args.manifest.resolve(), args.output.resolve()
    root = manifest.parent
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("Successor diagnostic requires a clean Git worktree")
    rows = [row for row in read_manifest(manifest) if row["include"] == "1"]
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": _git("rev-parse", "HEAD"),
        "manifest_sha256": sha256(manifest),
        "source_sha256": {relative: sha256(ROOT / relative) for relative in SOURCE_FILES},
        "worker_processes_requested": args.workers,
        "policy_ids": list(POLICY_IDS),
        "label_inputs_to_prediction": [],
        "labels_used_only_after_all_predictions": ["case_kind", "source_cells"],
        "data_role": "revealed_public_development_only",
        "independent_or_preregistered_claim_forbidden": True,
        "third_party_confirmation_files_read": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "shards").mkdir(exist_ok=True)
    metadata_path = output / "diagnostic_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("Successor diagnostic resume refused: inputs changed")
        if not args.resume:
            raise SystemExit("Successor diagnostic output exists; pass --resume")
    else:
        _write_json_atomic(metadata_path, metadata)

    pending = [
        row for row in rows
        if not (output / "shards" / f"{row['instance_id']}.json").is_file()
    ]
    workers = min(args.workers, max(1, len(pending)))
    print(
        f"V5 successor diagnostic scheduling: workers={workers}; "
        f"pending={len(pending)}; resumed={len(rows) - len(pending)}",
        flush=True,
    )
    payloads = [
        (str(root), str(output), row["instance_id"], row["workbook"])
        for row in pending
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_task, payload) for payload in payloads]
        for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
            print(f"[{index}/{len(futures)}] {future.result()}", flush=True)

    records = {}
    for row in rows:
        path = output / "shards" / f"{row['instance_id']}.json"
        records[row["instance_id"]] = audit_prediction_shard(path, row, root)
    group_by_instance, fold_by_instance = assign_group_folds(rows, root)
    events = []
    for policy_id in POLICY_IDS:
        for row in rows:
            methods = records[row["instance_id"]]["methods"]
            actions = policy_actions(methods, policy_id)
            sources = set(parse_source_cells(row["source_cells"]))
            events.append({
                "policy_id": policy_id,
                "instance_id": row["instance_id"],
                "corpus_id": row["corpus_id"],
                "group_sha256": group_by_instance[row["instance_id"]],
                "fold": fold_by_instance[row["instance_id"]],
                "case_kind": row["case_kind"],
                "action_count": len(actions),
                "actionable": int(bool(actions)),
                "action_hit": int(bool(set(actions) & sources)),
            })
    events_path = output / "diagnostic_events.csv"
    with events_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(events)
    summaries = {
        policy_id: summarize_policy([
            row for row in events if row["policy_id"] == policy_id
        ])
        for policy_id in POLICY_IDS
    }
    fold_summaries = {
        policy_id: [
            summarize_policy([
                row for row in events
                if row["policy_id"] == policy_id and row["fold"] == fold
            ])
            for fold in range(FOLD_COUNT)
        ]
        for policy_id in SUCCESSOR_POLICY_IDS
    }
    decisions = evaluate_successor_policies(summaries, fold_summaries)
    completion = {
        "protocol": "v5_successor_baseline_diagnostic_completion_v1",
        "complete": True,
        "cases": len(rows),
        "combined_shards_sha256": combined_shards_sha256(
            (output / "shards").glob("*.json")
        ),
        "events_sha256": sha256(events_path),
        "metadata_sha256": sha256(metadata_path),
        "ranking_summaries": _ranking_summary(records, rows),
        "policy_summaries": summaries,
        "successor_policy_decisions": decisions,
        "eligible_policy": next((
            policy_id for policy_id in SUCCESSOR_POLICY_IDS
            if decisions[policy_id]["eligible_for_new_architecture_preregistration"]
        ), None),
        "v4_source_candidate_audit": _source_candidate_audit(records, rows, root),
        "fold_summaries": fold_summaries,
        "third_party_confirmation_files_read": [],
        "data_are_revealed_development_evidence": True,
        "independent_or_preregistered_claim_forbidden": True,
    }
    completion_path = output / "diagnostic_complete.json"
    if completion_path.exists():
        raise SystemExit("Refusing to overwrite completed successor diagnostic")
    _write_json_atomic(completion_path, completion)
    print(completion_path)


if __name__ == "__main__":
    main()
