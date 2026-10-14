"""Score clean-workbook semantic-promotion false alarms from complete rankings."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    completion = json.loads((args.predictions / "prediction_complete.json").read_text(encoding="utf-8"))
    if not completion.get("complete"):
        raise SystemExit("Clean scoring refused: predictions incomplete")
    counts = {}
    total = 0
    for path in sorted((args.predictions / "shards").glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        total += 1
        for method, ranking in record["rankings"].items():
            if method.startswith("v6_"):
                counts[method] = counts.get(method, 0) + int(any(row["evidence"].get("promotion_target") for row in ranking))
    payload = {
        "clean_workbooks": total,
        "variants": {method: {"alarms": count, "false_alarm_rate": count / max(1, total)} for method, count in counts.items()},
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "v6_clean_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "v6_clean_summary.json")


if __name__ == "__main__":
    main()
