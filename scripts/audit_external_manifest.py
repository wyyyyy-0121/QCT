"""Inventory real-corpus support before running expensive localization."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.benchmark import parse_cell_label
from formulaguard.formula import FormulaSyntaxError, parse_formula
from formulaguard.workbook import WorkbookModel


def manifest_sources(row: dict[str, str]) -> set[tuple[str, str]]:
    labels = [
        label.strip() for label in row.get("source_cells", "").split(";")
        if label.strip()
    ] or [row.get("source_cell", "").strip()]
    return {parse_cell_label(label) for label in labels if label}


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit parser and label support for an external manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--intervention-cap", type=int, default=100)
    args = parser.parse_args()

    with args.manifest.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit("External manifest is empty")

    models: dict[Path, WorkbookModel] = {}
    formula_support: dict[Path, tuple[int, int]] = {}
    records: list[dict[str, object]] = []
    for row in rows:
        manifest_include = row.get("include", "1").strip().lower() not in {
            "0", "false", "no", "exclude"
        }
        record: dict[str, object] = {
            "instance_id": row["instance_id"],
            "error_event": row.get("error_event", ""),
            "manifest_include": int(manifest_include),
            "manifest_exclusion_reason": row.get("exclusion_reason", ""),
            "workbook": row.get("workbook", ""),
            "error_type": row.get("error_type", ""),
            "error_subtype": row.get("error_subtype", ""),
            "cell_type": row.get("cell_type", ""),
            "formula_count": 0,
            "supported_formula_count": 0,
            "parser_coverage": 0.0,
            "support_stratum": "not_evaluated",
            "labeled_cell_count": int(row.get("labeled_cell_count", "0") or 0),
            "labeled_formula_count": 0,
            "supported_source_formula_count": 0,
            "source_parser_coverage": 0.0,
            "intervention_scope_fraction": 0.0,
            "evaluation_ready": 0,
            "evaluation_exclusion_reason": row.get("exclusion_reason", ""),
        }
        if not manifest_include:
            records.append(record)
            continue
        workbook_path = (args.manifest.parent / row["workbook"]).resolve()
        if not workbook_path.is_file():
            record["evaluation_exclusion_reason"] = "workbook_not_found"
            records.append(record)
            continue
        try:
            if workbook_path not in models:
                model = WorkbookModel.from_xlsx(workbook_path)
                models[workbook_path] = model
                supported = 0
                for formula in model.formulas.values():
                    try:
                        parse_formula(formula)
                        supported += 1
                    except FormulaSyntaxError:
                        pass
                formula_support[workbook_path] = (len(model.formulas), supported)
            model = models[workbook_path]
            formula_count, supported_formula_count = formula_support[workbook_path]
            sources = manifest_sources(row)
        except Exception as exc:
            record["evaluation_exclusion_reason"] = f"load_or_label_error:{type(exc).__name__}:{exc}"
            records.append(record)
            continue
        formula_sources = sources & set(model.formulas)
        supported_sources = set()
        for source in formula_sources:
            try:
                parse_formula(model.formulas[source])
                supported_sources.add(source)
            except FormulaSyntaxError:
                pass
        parser_coverage = supported_formula_count / max(1, formula_count)
        source_parser_coverage = len(supported_sources) / max(1, len(formula_sources))
        if parser_coverage >= 0.90:
            stratum = "high"
        elif parser_coverage >= 0.50:
            stratum = "medium"
        else:
            stratum = "low"
        ready = bool(supported_sources)
        if not formula_sources:
            reason = "no_labeled_source_cell_is_a_formula"
        elif not supported_sources:
            reason = "all_labeled_source_formulas_unsupported"
        else:
            reason = ""
        record.update({
            "formula_count": formula_count,
            "supported_formula_count": supported_formula_count,
            "parser_coverage": parser_coverage,
            "support_stratum": stratum,
            "labeled_formula_count": len(formula_sources),
            "supported_source_formula_count": len(supported_sources),
            "source_parser_coverage": source_parser_coverage,
            "intervention_scope_fraction": min(1.0, args.intervention_cap / max(1, formula_count)),
            "evaluation_ready": int(ready),
            "evaluation_exclusion_reason": reason,
        })
        records.append(record)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)

    included = [record for record in records if record["manifest_include"]]
    ready = [record for record in records if record["evaluation_ready"]]
    audit = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_events": len(records),
        "manifest_included_events": len(included),
        "evaluation_ready_events": len(ready),
        "evaluation_excluded_after_support_audit": len(included) - len(ready),
        "unique_ready_workbooks": len({record["workbook"] for record in ready}),
        "ready_events_by_parser_stratum": {
            stratum: sum(record["support_stratum"] == stratum for record in ready)
            for stratum in ("high", "medium", "low")
        },
        "ready_events_over_intervention_cap": sum(
            int(record["formula_count"]) > args.intervention_cap for record in ready
        ),
        "formula_count_range_ready": [
            min((int(record["formula_count"]) for record in ready), default=0),
            max((int(record["formula_count"]) for record in ready), default=0),
        ],
        "quantitative_reporting_threshold_met": len(ready) >= 15,
        "reporting_warning": (
            "Parser coverage and event set size must accompany aggregate localization metrics. "
            "Multi-cell events are one event, not one sample per labeled cell."
        ),
    }
    audit_path = args.output.with_suffix(".audit.json")
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(audit_path)


if __name__ == "__main__":
    main()
