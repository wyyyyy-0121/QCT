"""Reveal and score V5.1.1 against a fresh five-model confirmation release."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from scripts.score_v51_natural_confirmation import (
    MODEL_NAMES as _OLD_MODEL_NAMES,
)
from scripts.score_v51_natural_confirmation import (
    bootstrap_delta,
    load_model_predictions,
    load_public,
    load_secret,
    pct,
    score_case,
    summarize,
)

MODEL_NAMES = (*_OLD_MODEL_NAMES, "v5_1_1_development")


def write_report(path: Path, result: dict) -> None:
    lines = [
        "# V5.1.1 natural-structure confirmation",
        "",
        f"Final decision: **{result['decision']['status']}**. {result['decision']['reason']}",
        "",
        "Models, thresholds, scorer, and gates were locked before the fresh seed and PUBLIC/SECRET release. Predictions were double-run and locked before SECRET reveal. This remains project-administered synthetic evidence, not independent third-party evidence.",
        "",
        "## Results",
        "",
        "| Model | Repair macro AP | Exact coverage | Candidate precision | Control FPR | Ambiguous rate | Group exact coverage | Group precision | Unsafe groups |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in MODEL_NAMES:
        row = result["models"][name]["summary"]
        lines.append(
            f"| {name} | {pct(row['repair_macro_ap'])} | {pct(row['exact_candidate_coverage'])} | {pct(row['candidate_location_precision'])} | {pct(row['control_workbook_candidate_fpr'])} | {pct(row['ambiguous_workbook_candidate_rate'])} | {pct(row['accepted_group_exact_coverage'])} | {pct(row['accepted_group_precision'])} | {row['unsafe_accepted_groups']} |"
        )
    lines += ["", "## V5.1.1 structure strata", ""]
    for cohort in ("singleton", "contiguous_block", "systematic_column"):
        lines.extend([f"### {cohort}", "", "| Model | Cases | Exact coverage | Macro AP |", "| --- | ---: | ---: | ---: |"])
        for name in MODEL_NAMES:
            row = result["models"][name]["summary"]["by_cohort"][cohort]
            lines.append(f"| {name} | {row['cases']} | {pct(row['exact_candidate_coverage'])} | {pct(row['average_precision'])} |")
        lines.append("")
    lines += ["## Paired comparisons", ""]
    for name, comparison in result["comparisons"].items():
        ap = comparison["macro_ap"]
        gates = ", ".join(
            f"{'PASS' if value else 'FAIL'} {key}"
            for key, value in comparison["gates"].items()
        )
        lines.append(f"- V5.1.1 minus {name}: AP delta {pct(ap['delta'])} (95% CI {pct(ap['ci95_lower'])} to {pct(ap['ci95_upper'])}); {gates}")
    lines += ["", "## Limitations", "", "This is a synthetic cohort administered by the same project. A promotion decision would still require an independently administered natural-workbook confirmation.", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = load_public(args.release.resolve())
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    if authorization.get("protocol") != "v511_natural_confirmation_reveal_authorization_v1":
        raise SystemExit("reveal refused: invalid authorization")
    import hashlib

    if authorization.get("model_lock_sha256") != hashlib.sha256(args.model_lock.read_bytes()).hexdigest():
        raise SystemExit("reveal refused: model lock hash mismatch")
    labels = load_secret(args.release / receipt["secret_archive"], receipt["secret_sha256"])
    labels_by_id = {case["case_id"]: case for case in labels["cases"]}
    model_rows = {}
    model_results = {}
    for name in MODEL_NAMES:
        _, shards = load_model_predictions(
            args.predictions / name,
            authorization["prediction_locks"][name],
            receipt["public_sha256"],
        )
        rows = [score_case(shards[case_id], label) for case_id, label in labels_by_id.items()]
        model_rows[name] = rows
        model_results[name] = {"summary": summarize(rows)}
    gates = json.loads(args.model_lock.read_text(encoding="utf-8"))["promotion_gates"]
    target = model_results["v5_1_1_development"]["summary"]
    comparisons = {}
    for name in ("v4_r1", "v5_v1", "v5_r2", "v5_1_development"):
        baseline = model_results[name]["summary"]
        ap = bootstrap_delta(model_rows["v5_1_1_development"], model_rows[name], int(gates["bootstrap_seed"]))
        by = target["by_cohort"]
        comparisons[name] = {
            "macro_ap": ap,
            "gates": {
                "AP delta CI lower > 0": ap["ci95_lower"] > gates["macro_ap_delta_ci95_lower_gt"],
                "exact coverage non-inferior >= -5pp": target["exact_candidate_coverage"] - baseline["exact_candidate_coverage"] >= gates["exact_coverage_noninferiority_margin"],
                "control FPR <= 10%": target["control_workbook_candidate_fpr"] <= gates["control_workbook_candidate_fpr_max"],
                "ambiguous rate <= 10%": target["ambiguous_workbook_candidate_rate"] <= gates["ambiguous_workbook_candidate_rate_max"],
                "accepted group exact coverage >= 50%": target["accepted_group_exact_coverage"] >= gates["accepted_group_exact_coverage_min"],
                "accepted group precision >= 95%": target["accepted_group_precision"] is not None and target["accepted_group_precision"] >= gates["accepted_group_precision_min"],
                "zero unsafe accepted groups": target["unsafe_accepted_groups"] <= gates["unsafe_accepted_groups_max"],
                "singleton exact coverage >= 90%": by["singleton"]["exact_candidate_coverage"] >= gates["singleton_exact_coverage_min"],
                "contiguous block exact coverage >= 70%": by["contiguous_block"]["exact_candidate_coverage"] >= gates["contiguous_block_exact_coverage_min"],
                "systematic column exact coverage >= 50%": by["systematic_column"]["exact_candidate_coverage"] >= gates["systematic_column_exact_coverage_min"],
            },
        }
        comparisons[name]["passed"] = all(comparisons[name]["gates"].values())
    promoted = all(item["passed"] for item in comparisons.values())
    result = {
        "protocol": "v511_natural_confirmation_result_v1",
        "models": model_results,
        "comparisons": comparisons,
        "decision": {
            "status": "PROMOTE_V5_1_1" if promoted else "DO_NOT_PROMOTE_V5_1_1",
            "reason": "V5.1.1 passed every preregistered gate."
            if promoted
            else "V5.1.1 failed one or more preregistered gates.",
        },
        "integrity": {
            "public_sha256": receipt["public_sha256"],
            "secret_sha256": receipt["secret_sha256"],
            "prediction_locks": authorization["prediction_locks"],
            "double_run_identical": True,
            "labels_loaded_after_authorization": True,
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, rows in model_rows.items():
        (args.output / f"{name}_case_scores.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_report(args.output / "REPORT.md", result)
    print(json.dumps(result["decision"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
