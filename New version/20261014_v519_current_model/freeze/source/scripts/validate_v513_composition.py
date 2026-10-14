"""Verify cached baselines and exercise V5.1.3 composition on revealed cohorts."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import statistics
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from formulaguard.localize import LocalizationResult
from formulaguard.v5_1_2_development import v5_1_2_development_scores
from formulaguard.v5_1_3_development import (
    compose_diagnosis,
    diagnose_v5_1_3_development,
    v5_1_3_development_default_parameters,
)
from scripts.evaluate_v512_real_retrospective import aggregate, event_score
from scripts.run_v512_evaluation import load_workbook, write_json
from scripts.score_v512_confirmation import (
    safe_path,
    score_case,
    sha256,
    summarize,
    verify_double_run,
)

POLICIES = ("structural", "review_only", "reject_all")


def freeze(output: Path) -> dict:
    files = sorted([
        *ROOT.glob("formulaguard/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py"),
        ROOT / "research/V513_DEVELOPMENT_PLAN.md", ROOT / "pyproject.toml",
    ])
    lock = {
        "protocol": "v513_development_source_lock_v1",
        "artifacts": {p.relative_to(ROOT).as_posix(): sha256(p) for p in files},
        "parameters": v5_1_3_development_default_parameters(), "python": platform.python_version(),
        "evidence_scope": "revealed development fixtures and retrospective real workbooks",
        "baseline_cache": "verified V512 validation v2 predictions, not new baseline inference",
    }
    write_json(output / "source_lock.json", lock)
    return lock


def verify_baseline_cache(cohort: str):
    release = ROOT / f"results/v512_{cohort}_release_v2"
    predictions = ROOT / f"results/v512_{cohort}_predictions_v2"
    authorization_path = ROOT / f"results/v512_{cohort}_result_v2/reveal_authorization.json"
    authorization = json.loads(authorization_path.read_text())
    source_path = ROOT / "results/v512_validation_freeze_v2/source_lock.json"
    if sha256(source_path) != authorization["source_lock_sha256"]:
        raise ValueError("historical source lock hash mismatch")
    source = json.loads(source_path.read_text())
    # API composition is new; existing algorithm and shared runtime modules must
    # still match the exact sources that generated the cache.
    for relative, digest in source["artifacts"].items():
        if relative.startswith("formulaguard/") and relative != "formulaguard/api.py" and sha256(ROOT / relative) != digest:
            raise ValueError(f"baseline dependency changed: {relative}")
    if platform.python_version() != source["python"]:
        raise ValueError("baseline Python runtime changed")
    if any(importlib.metadata.version(name) != version for name, version in source["dependencies"].items()):
        raise ValueError("baseline dependency environment changed")
    receipt_path = release / "release_receipt.json"
    if sha256(receipt_path) != authorization["release_receipt_sha256"]:
        raise ValueError("release receipt changed")
    receipt = json.loads(receipt_path.read_text())
    public = release / "PUBLIC"
    manifest_path = public / "manifest.json"
    if sha256(manifest_path) != receipt["public_manifest_sha256"]:
        raise ValueError("public manifest changed")
    rows = json.loads(manifest_path.read_text())["cases"]
    expected = {}
    for row in rows:
        path = safe_path(public, row["workbook_path"])
        if sha256(path) != row["workbook_sha256"]:
            raise ValueError("public workbook changed")
        model = load_workbook(path, row["format"])
        expected[row["case_id"]] = {**row, "formula_cells": list(model.formulas)}
    cache = {}
    for backend in ("v4", "v511", "v512"):
        cache[backend] = verify_double_run(predictions / backend, authorization["prediction_locks"][backend], expected)
        for run in ("run_a", "run_b"):
            metadata = json.loads((predictions / backend / run / "prediction_metadata.json").read_text())
            if metadata["source_lock_sha256"] != sha256(source_path) or metadata["public_manifest_sha256"] != sha256(manifest_path):
                raise ValueError("baseline source/workbook binding changed")
    if sha256(release / "labels.json") != receipt["labels_sha256"]:
        raise ValueError("previously disclosed labels changed")
    labels = json.loads((release / "labels.json").read_text())
    return public, expected, cache, labels, {
        "source_lock_sha256": sha256(source_path), "authorization_sha256": sha256(authorization_path),
        "prediction_locks": authorization["prediction_locks"], "release_receipt_sha256": sha256(receipt_path),
    }


def materialize(diagnosis, row, variant):
    results = diagnosis.to_results()
    groups = {r.evidence["group_id"] for r in results if r.evidence["group_state"] == "accepted"}
    return {
        "case_id": row["case_id"], "cluster_id": row["cluster_id"], "model": variant,
        "workbook_sha256": row["workbook_sha256"], "formula_count": len(results),
        "accepted_group_count": len(groups), "localization_sha256": diagnosis.localization_sha256,
        "ranking": [{"rank": i, "sheet": r.cell[0], "cell": r.cell[1], "score": r.score,
                     "candidate_formula": r.candidate_formula, "evidence": r.evidence} for i, r in enumerate(results, 1)],
    }


def compose_one(task):
    path, row, baselines = task
    model = load_workbook(Path(path), row["format"])
    before = dict(model.formulas)
    repairs_a = v5_1_2_development_scores(model)
    repairs_b = v5_1_2_development_scores(model)
    if repairs_a != repairs_b:
        raise ValueError("structural repair rerun differs")
    original_repairs = {(r["sheet"], r["cell"]): r["candidate_formula"] for r in baselines["v512"]["ranking"]}
    if {r.cell: r.candidate_formula for r in repairs_a} != original_repairs:
        raise ValueError("structural repairs differ from frozen V5.1.2")
    variants = {}
    for backend in ("v4", "v511"):
        cached = baselines[backend]["ranking"]
        baseline = [LocalizationResult((r["sheet"], r["cell"]), r["score"], r["candidate_formula"], r["evidence"]) for r in cached]
        expected = [(r.cell, float(r.score).hex()) for r in baseline]
        for policy in POLICIES:
            variant = f"{backend}_{policy}"
            a = compose_diagnosis(model, baseline, repairs_a, backend=backend, repair_policy=policy)
            b = compose_diagnosis(model, baseline, repairs_b, backend=backend, repair_policy=policy)
            if asdict(a) != asdict(b):
                raise ValueError("composition double run differs")
            if [(r.cell, float(r.score).hex()) for r in a.localization] != expected:
                raise ValueError("repair changed localization ordering or score bits")
            result = materialize(a, row, variant)
            accepted = {(r["sheet"], r["cell"]): r["candidate_formula"] for r in result["ranking"]}
            if policy == "structural" and accepted != original_repairs:
                raise ValueError("composition changed structural acceptance")
            if policy != "structural" and any(value is not None for value in accepted.values()):
                raise ValueError("review/reject policy accepted a repair")
            variants[variant] = result
    if model.formulas != before:
        raise ValueError("evaluation mutated formulas")
    return row["case_id"], variants


def regression_diagnostics(cache, labels):
    rows = []
    for event in labels["events"]:
        case = event["case_id"]
        scores = {name: event_score(shards[case], event) for name, shards in cache.items()}
        reference = cache["v512"][case]["ranking"]
        total = len(reference)
        reasons = Counter(r.get("evidence", {}).get("group_reason", "unknown") for r in reference)
        rows.append({
            "event": event["instance_id"], "case_id": case,
            "first_ranks": {name: value["first_rank"] for name, value in scores.items()},
            "rr_delta_v512_minus_v4": scores["v512"]["reciprocal_rank"] - scores["v4"]["reciprocal_rank"],
            "rr_delta_v512_minus_v511": scores["v512"]["reciprocal_rank"] - scores["v511"]["reciprocal_rank"],
            "v512_zero_score_fraction": sum(r["score"] == 0 for r in reference) / total if total else None,
            "v512_reason_counts": dict(reasons),
            "missing_formula_labels": scores["v512"]["missing_formula_labels"],
        })
    return sorted(rows, key=lambda row: row["rr_delta_v512_minus_v4"])


def run(args):
    args.output.mkdir(parents=True, exist_ok=False)
    lock = freeze(args.output)
    overall = {"protocol": "v513_composition_validation_v1", "cohorts": {},
               "source_lock_sha256": sha256(args.output / "source_lock.json"),
               "decision": "LAYER_SEPARATION_VERIFIED_NOT_PRODUCTION_PROMOTION"}
    for cohort in ("heldout", "real"):
        public, expected, cache, labels, provenance = verify_baseline_cache(cohort)
        rows = list(expected.values())
        variants = {f"{backend}_{policy}": {} for backend in ("v4", "v511") for policy in POLICIES}
        tasks = [(str(safe_path(public, row["workbook_path"])), row,
                  {name: shards[row["case_id"]] for name, shards in cache.items()}) for row in rows]
        with ProcessPoolExecutor(max_workers=min(args.workers, len(tasks))) as executor:
            for index, (case, computed) in enumerate(executor.map(compose_one, tasks), 1):
                for variant, shard in computed.items():
                    variants[variant][case] = shard
                    write_json(args.output / cohort / "predictions" / variant / f"{case}.json", shard)
                if index % 25 == 0 or index == len(tasks):
                    print(f"{cohort}: {index}/{len(tasks)} verified", flush=True)
        # Content-independent live end-to-end check: choose the smallest workbook
        # by formula count, then opaque case ID, never by its outcome/labels.
        sample = min(rows, key=lambda row: (len(row["formula_cells"]), row["case_id"]))
        sample_model = load_workbook(safe_path(public, sample["workbook_path"]), sample["format"])
        live_checks = []
        for backend in ("v4", "v511"):
            for policy in POLICIES:
                actual = diagnose_v5_1_3_development(sample_model, localization_backend=backend, repair_policy=policy)
                cached = variants[f"{backend}_{policy}"][sample["case_id"]]
                live = materialize(actual, sample, f"{backend}_{policy}")
                if live != cached:
                    raise ValueError("live public API differs from verified composition cache")
                live_checks.append({"case_id": sample["case_id"], "backend": backend, "policy": policy, "passed": True})
        cohort_result = {"workbooks": len(rows), "formula_cells": sum(len(row["formula_cells"]) for row in rows),
                         "variants": {}, "baseline_provenance": provenance, "live_api_checks": live_checks,
                         "rank_changes": 0, "score_bit_changes": 0, "coverage_changes": 0,
                         "composition_double_run_identical": True}
        for variant, shards in variants.items():
            if cohort == "heldout":
                scored = [score_case(shards[label["case_id"]], label) for label in labels["cases"]]
                cohort_result["variants"][variant] = summarize(scored)
            else:
                scored = [event_score(shards[event["case_id"]], event) for event in labels["events"]]
                cohort_result["variants"][variant] = {
                    "all_events": aggregate(scored),
                    "fully_rankable_events": aggregate([row for row in scored if row["fully_rankable"]]),
                    "accepted_candidates": sum(r["candidate_formula"] is not None for s in shards.values() for r in s["ranking"]),
                    "repair_precision": None, "false_positive_rate": None,
                }
            write_json(args.output / cohort / f"{variant}_case_scores.json", scored)
        if cohort == "real":
            diagnostics = regression_diagnostics(cache, labels)
            write_json(args.output / "v512_regression_cases.json", diagnostics)
            cohort_result["regression_summary"] = {
                "events_worse_than_v4": sum(row["rr_delta_v512_minus_v4"] < 0 for row in diagnostics),
                "events_worse_than_v511": sum(row["rr_delta_v512_minus_v511"] < 0 for row in diagnostics),
                "workbook_macro_zero_score_fraction": statistics.fmean(
                    sum(r["score"] == 0 for r in shard["ranking"]) / len(shard["ranking"])
                    for shard in cache["v512"].values()),
            }
        overall["cohorts"][cohort] = cohort_result
    if any(sha256(ROOT / relative) != digest for relative, digest in lock["artifacts"].items()):
        raise ValueError("source changed during validation")
    write_json(args.output / "result.json", overall)
    paths = sorted(p for p in args.output.rglob("*") if p.is_file())
    write_json(args.output / "artifact_hashes.json", {p.relative_to(args.output).as_posix(): sha256(p) for p in paths})
    print(json.dumps({"decision": overall["decision"], "cohorts": {name: {key: value for key, value in row.items() if key not in {"baseline_provenance", "variants"}} for name, row in overall["cohorts"].items()}}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("workers must be positive")
    run(args)
