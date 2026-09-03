"""Audit fifth-slot channel selection with structure-isolated outer folds."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    DEFAULT_SIGNALS,
    DEFAULT_V4,
    load_event_rows,
    load_shards,
    reject_protected,
    sha256,
    stable_hash,
)
from scripts.run_v4_static_fifth_experiment import (
    _bootstrap_delta,
    _metrics,
    git_commit,
    relative,
    score,
)

PROTOCOL = "formulaguard_v4_fifth_channel_structure_crossfit_v1"
CHANNELS = ("combined", "peer", "role", "impact")
DEFAULT_OUTPUT = ROOT / "results/v4_peer_channel_crossfit/receipt.json"


def _insert_fifth(v4: Sequence[str], candidate: str | None) -> list[str]:
    ranking = list(v4)
    if candidate is None or len(ranking) <= 5 or candidate in ranking[:5]:
        return ranking
    if candidate not in ranking:
        raise ValueError("channel candidate is outside the V4 inventory")
    ranking.remove(candidate)
    ranking.insert(4, candidate)
    return ranking


def channel_predictions(
    v4: Mapping[str, Mapping[str, object]],
    signals: Mapping[str, Mapping[str, object]],
    channel: str,
) -> dict[str, dict[str, object]]:
    if channel not in CHANNELS:
        raise ValueError(f"unknown fifth-slot channel: {channel}")
    predictions: dict[str, dict[str, object]] = {}
    for unit_id in sorted(v4):
        v4_cells = [str(row["cell"]) for row in v4[unit_id]["ranking"]]
        audit = signals[unit_id]["audit"]
        if audit.get("label_inputs") != []:
            raise ValueError(f"channel signal consumed labels: {unit_id}")
        review = [str(cell) for cell in audit["review_cells"][channel]]
        predictions[unit_id] = {
            "ranking": _insert_fifth(v4_cells, review[0] if review else None),
        }
    return predictions


def _loss_rate(rows: Sequence[Mapping[str, object]]) -> float:
    hits = sum(int(row["v4_top5"]) for row in rows)
    losses = sum(int(row["candidate_top5"]) < int(row["v4_top5"]) for row in rows)
    return losses / max(1, hits)


def choose_channel(
    channel_rows: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    outer_fold: int,
) -> tuple[str, dict[str, object]]:
    options = []
    for order, channel in enumerate(CHANNELS):
        train = [row for row in channel_rows[channel] if int(row["fold"]) != outer_fold]
        metrics = _metrics(train)
        loss_rate = _loss_rate(train)
        eligible = metrics["mrr_delta"] >= 0.0 and loss_rate <= 0.02
        key = (
            int(eligible),
            float(metrics["top5_delta_pp"]),
            float(metrics["mrr_delta"]),
            -loss_rate,
            -order,
        )
        options.append((key, channel, {**metrics, "v4_hit_loss_rate": loss_rate}))
    _key, channel, metrics = max(options, key=lambda row: row[0])
    return channel, metrics


def run(
    *,
    events_path: Path,
    v4_dir: Path,
    signal_dir: Path,
    output: Path,
) -> Path:
    for path in (events_path, v4_dir, signal_dir, output):
        reject_protected(path)
    events = load_event_rows(events_path)
    v4, v4_complete = load_shards(v4_dir, kind="V4")
    signals, signal_complete = load_shards(signal_dir, kind="peer signal")
    channel_rows: dict[str, list[dict[str, object]]] = {}
    for channel in CHANNELS:
        _summary, rows = score(events, channel_predictions(v4, signals, channel))
        channel_rows[channel] = rows

    fold_receipts = []
    crossfit_rows: list[dict[str, object]] = []
    for outer_fold in range(5):
        channel, training_metrics = choose_channel(channel_rows, outer_fold=outer_fold)
        held_out = [
            {**row, "selected_channel": channel}
            for row in channel_rows[channel]
            if int(row["fold"]) == outer_fold
        ]
        held_out_metrics = _metrics(held_out)
        crossfit_rows.extend(held_out)
        fold_receipts.append({
            "outer_fold": outer_fold,
            "training_folds": [fold for fold in range(5) if fold != outer_fold],
            "selected_channel": channel,
            "training_metrics": training_metrics,
            "held_out_metrics": held_out_metrics,
            "held_out_v4_hit_loss_rate": _loss_rate(held_out),
        })
    crossfit_rows.sort(key=lambda row: str(row["event_id"]))
    overall = _metrics(crossfit_rows)
    overall["v4_miss_recovery_rate"] = overall["recovered_events"] / max(
        1, sum(int(row["v4_top5"]) == 0 for row in crossfit_rows),
    )
    overall["v4_hit_loss_rate"] = _loss_rate(crossfit_rows)
    cohorts = {
        cohort: _metrics([row for row in crossfit_rows if row["cohort"] == cohort])
        for cohort in sorted({str(row["cohort"]) for row in crossfit_rows})
    }
    bootstrap = _bootstrap_delta(crossfit_rows)
    selected = [str(row["selected_channel"]) for row in fold_receipts]
    gates = {
        "crossfit_top5_gain_at_least_10pp": overall["top5_delta_pp"] >= 10.0,
        "crossfit_mrr_nonnegative": overall["mrr_delta"] >= 0.0,
        "crossfit_v4_hit_loss_at_most_2pct": overall["v4_hit_loss_rate"] <= 0.02,
        "all_outer_folds_top5_positive": all(
            row["held_out_metrics"]["top5_delta_pp"] > 0.0 for row in fold_receipts
        ),
        "all_main_cohorts_top5_nonnegative": all(
            cohorts[name]["top5_delta_pp"] >= 0.0
            for name in ("enron", "historical_100", "public:integer_corpus", "public:modified_euses")
        ),
        "structure_bootstrap_lower_bound_positive": bootstrap["ci95_delta_pp"][0] > 0.0,
        "peer_selected_in_at_least_four_folds": selected.count("peer") >= 4,
    }
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_git_commit": git_commit(),
        "selection": {
            "candidate_channels": list(CHANNELS),
            "training_only_constraints": {
                "mrr_delta_minimum": 0.0,
                "v4_hit_loss_rate_maximum": 0.02,
            },
            "objective": "maximum_structure_macro_top5_delta",
            "tie_breaks": ["mrr_delta", "lower_v4_hit_loss", "fixed_channel_order"],
            "outer_test_labels_used_for_selection": False,
        },
        "inputs": {
            "events": {"path": relative(events_path), "sha256": sha256(events_path)},
            "v4_combined_shards_sha256": v4_complete["combined_shards_sha256"],
            "signal_combined_shards_sha256": signal_complete["combined_shards_sha256"],
        },
        "folds": fold_receipts,
        "selected_channels": selected,
        "overall": overall,
        "by_cohort": cohorts,
        "structure_group_bootstrap": bootstrap,
        "gates": gates,
        "all_crossfit_gates_passed": all(gates.values()),
        "crossfit_event_rows_sha256": stable_hash(crossfit_rows),
        "protected_data_inputs": [],
    }
    payload["receipt_sha256"] = stable_hash(payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError("crossfit receipt already exists")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--signals", type=Path, default=DEFAULT_SIGNALS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    try:
        path = run(
            events_path=args.events.resolve(),
            v4_dir=args.v4.resolve(),
            signal_dir=args.signals.resolve(),
            output=args.output.resolve(),
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"peer channel crossfit audit refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
