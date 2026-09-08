from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_PREFIXES = ("formulaguard/",)
REQUIRED_FILES = {
    "scripts/run_experiments.py",
    "scripts/run_clean_evaluation.py",
}


def relevant_hashes(path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        row["path"]: row["sha256"]
        for row in payload.get("source_files", [])
        if row["path"].startswith(REQUIRED_PREFIXES) or row["path"] in REQUIRED_FILES
    }


def main():
    parser = argparse.ArgumentParser(description="Reject stale clean-alarm calibration results")
    parser.add_argument("--calibration", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    args = parser.parse_args()
    if not args.calibration.is_file():
        raise SystemExit(f"Calibration environment record not found: {args.calibration}")
    calibration = relevant_hashes(args.calibration)
    current = relevant_hashes(args.current)
    changed = sorted(path for path in set(calibration) | set(current) if calibration.get(path) != current.get(path))
    if changed:
        raise SystemExit(
            "Quick calibration was produced by different core code. Rerun quick before full. Changed: "
            + ", ".join(changed)
        )
    print("Calibration code hashes match current core code.")


if __name__ == "__main__":
    main()
