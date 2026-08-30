"""Audit whether existing label-free channels contain V4 residual headroom.

This is a revealed-label feasibility diagnostic, not a deployable selector.  It
asks whether an oracle that may retain V4's fifth cell or replace it with one
cell from a channel's five-cell candidate pool could recover additional source
hits while preserving the five-cell review budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVENTS = ROOT / "results/model_discovery_gate2_final_v3/event_scores.jsonl"
DEFAULT_OUTPUT = ROOT / "results/v4_residual_headroom_v0/receipt.json"
PROTOCOL = "formulaguard_v4_residual_headroom_v1"
CHANNELS = ("combined", "peer", "role", "impact")
MAIN_COHORTS = (
    "enron",
    "public:integer_corpus",
    "public:modified_euses",
    "historical_100",
)
REVIEW_BUDGET = 5


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(payload: Mapping[str, object]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_events(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    event_ids: set[str] = set()
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            required = {
                "event_id", "case_kind", "cohort", "structure_group",
                "source_formula_cells", "v4_rank", "review_cells",
            }
            missing = sorted(required - set(row))
            if missing:
                raise ValueError(f"line {line_number} missing fields: {missing}")
            event_id = str(row["event_id"])
            if event_id in event_ids:
                raise ValueError(f"duplicate event_id: {event_id}")
            event_ids.add(event_id)
            reviews = row["review_cells"]
            if not isinstance(reviews, dict) or any(channel not in reviews for channel in CHANNELS):
                raise ValueError(f"event {event_id} has incomplete channel reviews")
            rows.append(row)
    if not rows:
        raise ValueError("event table is empty")
    return rows


def source_hit(row: Mapping[str, object], cells: Sequence[str]) -> int:
    return int(bool(set(row["source_formula_cells"]) & set(cells)))


def structure_macro(
    rows: Sequence[Mapping[str, object]],
    score: Callable[[Mapping[str, object]], int],
) -> float | None:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        groups[str(row["structure_group"])].append(score(row))
    if not groups:
        return None
    group_means = [sum(values) / len(values) for values in groups.values()]
    return sum(group_means) / len(group_means)


def v4_cells(row: Mapping[str, object]) -> list[str]:
    return [str(cell) for cell in row["v4_rank"][:REVIEW_BUDGET]]


def channel_cells(row: Mapping[str, object], channel: str) -> list[str]:
    reviews = row["review_cells"]
    return [str(cell) for cell in reviews[channel][:REVIEW_BUDGET]]


def retained_or_replaced_hit(row: Mapping[str, object], channels: Sequence[str]) -> int:
    """Return the label-aware upper bound for one optional fifth-slot change.

    V4 positions one through four are immutable.  The oracle chooses exactly
    one fifth cell from the original V4 fifth cell and all candidates exposed
    by ``channels``.  For binary source hit@5 this equals the larger review-set
    union, but it still consumes only five cells at inference.
    """

    base = v4_cells(row)
    fixed_prefix = base[: REVIEW_BUDGET - 1]
    fifth_options = base[REVIEW_BUDGET - 1 : REVIEW_BUDGET]
    for channel in channels:
        fifth_options.extend(channel_cells(row, channel))
    return source_hit(row, fixed_prefix + fifth_options)


def forced_channel_top1_hit(row: Mapping[str, object], channel: str) -> int:
    """Diagnostic for always replacing V4's fifth cell with channel Top-1."""

    base = v4_cells(row)
    replacement = channel_cells(row, channel)[:1]
    return source_hit(row, base[: REVIEW_BUDGET - 1] + replacement)


def _count_changes(
    rows: Sequence[Mapping[str, object]], channels: Sequence[str],
) -> dict[str, int]:
    gains = losses = unchanged_hits = unchanged_misses = 0
    for row in rows:
        baseline = source_hit(row, v4_cells(row))
        upper = retained_or_replaced_hit(row, channels)
        if upper > baseline:
            gains += 1
        elif upper < baseline:
            losses += 1
        elif baseline:
            unchanged_hits += 1
        else:
            unchanged_misses += 1
    return {
        "event_gains": gains,
        "event_losses": losses,
        "unchanged_hits": unchanged_hits,
        "unchanged_misses": unchanged_misses,
    }


