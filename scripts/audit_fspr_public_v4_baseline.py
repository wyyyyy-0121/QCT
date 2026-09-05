#!/usr/bin/env python3
"""Audit locked FSPR predictions against the immutable V4-R1 baseline."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_fspr_public_predictions import (
    COHORTS,
    EXPECTED_EVENTS,
    EXPECTED_WORKBOOKS,
    REVIEW_BUDGET,
)
from scripts.run_header_partition_predictions import (
    canonical_json,
    sha256,
)
from scripts.score_fspr_public_predictions import (
    EXPECTED_CONTROLS,
    EXPECTED_ERRORS,
    EXPECTED_RUN_FILES,
    MAJOR_COHORTS,
    _event_metrics,
    _source_rank,
    _structure_macro,
    load_revealed_events,
    validate_run,
)
from scripts.score_sfri_predictions import validate_v4_run

PROTOCOL = "formulaguard_fspr_public_frozen_v4_audit_v1"
DEFAULT_RUN_A = ROOT / "results/fspr_public_predictions_run_a"
DEFAULT_RUN_B = ROOT / "results/fspr_public_predictions_run_b"
DEFAULT_V4 = ROOT / "results/model_discovery_v4_baseline"
DEFAULT_OUTPUT = ROOT / "results/fspr_public_frozen_v4_audit"
SOURCE_PATHS = (
    "scripts/audit_fspr_public_v4_baseline.py",
    "scripts/run_fspr_public_predictions.py",
    "scripts/score_fspr_public_predictions.py",
    "scripts/score_model_discovery_signals.py",
    "scripts/score_sfri_predictions.py",
)


def _source_state() -> dict[str, object]:
    status = subprocess.run(
        ("git", "status", "--porcelain", "--", *SOURCE_PATHS),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if status:
        raise ValueError("formal FSPR baseline audit requires clean scorer sources")
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return {
        "git_commit": commit,
        "source_sha256": {path: sha256(ROOT / path) for path in SOURCE_PATHS},
        "source_status": [],
        "formal_evidence": True,
    }


def _ranking(record: Mapping[str, object]) -> list[str]:
    rows = record.get("ranking")
    if not isinstance(rows, list):
        raise TypeError("frozen V4 ranking is malformed")
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise TypeError("frozen V4 ranking row is malformed")
        result.append(str(row["cell"]))
    return result


def _first_difference(left: Sequence[str], right: Sequence[str]) -> int | None:
    for index, values in enumerate(zip(left, right), 1):
        if values[0] != values[1]:
            return index
    if len(left) != len(right):
        return min(len(left), len(right)) + 1
    return None


def compare_frozen_v4(
    predictions: Sequence[Mapping[str, object]],
    frozen_by_hash: Mapping[str, Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, object]]:
    rows: list[dict[str, object]] = []
    cohort_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for prediction in predictions:
        workbook_hash = str(prediction["workbook_sha256"])
        frozen = frozen_by_hash.get(workbook_hash)
        if frozen is None:
            raise ValueError("locked FSPR workbook is absent from frozen V4 baseline")
        baseline = _ranking(frozen)
        embedded = [str(cell) for cell in prediction["v4_ranking"]]
        fspr = [str(cell) for cell in prediction["fspr_ranking"]]
        inventory_match = (
            len(baseline) == len(embedded) == len(fspr)
            and set(baseline) == set(embedded) == set(fspr)
        )
        full_match = embedded == baseline
        embedded_prefix_match = embedded[:4] == baseline[:4]
        fspr_prefix_match = fspr[:4] == baseline[:4]
        fspr_changed = fspr != baseline
        cohort = str(prediction["cohort"])
        counts = cohort_counts[cohort]
        counts["workbooks"] += 1
        counts["formula_inventory_matches"] += int(inventory_match)
        counts["embedded_v4_full_matches"] += int(full_match)
        counts["embedded_v4_prefix_matches"] += int(embedded_prefix_match)
        counts["fspr_frozen_prefix_matches"] += int(fspr_prefix_match)
        counts["fspr_changes_vs_frozen_v4"] += int(fspr_changed)
        rows.append(
            {
                "unit_id": str(prediction["unit_id"]),
                "workbook_sha256": workbook_hash,
                "cohort": cohort,
                "formula_count": len(fspr),
                "formula_inventory_match": inventory_match,
                "embedded_v4_full_match": full_match,
                "embedded_v4_prefix_match": embedded_prefix_match,
                "fspr_frozen_prefix_match": fspr_prefix_match,
                "fspr_changed_vs_frozen_v4": fspr_changed,
                "first_embedded_v4_difference_rank": _first_difference(
                    embedded, baseline
                ),
            }
        )
    rows.sort(key=lambda row: str(row["unit_id"]))
    totals: Counter[str] = Counter()
    for counts in cohort_counts.values():
        totals.update(counts)
    summary = {
        **dict(sorted(totals.items())),
        "embedded_v4_full_mismatches": (
            totals["workbooks"] - totals["embedded_v4_full_matches"]
        ),
        "embedded_v4_prefix_mismatches": (
            totals["workbooks"] - totals["embedded_v4_prefix_matches"]
        ),
        "fspr_frozen_prefix_mismatches": (
            totals["workbooks"] - totals["fspr_frozen_prefix_matches"]
        ),
        "by_cohort": {
            cohort: dict(sorted(counts.items()))
            for cohort, counts in sorted(cohort_counts.items())
        },
    }
    return rows, summary


def build_event_scores(
    events: Sequence[Mapping[str, object]],
    predictions: Sequence[Mapping[str, object]],
    frozen_by_hash: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    prediction_by_hash = {
        str(prediction["workbook_sha256"]): prediction
        for prediction in predictions
    }
    rows = []
    for event in events:
        workbook_hash = sha256(Path(event["path"]))
        prediction = prediction_by_hash.get(workbook_hash)
        frozen = frozen_by_hash.get(workbook_hash)
        if prediction is None or frozen is None:
            raise ValueError("revealed event lacks a locked prediction or V4 baseline")
        if event["cohort"] != prediction["cohort"]:
            raise ValueError("revealed event cohort differs from locked prediction")
        baseline = _ranking(frozen)
        fspr = [str(cell) for cell in prediction["fspr_ranking"]]
        sources = [
            str(cell) for cell in event["source_cells"] if str(cell) in set(baseline)
        ]
        v4_rank = _source_rank(baseline, sources)
        fspr_rank = _source_rank(fspr, sources)
        v4_top5 = int(v4_rank is not None and v4_rank <= REVIEW_BUDGET)
        fspr_top5 = int(fspr_rank is not None and fspr_rank <= REVIEW_BUDGET)
        rows.append(
            {
                "event_id": str(event["event_id"]),
                "unit_id": str(prediction["unit_id"]),
                "cohort": str(event["cohort"]),
                "case_kind": str(event["case_kind"]),
                "structure_group": str(prediction["structure_cluster_id"]),
                "source_formula_cells": sources,
                "ranking_changed_vs_frozen_v4": fspr != baseline,
                "v4_source_rank": v4_rank,
                "fspr_source_rank": fspr_rank,
                "v4_top5": v4_top5,
                "fspr_top5": fspr_top5,
                "v4_mrr": 1.0 / v4_rank if v4_rank else 0.0,
                "fspr_mrr": 1.0 / fspr_rank if fspr_rank else 0.0,
                "rescue": int(v4_top5 == 0 and fspr_top5 == 1),
                "loss": int(v4_top5 == 1 and fspr_top5 == 0),
            }
        )
    return sorted(rows, key=lambda row: str(row["event_id"]))


def summarize(
    event_rows: Sequence[Mapping[str, object]],
    baseline_audit: Mapping[str, object],
    *,
    predictions_byte_identical: bool,
) -> dict[str, object]:
    errors = [row for row in event_rows if row["case_kind"] == "error"]
    controls = [row for row in event_rows if row["case_kind"] == "control"]
    if (
        len(event_rows) != EXPECTED_EVENTS
        or len(errors) != EXPECTED_ERRORS
        or len(controls) != EXPECTED_CONTROLS
    ):
        raise ValueError("FSPR frozen-baseline event inventory is incomplete")
    overall = _event_metrics(errors)
    structure_macro = _structure_macro(errors)
    by_cohort = {
        cohort: _event_metrics([row for row in errors if row["cohort"] == cohort])
        for cohort in COHORTS
        if any(row["cohort"] == cohort for row in errors)
    }
    control_units = {str(row["unit_id"]) for row in controls}
    changed_controls = {
        str(row["unit_id"])
        for row in controls
        if row["ranking_changed_vs_frozen_v4"] is True
    }
    control_rate = len(changed_controls) / len(control_units)
    reference_match = baseline_audit.get("embedded_v4_full_mismatches") == 0
    prefix_match = baseline_audit.get("fspr_frozen_prefix_mismatches") == 0
    gates = {
        "g1_structure_macro_top5_delta_at_least_2pp": (
            structure_macro["top5_delta"] >= 0.02
        ),
        "g1_structure_macro_mrr_non_degradation": (
            structure_macro["mrr_delta"] >= 0.0
        ),
        "g2_net_top5_rescues_at_least_5": overall["net_rescues"] >= 5,
        "g2_top5_losses_at_most_2": overall["losses"] <= 2,
        "g3_enron_top5_non_degradation": by_cohort["enron"]["top5_delta"] >= 0.0,
        "g3_enron_mrr_non_degradation": by_cohort["enron"]["mrr_delta"] >= 0.0,
        "g3_other_major_cohort_regression_at_most_5pp": all(
            by_cohort[cohort]["top5_delta"] >= -0.05 for cohort in MAJOR_COHORTS
        ),
        "g4_control_ranking_change_rate_at_most_15pct": control_rate <= 0.15,
        "g5_prediction_runs_byte_identical": predictions_byte_identical,
        "g5_frozen_v4_full_reference_match": reference_match,
        "g5_frozen_v4_prefix_integrity": prefix_match,
    }
    return {
        "overall_error_event_micro": overall,
        "overall_error_structure_macro": structure_macro,
        "by_cohort_error_event_micro": by_cohort,
        "controls": {
            "events": len(controls),
            "workbooks": len(control_units),
            "ranking_change_workbooks_vs_frozen_v4": len(changed_controls),
            "ranking_change_rate_vs_frozen_v4": control_rate,
        },
        "public_gates": gates,
        "failed_gates": sorted(key for key, value in gates.items() if not value),
        "all_public_gates_passed": all(gates.values()),
    }


def _write_outputs(
    output: Path,
    workbook_rows: Sequence[Mapping[str, object]],
    event_rows: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> None:
    output = output.resolve()
    if not output.is_relative_to(ROOT):
        raise ValueError("FSPR frozen-baseline audit output must remain inside the repository")
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise ValueError("FSPR frozen-baseline audit output already exists")
    partial.mkdir(parents=True)
    try:
        workbook_path = partial / "workbook_baseline_audit.jsonl"
        event_path = partial / "event_scores.jsonl"
        workbook_path.write_text(
            "".join(canonical_json(row) + "\n" for row in workbook_rows),
            encoding="ascii",
        )
        event_path.write_text(
            "".join(canonical_json(row) + "\n" for row in event_rows),
            encoding="ascii",
        )
        payload = {
            **dict(summary),
            "workbook_baseline_audit_sha256": sha256(workbook_path),
            "event_scores_sha256": sha256(event_path),
        }
        (partial / "audit_summary.json").write_text(
            canonical_json(payload) + "\n",
            encoding="ascii",
        )
        os.replace(partial, output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def audit(
    run_a: Path,
    run_b: Path,
    v4_dir: Path,
    output: Path,
) -> dict[str, object]:
    source_state = _source_state()
    receipt_a, predictions_a = validate_run(run_a)
    receipt_b, predictions_b = validate_run(run_b)
    run_hashes_a = {name: sha256(run_a / name) for name in sorted(EXPECTED_RUN_FILES)}
    run_hashes_b = {name: sha256(run_b / name) for name in sorted(EXPECTED_RUN_FILES)}
    byte_identical = run_hashes_a == run_hashes_b
    if not byte_identical or predictions_a != predictions_b:
        raise ValueError("locked FSPR public prediction runs are not byte identical")
    if len(predictions_a) != EXPECTED_WORKBOOKS:
        raise ValueError("locked FSPR public prediction inventory is incomplete")
    v4 = validate_v4_run(v4_dir)
    frozen_by_hash = v4["records_by_hash"]
    if not isinstance(frozen_by_hash, Mapping) or len(frozen_by_hash) != EXPECTED_WORKBOOKS:
        raise ValueError("frozen V4 baseline inventory is incomplete")
    if set(frozen_by_hash) != {
        str(record["workbook_sha256"]) for record in predictions_a
    }:
        raise ValueError("FSPR and frozen V4 workbook inventories differ")
    workbook_rows, baseline_summary = compare_frozen_v4(
        predictions_a, frozen_by_hash
    )
    events, label_files = load_revealed_events()
    event_rows = build_event_scores(events, predictions_a, frozen_by_hash)
    metrics = summarize(
        event_rows,
        baseline_summary,
        predictions_byte_identical=byte_identical,
    )
    if _source_state() != source_state:
        raise ValueError("FSPR frozen-baseline audit source changed during the run")
    complete = v4["complete"]
    summary = {
        "protocol": PROTOCOL,
        "complete": True,
        "audit_kind": "post_lock_read_only_protocol_audit",
        **source_state,
        "prediction_run_a_hashes": run_hashes_a,
        "prediction_run_b_hashes": run_hashes_b,
        "prediction_receipt_a_commit": receipt_a["git_commit"],
        "prediction_receipt_b_commit": receipt_b["git_commit"],
        "frozen_v4_combined_shards_sha256": complete["combined_shards_sha256"],
        "label_files_read": label_files,
        "protected_data_inputs": [],
        "post_lock_model_changes": [],
        "post_lock_prediction_changes": [],
        "baseline_audit": baseline_summary,
        **metrics,
        "spreadsheetbench_v2_download_authorized": False,
        "version_artifact_authorized": False,
        "disposition": "stop_fspr_public_protocol_failure",
    }
    _write_outputs(output, workbook_rows, event_rows, summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-a", type=Path, default=DEFAULT_RUN_A)
    parser.add_argument("--run-b", type=Path, default=DEFAULT_RUN_B)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        payload = audit(
            args.run_a.resolve(),
            args.run_b.resolve(),
            args.v4.resolve(),
            args.output.resolve(),
        )
    except (
        OSError,
        TypeError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        raise SystemExit(f"FSPR frozen-baseline audit refused: {exc}") from exc
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
