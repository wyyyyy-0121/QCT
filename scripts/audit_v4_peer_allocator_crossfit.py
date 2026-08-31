"""Audit peer allocator architecture selection with structure-isolated folds."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_v4_residual_controller import reject_protected, sha256, stable_hash
from scripts.run_v4_static_fifth_experiment import _bootstrap_delta, _metrics, git_commit, relative


PROTOCOL = "formulaguard_v4_peer_allocator_structure_crossfit_v1"
MODELS = ("peer_fifth", "guarded_fifth", "evidence_allocator")
DEFAULT_INPUTS = {
    "peer_fifth": ROOT / "results/v4_peer_fifth_exploratory/event_scores.jsonl",
    "guarded_fifth": ROOT / "results/v4_peer_guarded_fifth_exploratory/event_scores.jsonl",
    "evidence_allocator": ROOT / "results/v4_peer_evidence_allocator_exploratory/event_scores.jsonl",
}
DEFAULT_OUTPUT = ROOT / "results/v4_peer_allocator_crossfit/receipt.json"


def load_rows(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            required = {
                "event_id", "structure_group", "fold", "cohort",
                "v4_top5", "candidate_top5", "v4_mrr", "candidate_mrr",
            }
            missing = sorted(required - set(row))
            if missing:
                raise ValueError(f"{path}:{line_number} missing fields: {missing}")
            rows.append(row)
    if not rows:
        raise ValueError(f"empty architecture score file: {path}")
    return rows


def _loss_rate(rows: Sequence[Mapping[str, object]]) -> float:
    hits = sum(int(row["v4_top5"]) for row in rows)
    losses = sum(int(row["candidate_top5"]) < int(row["v4_top5"]) for row in rows)
    return losses / max(1, hits)


def choose_model(
    model_rows: Mapping[str, Sequence[Mapping[str, object]]],
    *,
    outer_fold: int,
) -> tuple[str, dict[str, object]]:
    eligible_options = []
    for order, model in enumerate(MODELS):
        train = [row for row in model_rows[model] if int(row["fold"]) != outer_fold]
        metrics = _metrics(train)
        loss_rate = _loss_rate(train)
        if metrics["mrr_delta"] < 0.0 or loss_rate > 0.02:
            continue
        key = (
            float(metrics["top5_delta_pp"]),
            float(metrics["mrr_delta"]),
            -loss_rate,
            -order,
        )
        eligible_options.append((
            key,
            model,
            {**metrics, "v4_hit_loss_rate": loss_rate},
        ))
    if not eligible_options:
        raise ValueError(f"no eligible allocator on training folds for outer fold {outer_fold}")
    _key, model, metrics = max(eligible_options, key=lambda row: row[0])
    return model, metrics


def run(
    *,
    inputs: Mapping[str, Path],
    output: Path,
) -> Path:
    if tuple(inputs) != MODELS:
        raise ValueError("allocator crossfit input model order differs")
    for path in (*inputs.values(), output):
        reject_protected(path)
    model_rows = {model: load_rows(path) for model, path in inputs.items()}
    event_ids = {
        model: [str(row["event_id"]) for row in rows]
        for model, rows in model_rows.items()
    }
    if any(ids != event_ids[MODELS[0]] for ids in event_ids.values()):
        raise ValueError("allocator score files have different event inventories or order")
    baseline_projection = {
        model: stable_hash([
            {
                "event_id": row["event_id"],
                "structure_group": row["structure_group"],
                "fold": row["fold"],
                "cohort": row["cohort"],
                "v4_top5": row["v4_top5"],
                "v4_mrr": row["v4_mrr"],
            }
            for row in rows
        ])
        for model, rows in model_rows.items()
    }
    if len(set(baseline_projection.values())) != 1:
        raise ValueError("allocator score files have different V4 baselines")

    folds = []
    crossfit_rows: list[dict[str, object]] = []
    for outer_fold in range(5):
        model, training_metrics = choose_model(model_rows, outer_fold=outer_fold)
        held_out = [
            {**row, "selected_model": model}
            for row in model_rows[model]
            if int(row["fold"]) == outer_fold
        ]
        held_out_metrics = _metrics(held_out)
        crossfit_rows.extend(held_out)
        folds.append({
            "outer_fold": outer_fold,
            "training_folds": [fold for fold in range(5) if fold != outer_fold],
            "selected_model": model,
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
    selected = [str(row["selected_model"]) for row in folds]
    gates = {
        "crossfit_top5_gain_at_least_15pp": overall["top5_delta_pp"] >= 15.0,
        "crossfit_mrr_nonnegative": overall["mrr_delta"] >= 0.0,
        "crossfit_v4_hit_loss_at_most_2pct": overall["v4_hit_loss_rate"] <= 0.02,
        "all_outer_folds_top5_positive": all(
            row["held_out_metrics"]["top5_delta_pp"] > 0.0 for row in folds
        ),
        "all_main_cohorts_top5_positive": all(
            cohorts[name]["top5_delta_pp"] > 0.0
            for name in (
                "enron", "historical_100", "public:integer_corpus",
                "public:modified_euses",
            )
        ),
        "structure_bootstrap_lower_bound_positive": bootstrap["ci95_delta_pp"][0] > 0.0,
        "evidence_allocator_selected_in_all_folds": all(
            model == "evidence_allocator" for model in selected
        ),
    }
    payload: dict[str, object] = {
        "protocol": PROTOCOL,
        "complete": True,
        "source_git_commit": git_commit(),
        "selection": {
            "candidate_models": list(MODELS),
            "training_only_constraints": {
                "mrr_delta_minimum": 0.0,
                "v4_hit_loss_rate_maximum": 0.02,
            },
            "objective": "maximum_structure_macro_top5_delta",
            "tie_breaks": ["mrr_delta", "lower_v4_hit_loss", "fixed_model_order"],
            "outer_test_labels_used_for_selection": False,
            "retrospective_architecture_audit_not_independent_confirmation": True,
        },
        "inputs": {
            model: {"path": relative(path), "sha256": sha256(path)}
            for model, path in inputs.items()
        },
        "v4_baseline_projection_sha256": next(iter(baseline_projection.values())),
        "folds": folds,
        "selected_models": selected,
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
        raise ValueError("allocator crossfit receipt already exists")
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for model in MODELS:
        parser.add_argument(f"--{model.replace('_', '-')}", type=Path, default=DEFAULT_INPUTS[model])
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    inputs = {
        model: getattr(args, model).resolve()
        for model in MODELS
    }
    try:
        path = run(inputs=inputs, output=args.output.resolve())
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"peer allocator crossfit audit refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
