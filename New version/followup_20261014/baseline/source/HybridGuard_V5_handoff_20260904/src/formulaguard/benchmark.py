"""Benchmark validation and truth isolation helpers."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path

from .formula import normalized_formula
from .workbook import CellKey, WorkbookModel


def parse_cell_label(text: str) -> CellKey:
    sheet, address = text.rsplit("!", 1)
    return sheet.strip("'"), address.replace("$", "").upper()


def load_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def values_differ(left, right, tolerance=1e-9):
    try:
        return not math.isclose(float(left), float(right), rel_tol=tolerance, abs_tol=tolerance)
    except (TypeError, ValueError):
        return left != right


@dataclass
class ValidationRecord:
    instance_id: str
    valid: bool
    reasons: list[str]
    actual_depth: int | None
    depth_bin: str
    changed_formula_cells: int
    failed_sinks: list[str]
    formula_count: int


def validate_instance(root: Path, row: dict) -> tuple[ValidationRecord, WorkbookModel, WorkbookModel]:
    clean_path = root / row["clean_workbook"]
    mutant_path = root / row["mutant_workbook"]
    clean = WorkbookModel.from_xlsx(clean_path)
    mutant = WorkbookModel.from_xlsx(mutant_path)
    source = parse_cell_label(row["source_cell"])
    target_sink = parse_cell_label(row["sink_cell"])
    reasons: list[str] = []

    if normalized_formula(clean.formulas.get(source, "")) != normalized_formula(row["correct_formula"]):
        reasons.append("clean_formula_mismatch")
    if normalized_formula(mutant.formulas.get(source, "")) != normalized_formula(row["mutated_formula"]):
        reasons.append("mutant_formula_mismatch")
    clean_values, clean_errors = clean.evaluate()
    mutant_values, mutant_errors = mutant.evaluate()
    if clean_errors:
        reasons.append("clean_evaluation_error")
    if mutant_errors:
        reasons.append("explicit_or_evaluation_error")

    graph = mutant.dependency_graph()
    depth = graph.shortest_path_length(source, target_sink)
    if depth is None or depth < 1:
        reasons.append("source_does_not_reach_target_sink")
    changed = clean.changed_formula_cells(mutant)
    if len(changed) < 2:
        reasons.append("fewer_than_two_changed_formula_cells")
    all_sinks = set(clean.dependency_graph().sinks(clean.formula_cells)) | set(graph.sinks(mutant.formula_cells))
    failed_sinks = sorted(
        sink for sink in all_sinks
        if sink not in clean_errors and sink not in mutant_errors
        and values_differ(clean_values.get(sink), mutant_values.get(sink))
    )
    if target_sink not in failed_sinks:
        reasons.append("target_sink_unchanged")
    depth_bin = "invalid" if depth is None else ("shallow" if depth <= 2 else "medium" if depth <= 5 else "deep")
    record = ValidationRecord(
        instance_id=row["instance_id"],
        valid=not reasons,
        reasons=reasons,
        actual_depth=depth,
        depth_bin=depth_bin,
        changed_formula_cells=len(changed),
        failed_sinks=[f"{s}!{a}" for s, a in failed_sinks],
        formula_count=len(mutant.formulas),
    )
    return record, clean, mutant


def validate_dataset(root: Path, output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = list(load_jsonl(root / "instances.jsonl"))
    labels_path = root / "evaluation_labels.jsonl"
    if labels_path.is_file():
        labels = {row["instance_id"]: row for row in load_jsonl(labels_path)}
        missing = [row["instance_id"] for row in rows if row["instance_id"] not in labels]
        if missing:
            raise ValueError(f"Missing evaluation labels for {len(missing)} instances")
        rows = [{**row, **labels[row["instance_id"]]} for row in rows]
    valid_rows: list[dict] = []
    excluded_rows: list[dict] = []
    records: list[ValidationRecord] = []
    for row in rows:
        try:
            record, _, _ = validate_instance(root, row)
        except Exception as exc:
            record = ValidationRecord(
                instance_id=row.get("instance_id", "unknown"),
                valid=False,
                reasons=[f"validator_exception:{type(exc).__name__}:{exc}"],
                actual_depth=None,
                depth_bin="invalid",
                changed_formula_cells=0,
                failed_sinks=[],
                formula_count=0,
            )
        records.append(record)
        enriched = {**row, **asdict(record)}
        if record.valid:
            valid_rows.append(enriched)
        else:
            excluded_rows.append(enriched)

    with (output_dir / "validated_instances.jsonl").open("w", encoding="utf-8") as handle:
        for row in valid_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (output_dir / "validation_records.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
    with (output_dir / "exclusions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["instance_id", "template_family", "mutation_type", "reasons"])
        writer.writeheader()
        for row in excluded_rows:
            writer.writerow({
                "instance_id": row["instance_id"],
                "template_family": row.get("template_family", ""),
                "mutation_type": row.get("mutation_type", ""),
                "reasons": ";".join(row["reasons"]),
            })
    summary = {
        "total": len(rows),
        "valid": len(valid_rows),
        "excluded": len(excluded_rows),
        "valid_rate": len(valid_rows) / max(1, len(rows)),
        "by_depth": {},
        "by_mutation_type": {},
        "by_split": {},
    }
    for row in valid_rows:
        summary["by_depth"][row["depth_bin"]] = summary["by_depth"].get(row["depth_bin"], 0) + 1
        mtype = row["mutation_type"]
        summary["by_mutation_type"][mtype] = summary["by_mutation_type"].get(mtype, 0) + 1
        split = row.get("data_split", "unspecified")
        summary["by_split"][split] = summary["by_split"].get(split, 0) + 1
    (output_dir / "dataset_quality.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
