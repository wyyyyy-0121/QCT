#!/usr/bin/env python3
"""Verify locked FSPR predictions, then score the frozen public transfer gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
from collections import defaultdict
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
    SCHEMA_VERSION,
    SOURCE_PATHS,
    stable_hash,
    validate_record,
)
from scripts.run_fspr_public_predictions import PROTOCOL as PREDICTION_PROTOCOL
from scripts.run_header_partition_predictions import (
    canonical_json,
    sha256,
)
from scripts.score_model_discovery_signals import load_revealed_events

PROTOCOL = "formulaguard_fspr_public_score_v1"
REPRODUCTION_PROTOCOL = "formulaguard_fspr_public_reproduction_v1"
EXPECTED_ERRORS = 190
EXPECTED_CONTROLS = 30
MAJOR_COHORTS = (
    "historical_100",
    "public:integer_corpus",
    "public:modified_euses",
)
DEFAULT_RUN_A = ROOT / "results/fspr_public_predictions_run_a"
DEFAULT_RUN_B = ROOT / "results/fspr_public_predictions_run_b"
DEFAULT_REPRODUCTION_OUTPUT = ROOT / "results/fspr_public_reproduction"
DEFAULT_OUTPUT = ROOT / "results/fspr_public_score"
ZERO_INPUT_FIELDS = (
    "label_inputs",
    "revealed_localization_inputs",
    "answer_workbook_inputs",
    "task_text_inputs",
    "protected_data_inputs",
)
EXPECTED_RUN_FILES = {"completion_receipt.json", "predictions.jsonl"}


def _git_source_status() -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--", *SOURCE_PATHS),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def _load_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    if not isinstance(payload, dict):
        raise TypeError(f"JSON object required: {path}")
    return payload


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="ascii").splitlines(), 1):
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise TypeError(f"JSON object required at {path}:{line_number}")
        rows.append(payload)
    return rows


def _source_hashes() -> dict[str, str]:
    return {path: sha256(ROOT / path) for path in SOURCE_PATHS}


def validate_run(directory: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    observed = {path.name for path in directory.iterdir()}
    if observed != EXPECTED_RUN_FILES:
        raise ValueError(f"unexpected FSPR public run inventory: {directory}")
    receipt_path = directory / "completion_receipt.json"
    predictions_path = directory / "predictions.jsonl"
    receipt = _load_json(receipt_path)
    if (
        receipt.get("protocol") != PREDICTION_PROTOCOL
        or receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("complete") is not True
        or receipt.get("formal_evidence") is not True
        or receipt.get("prediction_records") != EXPECTED_WORKBOOKS
        or receipt.get("selected_identity_rows") != EXPECTED_EVENTS
        or receipt.get("review_budget") != REVIEW_BUDGET
        or receipt.get("selected_cohorts") != list(COHORTS)
    ):
        raise ValueError("FSPR public completion receipt violates the frozen contract")
    if any(receipt.get(field) != [] for field in ZERO_INPUT_FIELDS):
        raise ValueError("FSPR public completion receipt declares forbidden inputs")
    if receipt.get("source_status") != [] or receipt.get("source_sha256") != _source_hashes():
        raise ValueError("FSPR public prediction sources differ from the locked run")
    if _git_source_status():
        raise ValueError("FSPR public prediction/scorer sources are dirty")
    if receipt.get("predictions_sha256") != sha256(predictions_path):
        raise ValueError("FSPR public predictions hash mismatch")
    records = _load_jsonl(predictions_path)
    if len(records) != EXPECTED_WORKBOOKS or receipt.get("record_set_sha256") != stable_hash(records):
        raise ValueError("FSPR public prediction record set is incomplete")
    model_sha256 = str(receipt.get("model_sha256", ""))
    unit_ids: set[str] = set()
    for record in records:
        validate_record(record, model_sha256)
        unit_id = str(record.get("unit_id", ""))
        if not unit_id or unit_id in unit_ids:
            raise ValueError("FSPR public prediction unit IDs are missing or duplicated")
        unit_ids.add(unit_id)
    return receipt, records


def _write_immutable(path: Path, payload: bytes) -> None:
    if path.exists():
        if not path.is_file() or path.read_bytes() != payload:
            raise ValueError(f"completed FSPR output differs: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def verify_reproduction(run_a: Path, run_b: Path, output: Path) -> dict[str, object]:
    if run_a.resolve() == run_b.resolve():
        raise ValueError("FSPR public reproduction requires distinct run directories")
    receipt_a, _ = validate_run(run_a)
    receipt_b, _ = validate_run(run_b)
    hashes_a = {name: sha256(run_a / name) for name in sorted(EXPECTED_RUN_FILES)}
    hashes_b = {name: sha256(run_b / name) for name in sorted(EXPECTED_RUN_FILES)}
    payload = {
        "protocol": REPRODUCTION_PROTOCOL,
        "complete": True,
        "run_a_hashes": hashes_a,
        "run_b_hashes": hashes_b,
        "byte_identical": hashes_a == hashes_b,
        "source_state_identical": receipt_a.get("source_sha256")
        == receipt_b.get("source_sha256"),
        "model_identical": receipt_a.get("model_sha256") == receipt_b.get("model_sha256"),
        "all_prediction_gates_passed": hashes_a == hashes_b
        and receipt_a.get("source_sha256") == receipt_b.get("source_sha256")
        and receipt_a.get("model_sha256") == receipt_b.get("model_sha256"),
        "label_inputs": [],
        "revealed_localization_inputs": [],
        "answer_workbook_inputs": [],
        "task_text_inputs": [],
        "protected_data_inputs": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    if {path.name for path in output.iterdir()} - {"reproduction_receipt.json"}:
        raise ValueError("unexpected FSPR public reproduction output")
    _write_immutable(
        output / "reproduction_receipt.json",
        (canonical_json(payload) + "\n").encode("ascii"),
    )
    return payload


def _source_rank(ranking: Sequence[str], sources: Sequence[str]) -> int | None:
    positions = {cell: index for index, cell in enumerate(ranking, 1)}
    values = [positions[cell] for cell in sources if cell in positions]
    return min(values) if values else None


def attach_events(
    events: Sequence[Mapping[str, object]],
    records: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_hash = {str(record["workbook_sha256"]): record for record in records}
    rows = []
    for event in events:
        workbook_hash = sha256(Path(event["path"]))
        if workbook_hash not in by_hash:
            raise ValueError("revealed event workbook is absent from locked FSPR predictions")
        prediction = by_hash[workbook_hash]
        if event["cohort"] != prediction["cohort"]:
            raise ValueError("revealed event cohort differs from locked FSPR prediction")
        v4 = [str(cell) for cell in prediction["v4_ranking"]]
        fspr = [str(cell) for cell in prediction["fspr_ranking"]]
        sources = [str(cell) for cell in event["source_cells"] if str(cell) in set(v4)]
        v4_rank = _source_rank(v4, sources)
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
                "ranking_changed": bool(prediction["ranking_changed"]),
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


def _event_metrics(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not rows:
        raise ValueError("cannot summarize an empty FSPR event cohort")
    rescues = sum(int(row["rescue"]) for row in rows)
    losses = sum(int(row["loss"]) for row in rows)
    return {
        "events": len(rows),
        "v4_top5": statistics.fmean(float(row["v4_top5"]) for row in rows),
        "fspr_top5": statistics.fmean(float(row["fspr_top5"]) for row in rows),
        "top5_delta": statistics.fmean(
            float(row["fspr_top5"]) - float(row["v4_top5"]) for row in rows
        ),
        "v4_mrr": statistics.fmean(float(row["v4_mrr"]) for row in rows),
        "fspr_mrr": statistics.fmean(float(row["fspr_mrr"]) for row in rows),
        "mrr_delta": statistics.fmean(
            float(row["fspr_mrr"]) - float(row["v4_mrr"]) for row in rows
        ),
        "rescues": rescues,
        "losses": losses,
        "net_rescues": rescues - losses,
    }


def _structure_macro(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    groups: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        groups[str(row["structure_group"])].append(row)
    group_rows = []
    for group, values in sorted(groups.items()):
        group_rows.append(
            {
                "structure_group": group,
                "events": len(values),
                "v4_top5": statistics.fmean(float(row["v4_top5"]) for row in values),
                "fspr_top5": statistics.fmean(float(row["fspr_top5"]) for row in values),
                "v4_mrr": statistics.fmean(float(row["v4_mrr"]) for row in values),
                "fspr_mrr": statistics.fmean(float(row["fspr_mrr"]) for row in values),
            }
        )
    if not group_rows:
        raise ValueError("cannot summarize empty FSPR structure groups")
    v4_top5 = statistics.fmean(float(row["v4_top5"]) for row in group_rows)
    fspr_top5 = statistics.fmean(float(row["fspr_top5"]) for row in group_rows)
    v4_mrr = statistics.fmean(float(row["v4_mrr"]) for row in group_rows)
    fspr_mrr = statistics.fmean(float(row["fspr_mrr"]) for row in group_rows)
    return {
        "groups": len(group_rows),
        "events": len(rows),
        "v4_top5": v4_top5,
        "fspr_top5": fspr_top5,
        "top5_delta": fspr_top5 - v4_top5,
        "v4_mrr": v4_mrr,
        "fspr_mrr": fspr_mrr,
        "mrr_delta": fspr_mrr - v4_mrr,
        "group_records": group_rows,
    }


def summarize(
    rows: Sequence[Mapping[str, object]],
    reproduction: Mapping[str, object],
) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    if len(rows) != EXPECTED_EVENTS or len(errors) != EXPECTED_ERRORS or len(controls) != EXPECTED_CONTROLS:
        raise ValueError("FSPR revealed event counts differ from preregistration")
    overall = _event_metrics(errors)
    structure_macro = _structure_macro(errors)
    by_cohort = {
        cohort: _event_metrics([row for row in errors if row["cohort"] == cohort])
        for cohort in COHORTS
        if any(row["cohort"] == cohort for row in errors)
    }
    control_units = {str(row["unit_id"]) for row in controls}
    changed_controls = {
        str(row["unit_id"]) for row in controls if row["ranking_changed"] is True
    }
    control_rate = len(changed_controls) / len(control_units)
    gates = {
        "g1_structure_macro_top5_delta_at_least_2pp": structure_macro["top5_delta"] >= 0.02,
        "g1_structure_macro_mrr_non_degradation": structure_macro["mrr_delta"] >= 0.0,
        "g2_net_top5_rescues_at_least_5": overall["net_rescues"] >= 5,
        "g2_top5_losses_at_most_2": overall["losses"] <= 2,
        "g3_enron_top5_non_degradation": by_cohort["enron"]["top5_delta"] >= 0.0,
        "g3_enron_mrr_non_degradation": by_cohort["enron"]["mrr_delta"] >= 0.0,
        "g3_other_major_cohort_regression_at_most_5pp": all(
            by_cohort[cohort]["top5_delta"] >= -0.05 for cohort in MAJOR_COHORTS
        ),
        "g4_control_ranking_change_rate_at_most_15pct": control_rate <= 0.15,
        "g5_prediction_runs_byte_identical": reproduction.get("byte_identical") is True,
        "g5_prediction_integrity": reproduction.get("all_prediction_gates_passed") is True,
    }
    return {
        "overall_error_event_micro": overall,
        "overall_error_structure_macro": structure_macro,
        "by_cohort_error_event_micro": by_cohort,
        "controls": {
            "events": len(controls),
            "workbooks": len(control_units),
            "ranking_change_workbooks": len(changed_controls),
            "ranking_change_rate": control_rate,
        },
        "public_gates": gates,
        "all_public_gates_passed": all(gates.values()),
    }


def write_score(
    output: Path,
    rows: Sequence[Mapping[str, object]],
    summary: Mapping[str, object],
) -> None:
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise ValueError("FSPR score output or partial directory already exists")
    partial.mkdir(parents=True)
    try:
        event_path = partial / "event_scores.jsonl"
        event_bytes = "".join(canonical_json(row) + "\n" for row in rows).encode("ascii")
        event_path.write_bytes(event_bytes)
        payload = {**dict(summary), "event_scores_sha256": hashlib.sha256(event_bytes).hexdigest()}
        (partial / "score_summary.json").write_text(
            canonical_json(payload) + "\n",
            encoding="ascii",
        )
        os.replace(partial, output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def score(run_a: Path, run_b: Path, reproduction_output: Path, output: Path) -> dict[str, object]:
    reproduction = verify_reproduction(run_a, run_b, reproduction_output)
    if reproduction.get("all_prediction_gates_passed") is not True:
        raise ValueError("FSPR public prediction reproduction failed")
    _, records = validate_run(run_a)
    events, label_files = load_revealed_events()
    rows = attach_events(events, records)
    metrics = summarize(rows, reproduction)
    summary = {
        "protocol": PROTOCOL,
        "complete": True,
        "scorer_git_commit": subprocess.run(
            ("git", "rev-parse", "HEAD"),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "prediction_reproduction_sha256": sha256(
            reproduction_output / "reproduction_receipt.json"
        ),
        "prediction_model_sha256": records[0]["model_sha256"],
        "events": len(rows),
        "errors": EXPECTED_ERRORS,
        "controls": EXPECTED_CONTROLS,
        "review_budget": REVIEW_BUDGET,
        "label_files_read": label_files,
        "protected_data_inputs": [],
        **metrics,
    }
    write_score(output, rows, summary)
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-a", type=Path, default=DEFAULT_RUN_A)
    parser.add_argument("--run-b", type=Path, default=DEFAULT_RUN_B)
    parser.add_argument(
        "--reproduction-output",
        type=Path,
        default=DEFAULT_REPRODUCTION_OUTPUT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.verify_only:
            payload = verify_reproduction(
                args.run_a.resolve(),
                args.run_b.resolve(),
                args.reproduction_output.resolve(),
            )
        else:
            payload = score(
                args.run_a.resolve(),
                args.run_b.resolve(),
                args.reproduction_output.resolve(),
                args.output.resolve(),
            )
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"FSPR public scoring refused: {exc}") from exc
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
