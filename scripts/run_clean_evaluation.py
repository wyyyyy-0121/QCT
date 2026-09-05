from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.localize import localize
from formulaguard.workbook import WorkbookModel


def percentile(values, q):
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * q
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def select_threshold(mutant_scores, clean_scores, max_clean_alarm):
    """Maximize mutant-source recall subject to a bounded clean alarm rate."""
    values = sorted({float(value) for value in [*mutant_scores, *clean_scores]})
    if not values:
        return 0.0, 0.0, 0.0
    epsilon = max(1e-12, abs(values[-1]) * 1e-12)
    candidates = values + [values[-1] + epsilon]
    feasible = []
    for threshold in candidates:
        recall = statistics.fmean(score >= threshold for score in mutant_scores) if mutant_scores else 0.0
        alarm_rate = statistics.fmean(score >= threshold for score in clean_scores) if clean_scores else 0.0
        if alarm_rate <= max_clean_alarm + 1e-12:
            feasible.append((recall, threshold, alarm_rate))
    return max(feasible, key=lambda item: (item[0], item[1]))


def main():
    parser = argparse.ArgumentParser(description="Estimate clean-workbook alarm rate with leave-one-family-out thresholds")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--mutant-results", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--target-recall", type=float, default=0.95)
    parser.add_argument("--max-clean-alarm", type=float, default=0.25)
    parser.add_argument("--min-mutant-recall", type=float, default=0.80)
    parser.add_argument("--config", type=Path, help="Frozen quick configuration used by full evaluation")
    parser.add_argument("--model-version", choices=("v2", "v3"), default="v2")
    args = parser.parse_args()

    clean_manifest = json.loads((args.benchmark / "clean_manifest.json").read_text(encoding="utf-8"))
    primary_method = "formulaguard_v3" if args.model_version == "v3" else "formulaguard"
    with (args.mutant_results / "raw_results.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        mutant_rows = [row for row in csv.DictReader(handle) if row["method"] == primary_method]
    if not clean_manifest or not mutant_rows:
        raise SystemExit("Clean manifest or FormulaGuard mutant scores are empty.")

    gir_weights = (0.35, 0.50, 0.10, 0.05)
    frozen = None
    if args.config:
        frozen = json.loads(args.config.read_text(encoding="utf-8"))
        if frozen.get("model_version", args.model_version) != args.model_version:
            raise SystemExit("Frozen configuration model_version does not match clean evaluation.")
        args.candidate_limit = int(frozen["candidate_limit"])
        gir_weights = tuple(float(value) for value in frozen["gir_weights"])
    clean_families = {record["family"] for record in clean_manifest}
    calibration_families = {row["template_family"] for row in mutant_rows}
    scored_clean = []
    for record in clean_manifest:
        family = record["family"]
        model = WorkbookModel.from_xlsx(args.benchmark / record["path"])
        ranking = localize(model, primary_method, candidate_limit=args.candidate_limit, gir_weights=gir_weights)
        if args.model_version == "v3":
            top = max(ranking, key=lambda item: float(item.evidence.get("evidence_strength", 0.0)), default=None)
            top_score = float(top.evidence.get("evidence_strength", 0.0)) if top else 0.0
        else:
            top = ranking[0] if ranking else None
            top_score = top.score if top else 0.0
        scored_clean.append((record, len(model.formulas), top, top_score))

    score_field = "evidence_strength" if args.model_version == "v3" else "source_score"
    mutant_scores = [float(row[score_field]) for row in mutant_rows]
    clean_scores = [row[3] for row in scored_clean]
    if frozen:
        threshold = float(frozen["alarm_threshold"])
        calibration_recall = float(frozen["calibration_mutant_recall"])
        calibration_alarm = float(frozen["calibration_clean_alarm_rate"])
        protocol = "frozen quick threshold"
    else:
        calibration_recall, threshold, calibration_alarm = select_threshold(
            mutant_scores, clean_scores, args.max_clean_alarm
        )
        protocol = "maximize mutant-source recall subject to clean-alarm constraint"

    rows = []
    for record, formula_count, top, top_score in scored_clean:
        family = record["family"]
        rows.append({
            "clean_id": record["cleanId"],
            "template_family": family,
            "formula_count": formula_count,
            "threshold": threshold,
            "top_cell": top.cell_label if top else "",
            "top_score": top_score,
            "alarm": int(top_score >= threshold),
        })

    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "clean_results.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "clean_workbooks": len(rows),
        "target_mutant_recall": args.target_recall,
        "minimum_mutant_recall": args.min_mutant_recall,
        "maximum_clean_alarm_rate": args.max_clean_alarm,
        "selected_threshold": threshold,
        "calibration_mutant_recall": calibration_recall,
        "calibration_clean_alarm_rate": calibration_alarm,
        "threshold_gate_passed": calibration_recall >= args.min_mutant_recall and calibration_alarm <= args.max_clean_alarm,
        "threshold_protocol": protocol,
        "model_version": args.model_version,
        "alarm_score": score_field,
        "calibration_results": str(args.mutant_results),
        "frozen_config": str(args.config) if args.config else "",
        "gir_weights": gir_weights,
        "clean_families": sorted(clean_families),
        "calibration_families": sorted(calibration_families),
        "family_overlap": sorted(clean_families & calibration_families),
        "alarm_rate": statistics.fmean(row["alarm"] for row in rows),
        "median_top_score": statistics.median(row["top_score"] for row in rows),
        "warning": "This is a synthetic clean-workbook alarm estimate, not a production false-positive claim.",
    }
    (args.output / "clean_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
