"""Freeze the v3-real selection rule before the untouched Enron test run."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split-lock", type=Path, required=True)
    parser.add_argument("--development-analysis", type=Path, required=True)
    parser.add_argument("--development-raw", type=Path, required=True)
    parser.add_argument("--implementation-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    split = json.loads(args.split_lock.read_text(encoding="utf-8"))
    analysis = json.loads(args.development_analysis.read_text(encoding="utf-8"))
    if split.get("development_count") != 10 or split.get("test_count") != 20:
        raise SystemExit("Expected a locked 10-development / 20-test split")
    if not split.get("disjoint") or not split.get("union_equals_evaluation_ready"):
        raise SystemExit("External split is not a valid disjoint partition")
    if analysis.get("events") != 10 or analysis.get("quantitative_reporting_allowed"):
        raise SystemExit("Development analysis does not match the preregistered pilot rule")

    comparison = analysis["paired_comparisons"]["formulaguard_v3_real_minus_formulaguard"]
    if comparison["worse_events"] != 0:
        raise SystemExit("v3-real damaged the v2 development ranking; refusing to freeze")

    payload = {
        "schema_version": 1,
        "model_version": "v3-real-b",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "implementation_commit": args.implementation_commit,
        "selection_rule": "v2_raw_score_primary_then_positive_car_evidence_breaks_exact_ties_only",
        "candidate_limit": 15,
        "counterfactual_tiebreak_cap": 0.50,
        "weight_search_performed": False,
        "claim_policy": {
            "counterfactual_supported": "positive frozen-v3 CAR evidence exists",
            "pattern_only": "base pattern evidence exists but CAR support is absent",
            "insufficient_evidence": "no positive counterfactual or base evidence",
            "causal_claim_allowed": False,
        },
        "development": {
            "events": split["development_events"],
            "manifest_sha256": split["development_sha256"],
            "raw_results_sha256": sha256(args.development_raw),
            "analysis_sha256": sha256(args.development_analysis),
            "mrr_difference_vs_v2": comparison["mean_mrr_difference"],
            "worse_events_vs_v2": comparison["worse_events"],
        },
        "untouched_test": {
            "events": split["test_events"],
            "manifest_sha256": split["test_sha256"],
            "event_count": split["test_count"],
        },
        "source_hashes": {
            "formulaguard/localize.py": sha256(ROOT / "formulaguard/localize.py"),
            "scripts/run_external_evaluation.py": sha256(ROOT / "scripts/run_external_evaluation.py"),
            "scripts/analyze_external_results.py": sha256(ROOT / "scripts/analyze_external_results.py"),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
