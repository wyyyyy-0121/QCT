"""Audit completeness and pre-registered safety gates for the v4 dev run."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


EXPECTED_METHODS = (
    "graph",
    "pattern",
    "formulaguard",
    "formulaguard_v3",
    "formulaguard_v4",
)


def _as_float(row: dict[str, str], field: str, default: float = 0.0) -> float:
    value = row.get(field, "")
    return float(value) if value not in {"", None} else default


def build_audit(rows: list[dict[str, str]], *, expected_events: int = 30) -> dict[str, object]:
    """Return a machine-readable audit without hiding failed gates."""
    keys = [(row.get("instance_id", ""), row.get("method", "")) for row in rows]
    duplicate_keys = sorted(key for key, count in Counter(keys).items() if count > 1)
    by_instance: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        by_instance[row["instance_id"]][row["method"]] = row

    missing_pairs = [
        [instance_id, method]
        for instance_id in sorted(by_instance)
        for method in EXPECTED_METHODS
        if method not in by_instance[instance_id]
    ]
    unexpected_methods = sorted({row["method"] for row in rows} - set(EXPECTED_METHODS))
    v4_rows = [row for row in rows if row.get("method") == "formulaguard_v4"]
    statuses = Counter(row.get("diagnostic_status", "") for row in v4_rows)

    severe_v4_vs_graph = []
    severe_v3_vs_graph = []
    severe_v4_vs_v2 = []
    severe_v3_vs_v2 = []
    for instance_id, methods in sorted(by_instance.items()):
        if {"formulaguard_v4", "graph"} <= methods.keys():
            drop = int(float(methods["formulaguard_v4"]["rank"])) - int(float(methods["graph"]["rank"]))
            if drop > 20:
                severe_v4_vs_graph.append({"instance_id": instance_id, "rank_drop": drop})
        if {"formulaguard_v3", "graph"} <= methods.keys():
            drop = int(float(methods["formulaguard_v3"]["rank"])) - int(float(methods["graph"]["rank"]))
            if drop > 20:
                severe_v3_vs_graph.append({"instance_id": instance_id, "rank_drop": drop})
        if {"formulaguard_v4", "formulaguard"} <= methods.keys():
            drop = int(float(methods["formulaguard_v4"]["rank"])) - int(float(methods["formulaguard"]["rank"]))
            if drop > 20:
                severe_v4_vs_v2.append({"instance_id": instance_id, "rank_drop": drop})
        if {"formulaguard_v3", "formulaguard"} <= methods.keys():
            drop = int(float(methods["formulaguard_v3"]["rank"])) - int(float(methods["formulaguard"]["rank"]))
            if drop > 20:
                severe_v3_vs_v2.append({"instance_id": instance_id, "rank_drop": drop})

    invalid_promotions = []
    for row in v4_rows:
        status = row.get("diagnostic_status", "")
        promotion = int(float(row.get("promotion_cap", "0") or 0))
        controls = int(float(row.get("null_control_count", "0") or 0))
        delta = _as_float(row, "candidate_delta")
        irg = _as_float(row, "intervention_responsibility_gain")
        valid = (
            (status == "strong_counterfactual" and promotion == 10 and controls >= 2 and delta >= 0.05 and irg >= 3.0)
            or (status == "moderate_counterfactual" and promotion == 2 and controls >= 2 and delta >= 0.02 and irg >= 1.5)
            or (status not in {"strong_counterfactual", "moderate_counterfactual"} and promotion == 0)
        )
        if not valid:
            invalid_promotions.append({
                "instance_id": row.get("instance_id", ""),
                "status": status,
                "promotion": promotion,
                "controls": controls,
                "delta": delta,
                "irg": irg,
            })

    selected = sum(row.get("intervention_selected", "") == "1" for row in v4_rows)
    selected_empty = sum(
        row.get("intervention_selected", "") == "1"
        and int(float(row.get("candidate_count", "0") or 0)) == 0
        for row in v4_rows
    )
    source_not_selected = sum(row.get("intervention_selected", "") == "0" for row in v4_rows)
    completeness_pass = (
        len(by_instance) == expected_events
        and not duplicate_keys
        and not missing_pairs
        and not unexpected_methods
        and len(v4_rows) == expected_events
    )
    promotion_safety_pass = not invalid_promotions
    graph_regression_gate_pass = len(severe_v4_vs_graph) < len(severe_v3_vs_graph)
    v2_regression_gate_pass = len(severe_v4_vs_v2) <= len(severe_v3_vs_v2)
    return {
        "audit_scope": "retrospective_v4_development_not_confirmatory",
        "expected_events": expected_events,
        "evaluated_events": len(by_instance),
        "expected_methods": list(EXPECTED_METHODS),
        "row_count": len(rows),
        "expected_row_count": expected_events * len(EXPECTED_METHODS),
        "duplicate_instance_method_pairs": [list(key) for key in duplicate_keys],
        "missing_instance_method_pairs": missing_pairs,
        "unexpected_methods": unexpected_methods,
        "v4_status_counts": dict(sorted(statuses.items())),
        "v4_source_selected_for_intervention": selected,
        "v4_source_not_selected_for_intervention": source_not_selected,
        "v4_selected_source_with_empty_candidates": selected_empty,
        "v4_severe_rank_drops_gt20_vs_graph": severe_v4_vs_graph,
        "v3_severe_rank_drops_gt20_vs_graph": severe_v3_vs_graph,
        "v4_severe_rank_drops_gt20_vs_v2": severe_v4_vs_v2,
        "v3_severe_rank_drops_gt20_vs_v2": severe_v3_vs_v2,
        "invalid_evidence_promotions": invalid_promotions,
        "gates": {
            "complete_matrix": completeness_pass,
            "promotion_rules_respected": promotion_safety_pass,
            "fewer_severe_graph_regressions_than_v3": graph_regression_gate_pass,
            "no_more_severe_v2_regressions_than_v3": v2_regression_gate_pass,
        },
        "development_decision_ready": completeness_pass and promotion_safety_pass,
        "note": (
            "Passing these gates permits a documented development decision only. "
            "It does not establish generalization; an independent blind set is still required."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit the FormulaGuard-v4 retrospective development run")
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-events", type=int, default=30)
    args = parser.parse_args()
    with args.raw.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("V4 development raw results are empty")
    audit = build_audit(rows, expected_events=args.expected_events)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not audit["development_decision_ready"]:
        raise SystemExit("V4 development audit failed completeness or promotion-safety checks")


if __name__ == "__main__":
    main()
