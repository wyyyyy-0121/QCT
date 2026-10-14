"""Label-aware diagnosis of revealed R2 pressure failures.

This script is intentionally outside the localizer.  It recomputes only the
candidate-independent R2 source evidence for events whose frozen V4 result was
Top-5 but R2-R1 fell outside Top-5.  The output is development evidence; it is
never an independent evaluation and must not be imported by prediction code.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import parse_formula
from formulaguard.v5_core_r2 import v5_core_r2_scores
from formulaguard.workbook import WorkbookModel


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_sources(text: str) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for raw in str(text or "").split(";"):
        raw = raw.strip()
        if "!" not in raw:
            continue
        sheet, address = raw.rsplit("!", 1)
        result.add((sheet.strip("'"), address.replace("$", "").upper()))
    return result


def supported_model(model: WorkbookModel) -> tuple[WorkbookModel, set[tuple[str, str]]]:
    formulas: dict[tuple[str, str], str] = {}
    unsupported: set[tuple[str, str]] = set()
    for cell, formula in model.formulas.items():
        try:
            parse_formula(formula)
        except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            unsupported.add(cell)
        else:
            formulas[cell] = formula
    return WorkbookModel(model.cells, formulas, source=model.source), unsupported


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise SystemExit("Pressure-failure diagnostic produced no rows")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--event-ranks", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--formula-rank-fusion-weight", type=float)
    parser.add_argument("--all-events", action="store_true")
    args = parser.parse_args()

    events = read_csv(args.events)
    if events and "include" in events[0]:
        events = [row for row in events if row.get("include") == "1"]
    event_by_id = {row["instance_id"]: row for row in events}
    rank_rows = read_csv(args.event_ranks)
    ranks = {
        (row["instance_id"], row["method"]): int(row["rank"])
        for row in rank_rows
    }
    regression_ids = sorted(event_by_id) if args.all_events else sorted({
        instance_id for instance_id in event_by_id
        if ranks.get((instance_id, "v4"), 10**9) <= 5
        and ranks.get((instance_id, "r2_full"), 0) > 5
    })
    if not regression_ids:
        raise SystemExit("No V4-Top5 to R2-outside-Top5 regression events found")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.formula_rank_fusion_weight is not None:
        if not 0.0 <= args.formula_rank_fusion_weight <= 1.0:
            raise SystemExit("Formula rank fusion diagnostic weight must be in [0, 1]")
        config["formula_rank_fusion_weight"] = args.formula_rank_fusion_weight

    workbook_cache: dict[str, tuple[WorkbookModel, WorkbookModel, set[tuple[str, str]], list]] = {}
    workbook_contexts: dict[str, dict[str, object]] = {}
    rows: list[dict[str, object]] = []
    for instance_id in regression_ids:
        event = event_by_id[instance_id]
        relative = event.get("workbook", "")
        if not relative:
            raise SystemExit(f"Regression event has no workbook: {instance_id}")
        if relative not in workbook_cache:
            model = WorkbookModel.from_xlsx(args.root / relative)
            compatible, unsupported = supported_model(model)
            source_ranking = v5_core_r2_scores(compatible, stage="source", config=config)
            workbook_cache[relative] = (model, compatible, unsupported, source_ranking)
        model, compatible, unsupported, source_ranking = workbook_cache[relative]
        if relative not in workbook_contexts and source_ranking:
            leader = source_ranking[0].evidence
            formula_order = sorted(
                source_ranking,
                key=lambda item: (-float(item.evidence.get("formula_residual", 0.0)), item.cell),
            )
            first_formula = float(formula_order[0].evidence.get("formula_residual", 0.0))
            second_formula = (
                float(formula_order[1].evidence.get("formula_residual", 0.0))
                if len(formula_order) > 1 else 0.0
            )
            workbook_contexts[relative] = {
                "leader_raw_score": leader.get("observational_raw_score", 0.0),
                "leader_empirical_tail": leader.get("observational_empirical_tail", 1.0),
                "leader_formula_residual": leader.get("formula_residual", 0.0),
                "leader_regime_residual": leader.get("regime_conditioned_residual", 0.0),
                "leader_behavior_residual": leader.get("behavior_residual", 0.0),
                "leader_graph_residual": leader.get("graph_residual", 0.0),
                "leader_propagation_potential": leader.get("propagation_potential", 0.0),
                "top_formula_residual": first_formula,
                "formula_residual_margin": first_formula - second_formula,
                "top_formula_observational_rank": int(formula_order[0].evidence.get("observational_rank", 0)),
            }
        rank_lookup = {item.cell: index for index, item in enumerate(source_ranking, 1)}
        result_lookup = {item.cell: item for item in source_ranking}
        raw_order = sorted(
            source_ranking,
            key=lambda item: (-float(item.evidence["observational_raw_score"]), item.cell),
        )
        raw_rank = {item.cell: index for index, item in enumerate(raw_order, 1)}
        component_ranks: dict[str, dict[tuple[str, str], int]] = {}
        for field in (
            "formula_residual", "regime_conditioned_residual",
            "behavior_residual", "graph_residual", "propagation_potential",
        ):
            ordered = sorted(
                source_ranking,
                key=lambda item: (-float(item.evidence[field]), item.cell),
            )
            component_ranks[field] = {
                item.cell: index for index, item in enumerate(ordered, 1)
            }
        blend_ranks: dict[float, dict[tuple[str, str], int]] = {}
        for raw_weight in (0.25, 0.50, 0.75):
            ordered = sorted(
                source_ranking,
                key=lambda item: (
                    -(
                        raw_weight * float(item.evidence["observational_raw_score"])
                        + (1.0 - raw_weight)
                        * (1.0 - float(item.evidence["observational_empirical_tail"]))
                    ),
                    item.cell,
                ),
            )
            blend_ranks[raw_weight] = {
                item.cell: index for index, item in enumerate(ordered, 1)
            }
        sources = parse_sources(event.get("source_cells") or event.get("source_cell") or "")
        if not sources:
            raise SystemExit(f"Regression event has no valid source cells: {instance_id}")
        source_rows = []
        for source in sorted(sources):
            item = result_lookup.get(source)
            evidence = item.evidence if item else {}
            source_rows.append({
                "instance_id": instance_id,
                "workbook": relative,
                "source_cell": f"{source[0]}!{source[1]}",
                "source_count": len(sources),
                "formula_count": len(model.formulas),
                "supported_formula_count": len(compatible.formulas),
                "source_supported": int(source not in unsupported and item is not None),
                "v4_event_rank": ranks[(instance_id, "v4")],
                "r2_source_event_rank": ranks[(instance_id, "r2_source")],
                "r2_full_event_rank": ranks[(instance_id, "r2_full")],
                "source_rank": rank_lookup.get(source, len(model.formulas) + 1),
                "raw_only_rank": raw_rank.get(source, len(model.formulas) + 1),
                "formula_residual_rank": component_ranks["formula_residual"].get(source, len(model.formulas) + 1),
                "regime_residual_rank": component_ranks["regime_conditioned_residual"].get(source, len(model.formulas) + 1),
                "behavior_residual_rank": component_ranks["behavior_residual"].get(source, len(model.formulas) + 1),
                "graph_residual_rank": component_ranks["graph_residual"].get(source, len(model.formulas) + 1),
                "propagation_potential_rank": component_ranks["propagation_potential"].get(source, len(model.formulas) + 1),
                "blend_raw_025_rank": blend_ranks[0.25].get(source, len(model.formulas) + 1),
                "blend_raw_050_rank": blend_ranks[0.50].get(source, len(model.formulas) + 1),
                "blend_raw_075_rank": blend_ranks[0.75].get(source, len(model.formulas) + 1),
                "formula": model.formulas.get(source, ""),
                "regime_type": evidence.get("regime_type", "unsupported"),
                "raw_score": evidence.get("observational_raw_score", 0.0),
                "empirical_tail": evidence.get("observational_empirical_tail", 1.0),
                "formula_residual": evidence.get("formula_residual", 0.0),
                "regime_residual": evidence.get("regime_conditioned_residual", 0.0),
                "behavior_residual": evidence.get("behavior_residual", 0.0),
                "graph_residual": evidence.get("graph_residual", 0.0),
                "propagation_potential": evidence.get("propagation_potential", 0.0),
                "ancestor_penalty": evidence.get("ancestor_penalty", 0.0),
                "descendant_count": evidence.get("descendant_count", 0),
                "exception_release": int(bool(evidence.get("exception_release", False))),
                "error_type": event.get("error_type", ""),
                "error_subtype": event.get("error_subtype", ""),
                "description": event.get("error_description", ""),
            })
        rows.extend(source_rows)

    write_csv(args.output / "source_evidence.csv", rows)
    event_summary: list[dict[str, object]] = []
    for instance_id in regression_ids:
        current = [row for row in rows if row["instance_id"] == instance_id]
        supported = [row for row in current if row["source_supported"]]
        best = min(supported, key=lambda row: int(row["source_rank"])) if supported else current[0]
        context = workbook_contexts[best["workbook"]]
        event_summary.append({
            "instance_id": instance_id,
            "workbook": best["workbook"],
            "source_count": best["source_count"],
            "formula_count": best["formula_count"],
            "supported_source_count": sum(int(row["source_supported"]) for row in current),
            "v4_rank": best["v4_event_rank"],
            "r2_source_rank": best["r2_source_event_rank"],
            "r2_full_rank": best["r2_full_event_rank"],
            "diagnostic_config_source_rank": best["source_rank"],
            "raw_only_rank": min(int(row["raw_only_rank"]) for row in current),
            "formula_residual_rank": min(int(row["formula_residual_rank"]) for row in current),
            "regime_residual_rank": min(int(row["regime_residual_rank"]) for row in current),
            "behavior_residual_rank": min(int(row["behavior_residual_rank"]) for row in current),
            "graph_residual_rank": min(int(row["graph_residual_rank"]) for row in current),
            "propagation_potential_rank": min(int(row["propagation_potential_rank"]) for row in current),
            "blend_raw_025_rank": min(int(row["blend_raw_025_rank"]) for row in current),
            "blend_raw_050_rank": min(int(row["blend_raw_050_rank"]) for row in current),
            "blend_raw_075_rank": min(int(row["blend_raw_075_rank"]) for row in current),
            "best_source_cell": best["source_cell"],
            "best_regime_type": best["regime_type"],
            "best_raw_score": best["raw_score"],
            "best_empirical_tail": best["empirical_tail"],
            "best_formula_residual": best["formula_residual"],
            "best_regime_residual": best["regime_residual"],
            "best_behavior_residual": best["behavior_residual"],
            "best_graph_residual": best["graph_residual"],
            "best_propagation_potential": best["propagation_potential"],
            "best_ancestor_penalty": best["ancestor_penalty"],
            "best_descendant_count": best["descendant_count"],
            **context,
            "error_type": best["error_type"],
            "error_subtype": best["error_subtype"],
            "description": best["description"],
        })
    write_csv(args.output / "event_summary.csv", event_summary)
    payload = {
        "protocol": "v5_core_r2_pressure_failure_diagnosis_v1",
        "post_hoc_label_aware_development_only": True,
        "not_independent_evidence": True,
        "does_not_modify_model": True,
        "regression_events": len(regression_ids),
        "source_rows": len(rows),
        "workbooks_recomputed": len(workbook_cache),
        "event_ids": regression_ids,
        "diagnostic_config": config,
        "all_events": args.all_events,
    }
    (args.output / "diagnostic_receipt.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(args.output / "diagnostic_receipt.json")


if __name__ == "__main__":
    main()
