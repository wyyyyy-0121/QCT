"""Derive report numbers from existing predictions; do not run a model."""

import csv
import gzip
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROGRESS = ROOT / "New version"
sys.path.insert(0, str(ROOT))

from scripts.score_v512_confirmation import canonical_formula


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    dev = PROGRESS / "20261014_v519_current_model"
    enron = PROGRESS / "20261014_v519_enron_retrospective"
    metrics = read(dev / "METRICS_SUMMARY.json")
    labels = {r["case_id"]: r for r in read(dev / "release/labels.json")["cases"]}
    manifest = {r["case_id"]: r for r in read(dev / "release/PUBLIC/manifest.json")["cases"]}
    overall = {r["backend"]: r for r in metrics["strata"] if r["kind"] == "ALL"}
    derived = {}
    for backend in ("v4", "v511"):
        candidate_pairs = correct_pairs = formula_cells = errors = 0
        changed_cells = max_candidates_at_one_cell = 0
        for ident, label in labels.items():
            raw = read(dev / "release/PUBLIC" / manifest[ident]["workbook_path"])
            formulas = {tuple(r[:2]): canonical_formula(r[2]) for r in raw["formulas"]}
            truth = {(r["sheet"], r["cell"]): canonical_formula(r["expected_formula"])
                     for r in label["errors"]}
            expected = {c: truth.get(c, f) for c, f in formulas.items()}
            diagnosis = read(dev / f"predictions/shards/{backend}_main/{ident}.json")["diagnosis"]
            portfolio = defaultdict(set)
            for candidate in diagnosis["candidates"]:
                cell = tuple(candidate["cell"])
                formula = canonical_formula(candidate["formula"])
                if formula != formulas[cell]:
                    portfolio[cell].add(formula)
            candidate_pairs += sum(len(fs) for fs in portfolio.values())
            correct_pairs += sum(f == expected[c] for c, fs in portfolio.items() for f in fs)
            changed_cells += len(portfolio)
            max_candidates_at_one_cell = max(max_candidates_at_one_cell, max(map(len, portfolio.values()), default=0))
            formula_cells += len(formulas)
            errors += len(truth)
        assert correct_pairs == overall[backend]["exact_candidate_error_cells"] == 735
        assert candidate_pairs - correct_pairs == overall[backend]["wrong_formula_candidates"]
        assert candidate_pairs == changed_cells  # This run has one distinct changed formula per cell.
        derived[backend] = {
            "formula_cells": formula_cells, "error_cells": errors,
            "correct_cells": formula_cells - errors,
            "distinct_changed_candidate_pairs": candidate_pairs,
            "distinct_candidate_cells": changed_cells,
            "max_distinct_candidates_per_cell": max_candidates_at_one_cell,
            "correct_candidate_pairs": correct_pairs,
            "candidate_precision": correct_pairs / candidate_pairs,
            "false_candidate_rate_on_correct_formula_cells":
                overall[backend]["candidate_cells_on_correct_formulas"] / (formula_cells - errors),
        }

    execution = read(enron / "EXECUTION_PROGRESS.json")
    protocol = read(enron / "PROTOCOL.json")
    enron_result = read(enron / "RESULT.json")
    assert len(execution) == 50
    event_rows = list(csv.DictReader((enron / "EVENT_SCORES.csv").open(encoding="utf-8-sig")))
    successful = {
        b: {r["event_id"]: r for r in event_rows if r["backend"] == b
            and r["preincluded"] == "True" and r["execution_status"] == "completed"}
        for b in ("v4", "v511")
    }
    common = sorted(successful["v4"].keys() & successful["v511"].keys())
    enron_extra = {}
    for backend in ("v4", "v511"):
        tasks = [r for r in execution if r["backend"] == backend]
        completed = [r for r in tasks if r["status"] == "completed"]
        accepted = []
        unchanged = []
        for record in completed:
            payload = json.loads(gzip.decompress((enron / record["prediction"]).read_bytes()))
            workbook = Path(record["argv"][record["argv"].index("--workbook") + 1]).name
            unchanged.append(payload["model_unchanged"])
            for decision in payload["diagnosis"]["decisions"]:
                if decision["accepted_formula"] is not None:
                    accepted.append({"workbook": workbook, **decision, "correctness": "unknown"})
        assert len(accepted) == enron_result["summaries"][backend]["accepted_cells_across_unique_workbooks"] == 8
        assert all(unchanged)
        enron_extra[backend] = {
            "attempted_tasks": len(tasks), "completed_workbooks": len(completed),
            "timeouts": [Path(r["argv"][r["argv"].index("--workbook") + 1]).name
                         for r in tasks if r["status"] == "timeout"],
            "median_successful_task_seconds": statistics.median(r["elapsed_seconds"] for r in completed),
            "common_successful_preincluded_events": len(common),
            "top10_hits_on_common_events": sum(successful[backend][k]["top10_hit"] == "True" for k in common),
            "accepted_decisions_with_unknown_correctness": accepted,
            "all_successful_inputs_unchanged": all(unchanged),
        }
    score = read(dev / "score/result.json")
    source_lock = read(dev / "freeze/source_lock.json")
    sources = [dev / "METRICS_SUMMARY.json", dev / "score/result.json", dev / "freeze/source_lock.json",
               dev / "predictions/prediction_lock.json", dev / "HISTORICAL_COMPARISON.json",
               dev / "EXECUTION.json", enron / "RESULT.json", enron / "EVENT_SCORES.csv",
               enron / "PREDICTION_LOCK.json", enron / "PROTOCOL.json",
               PROGRESS / "20261014_dataset_review/ARCHIVE_AUDIT.json"]
    output = {
        "scope": "Report derivation from completed, previously revealed runs. No model execution or new-data scoring.",
        "model": "V5.1.9-development", "runtime_python": source_lock["environment"]["numeric"]["version"],
        "frozen_source_files": len(source_lock["sources"]),
        "development_stage_seconds": sum(r["elapsed_seconds"] for r in read(dev / "EXECUTION.json")),
        "replayed_certificates": sum(r["proof_replayed"] for r in score["records"]),
        "development_candidates": derived, "enron_supplement": enron_extra,
        "enron_timeout_seconds": protocol["timeout_seconds_per_workbook_and_backend"],
        "source_sha256": {p.relative_to(PROGRESS).as_posix(): sha(p) for p in sources},
    }
    target = Path(__file__).with_name("DERIVED_RESULT_AUDIT.json")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"runtime_python": output["runtime_python"], "development_candidates": derived,
                      "common_eligible_successful_enron_events": len(common), "output": str(target)},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
