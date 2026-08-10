from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Export cases where FormulaGuard loses to the strongest no-oracle baseline")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    with (args.results / "raw_results.csv").open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    comparison = json.loads((args.results / "paired_comparison.json").read_text(encoding="utf-8"))
    baseline = comparison["strongest_no_oracle_baseline"]
    indexed = {(row["instance_id"], row["method"]): row for row in rows}
    output_rows = []
    for instance_id in sorted({row["instance_id"] for row in rows}):
        fg = indexed.get((instance_id, "formulaguard"))
        base = indexed.get((instance_id, baseline))
        if not fg or not base:
            continue
        difference = int(fg["rank"]) - int(base["rank"])
        if difference > 0:
            output_rows.append({
                "instance_id": instance_id,
                "template_family": fg["template_family"],
                "data_split": fg.get("data_split", ""),
                "mutation_type": fg["mutation_type"],
                "depth_bin": fg["depth_bin"],
                "formula_count": fg["formula_count"],
                "formulaguard_rank": fg["rank"],
                "baseline": baseline,
                "baseline_rank": base["rank"],
                "rank_gap": difference,
                "candidate_formula": fg["candidate_formula"],
            })
    output_rows.sort(key=lambda row: (-row["rank_gap"], row["instance_id"]))
    output = args.output or args.results / "failure_cases.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "instance_id", "template_family", "data_split", "mutation_type", "depth_bin", "formula_count",
        "formulaguard_rank", "baseline", "baseline_rank", "rank_gap", "candidate_formula",
    ]
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(output_rows)
    print(output)


if __name__ == "__main__":
    main()
