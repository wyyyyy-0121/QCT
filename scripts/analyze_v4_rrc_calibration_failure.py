"""Explain a failed V4-RRC D0 calibration without changing its model."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    build_units,
    event_prediction_rows,
    fit_fold,
    load_event_rows,
    load_json,
    load_shards,
    predict_units,
    sha256,
    stable_hash,
    summarize_predictions,
)


PROTOCOL = "formulaguard_v4_rrc_calibration_failure_audit_v1"
DEFAULT_D0 = ROOT / "results/v4_rrc_d0"
DEFAULT_OUTPUT = ROOT / "results/v4_rrc_d0_failure_analysis.json"
SUMMARY_FIELDS = (
    "residual_event_gains",
    "acted_error_events",
    "positive_residual_action_precision",
    "v4_hit_loss_rate",
    "control_workbook_action_rate",
    "top5_difference",
    "action_units",
)


def compact(summary: Mapping[str, object]) -> dict[str, object]:
    return {field: summary[field] for field in SUMMARY_FIELDS}


def best(
    rows: Sequence[tuple[float, Mapping[str, object]]], field: str,
) -> dict[str, object] | None:
    if not rows:
        return None
    threshold, summary = max(
        rows,
        key=lambda row: (float(row[1][field]), -int(row[1]["action_units"]), row[0]),
    )
    return {"threshold": threshold, **compact(summary)}


def analyze(d0_dir: Path) -> dict[str, object]:
    receipt = load_json(d0_dir / "receipt.json")
    if receipt.get("protocol") != "formulaguard_v4_residual_controller_crossfit_v1":
        raise ValueError("unexpected D0 receipt")
    if receipt["decision"]["passed"] is not False:
        raise ValueError("calibration failure audit requires a failed D0")
    fold_records = json.loads((d0_dir / "fold_models.json").read_text(encoding="utf-8"))
    events = load_event_rows(DEFAULT_EVENTS)
    signals, _ = load_shards(DEFAULT_SIGNALS, kind="signal")
    v4, _ = load_shards(DEFAULT_V4, kind="V4")
    units = build_units(events, signals, v4)
    folds = []
    for outer in range(5):
        calibration_fold = (outer + 1) % 5
        train = [unit for unit in units if unit.fold not in {outer, calibration_fold}]
        calibration = [unit for unit in units if unit.fold == calibration_fold]
        model = fit_fold(train, revision=0)
        official = next(row for row in fold_records if row["outer_fold"] == outer)
        if model.to_dict() != official["model"]:
            raise ValueError(f"recomputed fold {outer} model differs from D0 artifact")
        predictions = predict_units(model, calibration, revision=0)
        scores = sorted({
            float(row["score"]) for row in predictions.values()
            if row["score"] is not None
        }, reverse=True)
        curves: list[tuple[float, Mapping[str, object]]] = []
        for score in scores:
            threshold = math.nextafter(score, -math.inf)
            summary = summarize_predictions(event_prediction_rows(
                calibration, predictions, threshold, outer_fold=None,
            ))
            curves.append((threshold, summary))
        with_three = [row for row in curves if int(row[1]["residual_event_gains"]) >= 3]
        safe_control = [
            row for row in with_three
            if row[1]["control_workbook_action_rate"] is not None
            and float(row[1]["control_workbook_action_rate"]) <= 0.15
        ]
        safe_loss = [
            row for row in safe_control
            if float(row[1]["v4_hit_loss_rate"]) <= 0.02
        ]
        eligible = [
            row for row in safe_loss
            if float(row[1]["positive_residual_action_precision"]) >= 0.75
        ]
        control_units = {
            unit.unit_id for unit in calibration
            if any(event["case_kind"] == "control" for event in unit.events)
        }
        folds.append({
            "outer_fold": outer,
            "calibration_fold": calibration_fold,
            "calibration_control_workbooks": len(control_units),
            "candidate_thresholds": len(curves),
            "thresholds_with_at_least_three_gains": len(with_three),
            "thresholds_also_safe_on_controls": len(safe_control),
            "thresholds_also_safe_on_v4_hits": len(safe_loss),
            "fully_eligible_thresholds": len(eligible),
            "best_precision_with_at_least_three_gains": best(
                with_three, "positive_residual_action_precision",
            ),
            "best_precision_after_control_and_v4_loss_constraints": best(
                safe_loss, "positive_residual_action_precision",
            ),
            "best_gain_after_control_and_v4_loss_constraints": best(
                safe_loss, "residual_event_gains",
            ),
        })
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "d0": {
            "receipt_path": "results/v4_rrc_d0/receipt.json",
            "receipt_sha256": sha256(d0_dir / "receipt.json"),
            "git_commit": receipt["git_commit"],
            "passed": receipt["decision"]["passed"],
        },
        "folds": folds,
        "conclusion": {
            "finite_thresholds": sum(row["fully_eligible_thresholds"] for row in folds),
            "all_folds_below_75pct_precision_with_three_gains": all(
                row["best_precision_with_at_least_three_gains"] is not None
                and float(row["best_precision_with_at_least_three_gains"]["positive_residual_action_precision"]) < 0.75
                for row in folds
            ),
            "failure_is_not_only_control_risk": any(
                row["best_precision_after_control_and_v4_loss_constraints"] is not None
                and float(row["best_precision_after_control_and_v4_loss_constraints"]["positive_residual_action_precision"]) < 0.75
                for row in folds
            ),
            "d1_allowed": receipt["decision"]["single_revision_allowed"],
            "line_stopped": not receipt["decision"]["single_revision_allowed"],
        },
        "protected_data_inputs": [],
    }
    payload["receipt_sha256"] = stable_hash(payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--d0-dir", type=Path, default=DEFAULT_D0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    payload = analyze(args.d0_dir.resolve())
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output = args.output.resolve()
    if output.exists():
        if output.read_bytes() != encoded:
            raise ValueError(f"completed failure audit differs: {output}")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(encoded)
        os.replace(temporary, output)
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
