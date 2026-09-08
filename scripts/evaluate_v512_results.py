"""Verify locked predictions, authorize label reading, and publish evaluation.

No result is promoted automatically. The real corpus has incomplete repair
truth, so its output deliberately contains no safety/repair-precision estimate.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_v512_evaluation import load_workbook, write_json
from scripts.score_v512_confirmation import (
    safe_path,
    score_case,
    sha256,
    summarize,
    verify_double_run,
)


def real_metrics(shards, events):
    rows = []
    for event in events:
        shard = shards[event["case_id"]]
        truth = set()
        for text in (event.get("source_cells") or event.get("source_cell") or "").split(";"):
            if "!" in text:
                sheet, cell = text.rsplit("!", 1)
                truth.add((sheet.strip("'"), cell.replace("$", "").upper()))
        ranking = [(r["sheet"], r["cell"]) for r in shard["ranking"]]
        if not truth or not truth <= set(ranking):
            raise ValueError(f"real event truth absent from complete ranking: {event['instance_id']}")
        positions = [i for i, cell in enumerate(ranking, 1) if cell in truth]
        rows.append({
            "event": event["instance_id"], "case_id": event["case_id"], "error_cells": len(truth),
            "first_rank": min(positions), "reciprocal_rank": 1 / min(positions),
            "average_precision": sum(hit / pos for hit, pos in enumerate(positions, 1)) / len(truth),
            "hit_at_1": int(min(positions) <= 1), "hit_at_5": int(min(positions) <= 5),
            "hit_at_10": int(min(positions) <= 10),
        })
    return {
        "events": len(rows), "workbooks": len(shards),
        **{name: statistics.fmean(r[name] for r in rows) for name in
           ("reciprocal_rank", "average_precision", "hit_at_1", "hit_at_5", "hit_at_10")},
        "emitted_candidates": sum(r["candidate_formula"] is not None for s in shards.values() for r in s["ranking"]),
        "repair_precision": None, "control_fpr": None,
        "reason_unavailable": "known error locations are not complete repair or clean-cell truth",
    }, rows


def fmt(value):
    return "n/a" if value is None else f"{value:.2%}"


def evaluate(args):
    receipt = json.loads((args.release / "release_receipt.json").read_text())
    if sha256(args.source_lock) != receipt["source_lock_sha256"]:
        raise ValueError("release source lock mismatch")
    public = args.release / "PUBLIC"
    manifest_path = public / "manifest.json"
    if sha256(manifest_path) != receipt["public_manifest_sha256"]:
        raise ValueError("public manifest changed")
    manifest = json.loads(manifest_path.read_text())
    expected = {}
    parser_cells = supported_cells = 0
    from formulaguard.formula import parse_formula
    for row in manifest["cases"]:
        path = safe_path(public, row["workbook_path"])
        if sha256(path) != row["workbook_sha256"]:
            raise ValueError("workbook changed before scoring")
        workbook = load_workbook(path, row["format"])
        expected[row["case_id"]] = {**row, "formula_cells": list(workbook.formulas)}
        parser_cells += len(workbook.formulas)
        for formula in workbook.formulas.values():
            try:
                parse_formula(formula)
            except (ValueError, RecursionError):
                continue
            supported_cells += 1
    verified = {}
    locks = {}
    for name in args.models:
        root = args.predictions / name
        locks[name] = {run: sha256(root / run / "prediction_lock.json") for run in ("run_a", "run_b")}
        verified[name] = verify_double_run(root, locks[name], expected)
        for run in ("run_a", "run_b"):
            metadata = json.loads((root / run / "prediction_metadata.json").read_text())
            if metadata["source_lock_sha256"] != sha256(args.source_lock) or metadata["public_manifest_sha256"] != sha256(manifest_path):
                raise ValueError("prediction source/public identity mismatch")
    args.output.mkdir(parents=True, exist_ok=False)
    authorization = {
        "protocol": "v512_reveal_authorization_v1", "authorized_at": datetime.now(UTC).isoformat(),
        "source_lock_sha256": sha256(args.source_lock), "prediction_locks": locks,
        "release_receipt_sha256": sha256(args.release / "release_receipt.json"),
        "labels_sha256": receipt["labels_sha256"],
        "verified_before_label_read": ["public workbooks", "source/public binding", "every shard", "both runs", "complete ranking identities"],
    }
    write_json(args.output / "reveal_authorization.json", authorization)
    # First label-file access occurs after successful verification/authorization.
    labels_path = args.release / "labels.json"
    if sha256(labels_path) != receipt["labels_sha256"]:
        raise ValueError("labels differ from release commitment")
    labels = json.loads(labels_path.read_text())
    result = {
        "protocol": "v512_evaluation_v1", "mode": receipt["mode"],
        "source_lock_sha256": sha256(args.source_lock), "models": {},
        "integrity": {"double_run_verified": True, "all_shards_verified": True,
                      "authorization_sha256": sha256(args.output / "reveal_authorization.json")},
        "parser_coverage": {"total_formula_cells": parser_cells, "supported_formula_cells": supported_cells,
                            "fraction": supported_cells / parser_cells if parser_cells else None},
    }
    lines = ["# V5.1.2 validation", "", f"Evidence scope: {receipt['mode']}", ""]
    if receipt["mode"] == "held_out_structure_fixtures":
        cases = labels["cases"]
        if len(cases) != len(expected) or {c["case_id"] for c in cases} != set(expected):
            raise ValueError("label cohort differs from PUBLIC")
        lines += ["| Model | AP | Exact coverage | Global exact candidate precision | Whole-group precision | Unsafe groups | Control FPR | Ambiguity |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name, shards in verified.items():
            rows = [score_case(shards[label["case_id"]], label) for label in cases]
            summary = summarize(rows)
            by_cohort = {cohort: summarize([r for r in rows if r["cohort"] == cohort]) for cohort in sorted({r["cohort"] for r in rows})}
            by_family = {family: summarize([r for r in rows if r["family"] == family]) for family in sorted({r["family"] for r in rows})}
            result["models"][name] = {"summary": summary, "by_cohort": by_cohort, "by_family": by_family}
            write_json(args.output / f"{name}_case_scores.json", rows)
            lines.append(f"| {name} | {fmt(summary['repair_macro_ap'])} | {fmt(summary['exact_candidate_coverage'])} | {fmt(summary['global_exact_candidate_precision'])} | {fmt(summary['accepted_group_precision'])} | {summary['unsafe_accepted_groups_all_workbooks']} | {fmt(summary['control_workbook_candidate_fpr'])} | {fmt(summary['ambiguous_workbook_candidate_rate'])} |")
        target = result["models"]["v512"]["summary"]
        gates = json.loads(args.source_lock.read_text())["gates"]
        result["gates"] = {
            "control_fpr": target["control_workbook_candidate_fpr"] is not None and target["control_workbook_candidate_fpr"] <= gates["control_fpr_max"],
            "ambiguous_rate": target["ambiguous_workbook_candidate_rate"] is not None and target["ambiguous_workbook_candidate_rate"] <= gates["ambiguous_rate_max"],
            "group_precision": target["accepted_group_precision"] is not None and target["accepted_group_precision"] >= gates["group_precision_min"],
            "unsafe_groups": target["unsafe_accepted_groups_all_workbooks"] <= gates["unsafe_groups_max"],
            "exact_coverage": target["exact_candidate_coverage"] >= gates["exact_coverage_min"],
        }
        result["decision"] = "DEVELOPMENT_GATES_PASS" if all(result["gates"].values()) else "DO_NOT_PROMOTE"
        lines += ["", f"Decision: {result['decision']}", "", "## V5.1.2 strata", "",
                  "| Cohort | Cases | Exact coverage | Unsafe groups |", "| --- | ---: | ---: | ---: |"]
        for cohort, summary in result["models"]["v512"]["by_cohort"].items():
            lines.append(f"| {cohort} | {summary['cases']} | {fmt(summary['exact_candidate_coverage'])} | {summary['unsafe_accepted_groups_all_workbooks']} |")
        lines += ["", "The same project authored these held-out fixtures. They test formula/layout transfer relative to development fixtures, not independent natural-workbook generalization. Gates were frozen before outcome inspection. No threshold tuning on these results is allowed."]
    else:
        lines += ["| Model | Events | MRR | AP | Hit@1 | Hit@5 | Hit@10 | Candidates |",
                  "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
        for name, shards in verified.items():
            summary, rows = real_metrics(shards, labels["events"])
            result["models"][name] = {"summary": summary}
            write_json(args.output / f"{name}_event_scores.json", rows)
            lines.append(f"| {name} | {summary['events']} | {fmt(summary['reciprocal_rank'])} | {fmt(summary['average_precision'])} | {fmt(summary['hit_at_1'])} | {fmt(summary['hit_at_5'])} | {fmt(summary['hit_at_10'])} | {summary['emitted_candidates']} |")
        result["decision"] = "RETROSPECTIVE_LOCALIZATION_ONLY"
        result["excluded_events"] = labels["excluded_events"]
        lines += ["", "These real Enron workbooks have been used previously in the project. Results are retrospective and event-level. Known error locations do not establish repair correctness or clean controls; repair precision and false-positive rate are unavailable."]
    lines += ["", f"Parser coverage: {supported_cells}/{parser_cells} formula cells.", "",
              "Both runs and every bound prediction shard were checked before label reading. Inputs and historical model sources were not edited.", ""]
    write_json(args.output / "result.json", result)
    (args.output / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "models": {name: value["summary"] for name, value in result["models"].items()}}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--models", nargs="+", default=["v512", "v511", "v4"])
    evaluate(parser.parse_args())


if __name__ == "__main__":
    main()
