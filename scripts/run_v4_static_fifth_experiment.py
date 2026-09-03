"""Evaluate the exploratory V4 top-four plus static-fifth ranker."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_rrc import structure_fold
from formulaguard.v4_static_fifth import (
    ARCHITECTURE,
    MODEL_VERSION,
    REVIEW_BUDGET,
    V4_PREFIX,
    static_fifth_decision,
)
from scripts.run_v4_residual_controller import (
    DEFAULT_EVENTS,
    DEFAULT_V4,
    load_event_rows,
    load_json,
    load_shards,
    reject_protected,
    relative,
    sha256,
    source_rank,
    stable_hash,
)
from scripts.run_v4_rrc_required_baselines import write_immutable

PROTOCOL = "formulaguard_v4_static_fifth_exploratory_v1"
DEFAULT_STATIC = ROOT / "results/v4_rrc_required_baselines"
DEFAULT_OUTPUT = ROOT / "results/v4_static_fifth_exploratory"
BOOTSTRAP_SEED = 20260831
BOOTSTRAP_SAMPLES = 20_000


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def load_static(directory: Path) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    receipt = load_json(directory / "receipt.json")
    if receipt.get("complete") is not True or receipt.get("protected_data_inputs") != []:
        raise ValueError("static-anchor baseline is incomplete or protected-data contaminated")
    result: dict[str, dict[str, object]] = {}
    for path in sorted((directory / "shards").glob("*.json")):
        payload = load_json(path)
        if payload.get("label_inputs") != [] or payload.get("protected_data_inputs") != []:
            raise ValueError(f"invalid static-anchor shard boundary: {path}")
        unit_id = str(payload["unit_id"])
        if unit_id in result:
            raise ValueError(f"duplicate static-anchor unit: {unit_id}")
        result[unit_id] = payload
    if len(result) != int(receipt["counts"]["units"]):
        raise ValueError("static-anchor shard count differs from receipt")
    return result, receipt


def predict(
    v4: Mapping[str, Mapping[str, object]],
    static: Mapping[str, Mapping[str, object]],
    output_dir: Path,
) -> dict[str, dict[str, object]]:
    if set(v4) != set(static):
        raise ValueError("V4 and static unit inventories differ")
    predictions: dict[str, dict[str, object]] = {}
    for unit_id in sorted(v4):
        v4_cells = [str(row["cell"]) for row in v4[unit_id]["ranking"]]
        static_cells = [str(cell) for cell in static[unit_id]["v5_psl_static_anchor"]["ranking"]]
        decision = static_fifth_decision(v4_cells, static_cells)
        payload: dict[str, object] = {
            "protocol": PROTOCOL,
            "model_version": MODEL_VERSION,
            "unit_id": unit_id,
            "workbook_sha256": v4[unit_id]["workbook_sha256"],
            "ranking": list(decision.ranking),
            "top5": list(decision.top5),
            "static_candidate": decision.static_candidate,
            "displaced_v4_fifth": decision.displaced_v4_fifth,
            "changed": decision.changed,
            "label_inputs": [],
            "protected_data_inputs": [],
        }
        encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        path = output_dir / "shards" / (unit_id.split(":", 1)[1] + ".json")
        write_immutable(path, encoded)
        predictions[unit_id] = payload
    return predictions


def _macro(rows: Sequence[Mapping[str, object]], field: str) -> float | None:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["structure_group"])].append(float(row[field]))
    if not groups:
        return None
    return sum(sum(values) / len(values) for values in groups.values()) / len(groups)


def _metrics(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    v4_top5 = _macro(rows, "v4_top5")
    candidate_top5 = _macro(rows, "candidate_top5")
    v4_mrr = _macro(rows, "v4_mrr")
    candidate_mrr = _macro(rows, "candidate_mrr")
    return {
        "events": len(rows),
        "structure_groups": len({str(row["structure_group"]) for row in rows}),
        "v4_top5": v4_top5,
        "candidate_top5": candidate_top5,
        "top5_delta_pp": 100.0 * (float(candidate_top5) - float(v4_top5)),
        "v4_mrr": v4_mrr,
        "candidate_mrr": candidate_mrr,
        "mrr_delta": float(candidate_mrr) - float(v4_mrr),
        "recovered_events": sum(int(row["candidate_top5"]) > int(row["v4_top5"]) for row in rows),
        "lost_events": sum(int(row["candidate_top5"]) < int(row["v4_top5"]) for row in rows),
    }


def _bootstrap_delta(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_group: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        by_group[str(row["structure_group"])].append(
            float(row["candidate_top5"]) - float(row["v4_top5"])
        )
    group_deltas = [sum(values) / len(values) for values in by_group.values()]
    rng = random.Random(BOOTSTRAP_SEED)
    samples = sorted(
        sum(rng.choice(group_deltas) for _ in group_deltas) / len(group_deltas)
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return {
        "seed": BOOTSTRAP_SEED,
        "samples": BOOTSTRAP_SAMPLES,
        "groups": len(group_deltas),
        "mean_delta_pp": 100.0 * sum(group_deltas) / len(group_deltas),
        "ci95_delta_pp": [100.0 * samples[500], 100.0 * samples[19_499]],
        "positive_groups": sum(value > 0 for value in group_deltas),
        "zero_groups": sum(value == 0 for value in group_deltas),
        "negative_groups": sum(value < 0 for value in group_deltas),
    }


def score(
    events: Sequence[Mapping[str, object]],
    predictions: Mapping[str, Mapping[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    for event in events:
        if event["case_kind"] != "error":
            continue
        prediction = predictions[str(event["unit_id"])]
        v4_rank = int(event["metrics"]["v4"]["rank"]) if event["metrics"]["v4"]["rank"] else None
        candidate_rank = source_rank(
            prediction["ranking"],
            [str(cell) for cell in event["source_formula_cells"]],
        )
        rows.append({
            "event_id": event["event_id"],
            "unit_id": event["unit_id"],
            "structure_group": event["structure_group"],
            "cohort": event["cohort"],
            "fold": structure_fold(str(event["structure_group"])),
            "v4_rank": v4_rank,
            "candidate_rank": candidate_rank,
            "v4_top5": int(v4_rank is not None and v4_rank <= REVIEW_BUDGET),
            "candidate_top5": int(candidate_rank is not None and candidate_rank <= REVIEW_BUDGET),
            "v4_mrr": 1.0 / v4_rank if v4_rank else 0.0,
            "candidate_mrr": 1.0 / candidate_rank if candidate_rank else 0.0,
        })
    overall = _metrics(rows)
    v4_hits = sum(int(row["v4_top5"]) for row in rows)
    v4_misses = len(rows) - v4_hits
    overall.update({
        "v4_miss_recovery_rate": overall["recovered_events"] / v4_misses,
        "v4_hit_loss_rate": overall["lost_events"] / v4_hits,
    })
    cohorts = {
        cohort: _metrics([row for row in rows if row["cohort"] == cohort])
        for cohort in sorted({str(row["cohort"]) for row in rows})
    }
    folds = {
        str(fold): _metrics([row for row in rows if row["fold"] == fold])
        for fold in range(5)
    }
    bootstrap = _bootstrap_delta(rows)
    main_n2 = ("historical_100", "public:integer_corpus", "public:modified_euses")
    gates = {
        "overall_top5_gain_at_least_5pp": overall["top5_delta_pp"] >= 5.0,
        "enron_top5_nonnegative": cohorts["enron"]["top5_delta_pp"] >= 0.0,
        "all_main_n2_regressions_within_2pp": all(
            cohorts[name]["top5_delta_pp"] >= -2.0 for name in main_n2
        ),
        "v4_miss_recovery_at_least_15pct": overall["v4_miss_recovery_rate"] >= 0.15,
        "v4_hit_loss_at_most_2pct": overall["v4_hit_loss_rate"] <= 0.02,
        "at_least_four_nonnegative_folds": sum(
            fold["top5_delta_pp"] >= 0.0 for fold in folds.values()
        ) >= 4,
        "structure_bootstrap_lower_bound_positive": bootstrap["ci95_delta_pp"][0] > 0.0,
        "mrr_nonnegative": overall["mrr_delta"] >= 0.0,
    }
    return {
        "overall": overall,
        "by_cohort": cohorts,
        "by_structure_fold": folds,
        "structure_group_bootstrap": bootstrap,
        "exploratory_gates": gates,
        "all_exploratory_gates_passed": all(gates.values()),
    }, rows


def run(*, events_path: Path, v4_dir: Path, static_dir: Path, output_dir: Path) -> Path:
    for path in (events_path, v4_dir, static_dir, output_dir):
        reject_protected(path)
    v4, v4_complete = load_shards(v4_dir, kind="V4")
    static, static_receipt = load_static(static_dir)
    predictions = predict(v4, static, output_dir)

    # Labels are opened only after all complete rankings have been persisted.
    events = load_event_rows(events_path)
    summary, event_rows = score(events, predictions)
    event_bytes = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
        for row in sorted(event_rows, key=lambda row: str(row["event_id"]))
    ).encode("utf-8")
    write_immutable(output_dir / "event_scores.jsonl", event_bytes)
    shard_hash = hashlib.sha256()
    for path in sorted((output_dir / "shards").glob("*.json")):
        shard_hash.update(path.name.encode("utf-8") + b"\0" + bytes.fromhex(sha256(path)))
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_lock_git_commit": git_commit(),
        "model": {
            "version": MODEL_VERSION,
            "architecture": ARCHITECTURE,
            "review_budget": REVIEW_BUDGET,
            "immutable_v4_prefix": V4_PREFIX,
            "formal_v5_authorized": False,
        },
        "parameter_selection_disclosure": {
            "role": "exploratory_development_not_independent_validation",
            "observed_prefix_quota_grid": [0, 1, 2, 3, 4, 5],
            "selected_v4_prefix_quota": V4_PREFIX,
            "selection_reason": "best simple five-slot allocation preserving Enron while exceeding V4 overall",
        },
        "inputs": {
            "events_for_scoring_only": {"path": relative(events_path), "sha256": sha256(events_path)},
            "v4": {"path": relative(v4_dir), "combined_shards_sha256": v4_complete["combined_shards_sha256"]},
            "static": {"path": relative(static_dir), "receipt_sha256": static_receipt["receipt_sha256"]},
        },
        "counts": {
            "units": len(predictions),
            "events": len(events),
            "error_events": len(event_rows),
            "changed_units": sum(bool(row["changed"]) for row in predictions.values()),
        },
        "summary": summary,
        "artifacts": {
            "event_scores": {"path": relative(output_dir / "event_scores.jsonl"), "sha256": hashlib.sha256(event_bytes).hexdigest()},
            "combined_shards_sha256": shard_hash.hexdigest(),
        },
        "label_boundary": {
            "prediction_label_inputs": [],
            "labels_opened_after_all_prediction_shards": True,
        },
        "protected_data_inputs": [],
        "next_data_access_authorized": False,
    }
    payload["receipt_sha256"] = stable_hash(payload)
    receipt = output_dir / "receipt.json"
    write_immutable(
        receipt,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--static", type=Path, default=DEFAULT_STATIC)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    receipt = run(
        events_path=args.events.resolve(),
        v4_dir=args.v4.resolve(),
        static_dir=args.static.resolve(),
        output_dir=args.output_dir.resolve(),
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
