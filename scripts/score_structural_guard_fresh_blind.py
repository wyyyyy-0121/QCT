"""Reveal and score three locked predictions against the committed SECRET."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import zipfile
from collections import defaultdict
from pathlib import Path


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
    if labels.get("protocol") != "structural_guard_fresh_blind_secret_v1":
        raise ValueError("unexpected SECRET protocol")
    cases = labels.get("cases", [])
    if len(cases) != 360 or len({case["case_id"] for case in cases}) != 360:
        raise ValueError("SECRET label identity failure")
    expected_mutations = sum(len(case["errors"]) for case in cases)
    if len(mutations) != expected_mutations:
        raise ValueError("SECRET mutation ledger count failure")
    return labels


def load_model_predictions(
    root: Path, expected_hash: str
) -> tuple[dict, dict[str, dict]]:
    lock_path = root / "prediction_lock.json"
    if sha256_file(lock_path) != expected_hash:
        raise ValueError(f"prediction lock hash differs: {root}")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    shards = {}
    for path in sorted((root / "shards").glob("*.json")):
        shard = json.loads(path.read_text(encoding="utf-8"))
        shards[shard["case_id"]] = shard
    if len(shards) != 360:
        raise ValueError(f"prediction shard count differs: {root}")
    return lock, shards


def score_case(shard: dict, label: dict) -> dict:
    truth = {cell_key(item["sheet"], item["cell"]) for item in label["errors"]}
    expected = {
        cell_key(item["sheet"], item["cell"]): canonical_formula(
            item["expected_formula"]
        )
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
    accepted_candidates = {
        cell
        for cell, item in zip(ranking, shard["ranking"], strict=True)
        if item["candidate_formula"] is not None
        and str(item.get("evidence", {}).get("group_state", "")) == "accepted"
    }
    accepted_exact = accepted_candidates & exact
    return {
        "case_id": label["case_id"],
        "cluster_id": label["cluster_id"],
        "cohort": label["cohort"],
        "decision": label["decision"],
        "language": label["language"],
        "errors": len(truth),
        "average_precision": average_precision(ranking, truth),
        "candidate_count": len(candidates),
        "candidate_truth_hits": len(set(candidates) & truth),
        "exact_repairs": len(exact),
        "accepted_candidate_count": len(accepted_candidates),
        "accepted_exact_repairs": len(accepted_exact),
        "accepted_group_count": shard["accepted_group_count"],
    }


def summarize(rows: list[dict]) -> dict:
    repair = [row for row in rows if row["decision"] == "detect_and_repair"]
    abstain = [row for row in rows if row["decision"] == "abstain"]
    controls = [row for row in rows if row["decision"] == "no_action"]
    error_cells = sum(row["errors"] for row in repair)
    candidates = sum(row["candidate_count"] for row in repair)
    accepted = sum(row["accepted_candidate_count"] for row in repair)
    return {
        "repair_cases": len(repair),
        "repair_error_cells": error_cells,
        "repair_macro_ap": statistics.fmean(row["average_precision"] for row in repair),
        "exact_candidate_coverage": sum(row["exact_repairs"] for row in repair)
        / error_cells,
        "candidate_location_precision": (
            sum(row["candidate_truth_hits"] for row in repair) / candidates
            if candidates
            else None
        ),
        "control_workbook_candidate_fpr": sum(
            row["candidate_count"] > 0 for row in controls
        )
        / len(controls),
        "ambiguous_workbook_candidate_rate": sum(
            row["candidate_count"] > 0 for row in abstain
        )
        / len(abstain),
        "accepted_group_exact_coverage": sum(
            row["accepted_exact_repairs"] for row in repair
        )
        / error_cells,
        "accepted_group_precision": (
            sum(row["accepted_exact_repairs"] for row in repair) / accepted
            if accepted
            else None
        ),
        "unsafe_accepted_groups": sum(
            row["accepted_group_count"]
            for row in rows
            if row["decision"] != "detect_and_repair"
        ),
        "accepted_groups_repair_cases": sum(
            row["accepted_group_count"] for row in repair
        ),
    }


def bootstrap_ap_delta(left: list[dict], right: list[dict]) -> dict:
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
    rng = random.Random(20260904)
    samples = []
    for _ in range(10_000):
        selected = [rng.choice(clusters) for _ in clusters]
        left_values = [value for cluster in selected for value in by_left[cluster]]
        right_values = [value for cluster in selected for value in by_right[cluster]]
        samples.append(statistics.fmean(left_values) - statistics.fmean(right_values))
    samples.sort()
    return {"delta": observed, "ci95_lower": samples[249], "ci95_upper": samples[9749]}


def pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.2f}%"


def write_report(path: Path, result: dict) -> None:
    models = result["models"]
    comparisons = result["comparisons"]
    decision = result["decision"]
    lines = [
        "# Fresh blind comparison: Structural Guard R2",
        "",
        "## Technical summary",
        "",
        f"Final decision: **{decision['status']}**. {decision['reason']}",
        "",
        "This is a fresh, AI-administered synthetic blind comparison. All model trees, parameters, metrics, and gates were committed before the generation seed was selected; all PUBLIC predictions were locked before SECRET reveal. It is not independent third-party evidence.",
        "",
        "## Frozen-model results",
        "",
        "| Model | Repair macro AP | Exact repair coverage | Repair candidate precision | Control workbook FPR | Accepted-group exact coverage | Accepted-group precision |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in ("v4_r1", "v5_v1", "v5_r2"):
        row = models[name]["summary"]
        lines.append(
            f"| {name} | {pct(row['repair_macro_ap'])} | {pct(row['exact_candidate_coverage'])} | "
            f"{pct(row['candidate_location_precision'])} | {pct(row['control_workbook_candidate_fpr'])} | "
            f"{pct(row['accepted_group_exact_coverage'])} | {pct(row['accepted_group_precision'])} |"
        )
    lines += ["", "## Preregistered gate decisions", ""]
    for comparator in ("v4_r1", "v5_v1"):
        comp = comparisons[comparator]
        lines += [
            f"### R2 versus {comparator}",
            "",
            (
                f"Paired cluster-bootstrap macro-AP delta: {pct(comp['macro_ap']['delta'])} "
                f"(95% CI {pct(comp['macro_ap']['ci95_lower'])} to "
                f"{pct(comp['macro_ap']['ci95_upper'])})."
            ),
            "",
        ]
        for gate, passed in comp["gates"].items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} — {gate}")
        lines.append("")
    lines += [
        "## Scope and metric definitions",
        "",
        "The denominator for macro AP is 180 repair-required workbooks. Exact repair coverage uses all true erroneous cells in those workbooks. Control FPR uses 120 no-action workbooks. Group metrics apply only to explicit accepted-group evidence emitted by frozen R2.",
        "",
        "## Method and integrity",
        "",
        "The comparison used 360 fresh generated XLSX files in 30 paired clusters across English, Chinese, and Spanish strata. Each model was executed from its exact Git tree. Two independent executions per model had to produce identical combined shard hashes. The scorer verified the PUBLIC-embedded SECRET SHA-256 commitment and the reveal authorization containing all prediction-lock hashes.",
        "",
        "## Limitations and robustness",
        "",
        "The benchmark is synthetic and the same AI administered generation and evaluation. Freezing prevents post-label model adaptation, but it does not make the test independent of the test designer. Results establish behavior on this declared cohort only. Tables are used instead of charts because the decision rests on a small set of exact gate values and confidence intervals.",
        "",
        "## Recommended next step",
        "",
        "If the decision is DO_NOT_PROMOTE, keep R2 as a frozen diagnostic result and design a new core against disclosed development evidence; do not tune on this SECRET and reuse it as blind confirmation. If it passes, seek a separately administered human/external confirmation cohort before replacing the historical baseline.",
        "",
        "## Further question",
        "",
        "The remaining external-validity question is whether the same safety/coverage tradeoff holds in independently sourced, naturally occurring workbooks.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release = json.loads(
        (args.release / "release_receipt.json").read_text(encoding="utf-8")
    )
    public_commitment = (
        (args.release / "PUBLIC" / "SECRET_ARCHIVE_SHA256.txt").read_text().strip()
    )
    if public_commitment != release["secret_sha256"]:
        raise SystemExit(
            "reveal refused: PUBLIC SECRET commitment differs from release receipt"
        )
    authorization = json.loads(args.authorization.read_text(encoding="utf-8"))
    if (
        authorization.get("protocol")
        != "structural_guard_fresh_blind_reveal_authorization_v1"
    ):
        raise SystemExit("reveal refused: invalid authorization")
    labels = load_secret(args.release / release["secret_archive"], public_commitment)
    labels_by_id = {case["case_id"]: case for case in labels["cases"]}
    model_rows = {}
    model_results = {}
    for name in ("v4_r1", "v5_v1", "v5_r2"):
        expected = authorization["prediction_locks"][name]
        _, shards = load_model_predictions(args.predictions / name / "run_a", expected)
        second_hash = sha256_file(
            args.predictions / name / "run_b" / "prediction_lock.json"
        )
        if second_hash != expected:
            raise SystemExit(f"reveal refused: {name} run locks are not identical")
        rows = [
            score_case(shards[case_id], label)
            for case_id, label in labels_by_id.items()
        ]
        model_rows[name] = rows
        model_results[name] = {"summary": summarize(rows)}
    comparisons = {}
    r2 = model_results["v5_r2"]["summary"]
    for comparator in ("v4_r1", "v5_v1"):
        baseline = model_results[comparator]["summary"]
        ap = bootstrap_ap_delta(model_rows["v5_r2"], model_rows[comparator])
        gates = {
            "macro AP delta CI lower bound > 0": ap["ci95_lower"] > 0,
            "exact repair coverage non-inferiority >= -5pp": r2[
                "exact_candidate_coverage"
            ]
            - baseline["exact_candidate_coverage"]
            >= -0.05,
            "control workbook FPR <= comparator": r2["control_workbook_candidate_fpr"]
            <= baseline["control_workbook_candidate_fpr"],
            "control workbook FPR <= 20%": r2["control_workbook_candidate_fpr"] <= 0.20,
            "accepted-group exact coverage >= 50%": r2["accepted_group_exact_coverage"]
            >= 0.50,
            "accepted-group precision >= 95%": r2["accepted_group_precision"]
            is not None
            and r2["accepted_group_precision"] >= 0.95,
            "zero unsafe accepted groups": r2["unsafe_accepted_groups"] == 0,
        }
        comparisons[comparator] = {
            "macro_ap": ap,
            "gates": gates,
            "passed": all(gates.values()),
        }
    promoted = all(item["passed"] for item in comparisons.values())
    result = {
        "protocol": "structural_guard_fresh_blind_result_v1",
        "models": model_results,
        "comparisons": comparisons,
        "decision": {
            "status": "PROMOTE_R2" if promoted else "DO_NOT_PROMOTE",
            "reason": "R2 passed every preregistered gate against both comparators."
            if promoted
            else "R2 failed one or more preregistered safety or utility gates.",
        },
        "integrity": {
            "public_sha256": release["public_sha256"],
            "secret_sha256": release["secret_sha256"],
            "prediction_locks": authorization["prediction_locks"],
            "double_run_identical": True,
        },
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for name, rows in model_rows.items():
        (args.output / f"{name}_case_scores.json").write_text(
            json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    write_report(args.output / "REPORT.md", result)
    print(json.dumps(result["decision"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
