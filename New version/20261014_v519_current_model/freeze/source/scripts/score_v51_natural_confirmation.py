"""Reveal and score four locked V5.1 natural-structure predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path

MODEL_NAMES = ("v4_r1", "v5_v1", "v5_r2", "v5_1_development")
REPAIR_COHORTS = ("singleton", "contiguous_block", "systematic_column")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_formula(value: str | None) -> str | None:
    return None if value is None else "".join(str(value).split()).upper()


def cell_key(sheet: str, cell: str) -> tuple[str, str]:
    return sheet, cell.upper()


def average_precision(
    ranking: list[tuple[str, str]], truth: set[tuple[str, str]]
) -> float | None:
    if not truth:
        return None
    hits = 0
    total = 0.0
    for rank, cell in enumerate(ranking, 1):
        if cell in truth:
            hits += 1
            total += hits / rank
    return total / len(truth)


def load_secret(archive_path: Path, expected_sha: str) -> dict:
    if sha256_file(archive_path) != expected_sha:
        raise ValueError("SECRET hash differs from PUBLIC commitment")
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        if "SECRET/labels.json" not in names or "SECRET/mutation_log.json" not in names:
            raise ValueError("SECRET is incomplete")
        labels = json.loads(archive.read("SECRET/labels.json"))
        mutations = json.loads(archive.read("SECRET/mutation_log.json"))
    if labels.get("protocol") != "v51_natural_confirmation_secret_v1":
        raise ValueError("unexpected SECRET protocol")
    cases = labels.get("cases", [])
    if len(cases) != 240 or len({case["case_id"] for case in cases}) != 240:
        raise ValueError("SECRET label identity failure")
    if len(mutations) != sum(len(case["errors"]) for case in cases):
        raise ValueError("SECRET mutation ledger count failure")
    return labels


def load_public(release: Path) -> dict:
    receipt = json.loads((release / "release_receipt.json").read_text(encoding="utf-8"))
    public = release / "PUBLIC"
    commitment = (public / "SECRET_ARCHIVE_SHA256.txt").read_text().strip()
    if commitment != receipt["secret_sha256"]:
        raise ValueError("PUBLIC SECRET commitment differs from receipt")
    if sha256_file(release / receipt["public_archive"]) != receipt["public_sha256"]:
        raise ValueError("PUBLIC archive hash differs from receipt")
    with (public / "manifest.csv").open(encoding="utf-8") as stream:
        import csv

        rows = list(csv.DictReader(stream))
    if len(rows) != 240 or len({row["case_id"] for row in rows}) != 240:
        raise ValueError("PUBLIC identity failure")
    return receipt


def load_model_predictions(root: Path, expected_hash: str, public_archive_sha: str):
    lock_path = root / "run_a" / "prediction_lock.json"
    if sha256_file(lock_path) != expected_hash:
        raise ValueError(f"prediction lock hash differs: {root}")
    second = root / "run_b" / "prediction_lock.json"
    if sha256_file(second) != expected_hash:
        raise ValueError(f"double-run lock mismatch: {root}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    shards: dict[str, dict] = {}
    for path in sorted((root / "run_a" / "shards").glob("*.json")):
        shard = json.loads(path.read_text(encoding="utf-8"))
        shards[shard["case_id"]] = shard
    if len(shards) != 240:
        raise ValueError(f"prediction shard count differs: {root}")
    for run in ("run_a", "run_b"):
        metadata = json.loads(
            (root / run / "prediction_metadata.json").read_text(encoding="utf-8")
        )
        if metadata.get("labels_read") != []:
            raise ValueError(f"labels were read by {root.name} {run}")
        if metadata.get("public_archive_sha256") != public_archive_sha:
            raise ValueError(f"PUBLIC hash mismatch in {root.name} {run}")
    return lock, shards


def score_case(shard: dict, label: dict) -> dict:
    truth = {cell_key(item["sheet"], item["cell"]) for item in label["errors"]}
    expected = {
        cell_key(item["sheet"], item["cell"]): canonical_formula(item["expected_formula"])
        for item in label["errors"]
    }
    ranking = [cell_key(item["sheet"], item["cell"]) for item in shard["ranking"]]
    candidates = {
        cell_key(item["sheet"], item["cell"]): item["candidate_formula"]
        for item in shard["ranking"]
        if item["candidate_formula"] is not None
    }
    exact = {
        cell
        for cell, formula in candidates.items()
        if cell in expected and canonical_formula(formula) == expected[cell]
    }
    accepted = {
        cell
        for cell, item in zip(ranking, shard["ranking"], strict=True)
        if item["candidate_formula"] is not None
        and str(item.get("evidence", {}).get("group_state", "")) == "accepted"
    }
    accepted_exact = accepted & exact
    return {
        "case_id": label["case_id"],
        "cluster_id": label["cluster_id"],
        "family": label["family"],
        "cohort": label["cohort"],
        "decision": label["decision"],
        "errors": len(truth),
        "average_precision": average_precision(ranking, truth),
        "candidate_count": len(candidates),
        "candidate_truth_hits": len(set(candidates) & truth),
        "exact_repairs": len(exact),
        "accepted_candidate_count": len(accepted),
        "accepted_exact_repairs": len(accepted_exact),
        "accepted_group_count": int(shard.get("accepted_group_count", 0)),
    }


def summarize(rows: list[dict]) -> dict:
    repair = [row for row in rows if row["decision"] == "detect_and_repair"]
    abstain = [row for row in rows if row["decision"] == "abstain"]
    controls = [row for row in rows if row["decision"] == "no_action"]
    error_cells = sum(row["errors"] for row in repair)
    candidates = sum(row["candidate_count"] for row in repair)
    accepted = sum(row["accepted_candidate_count"] for row in repair)
    by_cohort = {}
    for cohort in REPAIR_COHORTS:
        subset = [row for row in repair if row["cohort"] == cohort]
        errors = sum(row["errors"] for row in subset)
        by_cohort[cohort] = {
            "cases": len(subset),
            "errors": errors,
            "exact_candidate_coverage": (
                sum(row["exact_repairs"] for row in subset) / errors if errors else None
            ),
            "average_precision": statistics.fmean(
                row["average_precision"] for row in subset
            )
            if subset
            else None,
        }
    return {
        "repair_cases": len(repair),
        "repair_error_cells": error_cells,
        "repair_macro_ap": statistics.fmean(row["average_precision"] for row in repair),
        "exact_candidate_coverage": sum(row["exact_repairs"] for row in repair) / error_cells,
        "candidate_location_precision": sum(row["candidate_truth_hits"] for row in repair) / candidates
        if candidates
        else None,
        "control_workbook_candidate_fpr": sum(row["candidate_count"] > 0 for row in controls)
        / len(controls),
        "ambiguous_workbook_candidate_rate": sum(row["candidate_count"] > 0 for row in abstain)
        / len(abstain),
        "accepted_group_exact_coverage": sum(row["accepted_exact_repairs"] for row in repair)
        / error_cells,
        "accepted_group_precision": sum(row["accepted_exact_repairs"] for row in repair) / accepted
        if accepted
        else None,
        "unsafe_accepted_groups": sum(
            row["accepted_group_count"] for row in rows if row["decision"] != "detect_and_repair"
        ),
        "accepted_groups_repair_cases": sum(row["accepted_group_count"] for row in repair),
        "by_cohort": by_cohort,
    }


def bootstrap_delta(left: list[dict], right: list[dict], seed: int) -> dict:
    by_left = defaultdict(list)
    by_right = defaultdict(list)
    for row in left:
        if row["decision"] == "detect_and_repair":
            by_left[row["cluster_id"]].append(row["average_precision"])
    for row in right:
        if row["decision"] == "detect_and_repair":
            by_right[row["cluster_id"]].append(row["average_precision"])
    clusters = sorted(by_left)
    if clusters != sorted(by_right):
        raise ValueError("paired cluster identities differ")
    observed = statistics.fmean(
        value for cluster in clusters for value in by_left[cluster]
    ) - statistics.fmean(value for cluster in clusters for value in by_right[cluster])
    rng = random.Random(seed)
    samples = []
    for _ in range(10_000):
        selected = [rng.choice(clusters) for _ in clusters]
        samples.append(
            statistics.fmean(value for cluster in selected for value in by_left[cluster])
            - statistics.fmean(value for cluster in selected for value in by_right[cluster])
        )
    samples.sort()
    return {"delta": observed, "ci95_lower": samples[249], "ci95_upper": samples[9749]}


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def write_report(path: Path, result: dict) -> None:
    lines = [
        "# V5.1-development natural-structure confirmation",
        "",
        f"Final decision: **{result['decision']['status']}**. {result['decision']['reason']}",
        "",
        "This is a fresh synthetic confirmation cohort administered by the same project. Model trees, thresholds, scorer, and gates were locked before the seed and PUBLIC/SECRET release; all predictions were double-run and locked before SECRET reveal.",
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
    lines += ["", "## V5.1 structure-stratum results", ""]
    for cohort in REPAIR_COHORTS:
        lines.append(f"### {cohort}")
        lines.append("")
        lines.append("| Model | Cases | Exact coverage | Macro AP |")
        lines.append("| --- | ---: | ---: | ---: |")
        for name in MODEL_NAMES:
            row = result["models"][name]["summary"]["by_cohort"][cohort]
            lines.append(
                f"| {name} | {row['cases']} | {pct(row['exact_candidate_coverage'])} | {pct(row['average_precision'])} |"
            )
        lines.append("")
    lines += ["## Paired comparisons", ""]
    for name, comparison in result["comparisons"].items():
        ap = comparison["macro_ap"]
        lines.append(
            f"- V5.1 minus {name}: AP delta {pct(ap['delta'])} (95% CI {pct(ap['ci95_lower'])} to {pct(ap['ci95_upper'])}); gates: "
            + ", ".join(f"{'PASS' if value else 'FAIL'} {key}" for key, value in comparison["gates"].items())
        )
    lines += [
        "",
        "## Limitations",
        "",
        "The cohort is synthetic and not independent third-party evidence. A PASS would justify a separately administered external confirmation, not replacement of the historical baseline by itself. A FAIL is diagnostic evidence and does not alter frozen historical results.",
        "",
    ]
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
    if authorization.get("protocol") != "v51_natural_confirmation_reveal_authorization_v1":
        raise SystemExit("reveal refused: invalid authorization")
    if authorization.get("model_lock_sha256") != sha256_file(args.model_lock.resolve()):
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
    target = model_results["v5_1_development"]["summary"]
    comparisons = {}
    for name in ("v4_r1", "v5_v1", "v5_r2"):
        baseline = model_results[name]["summary"]
        ap = bootstrap_delta(model_rows["v5_1_development"], model_rows[name], int(gates["bootstrap_seed"]))
        target_by = target["by_cohort"]
        cmp_gates = {
            "AP delta CI lower > 0": ap["ci95_lower"] > gates["macro_ap_delta_ci95_lower_gt"],
            "exact coverage non-inferior >= -5pp": target["exact_candidate_coverage"] - baseline["exact_candidate_coverage"] >= gates["exact_coverage_noninferiority_margin"],
            "control FPR <= 10%": target["control_workbook_candidate_fpr"] <= gates["control_workbook_candidate_fpr_max"],
            "ambiguous rate <= 10%": target["ambiguous_workbook_candidate_rate"] <= gates["ambiguous_workbook_candidate_rate_max"],
            "accepted group exact coverage >= 50%": target["accepted_group_exact_coverage"] >= gates["accepted_group_exact_coverage_min"],
            "accepted group precision >= 95%": target["accepted_group_precision"] is not None and target["accepted_group_precision"] >= gates["accepted_group_precision_min"],
            "zero unsafe accepted groups": target["unsafe_accepted_groups"] <= gates["unsafe_accepted_groups_max"],
            "singleton exact coverage >= 90%": target_by["singleton"]["exact_candidate_coverage"] >= gates["singleton_exact_coverage_min"],
            "contiguous block exact coverage >= 70%": target_by["contiguous_block"]["exact_candidate_coverage"] >= gates["contiguous_block_exact_coverage_min"],
            "systematic column exact coverage >= 50%": target_by["systematic_column"]["exact_candidate_coverage"] >= gates["systematic_column_exact_coverage_min"],
        }
        comparisons[name] = {"macro_ap": ap, "gates": cmp_gates, "passed": all(cmp_gates.values())}
    promoted = all(item["passed"] for item in comparisons.values())
    result = {
        "protocol": "v51_natural_confirmation_result_v1",
        "models": model_results,
        "comparisons": comparisons,
        "decision": {
            "status": "PROMOTE_V5_1" if promoted else "DO_NOT_PROMOTE_V5_1",
            "reason": "V5.1 passed every preregistered safety, structure, and paired utility gate."
            if promoted
            else "V5.1 failed one or more preregistered safety, structure, or paired utility gates.",
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
