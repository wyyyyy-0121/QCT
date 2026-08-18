"""Select V5.2 only after all three predeclared development rounds exist."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_external_evaluation import sha256_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Select V5.2-A/B/C after all rounds")
    parser.add_argument("--audit-a", type=Path, required=True)
    parser.add_argument("--audit-b", type=Path, required=True)
    parser.add_argument("--audit-c", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audits = []
    for expected, path in zip(("a", "b", "c"), (args.audit_a, args.audit_b, args.audit_c)):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("variant") != expected:
            raise SystemExit(f"Audit variant mismatch: expected {expected}: {path}")
        audits.append((path, record))
    candidates = []
    for path, record in audits:
        metrics = record["selection_metrics"]
        if (
            record.get("hard_gates_passed")
            and int(metrics["combined_incremental_rescue_hits"]) >= 2
        ):
            candidates.append((
                -int(metrics["combined_incremental_rescue_hits"]),
                float(metrics["clean_rescue_activation_rate"]),
                float(metrics["combined_runtime_median_sum"]),
                str(record["variant"]),
                path,
                record,
            ))
    candidates.sort()
    selected = candidates[0] if candidates else None
    receipt = {
        "protocol": "v5.2_select_after_three_predeclared_rounds",
        "selection_order": [
            "maximum_combined_incremental_rescue_hits",
            "minimum_clean_rescue_activation_rate",
            "minimum_combined_runtime_median_sum",
        ],
        "minimum_incremental_rescue_hits": 2,
        "rounds": {
            record["variant"]: {
                "audit": str(path.resolve()),
                "audit_sha256": sha256_file(path),
                "hard_gates_passed": record.get("hard_gates_passed"),
                "selection_metrics": record.get("selection_metrics"),
            }
            for path, record in audits
        },
        "selected_variant": selected[3] if selected else None,
        "decision": "v52_selected_for_freeze" if selected else "retain_v4_v52_exploratory_only",
        "selection_is_confirmation": False,
        "independent_validation_still_required": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if selected is None:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
