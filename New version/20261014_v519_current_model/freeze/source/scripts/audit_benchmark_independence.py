"""Quantify design coupling between synthetic mutations and repair candidates.

This audit is deliberately adversarial.  It asks whether the benchmark's known
correct formulas are recoverable because the mutation families mirror the
bounded edits implemented by FormulaGuard.  A high coupling score is not a
software failure; it is a limit on what synthetic accuracy can prove.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import load_jsonl, parse_cell_label
from formulaguard.formula import normalized_formula
from formulaguard.localize import generate_candidates
from formulaguard.workbook import WorkbookModel

MUTATION_TO_REPAIR_KINDS = {
    "M1_reference_shift": {"reference_shift", "copy_offset", "copy_offset_row"},
    "M2_range_boundary": {
        "range_boundary",
        "range_boundary_row",
        "range_boundary_end_row",
        "range_boundary_end_col",
    },
    "M3_operator": {"operator"},
    "M4_function": {"aggregate_function"},
    "M5_absolute_reference": {"absolute_reference", "parameter_anchor", "reference_shift"},
    "M6_copy_offset": {"copy_offset", "copy_offset_row", "reference_shift"},
}


def classify_coupling(mutation_type: str, edit_kinds: set[str]) -> bool:
    """Return whether the exact repair uses the mutation family's mirrored edit."""
    return bool(MUTATION_TO_REPAIR_KINDS.get(mutation_type, set()) & edit_kinds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit coupling between benchmark mutations and candidate repair operators"
    )
    parser.add_argument("--validation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--candidate-limit", type=int, default=15)
    parser.add_argument("--sample-limit", type=int, default=0)
    args = parser.parse_args()

    rows = list(load_jsonl(args.validation / "validated_instances.jsonl"))
    if args.sample_limit:
        rows = rows[: args.sample_limit]
    if not rows:
        raise SystemExit("No validated instances found")

    benchmark_root = args.validation.parent
    details: list[dict[str, object]] = []
    for index, row in enumerate(rows, 1):
        workbook = benchmark_root / row["mutant_workbook"]
        model = WorkbookModel.from_xlsx(workbook)
        source = parse_cell_label(row["source_cell"])
        correct = normalized_formula(row["correct_formula"])
        candidates = generate_candidates(model, source, args.candidate_limit)
        exact_rank = 0
        exact_sources: set[str] = set()
        exact_kinds: set[str] = set()
        for rank, candidate in enumerate(candidates, 1):
            if normalized_formula(candidate.formula) == correct:
                exact_rank = rank
                exact_sources.update(candidate.sources)
                exact_kinds.update(candidate.edit_kinds)
                break
        details.append({
            "instance_id": row["instance_id"],
            "template_family": row.get("template_family", ""),
            "mutation_type": row["mutation_type"],
            "generator": row.get("generator", ""),
            "formula_count": len(model.formulas),
            "exact_candidate_found": int(exact_rank > 0),
            "exact_candidate_rank": exact_rank or "",
            "exact_candidate_sources": ";".join(sorted(exact_sources)),
            "exact_candidate_edit_kinds": ";".join(sorted(exact_kinds)),
            "mirrored_operator_match": int(classify_coupling(row["mutation_type"], exact_kinds)),
            "bounded_edit_involved": int("bounded_edit" in exact_sources),
            "peer_translation_involved": int("peer_translation" in exact_sources),
        })
        if index % 100 == 0:
            print(f"[{index}/{len(rows)}]", flush=True)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(details[0]))
        writer.writeheader()
        writer.writerows(details)

    count = len(details)
    found = sum(int(row["exact_candidate_found"]) for row in details)
    mirrored = sum(int(row["mirrored_operator_match"]) for row in details)
    bounded = sum(int(row["bounded_edit_involved"]) for row in details)
    peer = sum(int(row["peer_translation_involved"]) for row in details)
    by_mutation: dict[str, dict[str, object]] = {}
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in details:
        groups[str(row["mutation_type"])].append(row)
    for mutation, group in sorted(groups.items()):
        by_mutation[mutation] = {
            "instances": len(group),
            "candidate_coverage_at_limit": sum(int(r["exact_candidate_found"]) for r in group) / len(group),
            "mirrored_operator_rate": sum(int(r["mirrored_operator_match"]) for r in group) / len(group),
            "candidate_rank_counts": dict(sorted(Counter(
                str(r["exact_candidate_rank"]) for r in group if r["exact_candidate_rank"]
            ).items())),
        }

    coverage = found / count
    mirror_rate = mirrored / count
    if coverage >= 0.95 and mirror_rate >= 0.90:
        risk = "high"
    elif coverage >= 0.80 or mirror_rate >= 0.75:
        risk = "moderate"
    else:
        risk = "low"
    audit = {
        "instances": count,
        "candidate_limit": args.candidate_limit,
        "exact_candidate_coverage": coverage,
        "mirrored_operator_rate": mirror_rate,
        "bounded_edit_involvement_rate": bounded / count,
        "peer_translation_involvement_rate": peer / count,
        "design_coupling_risk": risk,
        "by_mutation_type": by_mutation,
        "interpretation": (
            "High coverage is useful for testing localization after a candidate exists, "
            "but mirrored mutation and repair operators mean this benchmark is not an "
            "independent test of repair-candidate generalization."
        ),
        "paper_rule": (
            "Report synthetic localization and controlled propagation evidence, but reserve "
            "real-world generalization claims for naturally occurring or independently authored errors."
        ),
    }
    audit_path = args.output.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(audit_path)


if __name__ == "__main__":
    main()
