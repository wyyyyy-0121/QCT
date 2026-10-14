"""Summarize already locked and scored predictions without rerunning a solver."""

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(formula):
    from scripts.score_v512_confirmation import canonical_formula

    return canonical_formula(formula)


def write_csv(path, rows):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    result = read(RUN / "score/result.json")
    assert result["workbooks"] == 51 and result["diagnoses"] == 612
    lock = read(RUN / "predictions/prediction_lock.json")
    assert lock["labels_read"] == [] and len(lock["shards"]) == 612
    for name, expected in lock["shards"].items():
        assert hashlib.sha256((RUN / "predictions" / name).read_bytes()).hexdigest() == expected
    labels = {r["case_id"]: r for r in read(RUN / "release/labels.json")["cases"]}
    manifest = read(RUN / "release/PUBLIC/manifest.json")
    manifest_by_id = {r["case_id"]: r for r in manifest["cases"]}
    inventory = []
    metrics = []
    for case_id, label in labels.items():
        public = manifest_by_id[case_id]
        raw = read(RUN / "release/PUBLIC" / public["workbook_path"])
        formulas = {tuple(r[:2]): r[2] for r in raw["formulas"]}
        truth = {tuple((r["sheet"], r["cell"])): canonical(r["expected_formula"]) for r in label["errors"]}
        expected = {c: truth.get(c, canonical(f)) for c, f in formulas.items()}
        assert set(truth) <= set(formulas)
        inventory.append({
            "slot": public["slot"], "case_id": case_id, "family": label["family"],
            "kind": label["kind"], "candidate_count": label["count"],
            "formula_cells": len(formulas), "error_cells": len(truth),
            "workbook_path": public["workbook_path"], "workbook_sha256": public["workbook_sha256"],
            "document_path": public["document_path"], "document_sha256": public["document_sha256"],
        })
        for backend in ("v4", "v511"):
            shard = read(RUN / f"predictions/shards/{backend}_main/{case_id}.json")
            diagnosis = shard["diagnosis"]
            ranking = [tuple(r["cell"]) for r in diagnosis["localization"]]
            assert len(ranking) == len(set(ranking)) == len(formulas) and set(ranking) == set(formulas)
            hits, ap_sum = 0, 0.0
            for rank, cell in enumerate(ranking, 1):
                if cell in truth:
                    hits += 1
                    ap_sum += hits / rank
            portfolio = defaultdict(set)
            for candidate in diagnosis["candidates"]:
                cell = tuple(candidate["cell"])
                candidate_formula = canonical(candidate["formula"])
                if candidate_formula != canonical(formulas[cell]):
                    portfolio[cell].add(candidate_formula)
            accepted = {tuple(d["cell"]): canonical(d["accepted_formula"])
                        for d in diagnosis["decisions"] if d["accepted_formula"] is not None}
            exact_candidates = sum(expected[c] in fs for c, fs in portfolio.items() if c in truth)
            correct_accepted = sum(c in truth and f == expected[c] for c, f in accepted.items())
            harmful = sum(c not in truth and f != expected[c] for c, f in accepted.items())
            metrics.append({
                "case_id": case_id, "backend": backend, "family": label["family"], "kind": label["kind"],
                "formula_cells": len(formulas), "error_cells": len(truth),
                "ordered_ap": ap_sum / len(truth) if truth else None,
                "recall_at_5": sum(c in truth for c in ranking[:5]) / len(truth) if truth else None,
                "recall_at_10": sum(c in truth for c in ranking[:10]) / len(truth) if truth else None,
                "recall_at_error_count": sum(c in truth for c in ranking[:len(truth)]) / len(truth) if truth else None,
                "candidate_cells": len(portfolio), "exact_candidate_error_cells": exact_candidates,
                "candidate_cells_on_correct_formulas": sum(c not in truth for c in portfolio),
                "wrong_formula_candidates": sum(f != expected[c] for c, fs in portfolio.items() for f in fs),
                "accepted_cells": len(accepted), "correct_accepted_error_cells": correct_accepted,
                "harmful_accepted_correct_cells": harmful,
                "search_status": diagnosis["search"]["status"],
                "ranking_seconds": shard["ranking_seconds"], "diagnosis_seconds": shard["diagnosis_seconds"],
            })
    inventory.sort(key=lambda r: r["slot"])
    write_csv(RUN / "INPUT_INVENTORY.csv", inventory)
    write_csv(RUN / "LOCALIZATION_AND_CANDIDATES.csv", metrics)
    strata = []
    for backend in ("v4", "v511"):
        kinds = sorted({r["kind"] for r in metrics})
        for kind in ["ALL", *kinds]:
            rows = [r for r in metrics if r["backend"] == backend and (kind == "ALL" or r["kind"] == kind)]
            errors = sum(r["error_cells"] for r in rows)
            correct = sum(r["correct_accepted_error_cells"] for r in rows)
            accepted = sum(r["accepted_cells"] for r in rows)
            strata.append({
                "backend": backend, "kind": kind, "workbooks": len(rows), "error_cells": errors,
                "macro_ordered_ap": statistics.mean(r["ordered_ap"] for r in rows if r["ordered_ap"] is not None),
                "macro_recall_at_5": statistics.mean(r["recall_at_5"] for r in rows if r["recall_at_5"] is not None),
                "macro_recall_at_10": statistics.mean(r["recall_at_10"] for r in rows if r["recall_at_10"] is not None),
                "macro_recall_at_error_count": statistics.mean(r["recall_at_error_count"] for r in rows if r["recall_at_error_count"] is not None),
                "exact_candidate_error_cells": sum(r["exact_candidate_error_cells"] for r in rows),
                "candidate_cells_on_correct_formulas": sum(r["candidate_cells_on_correct_formulas"] for r in rows),
                "wrong_formula_candidates": sum(r["wrong_formula_candidates"] for r in rows),
                "accepted_cells": accepted, "correct_accepted_error_cells": correct,
                "accepted_precision": correct / accepted if accepted else None,
                "repair_coverage": correct / errors if errors else None,
                "harmful_accepted_correct_cells": sum(r["harmful_accepted_correct_cells"] for r in rows),
                "median_ranking_seconds": statistics.median(r["ranking_seconds"] for r in rows),
                "median_diagnosis_seconds": statistics.median(r["diagnosis_seconds"] for r in rows),
            })
    write_csv(RUN / "STRATIFIED_METRICS.csv", strata)
    historical = read(ROOT / "research/V519_DEVELOPMENT_VALIDATION_V1/result.json")
    comparison = {key: {field: {"previous": historical["summaries"][key][field], "current": value[field],
                             "equal": historical["summaries"][key][field] == value[field]}
                       for field in ("workbooks", "required_cells", "correct_cells", "accepted_cells", "accepted_groups", "unsafe_groups", "coverage", "statuses")}
                  for key, value in result["summaries"].items()}
    all_equal = all(field["equal"] for entry in comparison.values() for field in entry.values())
    (RUN / "HISTORICAL_COMPARISON.json").write_text(json.dumps({"all_equal": all_equal, "comparison": comparison}, indent=2) + "\n")
    summary = {"scope": "fixed development generator, already revealed; no independent real-workbook validation",
               "workbooks": result["workbooks"], "diagnoses": result["diagnoses"],
               "historical_metrics_match": all_equal, "gate_passed": result["gate_passed"],
               "summaries": result["summaries"], "strata": strata,
               "metric_definitions": {"ordered_ap": "sum precision at each labeled error rank divided by all labeled errors; deterministic API order, without regrouping tied scores",
                                      "candidate_cells_on_correct_formulas": "unaccepted portfolio suggestions on correct formulas; distinct cells, not automatic changes",
                                      "accepted_precision": "correct accepted error formulas / all accepted formulas",
                                      "repair_coverage": "correct accepted error formulas / all labeled errors, including abstentions"}}
    (RUN / "METRICS_SUMMARY.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"historical_metrics_match": all_equal, "gate_passed": result["gate_passed"],
                      "overall": [r for r in strata if r["kind"] == "ALL"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    import sys

    sys.path.insert(0, str(ROOT))
    main()