def summarize(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    baseline = structure_macro(errors, lambda row: source_hit(row, v4_cells(row)))
    if baseline is None:
        raise ValueError("headroom summary requires at least one error event")
    methods: dict[str, object] = {}
    for channel in CHANNELS:
        upper = structure_macro(
            errors,
            lambda row, name=channel: retained_or_replaced_hit(row, (name,)),
        )
        forced = structure_macro(
            errors,
            lambda row, name=channel: forced_channel_top1_hit(row, name),
        )
        assert upper is not None and forced is not None
        methods[channel] = {
            "retained_or_replaced_v5_oracle_top5": upper,
            "recoverable_headroom": upper - baseline,
            "forced_channel_top1_top5": forced,
            "forced_channel_top1_difference": forced - baseline,
            **_count_changes(errors, (channel,)),
        }
    all_upper = structure_macro(
        errors, lambda row: retained_or_replaced_hit(row, CHANNELS),
    )
    assert all_upper is not None
    methods["all_channels"] = {
        "retained_or_replaced_v5_oracle_top5": all_upper,
        "recoverable_headroom": all_upper - baseline,
        **_count_changes(errors, CHANNELS),
    }
    return {
        "events": len(rows),
        "errors": len(errors),
        "controls": sum(row["case_kind"] == "control" for row in rows),
        "structure_groups": len({str(row["structure_group"]) for row in errors}),
        "v4_top5": baseline,
        "methods": methods,
    }


def build_receipt(rows: Sequence[Mapping[str, object]], events_path: Path) -> dict[str, object]:
    cohorts = sorted({str(row["cohort"]) for row in rows})
    by_cohort = {
        cohort: summarize([row for row in rows if row["cohort"] == cohort])
        for cohort in cohorts
        if any(row["cohort"] == cohort and row["case_kind"] == "error" for row in rows)
    }
    overall = summarize(rows)
    single = {
        channel: float(overall["methods"][channel]["recoverable_headroom"])
        for channel in CHANNELS
    }
    best_channel = max(CHANNELS, key=lambda channel: (single[channel], -CHANNELS.index(channel)))
    enron = by_cohort["enron"]
    enron_headroom = float(enron["methods"][best_channel]["recoverable_headroom"])
    bounded_equivalence = all(
        retained_or_replaced_hit(row, (channel,))
        == source_hit(row, v4_cells(row) + channel_cells(row, channel))
        for row in rows if row["case_kind"] == "error"
        for channel in CHANNELS
    )
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "input": {
            "path": str(events_path.resolve().relative_to(ROOT)),
            "sha256": sha256(events_path),
        },
        "aggregation": "structure_group_macro_over_error_events",
        "review_budget": REVIEW_BUDGET,
        "channels": list(CHANNELS),
        "overall": overall,
        "by_cohort": by_cohort,
        "decision": {
            "best_single_channel": best_channel,
            "best_single_channel_overall_headroom": single[best_channel],
            "best_single_channel_enron_headroom": enron_headroom,
            "overall_recoverable_headroom_at_least_5pp": single[best_channel] >= 0.05,
            "enron_recoverable_headroom_nonnegative": enron_headroom >= 0.0,
            "fixed_budget_union_equivalence_verified": bounded_equivalence,
            "eligible_for_residual_controller_preregistration": (
                single[best_channel] >= 0.05
                and enron_headroom >= 0.0
                and bounded_equivalence
            ),
        },
        "evidence_role": {
            "revealed_development_labels_used": True,
            "deployable_model_result": False,
            "independent_validation_result": False,
            "control_risk_estimated_by_oracle": False,
            "protected_data_inputs": [],
        },
    }
    payload["receipt_sha256"] = stable_hash(payload)
    return payload


def write_immutable(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.exists():
        if path.read_bytes() != encoded:
            raise ValueError(f"completed headroom receipt differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    os.replace(temporary, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    events_path = args.events.resolve()
    if "FormulaGuard_240_120" in events_path.parts:
        raise SystemExit("protected 240+120 input is forbidden for this diagnostic")
    receipt = build_receipt(load_events(events_path), events_path)
    write_immutable(args.output.resolve(), receipt)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
