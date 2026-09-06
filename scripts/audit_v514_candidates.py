"""Revealed-data candidate audit; labels never enter proposal generation."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from formulaguard.v5_1_2_development import (
    Parameters,
    _proposals,
    v5_1_2_development_scores,
)
from scripts.run_v512_evaluation import load_workbook, write_json
from scripts.score_v512_confirmation import canonical_formula, safe_path, sha256
from scripts.validate_v513_composition import verify_baseline_cache


def classify(correct_proposals, accepted_correct, reason):
    if accepted_correct:
        return "repaired"
    if not correct_proposals:
        return "no_correct_candidate"
    # Passing one member's gate is not sufficient for group acceptance or margin.
    # Only a self-reported accepted-evidence reason without an output is a rule
    # inconsistency; empirical correctness alone cannot establish authorization.
    if any(p.passes for p in correct_proposals) and reason in {
        "stable_copy_template", "two_sided_anchors_and_role",
    }:
        return "evidence_passed_but_rule_blocked"
    return "correct_candidate_insufficient_evidence"


def run(output: Path):
    output.mkdir(parents=True, exist_ok=False)
    public, expected, cache, labels, provenance = verify_baseline_cache("heldout")
    rows, case_rows = [], []
    for label in labels["cases"]:
        case = label["case_id"]
        row = expected[case]
        model = load_workbook(safe_path(public, row["workbook_path"]), row["format"])
        proposals = _proposals(model, Parameters())
        raw = defaultdict(list)
        for proposal in proposals:
            raw[proposal.cell].append(proposal)
        repairs = {r.cell: r for r in v5_1_2_development_scores(model)}
        cached = {(r["sheet"], r["cell"]): r for r in cache["v512"][case]["ranking"]}
        assert {k: r.candidate_formula for k, r in repairs.items()} == {
            k: r["candidate_formula"] for k, r in cached.items()
        }
        portfolios = {name: {(r["sheet"], r["cell"]): r["candidate_formula"]
                             for r in cache[name][case]["ranking"]} for name in ("v4", "v511")}
        case_result = {"case_id": case, "cohort": label["cohort"], "family": label["family"],
                       "decision": label["decision"], "raw_proposal_count": len(proposals),
                       "accepted_cells": sum(r.candidate_formula is not None for r in repairs.values()),
                       "error_cells": len(label["errors"])}
        case_rows.append(case_result)
        for error in label["errors"]:
            cell = (error["sheet"], error["cell"])
            truth = canonical_formula(error["expected_formula"])
            matches = [p for p in raw[cell] if canonical_formula(p.formula) == truth]
            repair = repairs[cell]
            accepted_correct = repair.candidate_formula is not None and canonical_formula(repair.candidate_formula) == truth
            legacy_correct = {name: bool(portfolios[name][cell]) and canonical_formula(portfolios[name][cell]) == truth
                              for name in portfolios}
            rows.append({
                **{k: case_result[k] for k in ("case_id", "cohort", "family", "decision")},
                "cell": cell, "expected_formula": error["expected_formula"],
                "original_formula": model.formulas[cell],
                "category": classify(matches, accepted_correct, repair.evidence["group_reason"]),
                "raw_structural_correct_candidate": bool(matches),
                "v513_a_portfolio_correct_candidate": bool(matches) or legacy_correct["v4"],
                "v513_b_portfolio_correct_candidate": bool(matches) or legacy_correct["v511"],
                "accepted_correct": accepted_correct, "reason": repair.evidence["group_reason"],
                "proposals": [asdict(p) for p in raw[cell]],
            })
    repair_rows = [r for r in rows if r["decision"] == "detect_and_repair"]
    def summarize(selected):
        count = len(selected)
        return {"error_cells": count, "categories": dict(Counter(r["category"] for r in selected)),
                **{field: {"covered": sum(r[field] for r in selected), "total": count,
                           "rate": sum(r[field] for r in selected) / count if count else None}
                   for field in ("raw_structural_correct_candidate", "v513_a_portfolio_correct_candidate",
                                 "v513_b_portfolio_correct_candidate", "accepted_correct")}}
    summary = {"scope": "previously revealed development fixtures; no new confirmation",
               "case_count": len(case_rows), "provenance": provenance,
               "repair_required": summarize(repair_rows),
               "abstention_labeled_errors": summarize([r for r in rows if r["decision"] == "abstain"]),
               "by_repair_cohort": {name: summarize([r for r in repair_rows if r["cohort"] == name])
                                    for name in sorted({r["cohort"] for r in repair_rows})},
               "category_scope": "V512 raw structural proposal mechanism, not all baseline suggestions",
               "portfolio_scope": "oracle union of raw structural and baseline proposals, an upper bound",
               "audit_source_sha256": sha256(Path(__file__))}
    write_json(output / "error_cells.json", rows)
    write_json(output / "cases.json", case_rows)
    write_json(output / "summary.json", summary)
    write_json(output / "artifact_hashes.json", {p.name: sha256(p) for p in sorted(output.glob("*.json"))})
    print(json.dumps({k: summary[k] for k in ("case_count", "repair_required", "by_repair_cohort")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args().output)
