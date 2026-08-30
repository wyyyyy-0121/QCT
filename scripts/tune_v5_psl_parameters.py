"""Run the bounded, revealed-data V5-PSL parameter comparison."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl import PSLConfig, diagnose_v5_psl
from formulaguard.v5_psl_protocol import (
    DEFAULT_WORKERS,
    DIAGNOSTIC_STATES,
    aggregate_file_sha256,
    canonical_cell,
    canonical_json_sha256,
    parse_source_cells,
    safe_path,
    sha256,
    source_rank,
    validate_complete_ranking,
)
from formulaguard.workbook import WorkbookModel
from scripts.freeze_v5_psl_candidate import _git, candidate_source_files
from scripts.run_v5_psl_public_pressure import read_manifest


PROTOCOL = "v5_psl_parameter_tuning_v1"
BASELINE_ID = "no_perturbation"
FOLD_COUNT = 5
EVIDENCE_PROFILES: tuple[tuple[str, Mapping[str, float]], ...] = (
    ("default", {}),
    ("effect30", {"strong_effect": 0.30, "weak_effect": 0.15}),
    ("effect40", {"strong_effect": 0.40, "weak_effect": 0.20}),
    ("stability85", {"strong_stability": 0.85, "weak_stability": 0.70}),
    ("balanced", {
        "strong_effect": 0.30, "strong_stability": 0.85,
        "weak_effect": 0.15, "weak_stability": 0.70,
    }),
    ("strict", {
        "strong_effect": 0.40, "strong_stability": 0.85,
        "weak_tail": 0.15, "weak_effect": 0.20, "weak_stability": 0.70,
    }),
)
MARGINS = (0.15, 0.25)
EVENT_FIELDS = (
    "profile_id", "instance_id", "corpus_id", "group_sha256", "fold",
    "case_kind", "state", "formula_count", "inspected_cells", "actionable",
    "action_hit", "source_rank", "top1", "top5", "mrr",
)


def tuning_profiles() -> dict[str, dict[str, object]]:
    base = asdict(PSLConfig())
    profiles: dict[str, dict[str, object]] = {}
    for name, overrides in EVIDENCE_PROFILES:
        for margin in MARGINS:
            profile_id = f"{name}_m{int(round(100 * margin)):02d}"
            values = {**base, **overrides, "localization_margin": margin}
            profiles[profile_id] = asdict(PSLConfig.from_mapping(values))
    return profiles


def assign_group_folds(
    rows: Sequence[Mapping[str, str]],
    root: Path,
) -> tuple[dict[str, str], dict[str, int]]:
    group_by_instance: dict[str, str] = {}
    grouped: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in rows:
        original = safe_path(root, row["original_workbook"])
        digest = sha256(original)
        group_by_instance[row["instance_id"]] = digest
        grouped[digest].append(row)

    corpus_loads = [Counter() for _ in range(FOLD_COUNT)]
    total_loads = [0] * FOLD_COUNT
    fold_by_group: dict[str, int] = {}
    ordered = sorted(grouped.items(), key=lambda item: (
        -len(item[1]), item[0],
    ))
    for digest, group_rows in ordered:
        group_corpora = Counter(row["corpus_id"] for row in group_rows)
        fold = min(range(FOLD_COUNT), key=lambda index: (
            sum(
                corpus_loads[index][corpus_id] * count
                for corpus_id, count in group_corpora.items()
            ),
            total_loads[index],
            index,
        ))
        fold_by_group[digest] = fold
        corpus_loads[fold].update(group_corpora)
        total_loads[fold] += len(group_rows)
    fold_by_instance = {
        row["instance_id"]: fold_by_group[group_by_instance[row["instance_id"]]]
        for row in rows
    }
    return group_by_instance, fold_by_instance


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def _case_task(payload: tuple[str, str, str, str]) -> str:
    root_text, output_text, instance_id, workbook_label = payload
    root, output = Path(root_text), Path(output_text)
    workbook = safe_path(root, workbook_label)
    model = WorkbookModel.from_xlsx(workbook)
    workbook_sha256 = sha256(workbook)
    formula_count = len(model.formulas)
    jobs: list[tuple[str, dict[str, object], str | None]] = [
        (profile_id, config, None)
        for profile_id, config in tuning_profiles().items()
    ]
    jobs.append((BASELINE_ID, asdict(PSLConfig()), BASELINE_ID))
    for profile_id, config, ablation in jobs:
        started = time.perf_counter()
        report = diagnose_v5_psl(model, config=config, ablation=ablation)
        record = {
            "protocol": PROTOCOL,
            "profile_id": profile_id,
            "instance_id": instance_id,
            "workbook": workbook_label,
            "workbook_sha256": workbook_sha256,
            "formula_count": formula_count,
            "configuration": config,
            "ablation": ablation,
            "result": report.as_dict(),
            "runtime_seconds": time.perf_counter() - started,
            "label_inputs_to_model": [],
        }
        _write_json_atomic(
            output / "shards" / profile_id / f"{instance_id}.json", record,
        )
    return instance_id


def _audit_case(
    output: Path,
    root: Path,
    row: Mapping[str, str],
    profiles: Mapping[str, Mapping[str, object]],
) -> None:
    workbook = safe_path(root, row["workbook"])
    model = WorkbookModel.from_xlsx(workbook)
    formula_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    expected = {**profiles, BASELINE_ID: asdict(PSLConfig())}
    for profile_id, config in expected.items():
        path = output / "shards" / profile_id / f"{row['instance_id']}.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        if (
            record.get("protocol") != PROTOCOL
            or record.get("profile_id") != profile_id
            or record.get("instance_id") != row["instance_id"]
            or record.get("workbook") != row["workbook"]
        ):
            raise ValueError(f"Invalid tuning shard identity: {path}")
        if record.get("workbook_sha256") != sha256(workbook):
            raise ValueError(f"Tuning workbook changed: {path}")
        if canonical_json_sha256(record.get("configuration")) != canonical_json_sha256(config):
            raise ValueError(f"Tuning configuration changed: {path}")
        if record.get("ablation") != (BASELINE_ID if profile_id == BASELINE_ID else None):
            raise ValueError(f"Tuning ablation changed: {path}")
        result = record.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"Invalid tuning result: {path}")
        provenance = result.get("provenance")
        if (
            not isinstance(provenance, dict)
            or canonical_json_sha256(provenance.get("parameters"))
            != canonical_json_sha256(config)
            or provenance.get("ablation")
            != (BASELINE_ID if profile_id == BASELINE_ID else None)
        ):
            raise ValueError(f"Tuning result provenance changed: {path}")
        if record.get("formula_count") != len(formula_cells):
            raise ValueError(f"Tuning formula count changed: {path}")
        validate_complete_ranking(result.get("ranking", []), formula_cells)
        actions = result.get("review_cells")
        if not isinstance(actions, list):
            raise ValueError(f"Invalid tuning action set: {path}")
        canonical_actions = [canonical_cell(value) for value in actions]
        canonical_formulas = {canonical_cell(value) for value in formula_cells}
        if (
            len(canonical_actions) != len(set(canonical_actions))
            or not set(canonical_actions) <= canonical_formulas
        ):
            raise ValueError(f"Invalid tuning action set: {path}")
        state = result.get("state")
        if state not in DIAGNOSTIC_STATES:
            raise ValueError(f"Invalid tuning diagnostic state: {path}")
        fixed_count = min(5, len(formula_cells))
        expected_actions = {"localized": 1, "review": fixed_count}.get(str(state), 0)
        if len(canonical_actions) != expected_actions:
            raise ValueError(f"Invalid tuning action budget: {path}")
        ranked = [canonical_cell(item["cell"]) for item in result["ranking"]]
        if canonical_actions != ranked[:expected_actions]:
            raise ValueError(f"Tuning actions differ from ranking: {path}")
        if record.get("label_inputs_to_model") != []:
            raise ValueError(f"Labels reached tuning prediction: {path}")


def _mean(values: Sequence[float | int]) -> float:
    return statistics.fmean(values) if values else 0.0


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    inspected = sum(int(row["inspected_cells"]) for row in rows)
    found = sum(int(row["action_hit"]) for row in errors)
    return {
        "cases": len(rows),
        "errors": len(errors),
        "controls": len(controls),
        "state_counts": dict(sorted(Counter(str(row["state"]) for row in rows).items())),
        "supported_rate": _mean([int(row["state"] != "unsupported") for row in rows]),
        "error_top1": _mean([int(row["top1"]) for row in errors]),
        "error_top5": _mean([int(row["top5"]) for row in errors]),
        "error_mrr": _mean([float(row["mrr"]) for row in errors]),
        "control_actionable_rate": _mean([int(row["actionable"]) for row in controls]),
        "inspected_cells": inspected,
        "source_cases_found": found,
        "review_efficiency_per_100_cells": 100 * found / inspected if inspected else 0.0,
    }


def select_profile(
    summaries: Mapping[str, Mapping[str, object]],
    folds: Mapping[str, Sequence[Mapping[str, object]]],
) -> tuple[str | None, dict[str, dict[str, object]]]:
    baseline_efficiency = float(
        summaries[BASELINE_ID]["review_efficiency_per_100_cells"]
    )
    decisions: dict[str, dict[str, object]] = {}
    for profile_id in tuning_profiles():
        summary = summaries[profile_id]
        fold_summaries = [summarize(rows) for rows in folds[profile_id]]
        stable_folds = sum(
            float(fold["error_top5"]) >= 0.50
            and float(fold["control_actionable_rate"]) <= 0.25
            for fold in fold_summaries
        )
        gates = {
            "supported_rate_at_least_80_percent": float(summary["supported_rate"]) >= 0.80,
            "error_top5_at_least_60_percent": float(summary["error_top5"]) >= 0.60,
            "control_actionable_rate_at_most_15_percent": float(summary["control_actionable_rate"]) <= 0.15,
            "efficiency_not_below_no_perturbation": float(
                summary["review_efficiency_per_100_cells"]
            ) >= baseline_efficiency,
            "at_least_four_stable_folds": stable_folds >= 4,
        }
        decisions[profile_id] = {
            "eligible": all(gates.values()),
            "gates": gates,
            "stable_folds": stable_folds,
            "fold_summaries": fold_summaries,
        }
    eligible = [profile_id for profile_id, row in decisions.items() if row["eligible"]]
    if not eligible:
        return None, decisions
    selected = min(eligible, key=lambda profile_id: (
        -min(float(row["error_top5"]) for row in decisions[profile_id]["fold_summaries"]),
        -float(summaries[profile_id]["review_efficiency_per_100_cells"]),
        -float(summaries[profile_id]["error_top5"]),
        float(summaries[profile_id]["control_actionable_rate"]),
        profile_id,
    ))
    return selected, decisions


def _build_events(
    output: Path,
    rows: Sequence[Mapping[str, str]],
    group_by_instance: Mapping[str, str],
    fold_by_instance: Mapping[str, int],
) -> list[dict[str, object]]:
    events = []
    for profile_id in (*tuning_profiles(), BASELINE_ID):
        for row in rows:
            record = json.loads((
                output / "shards" / profile_id / f"{row['instance_id']}.json"
            ).read_text(encoding="utf-8"))
            result = record["result"]
            sources = set(parse_source_cells(row["source_cells"]))
            rank = source_rank(result["ranking"], sources) if sources else None
            actions = set(result["review_cells"])
            events.append({
                "profile_id": profile_id,
                "instance_id": row["instance_id"],
                "corpus_id": row["corpus_id"],
                "group_sha256": group_by_instance[row["instance_id"]],
                "fold": fold_by_instance[row["instance_id"]],
                "case_kind": row["case_kind"],
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Run bounded V5-PSL parameter tuning")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--workers", type=int, default=min(DEFAULT_WORKERS, os.cpu_count() or 1),
    )
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    manifest = args.manifest.resolve()
    root = manifest.parent
    output = args.output.resolve()
    profiles = tuning_profiles()
    try:
        if _git("status", "--porcelain", "--untracked-files=all"):
            raise ValueError("Formal tuning requires a clean Git worktree")
        rows = [row for row in read_manifest(manifest) if row["include"] == "1"]
        source_sha256 = {
            relative: sha256(ROOT / relative)
            for relative in candidate_source_files()
        }
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"V5-PSL tuning refused: {exc}") from exc

    metadata = {
        "protocol": PROTOCOL,
        "git_commit": _git("rev-parse", "HEAD"),
        "manifest_sha256": sha256(manifest),
        "source_sha256": source_sha256,
        "profiles": profiles,
        "baseline": BASELINE_ID,
        "fold_count": FOLD_COUNT,
        "worker_processes_requested": args.workers,
        "label_inputs_to_model": [],
        "labels_used_only_after_all_profile_predictions": [
            "case_kind", "source_cells",
        ],
        "data_role": "revealed_public_development_only",
        "independent_or_preregistered_claim_forbidden": True,
        "third_party_confirmation_files_read": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    for profile_id in (*profiles, BASELINE_ID):
        (output / "shards" / profile_id).mkdir(parents=True, exist_ok=True)
    metadata_path = output / "tuning_metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="utf-8")) != metadata:
            raise SystemExit("V5-PSL tuning resume refused: inputs or source changed")
        if not args.resume:
            raise SystemExit("V5-PSL tuning output exists; pass --resume")
    else:
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )

    pending = []
    for row in rows:
        expected = [
            output / "shards" / profile_id / f"{row['instance_id']}.json"
            for profile_id in (*profiles, BASELINE_ID)
        ]
        if all(path.is_file() for path in expected):
            _audit_case(output, root, row, profiles)
        else:
            pending.append(row)
    workers = min(args.workers, max(1, len(pending)))
    print(
        f"V5-PSL tuning scheduling: workers={workers}; pending={len(pending)}; "
        f"resumed={len(rows) - len(pending)}; profiles={len(profiles)}",
        flush=True,
    )
    payloads = [
        (str(root), str(output), row["instance_id"], row["workbook"])
        for row in pending
    ]
    if workers == 1:
        for index, payload in enumerate(payloads, 1):
            print(f"[{index}/{len(payloads)}] {_case_task(payload)}", flush=True)
    else:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_case_task, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(payloads)}] {future.result()}", flush=True)

    for row in rows:
        _audit_case(output, root, row, profiles)
    group_by_instance, fold_by_instance = assign_group_folds(rows, root)
    events = _build_events(output, rows, group_by_instance, fold_by_instance)
    events_path = output / "tuning_events.csv"
    with events_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EVENT_FIELDS)
        writer.writeheader()
        writer.writerows(events)
    summaries = {
        profile_id: summarize([
            row for row in events if row["profile_id"] == profile_id
        ])
        for profile_id in (*profiles, BASELINE_ID)
    }
    folds = {
        profile_id: [
            [
                row for row in events
                if row["profile_id"] == profile_id and row["fold"] == fold
            ]
            for fold in range(FOLD_COUNT)
        ]
        for profile_id in profiles
    }
    selected, decisions = select_profile(summaries, folds)
    shard_paths = sorted((output / "shards").glob("*/*.json"))
    completion = {
        "protocol": "v5_psl_parameter_tuning_completion_v1",
        "complete": True,
        "cases": len(rows),
        "profiles": len(profiles),
        "shards": len(shard_paths),
        "combined_shards_sha256": aggregate_file_sha256(
            (path.relative_to(output).as_posix(), path) for path in shard_paths
        ),
        "events_sha256": sha256(events_path),
        "metadata_sha256": sha256(metadata_path),
        "summaries": summaries,
        "selection_decisions": decisions,
        "selected_profile": selected,
        "parameter_only_candidate_found": selected is not None,
        "third_party_confirmation_files_read": [],
        "data_are_revealed_development_evidence": True,
        "independent_or_preregistered_claim_forbidden": True,
    }
    completion_path = output / "tuning_complete.json"
    if completion_path.exists():
        raise SystemExit("Refusing to overwrite completed tuning result")
    completion_path.write_text(
        json.dumps(completion, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(completion_path)


if __name__ == "__main__":
    main()
