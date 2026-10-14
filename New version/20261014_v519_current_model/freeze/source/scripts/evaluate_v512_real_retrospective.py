"""Versioned Enron scope audit after the strict scorer found partial labels.

Preserve all events, expose missing formula labels, and report both full-label
and fully rankable-event scopes. This is retrospective diagnosis, not a change
to the frozen synthetic scorer, model, or promotion gates.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_v512_evaluation import load_workbook, write_json
from scripts.score_v512_confirmation import safe_path, sha256, verify_double_run


def event_score(shard: dict, event: dict) -> dict:
    truth = set()
    for value in (event.get("source_cells") or event.get("source_cell") or "").split(";"):
        if "!" in value:
            sheet, cell = value.rsplit("!", 1)
            truth.add((sheet.strip("'"), cell.replace("$", "").upper()))
    if not truth:
        raise ValueError("event has no source labels")
    cells = [(r["sheet"], r["cell"]) for r in shard["ranking"]]
    missing = truth - set(cells)
    positions = [rank for rank, cell in enumerate(cells, 1) if cell in truth]
    ap_sum = sum(hit / rank for hit, rank in enumerate(positions, 1))
    first = min(positions) if positions else None
    return {
        "event": event["instance_id"], "case_id": event["case_id"],
        "annotated_cells": len(truth), "rankable_labeled_cells": len(truth) - len(missing),
        "missing_formula_labels": sorted(missing), "fully_rankable": not missing,
        "first_rank": first, "reciprocal_rank": 1 / first if first else 0.0,
        "ap_full_label_denominator": ap_sum / len(truth),
        "ap_rankable_label_denominator": ap_sum / len(positions) if positions else None,
        "hit_at_1": int(first is not None and first <= 1),
        "hit_at_5": int(first is not None and first <= 5),
        "hit_at_10": int(first is not None and first <= 10),
    }


def aggregate(rows: list[dict]) -> dict:
    names = ("reciprocal_rank", "ap_full_label_denominator", "hit_at_1", "hit_at_5", "hit_at_10")
    return {"events": len(rows), **{
        name: statistics.fmean(row[name] for row in rows) if rows else None for name in names
    }}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt_path = args.release / "release_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    authorization = json.loads(args.authorization.read_text())
    source_hash = sha256(args.source_lock)
    if receipt["mode"] != "retrospective_enron":
        raise ValueError("this scope audit is only for retrospective Enron labels")
    if source_hash != receipt["source_lock_sha256"] or source_hash != authorization["source_lock_sha256"]:
        raise ValueError("source lock mismatch")
    if sha256(receipt_path) != authorization["release_receipt_sha256"]:
        raise ValueError("release commitment mismatch")
    public = args.release / "PUBLIC"
    public_hash = sha256(public / "manifest.json")
    if public_hash != receipt["public_manifest_sha256"]:
        raise ValueError("PUBLIC manifest changed")
    expected = {}
    total_formulas = supported_formulas = 0
    from formulaguard.formula import parse_formula
    for row in json.loads((public / "manifest.json").read_text())["cases"]:
        path = safe_path(public, row["workbook_path"])
        if sha256(path) != row["workbook_sha256"]:
            raise ValueError("workbook hash mismatch")
        workbook = load_workbook(path, row["format"])
        expected[row["case_id"]] = {**row, "formula_cells": list(workbook.formulas)}
        total_formulas += len(workbook.formulas)
        for formula in workbook.formulas.values():
            try:
                parse_formula(formula)
            except (ValueError, RecursionError):
                continue
            supported_formulas += 1
    verified = {}
    for name, locks in authorization["prediction_locks"].items():
        root = args.predictions / name
        verified[name] = verify_double_run(root, locks, expected)
        for run in ("run_a", "run_b"):
            metadata = json.loads((root / run / "prediction_metadata.json").read_text())
            if metadata["source_lock_sha256"] != source_hash or metadata["public_manifest_sha256"] != public_hash:
                raise ValueError("prediction provenance mismatch")
    if sha256(args.release / "labels.json") != receipt["labels_sha256"]:
        raise ValueError("real labels changed")
    labels = json.loads((args.release / "labels.json").read_text())
    events = labels["events"]
    if len({e["instance_id"] for e in events}) != len(events):
        raise ValueError("duplicate real events")
    args.output.mkdir(parents=True, exist_ok=False)
    result = {
        "protocol": "v512_real_scope_audit_v1", "decision": "RETROSPECTIVE_LOCALIZATION_ONLY",
        "source_lock_sha256": source_hash, "analyzer_sha256": sha256(Path(__file__)),
        "prior_authorization_sha256": sha256(args.authorization),
        "model_and_prediction_changes": False,
        "integrity": {"all_shards_verified": True, "double_run_verified": True},
        "parser_coverage": {"total": total_formulas, "supported": supported_formulas,
                            "fraction": supported_formulas / total_formulas},
        "repair_precision": None, "false_positive_rate": None,
        "excluded_manifest_events": labels["excluded_events"], "models": {},
    }
    lines = ["# V5.1.2 real-workbook validation", "",
             "Scope: retrospective Enron localization on all included events; no automatic promotion.", "",
             "The original strict scorer rejected two events with labels outside the formula ranking. This versioned scope audit preserves all events, gives missing labels zero AP credit in the full-label denominator, and separately reports fully rankable events. Frozen predictions, model sources, and synthetic scoring gates are unchanged.", "",
             "| Model | Events | MRR | AP, full labels | Hit@1 | Hit@5 | Hit@10 | Candidate cells |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for name, shards in verified.items():
        rows = [event_score(shards[event["case_id"]], event) for event in events]
        all_events = aggregate(rows)
        complete = aggregate([row for row in rows if row["fully_rankable"]])
        candidate_count = sum(r["candidate_formula"] is not None for s in shards.values() for r in s["ranking"])
        result["models"][name] = {"all_events": all_events, "fully_rankable_events": complete,
                                  "candidate_cells": candidate_count}
        write_json(args.output / f"{name}_event_scores.json", rows)
        if "scope_audit" not in result:
            result["scope_audit"] = {
                "events": len(rows), "workbooks": len(expected),
                "fully_rankable_events": sum(row["fully_rankable"] for row in rows),
                "partial_events": [{key: row[key] for key in ("event", "annotated_cells", "rankable_labeled_cells", "missing_formula_labels")} for row in rows if not row["fully_rankable"]],
                "missing_formula_labels": sum(len(row["missing_formula_labels"]) for row in rows),
            }
        lines.append(f"| {name} | {len(rows)} | {all_events['reciprocal_rank']:.2%} | {all_events['ap_full_label_denominator']:.2%} | {all_events['hit_at_1']:.2%} | {all_events['hit_at_5']:.2%} | {all_events['hit_at_10']:.2%} | {candidate_count} |")
    lines += ["", "## Fully rankable events", "", "| Model | Events | MRR | AP |", "| --- | ---: | ---: | ---: |"]
    for name, value in result["models"].items():
        row = value["fully_rankable_events"]
        lines.append(f"| {name} | {row['events']} | {row['reciprocal_rank']:.2%} | {row['ap_full_label_denominator']:.2%} |")
    lines += ["", "## Label scope and limits", ""]
    for event in result["scope_audit"]["partial_events"]:
        lines.append(f"- {event['event']}: {event['rankable_labeled_cells']}/{event['annotated_cells']} annotated cells are present in the formula ranking; missing coordinates are recorded in result.json.")
    lines += ["", f"Parser coverage: {supported_formulas}/{total_formulas} formula cells.", "",
              "Known error locations do not establish correct repair formulas or complete clean-cell truth. Repair precision and false-positive rate are unavailable. Results are retrospective because these workbooks have previously been used in the project.", "",
              "The v4 and v511 algorithm source files match their historical files. All methods use the common current parsing runtime frozen for this evaluation. V4's shared a1/formula/workbook modules differ from its original release tree; this is not a replay of the complete original V4 environment.", ""]
    write_json(args.output / "result.json", result)
    (args.output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"scope": {key: value for key, value in result["scope_audit"].items() if key != "partial_events"}, "models": result["models"], "parser_coverage": result["parser_coverage"]}))


if __name__ == "__main__":
    main()
