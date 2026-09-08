"""Codex-owned 24-case V6 engineering smoke and artifact audit."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.workbook import WorkbookModel


def run(*parts):
    completed = subprocess.run([sys.executable, *map(str, parts)], cwd=ROOT, check=False)
    if completed.returncode:
        raise SystemExit(completed.returncode)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_prediction_shards(prediction: Path) -> dict[str, bool]:
    complete_rankings = True
    evidence_complete = True
    at_most_one_promotion = True
    stable_v4_remainder = True
    for path in sorted((prediction / "shards").glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        v4 = [row["cell"] for row in payload["rankings"]["v4"]]
        formula_count = payload["formula_count"]
        for variant in ("v6_a", "v6_b", "v6_c"):
            ranking = payload["rankings"][variant]
            cells = [row["cell"] for row in ranking]
            promoted = [row["cell"] for row in ranking if row["evidence"].get("promotion_target")]
            complete_rankings &= len(cells) == formula_count and len(set(cells)) == formula_count
            at_most_one_promotion &= len(promoted) <= 1
            stable_v4_remainder &= (
                [cell for cell in cells if cell not in promoted]
                == [cell for cell in v4 if cell not in promoted]
            )
            evidence_complete &= all(
                "semantic_energy_gain" in row["evidence"]
                and "counterfactual_delta" in row["evidence"]
                and "candidate_portfolio" in row["evidence"]
                for row in ranking
            )
    return {
        "complete_nonduplicate_rankings": complete_rankings,
        "semantic_counterfactual_evidence_complete": evidence_complete,
        "at_most_one_promotion_per_workbook": at_most_one_promotion,
        "nonpromoted_v4_order_preserved": stable_v4_remainder,
    }


def main():
    benchmark = Path("data/v6_smoke_semantic_r4")
    clean = Path("data/v6_smoke_semantic_clean_r4")
    output = Path("results/v6_smoke_semantic_r4")
    if not (benchmark / "dataset_manifest.json").exists():
        run("scripts/build_v6_dataset.py", "--profile", "smoke", "--output", benchmark)
    if not (clean / "dataset_manifest.json").exists():
        run("scripts/build_v6_dataset.py", "--profile", "clean", "--output", clean, "--limit", "6")
    run("scripts/audit_v6_dataset.py", benchmark, clean)
    prediction = output / "predictions"
    if not (prediction / "prediction_complete.json").exists():
        run("scripts/run_v6_predictions.py", "--benchmark", benchmark, "--output", prediction, "--variants", "a", "b", "c", "--workers", "4")
    run("scripts/run_v6_predictions.py", "--benchmark", benchmark, "--output", prediction, "--variants", "a", "b", "c", "--workers", "4", "--resume")
    run("scripts/score_v6_predictions.py", "--benchmark", benchmark, "--predictions", prediction, "--output", output, "--bootstrap", "200")
    run("scripts/build_v6_report.py", "--results", output, "--title", "FormulaGuard V6 24-case smoke")
    clean_prediction = output / "clean_predictions"
    if not (clean_prediction / "prediction_complete.json").exists():
        run("scripts/run_v6_predictions.py", "--benchmark", clean, "--output", clean_prediction, "--variants", "a", "b", "c", "--workers", "4", "--clean")
    run("scripts/run_v6_predictions.py", "--benchmark", clean, "--output", clean_prediction, "--variants", "a", "b", "c", "--workers", "4", "--clean", "--resume")
    run("scripts/score_v6_clean.py", "--predictions", clean_prediction, "--output", output / "clean")
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    quality = json.loads((benchmark / "validation/dataset_quality.json").read_text(encoding="utf-8"))
    clean_summary = json.loads((output / "clean/v6_clean_summary.json").read_text(encoding="utf-8"))
    metadata = json.loads((prediction / "prediction_metadata.json").read_text(encoding="utf-8"))
    errors = summary["summaries"]["v6_c"]["by_error"]
    workbook = output / "FormulaGuard_V6_results.xlsx"
    checks = {
        "all_24_instances_valid": quality["valid_instances"] == 24 and quality["valid_rate"] == 1.0,
        "six_error_types_covered": len(errors) == 6 and all(row["events"] == 4 for row in errors.values()),
        "candidate_coverage_at_25_complete": summary["summaries"]["v6_c"]["candidate_coverage_at_25"] == 1.0,
        "traceability_complete": summary["traceability_complete"],
        "formula_safe_xlsx": workbook.exists() and not WorkbookModel.from_xlsx(workbook).formulas,
        "paper_tables_and_figures_exist": all((output / name).exists() for name in (
            "REPORT.md", "by_stratum.csv", "failure_cases.csv", "v6_macro_top5.svg", "v6_error_top5.svg",
        )),
        "resume_and_full_ranking_audit_verified": all(
            json.loads((path / "prediction_complete.json").read_text(encoding="utf-8")).get("full_ranking_audit_passed")
            for path in (prediction, clean_prediction)
        ),
        "current_v6_source_hash_recorded": metadata["v6_source_sha256"] == sha256(ROOT / "formulaguard/v6.py"),
        "clean_special_cases_not_promoted": all(row["alarms"] == 0 for row in clean_summary["variants"].values()),
    }
    checks.update(audit_prediction_shards(prediction))
    audit = {"protocol": "v6_24_case_engineering_smoke", "checks": checks, "passed": all(checks.values())}
    (output / "completion_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output / "completion_audit.json")
    if not audit["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
