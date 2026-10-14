"""Audit revealed v4 blind workbooks without changing locked predictions."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from formulaguard.workbook import WorkbookModel


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def workbook_values(path: Path) -> tuple[dict[str, object], int]:
    model = WorkbookModel.from_xlsx(path)
    # Formula text takes precedence over cached values so recalculation caches do
    # not look like additional workbook edits.
    combined: dict[tuple[str, str], object] = dict(model.cells)
    combined.update(model.formulas)
    values = {f"{sheet}!{address}": value for (sheet, address), value in combined.items()}
    return values, len(model.formulas)


def build_audit(
    manifest_rows: list[dict[str, str]],
    label_rows: list[dict[str, str]],
    ledger_rows: list[dict[str, str]],
    manifest_parent: Path,
    originals: Path,
) -> dict[str, object]:
    manifest = {row["instance_id"]: row for row in manifest_rows}
    labels = {row["instance_id"]: row["source_cell"] for row in label_rows}
    ledger = {row["instance_id"]: row for row in ledger_rows}
    id_sets_match = set(manifest) == set(labels) == set(ledger)
    events: list[dict[str, object]] = []
    for instance_id in sorted(set(manifest) | set(labels) | set(ledger)):
        if instance_id not in manifest or instance_id not in labels or instance_id not in ledger:
            events.append({"instance_id": instance_id, "complete_metadata": False})
            continue
        row = ledger[instance_id]
        mutant_path = (manifest_parent / manifest[instance_id]["workbook"]).resolve()
        original_path = (originals / f"{instance_id}_original.xlsx").resolve()
        mutant_values, mutant_formula_count = workbook_values(mutant_path)
        original_values, original_formula_count = workbook_values(original_path)
        all_cells = set(mutant_values) | set(original_values)
        differences = sorted(
            cell for cell in all_cells if mutant_values.get(cell) != original_values.get(cell)
        )
        source = labels[instance_id]
        event = {
            "instance_id": instance_id,
            "complete_metadata": True,
            "source_cell": source,
            "label_matches_ledger": source == row["source_cell"],
            "mutant_exists": mutant_path.is_file(),
            "original_exists": original_path.is_file(),
            "changed_cells": differences,
            "changed_cell_count": len(differences),
            "only_registered_source_changed": differences == [source],
            "original_formula_matches_ledger": (
                original_values.get(source) == row["original_formula"]
            ),
            "mutated_formula_matches_ledger": (
                mutant_values.get(source) == row["mutated_formula"]
            ),
            "original_formula_count": original_formula_count,
            "mutant_formula_count": mutant_formula_count,
            "formula_count_matches_ledger": (
                mutant_formula_count == int(row["formula_count"])
                and original_formula_count == int(row["formula_count"])
            ),
            "error_type": row["error_type"],
            "expected_depth": row["expected_depth"],
            "permission": row["permission"],
            "injector": row["injector"],
        }
        event["passed"] = all([
            event["label_matches_ledger"],
            event["mutant_exists"],
            event["original_exists"],
            event["only_registered_source_changed"],
            event["original_formula_matches_ledger"],
            event["mutated_formula_matches_ledger"],
            event["formula_count_matches_ledger"],
        ])
        events.append(event)
    return {
        "audit_scope": "independent_synthetic_blind_set_after_prediction_lock",
        "events": len(events),
        "id_sets_match": id_sets_match,
        "passed_events": sum(bool(event.get("passed")) for event in events),
        "failed_events": sum(not bool(event.get("passed")) for event in events),
        "error_type_counts": dict(sorted(Counter(
            str(event.get("error_type")) for event in events if event.get("complete_metadata")
        ).items())),
        "expected_depth_counts": dict(sorted(Counter(
            str(event.get("expected_depth")) for event in events if event.get("complete_metadata")
        ).items())),
        "all_permissions_recorded": all(bool(event.get("permission")) for event in events),
        "all_injectors_recorded": all(bool(event.get("injector")) for event in events),
        "dataset_decision_ready": id_sets_match and all(bool(event.get("passed")) for event in events),
        "events_detail": events,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit revealed v4 blind workbook pairs")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--originals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = build_audit(
        read_csv(args.manifest), read_csv(args.labels), read_csv(args.ledger),
        args.manifest.resolve().parent, args.originals.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not audit["dataset_decision_ready"]:
        raise SystemExit("Blind dataset audit failed")


if __name__ == "__main__":
    main()
