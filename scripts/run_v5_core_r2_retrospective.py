"""Run the preregistered V5-Core R2 retrospective development experiment.

Prediction workers receive only public workbook rows. The parent opens labels
only after every prediction shard has been atomically written and audited.
These results are retrospective development evidence, never blind evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula
from formulaguard.v5_core_r2 import v5_core_r2_scores
from formulaguard.workbook import WorkbookModel

BASE_METHODS = ("r2_source", "r2_full")
ABLATIONS = {
    "ablate_no_rcr": "no_rcr",
    "ablate_no_boundary": "no_boundary",
    "ablate_no_role_replication": "no_role_replication",
    "ablate_no_ancestor": "no_ancestor",
    "ablate_additive_dcf": "additive_dcf",
    "ablate_no_placebo": "no_placebo",
    "ablate_unrestricted_rerank": "unrestricted_rerank",
    "ablate_no_formula_probe": "no_formula_probe",
}
DROPOUTS = {"dropout_25": 0.75, "dropout_50": 0.50, "dropout_100": 0.0}
ERROR_METHODS = BASE_METHODS + tuple(ABLATIONS) + tuple(DROPOUTS)
WCN_VARIANTS = {
    "wcn_rcr": ("rcr", "RCR", lambda row: row[0]),
    "wcn_rcr_observational": (
        "rcr_observational", "0.80*RCR+0.20*O", lambda row: 0.80 * row[0] + 0.20 * row[1],
    ),
    "wcn_rcr_directional": (
        "rcr_directional", "0.70*RCR+0.30*DCF", lambda row: 0.70 * row[0] + 0.30 * row[2],
    ),
}


def read_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_executable() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    return "git" if subprocess.run(["where", "git"], capture_output=True).returncode == 0 else str(bundled)


def git_commit() -> str:
    return subprocess.check_output([git_executable(), "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def git_dirty() -> bool:
    output = subprocess.check_output(
        [git_executable(), "status", "--porcelain", "--untracked-files=all"], cwd=ROOT, text=True,
    )
    return bool(output.strip())


def serial_result(result, rank: int, *, compact: bool = False) -> dict:
    evidence = dict(result.evidence)
    if compact:
        evidence = {key: evidence.get(key) for key in (
            "ablation", "observational_rank", "candidate_keep_fraction",
            "candidate_coverage", "diagnostic_status",
        )}
    return {
        "rank": rank,
        "cell": result.cell_label,
        "score": result.score,
        "candidate_formula": result.candidate_formula or "",
        "evidence": evidence,
    }


def prediction_task(payload: tuple[str, str, str, str, bool, dict]) -> str:
    dataset_text, output_text, instance_id, workbook_rel, with_ablations, config = payload
    dataset, output = Path(dataset_text), Path(output_text)
    workbook = dataset / workbook_rel
    model = WorkbookModel.from_xlsx(workbook)
    started = time.perf_counter()
    full = v5_core_r2_scores(model, stage="full", config=config)
    source = sorted(full, key=lambda row: int(row.evidence["observational_rank"]))
    rankings = {
        "r2_source": [serial_result(item, rank) for rank, item in enumerate(source, 1)],
        "r2_full": [serial_result(item, rank) for rank, item in enumerate(full, 1)],
    }
    if with_ablations:
        for method, ablation in ABLATIONS.items():
            results = v5_core_r2_scores(model, stage="full", config=config, ablation=ablation)
            rankings[method] = [
                serial_result(item, rank, compact=True) for rank, item in enumerate(results, 1)
            ]
        for method, fraction in DROPOUTS.items():
            results = v5_core_r2_scores(
                model, stage="full", config=config, candidate_keep_fraction=fraction,
            )
            rankings[method] = [
                serial_result(item, rank, compact=True) for rank, item in enumerate(results, 1)
            ]
    record = {
        "instance_id": instance_id,
        "workbook": workbook_rel,
        "workbook_sha256": sha256(workbook),
        "formula_count": len(model.formulas),
        "rankings": rankings,
        "diagnostic_status": full[0].evidence["diagnostic_status"] if full else "unsupported_coverage",
        "localization_seconds": time.perf_counter() - started,
    }
    write_json(output / "shards" / f"{instance_id}.json", record)
    return instance_id


def audit_shard(path: Path, dataset: Path, row: dict, workbook_key: str, id_key: str,
                expected_methods: tuple[str, ...]) -> None:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record["instance_id"] != row[id_key]:
        raise SystemExit(f"Wrong instance in {path}")
    workbook = dataset / row[workbook_key]
    if record["workbook_sha256"] != sha256(workbook):
        raise SystemExit(f"Workbook changed for {path}")
    if set(record["rankings"]) != set(expected_methods):
        raise SystemExit(f"Method set mismatch in {path}")
    count = int(record["formula_count"])
    for method in expected_methods:
        ranking = record["rankings"][method]
        cells = [item["cell"] for item in ranking]
        if len(ranking) != count or len(set(cells)) != count:
            raise SystemExit(f"Incomplete {method} ranking in {path}")
        if [item["rank"] for item in ranking] != list(range(1, count + 1)):
            raise SystemExit(f"Invalid ranks in {path}: {method}")


def prediction_receipt(*, dataset: Path, rows: list[dict], workers: int,
                       with_ablations: bool, config: dict, config_path: Path | None) -> dict:
    manifest = dataset / ("instances.jsonl" if (dataset / "instances.jsonl").exists() else "clean_manifest.json")
    files = {
        "model_source": ROOT / "formulaguard/v5_core_r2.py",
        "runner_source": ROOT / "scripts/run_v5_core_r2_retrospective.py",
        "method_spec": ROOT / "research/V5_CORE_R2_METHOD_SPEC.md",
        "public_manifest": manifest,
    }
    if config_path:
        files["experiment_config"] = config_path
    return {
        "protocol": "v5_core_r2_retrospective_predictions_v2",
        "development_only": True,
        "independent_evidence": False,
        "instances": len(rows),
        "workers_requested": workers,
        "ablations_included": with_ablations,
        "model_config": config,
        "labels_read_by_prediction_workers": [],
        "git_commit": git_commit(),
        "hashes": {name: sha256(path) for name, path in files.items()},
    }


def run_group(dataset: Path, output: Path, rows: list[dict], *, workbook_key: str,
              id_key: str, workers: int, resume: bool, with_ablations: bool,
              config: dict, config_path: Path | None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "shards").mkdir(parents=True, exist_ok=True)
    expected_methods = ERROR_METHODS if with_ablations else BASE_METHODS
    pending = []
    for row in rows:
        shard = output / "shards" / f"{row[id_key]}.json"
        if shard.exists() and resume:
            audit_shard(shard, dataset, row, workbook_key, id_key, expected_methods)
            continue
        if shard.exists():
            raise SystemExit(f"Output exists; pass --resume: {shard}")
        pending.append((
            str(dataset), str(output), row[id_key], row[workbook_key], with_ablations, config,
        ))
    active_workers = max(1, min(workers, len(pending))) if pending else 1
    if pending:
        with concurrent.futures.ProcessPoolExecutor(max_workers=active_workers) as pool:
            futures = [pool.submit(prediction_task, item) for item in pending]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(futures)}] {future.result()}", flush=True)
    for row in rows:
        audit_shard(output / "shards" / f"{row[id_key]}.json", dataset, row,
                    workbook_key, id_key, expected_methods)
    write_json(output / "prediction_complete.json", prediction_receipt(
        dataset=dataset, rows=rows, workers=workers, with_ablations=with_ablations,
        config=config, config_path=config_path,
    ))


def aggregate_metrics(values: list[dict]) -> dict:
    n = len(values) or 1
    by_type: dict[str, list[dict]] = defaultdict(list)
    for item in values:
        by_type[item["error_type"]].append(item)
    typed = {
        error_type: {
            "events": len(group),
            "top5": sum(item["rank"] <= 5 for item in group) / len(group),
            "mrr": sum(1.0 / item["rank"] for item in group) / len(group),
        }
        for error_type, group in sorted(by_type.items())
    }
    top5_values = [row["top5"] for row in typed.values()]
    return {
        "events": len(values),
        "top1": sum(item["rank"] <= 1 for item in values) / n,
        "top3": sum(item["rank"] <= 3 for item in values) / n,
        "top5": sum(item["rank"] <= 5 for item in values) / n,
        "mrr": sum(1.0 / item["rank"] for item in values) / n,
        "exam": sum((item["rank"] - 1) / max(1, item["formula_count"]) for item in values) / n,
        "exact_repair": sum(item["exact_repair"] for item in values) / n,
        "macro_top5": sum(top5_values) / max(1, len(top5_values)),
        "weakest_top5": min(top5_values, default=0.0),
        "by_error_type": typed,
    }


def summarize_error_group(dataset: Path, output: Path, rows: list[dict]) -> dict:
    if not (output / "prediction_complete.json").exists():
        raise SystemExit("Predictions must complete before labels are read")
    labels = {row["instance_id"]: row for row in read_jsonl(dataset / "evaluation_labels.jsonl")}
    metrics: dict[str, list[dict]] = defaultdict(list)
    diagnostics: list[dict] = []
    for row in rows:
        label = labels[row["instance_id"]]
        record = json.loads((output / "shards" / f"{row['instance_id']}.json").read_text(encoding="utf-8"))
        source_cell = label["source_cell"]
        correct_formula = str(label.get("correct_formula") or "")
        ranks: dict[str, int] = {}
        for method, ranking in record["rankings"].items():
            source_row = next(item for item in ranking if item["cell"] == source_cell)
            ranks[method] = int(source_row["rank"])
            exact = bool(correct_formula and source_row["candidate_formula"] and
                         normalized_formula(source_row["candidate_formula"]) == normalized_formula(correct_formula))
            metrics[method].append({
                "rank": ranks[method], "formula_count": record["formula_count"],
                "exact_repair": exact, "error_type": label["mutation_type"],
            })
        full_source = next(item for item in record["rankings"]["r2_full"] if item["cell"] == source_cell)
        evidence = full_source["evidence"]
        diagnostics.append({
            "instance_id": row["instance_id"], "workbook": row["mutant_workbook"],
            "error_type": label["mutation_type"], "source_cell": source_cell,
            "source_rank": ranks["r2_source"], "full_rank": ranks["r2_full"],
            "dropout_100_rank": ranks["dropout_100"],
            "candidate_coverage": bool(evidence["candidate_coverage"]),
            "observational_tail": evidence["observational_empirical_tail"],
            "counterfactual_tail": evidence["counterfactual_empirical_tail"],
            "placebo_treatment": evidence["placebo_treatment"],
            "diagnostic_status": record["diagnostic_status"],
        })
    summary = {
        "protocol": "v5_core_r2_retrospective_score_v2", "development_only": True,
        "independent_evidence": False,
        "disclosure": "Labels were previously revealed and are used for direction finding and bounded tuning.",
        "metrics": {method: aggregate_metrics(values) for method, values in sorted(metrics.items())},
        "source_candidate_coverage": sum(row["candidate_coverage"] for row in diagnostics) / max(1, len(diagnostics)),
        "counterfactual_improved_rank": sum(row["full_rank"] < row["source_rank"] for row in diagnostics),
        "counterfactual_harmed_rank": sum(row["full_rank"] > row["source_rank"] for row in diagnostics),
        "counterfactual_harmed_rate": sum(row["full_rank"] > row["source_rank"] for row in diagnostics) / max(1, len(diagnostics)),
        "dropout_100_source_rank_identical": all(row["dropout_100_rank"] == row["source_rank"] for row in diagnostics),
        "diagnostics": diagnostics,
    }
    write_json(output / "retrospective_summary.json", summary)
    return summary


def summarize_clean_group(output: Path, rows: list[dict]) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for row in rows:
        record = json.loads((output / "shards" / f"{row['clean_id']}.json").read_text(encoding="utf-8"))
        counts[record["diagnostic_status"]] += 1
    summary = {
        "events": len(rows), "status_counts": dict(sorted(counts.items())),
        "note": "The registered WCN leave-one-out false alarm rate is the clean safety metric.",
    }
    write_json(output / "clean_summary.json", summary)
    return summary


def cross_workbook_null_summary(error_output: Path, error_rows: list[dict],
                                clean_output: Path, clean_rows: list[dict], *,
                                protected_global_max: bool = False) -> dict:
    """Evaluate and select the three preregistered workbook-null statistics."""
    def features(path: Path) -> list[tuple[float, float, float]]:
        record = json.loads(path.read_text(encoding="utf-8"))
        rows = record["rankings"]["r2_full"]
        if not protected_global_max:
            rows = rows[:1]
        return [(
            float(item["evidence"].get(
                "alarm_regime_conditioned_residual" if protected_global_max
                else "regime_conditioned_residual",
                item["evidence"]["regime_conditioned_residual"],
            )),
            float(item["evidence"]["observational_raw_score"]),
            float(item["evidence"]["placebo_treatment"]),
        ) for item in rows]

    error_features = [features(error_output / "shards" / f"{row['instance_id']}.json") for row in error_rows]
    clean_features = [features(clean_output / "shards" / f"{row['clean_id']}.json") for row in clean_rows]
    variants: dict[str, dict] = {}
    for name, (config_name, formula, statistic) in WCN_VARIANTS.items():
        clean_values = [max((statistic(row) for row in rows), default=0.0) for rows in clean_features]
        error_values = [max((statistic(row) for row in rows), default=0.0) for rows in error_features]
        clean_tails = [
            (1 + sum(other >= value for index, other in enumerate(clean_values) if index != own))
            / max(1, len(clean_values)) for own, value in enumerate(clean_values)
        ]
        error_tails = [
            (1 + sum(other >= value for other in clean_values)) / (1 + len(clean_values))
            for value in error_values
        ]
        variants[name] = {
            "config_name": config_name, "formula": formula, "clean_null_scores": clean_values,
            "tail_threshold": 0.10,
            "error_alarm_recall": sum(value <= 0.10 for value in error_tails) / max(1, len(error_tails)),
            "clean_false_alarm_rate": sum(value <= 0.10 for value in clean_tails) / max(1, len(clean_tails)),
            "error_tails": error_tails, "clean_leave_one_out_tails": clean_tails,
        }
    complexity = {"wcn_rcr": 0, "wcn_rcr_observational": 1, "wcn_rcr_directional": 2}
    eligible = [name for name, row in variants.items() if row["clean_false_alarm_rate"] <= 0.10]
    selected = min(eligible, key=lambda name: (
        -variants[name]["error_alarm_recall"], variants[name]["clean_false_alarm_rate"], complexity[name],
    ), default=None)
    return {
        "selection_rule": "FPR<=0.10; max error recall; min FPR; simplest RCR",
        "protected_global_max": protected_global_max,
        "selected": selected,
        "selected_config_name": variants[selected]["config_name"] if selected else None,
        "ablation_no_wcn": {
            "interpretation": "Forced localization without a cross-workbook clean null",
            "error_alarm_recall": 1.0 if error_features else 0.0,
            "clean_false_alarm_rate": 1.0 if clean_features else 0.0,
        },
        "variants": variants,
    }


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_tables(output: Path, error_summary: dict, workbook_null: dict) -> None:
    summary_rows, by_error_rows = [], []
    for method, values in sorted(error_summary["metrics"].items()):
        summary_rows.append({"method": method, **{key: values[key] for key in (
            "events", "top1", "top3", "top5", "mrr", "exam", "exact_repair", "macro_top5", "weakest_top5"
        )}})
        for error_type, group in values["by_error_type"].items():
            by_error_rows.append({"method": method, "error_type": error_type, **group})
    write_csv(output / "summary.csv", summary_rows,
              ["method", "events", "top1", "top3", "top5", "mrr", "exam", "exact_repair", "macro_top5", "weakest_top5"])
    write_csv(output / "by_error.csv", by_error_rows,
              ["method", "error_type", "events", "top5", "mrr"])
    failures = [row for row in error_summary["diagnostics"] if
                row["source_rank"] > 5 or row["full_rank"] > 5 or
                row["full_rank"] > row["source_rank"] or not row["candidate_coverage"]]
    write_csv(output / "failure_cases.csv", failures, [
        "instance_id", "workbook", "error_type", "source_cell", "source_rank", "full_rank",
        "dropout_100_rank", "candidate_coverage", "observational_tail", "counterfactual_tail",
        "placebo_treatment", "diagnostic_status",
    ])
    wcn_rows = [{
        "variant": name, "formula": values["formula"],
        "error_alarm_recall": values["error_alarm_recall"],
        "clean_false_alarm_rate": values["clean_false_alarm_rate"],
        "selected": name == workbook_null["selected"],
    } for name, values in workbook_null["variants"].items()]
    write_csv(output / "wcn_summary.csv", wcn_rows,
              ["variant", "formula", "error_alarm_recall", "clean_false_alarm_rate", "selected"])


def evaluate_gates(error_summary: dict, workbook_null: dict) -> dict:
    metrics = error_summary["metrics"]
    source, full = metrics["r2_source"], metrics["r2_full"]
    selected_name = workbook_null["selected"]
    selected = workbook_null["variants"].get(selected_name, {})
    event_improved_types = 0
    headroom_types = []
    net_improved_types = []
    for error_type, source_values in source["by_error_type"].items():
        typed = [row for row in error_summary["diagnostics"] if row["error_type"] == error_type]
        if any(row["full_rank"] < row["source_rank"] for row in typed):
            event_improved_types += 1
        if source_values["mrr"] < 1.0 - 1e-12:
            headroom_types.append(error_type)
            if full["by_error_type"][error_type]["mrr"] > source_values["mrr"] + 1e-12:
                net_improved_types.append(error_type)
    required_net_improved_types = min(4, len(headroom_types))
    strongest_ablation_mrr = max(
        (values["mrr"] for name, values in metrics.items() if name.startswith("ablate_")),
        default=-math.inf,
    )
    gates = {
        "source_macro_top5_at_least_0_90": source["macro_top5"] >= 0.90,
        "source_weakest_top5_at_least_0_75": source["weakest_top5"] >= 0.75,
        "full_mrr_not_below_source": full["mrr"] + 1e-12 >= source["mrr"],
        "counterfactual_harmed_rate_at_most_0_02": error_summary["counterfactual_harmed_rate"] <= 0.02,
        "dropout_100_source_order_invariant": error_summary["dropout_100_source_rank_identical"],
        "wcn_selected": selected_name is not None,
        "wcn_clean_fpr_at_most_0_10": bool(selected) and selected["clean_false_alarm_rate"] <= 0.10,
        "wcn_error_recall_at_least_0_80": bool(selected) and selected["error_alarm_recall"] >= 0.80,
        "net_improvement_covers_available_headroom_types": (
            len(net_improved_types) >= required_net_improved_types
        ),
        "critical_ablation_not_above_full_by_0_02": strongest_ablation_mrr <= full["mrr"] + 0.02,
    }
    return {
        "values": {
            "event_improved_error_types": event_improved_types,
            "headroom_error_types": headroom_types,
            "net_improved_error_types": net_improved_types,
            "required_net_improved_error_types": required_net_improved_types,
            "gate_semantics": "net_mrr_over_non_ceiling_types_v1",
            "strongest_ablation_mrr": strongest_ablation_mrr,
            "full_mrr": full["mrr"],
        },
        "gates": gates, "hard_gate_passed": all(gates.values()),
        "failed_gates": [name for name, passed in gates.items() if not passed],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--errors", type=Path, default=Path("data/v5_core_validation"))
    parser.add_argument("--clean", type=Path, default=Path("data/v5_core_clean"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_r2_retrospective"))
    parser.add_argument("--workers", type=int, default=24)
    parser.add_argument("--error-limit", type=int)
    parser.add_argument("--error-offset", type=int, default=0,
                        help="Use a contiguous public-manifest slice for short regression checks")
    parser.add_argument("--clean-limit", type=int)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--config", type=Path, help="Label-free, versioned R2 experiment configuration")
    parser.add_argument("--allow-dirty", action="store_true", help="Only for Codex short smoke tests")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.workers < 1:
        raise SystemExit("--workers must be positive")
    if args.error_offset < 0:
        raise SystemExit("--error-offset must be non-negative")
    if git_dirty() and not args.allow_dirty:
        raise SystemExit("Tracked or untracked changes exist. Commit and push before the large R2 run.")
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    forbidden = {"source_cell", "error_type", "correct_formula", "labels", "instance_id", "workbook_filename"}
    if forbidden & set(config):
        raise SystemExit("R2 configuration contains forbidden label or identity fields")
    started = time.perf_counter()
    error_rows = read_jsonl(args.errors / "instances.jsonl")
    clean_rows = json.loads((args.clean / "clean_manifest.json").read_text(encoding="utf-8"))
    if args.error_limit is not None:
        error_rows = error_rows[args.error_offset:args.error_offset + args.error_limit]
    elif args.error_offset:
        error_rows = error_rows[args.error_offset:]
    if args.clean_limit is not None:
        clean_rows = clean_rows[:args.clean_limit]
    error_output, clean_output = args.output / "errors", args.output / "clean"
    run_group(args.errors, error_output, error_rows, workbook_key="mutant_workbook",
              id_key="instance_id", workers=args.workers, resume=args.resume, with_ablations=True,
              config=config, config_path=args.config)
    run_group(args.clean, clean_output, clean_rows, workbook_key="workbook",
              id_key="clean_id", workers=args.workers, resume=args.resume, with_ablations=False,
              config=config, config_path=args.config)
    error_summary = summarize_error_group(args.errors, error_output, error_rows)
    clean_summary = summarize_clean_group(clean_output, clean_rows)
    workbook_null = cross_workbook_null_summary(
        error_output, error_rows, clean_output, clean_rows,
        protected_global_max=bool(config.get("wcn_protected_global_max", False)),
    )
    gates = evaluate_gates(error_summary, workbook_null)
    input_hashes = {
        "error_public_manifest": sha256(args.errors / "instances.jsonl"),
        "error_labels": sha256(args.errors / "evaluation_labels.jsonl"),
        "clean_public_manifest": sha256(args.clean / "clean_manifest.json"),
        "model_source": sha256(ROOT / "formulaguard/v5_core_r2.py"),
        "runner_source": sha256(ROOT / "scripts/run_v5_core_r2_retrospective.py"),
        "method_spec": sha256(ROOT / "research/V5_CORE_R2_METHOD_SPEC.md"),
    }
    if args.config:
        input_hashes["experiment_config"] = sha256(args.config)
    selected_name = workbook_null["selected"]
    write_json(args.output / "selected_wcn.json", {
        "development_only": True, "selected": selected_name,
        "selected_config_name": workbook_null["selected_config_name"],
        "selection_rule": workbook_null["selection_rule"],
        "selected_evidence": workbook_null["variants"].get(selected_name),
        "git_commit": git_commit(), "hashes": input_hashes, "model_config": config,
    })
    write_tables(args.output, error_summary, workbook_null)
    audit = {
        "protocol": "v5_core_r2_retrospective_audit_v2", "development_only": True,
        "independent_evidence": False, "errors": len(error_rows), "clean": len(clean_rows),
        "workers": args.workers, "wall_seconds": time.perf_counter() - started,
        "git_commit": git_commit(), "hashes": input_hashes, "model_config": config,
        "error_metrics": error_summary["metrics"], "clean_metrics": clean_summary,
        "cross_workbook_null": workbook_null, "gates": gates,
        "next_use": "mechanism diagnosis and bounded tuning only",
    }
    write_json(args.output / "r2_retrospective_audit.json", audit)
    print(args.output / "r2_retrospective_audit.json")
    print(f"R2 retrospective gates passed: {gates['hard_gate_passed']}")
    if not gates["hard_gate_passed"]:
        print("Failed gates: " + ", ".join(gates["failed_gates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
