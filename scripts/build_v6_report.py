"""Build reproducible Markdown, SVG, and formula-safe XLSX V6 artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR)); sys.path.insert(0, str(ROOT))
from build_v6_dataset import write_xlsx

from formulaguard.workbook import WorkbookModel


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--title", default="FormulaGuard V6 Results")
    args = parser.parse_args()
    payload = json.loads((args.results / "summary.json").read_text(encoding="utf-8"))
    with (args.results / "by_error.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        by_error = list(csv.DictReader(handle))
    with (args.results / "by_stratum.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        by_stratum = list(csv.DictReader(handle))
    with (args.results / "failure_cases.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        failures = list(csv.DictReader(handle))
    methods = sorted(payload["summaries"])
    markdown = [f"# {args.title}", "", f"Events: {payload['events']}", "", "| Method | Top-1 | Top-5 | Macro Top-5 | MRR | Repair |", "|---|---:|---:|---:|---:|---:|"]
    for method in methods:
        row = payload["summaries"][method]
        markdown.append(f"| {method} | {row['top1']:.4f} | {row['top5']:.4f} | {row['macro_top5']:.4f} | {row['mrr']:.4f} | {row['repair_exact']:.4f} |")
    markdown.extend([
        "", f"Main-variant Top-5 failures recorded: {len(failures)}.", "",
        ("All figures and tables are regenerated from summary.json, by_error.csv, "
        "by_stratum.csv, and failure_cases.csv. Formula text is exported as inline "
        "text, never as executable workbook formulas."),
    ])
    (args.results / "REPORT.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")

    cells = {"A1": args.title, "A2": "Method", "B2": "Top-1", "C2": "Top-5", "D2": "Macro Top-5", "E2": "MRR", "F2": "Repair exact"}
    for index, method in enumerate(methods, 3):
        row = payload["summaries"][method]
        cells.update({f"A{index}": method, f"B{index}": row["top1"], f"C{index}": row["top5"], f"D{index}": row["macro_top5"], f"E{index}": row["mrr"], f"F{index}": row["repair_exact"]})
    start = len(methods) + 5
    for col, name in zip("ABCDEF", ("Method", "Error type", "Events", "Top-5", "MRR", "Candidate formula example")):
        cells[f"{col}{start}"] = name
    for offset, row in enumerate(by_error, start + 1):
        cells.update({f"A{offset}": row["method"], f"B{offset}": row["error_type"], f"C{offset}": int(row["events"]), f"D{offset}": float(row["top5"]), f"E{offset}": float(row["mrr"]), f"F{offset}": "=SUM(A1:A2) (text safety check)"})
    stratum_cells = {"A1": "Method", "B1": "Stratum", "C1": "Value", "D1": "Events", "E1": "Top-1", "F1": "Top-5", "G1": "MRR", "H1": "Repair exact"}
    for index, row in enumerate(by_stratum, 2):
        for col, key in zip("ABCDEFGH", ("method", "stratum", "value", "events", "top1", "top5", "mrr", "repair_exact")):
            value = row[key]
            stratum_cells[f"{col}{index}"] = int(value) if key == "events" else float(value) if key in {"top1", "top5", "mrr", "repair_exact"} and value else value
    failure_fields = (
        "instance_id", "method", "error_type", "topology", "expected_depth", "source_cell",
        "rank", "candidate_formula", "candidate_sources", "candidate_edit_kinds",
        "semantic_tier", "counterfactual_delta", "counterfactual_irg", "global_harm",
    )
    failure_cells = {f"{chr(65 + index)}1": field for index, field in enumerate(failure_fields)}
    for row_index, row in enumerate(failures, 2):
        for col_index, field in enumerate(failure_fields):
            failure_cells[f"{chr(65 + col_index)}{row_index}"] = row.get(field, "")
    workbook = args.results / "FormulaGuard_V6_results.xlsx"
    write_xlsx(workbook, [("Summary", cells, {}), ("ByStratum", stratum_cells, {}), ("Failures", failure_cells, {})])
    if WorkbookModel.from_xlsx(workbook).formulas:
        raise SystemExit("V6 workbook safety audit failed: formula text was executed")

    chart_methods = [method for method in ("v4", "v6_a", "v6_b", "v6_c") if method in methods]
    bars = []
    for index, method in enumerate(chart_methods):
        value = payload["summaries"][method]["macro_top5"]
        y = 35 + index * 34
        bars.append(f'<text x="10" y="{y+16}" font-size="12">{method}</text><rect x="150" y="{y}" width="{500*value:.1f}" height="22" fill="#2E74B5"/><text x="{160+500*value:.1f}" y="{y+16}" font-size="12">{value:.3f}</text>')
    height = 70 + 34 * len(chart_methods)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="760" height="{height}"><rect width="100%" height="100%" fill="white"/><text x="10" y="22" font-size="18" font-weight="bold">Macro Top-5</text>{"".join(bars)}</svg>'
    (args.results / "v6_macro_top5.svg").write_text(svg, encoding="utf-8")
    errors = sorted({row["error_type"] for row in by_error})
    error_lookup = {(row["method"], row["error_type"]): float(row["top5"]) for row in by_error}
    colors = {"v4": "#777777", "v6_a": "#4E79A7", "v6_b": "#59A14F", "v6_c": "#E15759"}
    elements = ['<text x="10" y="22" font-size="18" font-weight="bold">Top-5 by error type</text>']
    for error_index, error in enumerate(errors):
        y = 40 + error_index * 92
        elements.append(f'<text x="10" y="{y+14}" font-size="11">{error}</text>')
        for method_index, method in enumerate(chart_methods):
            value = error_lookup.get((method, error), 0.0)
            bar_y = y + 20 + method_index * 16
            elements.append(f'<text x="20" y="{bar_y+11}" font-size="9">{method}</text><rect x="85" y="{bar_y}" width="{420*value:.1f}" height="12" fill="{colors[method]}"/><text x="{90+420*value:.1f}" y="{bar_y+11}" font-size="9">{value:.2f}</text>')
    error_svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="620" height="{55+92*len(errors)}"><rect width="100%" height="100%" fill="white"/>{"".join(elements)}</svg>'
    (args.results / "v6_error_top5.svg").write_text(error_svg, encoding="utf-8")
    print(args.results / "REPORT.md"); print(workbook)


if __name__ == "__main__":
    main()
