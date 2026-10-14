"""Build a deterministic 36-event V5.2 safety red-team development manifest.

All cases are purpose-built development controls, balanced across six error
types, three depths, and two intended V4 rank strata.  They are never described
as independent data.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_v52_stress_workbooks import build_redteam_workbooks


def build_rows(benchmark: Path, output_directory: Path) -> list[dict[str, object]]:
    if not (benchmark / "validation" / "validated_instances.jsonl").is_file():
        raise ValueError("Registered PropagationBench-v3 full corpus is missing")
    rows = []
    stress_directory = output_directory / "stress_workbooks"
    for record in build_redteam_workbooks(stress_directory):
        index = len(rows) + 1
        intended = str(record["intended_v4_stratum"])
        rows.append({
            "instance_id": f"v52_red_{index:03d}",
            "workbook": "stress_workbooks/" + Path(record["path"]).name,
            "source_cell": record["source_cell"],
            "correct_formula": record["correct_formula"],
            "error_type": record["error_type"],
            "error_subtype": (
                "correct_exception_decoy_stress" if intended == "below5"
                else "ordinary_single_error_control"
            ),
            "expected_depth": record["depth_bin"],
            "actual_depth": record["actual_depth"],
            "depth_bin": record["depth_bin"],
            "template_family": (
                "v52_structural_exception_stress" if intended == "below5"
                else "v52_ordinary_control"
            ),
            "source_instance_id": record["instance_id"],
            "data_role": "purpose_built_development_redteam",
            "intended_v4_stratum": intended,
        })
    if len(rows) != 36:
        raise AssertionError(f"Expected 36 total red-team events, got {len(rows)}")
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the V5.2 36-event red-team manifest")
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing manifest: {args.output}")
    rows = build_rows(args.benchmark, args.output.parent)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(args.output)


if __name__ == "__main__":
    main()
