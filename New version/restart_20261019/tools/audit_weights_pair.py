#!/usr/bin/env python3
"""Post-lock dual-parser inventory; version differences are not truth labels."""
from pathlib import Path
import collections
import datetime
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT.parent / "followup_20261014"
sys.path[:0] = [str(LEGACY / "qa"), str(LEGACY / "scripts"),
               str(LEGACY / "baseline/source/HybridGuard_V5_handoff_20260904/src")]
import diff_hobyah_natural_dev26 as inventory
import run_weights_natural_dev33 as runner
from run_selector_dev5 import read, save, sha
RUN = runner.RUN


def main():
    runner.engine.verify()
    lock = read(RUN / "prediction_lock.json")
    replay = read(RUN / "replay.json")
    assert lock["status"] == "complete" and replay["all_predictions_identical"]
    assert replay["prediction_lock_sha256"] == sha(RUN / "prediction_lock.json")
    correction = read(RUN / "correction_acquisition.json")
    assert correction["original_prediction_lock_sha256"] == sha(RUN / "prediction_lock.json")
    for row in correction["records"]:
        assert row["ok"] and sha(LEGACY / row["path"]) == row["sha256"]
    before = inventory.snapshot(RUN / "raw/before.xlsx")
    after = inventory.snapshot(RUN / "raw/after.xlsx")
    diff = []
    for key in sorted(before["values"].keys() | after["values"].keys()):
        old, new = before["values"].get(key), after["values"].get(key)
        if old != new:
            kind = ("formula_changed" if key in before["formulas"] and key in after["formulas"]
                    else "formula_removed" if key in before["formulas"]
                    else "formula_added" if key in after["formulas"] else "nonformula_changed")
            diff.append({"cell": key, "before": old, "after": new, "kind": kind})
    local = RUN / "author_diff.local.json.gz"
    if local.exists():
        raise SystemExit("Preserve existing pair audit")
    def typed_scalar(value):
        if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
            return {"scalar_type": type(value).__name__, "iso_value": value.isoformat()}
        raise TypeError("Unsupported inventory scalar: " + type(value).__name__)
    payload = {"before": before, "after": after, "changes": diff,
               "all_changed_formulas_assumed_errors": False}
    save(local, json.loads(json.dumps(payload, default=typed_scalar)))
    prediction = read(RUN / "prediction.json.gz")
    summary = {
        "original_prediction_lock_sha256": sha(RUN / "prediction_lock.json"),
        "correction_acquisition_sha256": sha(RUN / "correction_acquisition.json"),
        "local_diff_sha256": sha(local), "auditor_sha256": sha(Path(__file__)),
        "dual_parser_formula_inventories_agree": True,
        "before_formula_cells": len(before["formulas"]),
        "after_formula_cells": len(after["formulas"]),
        "before_sheets": before["sheets"], "after_sheets": after["sheets"],
        "change_counts": dict(collections.Counter(row["kind"] for row in diff)),
        "before_comment_count": len(before["comments"]),
        "after_comment_count": len(after["comments"]),
        "proposals": {name: sum(row.get("status") == "propose" for row in prediction[name]["rows"])
                      for name in ("paper", "dev11")},
        "certified_natural_error_count": 0,
        "truth_status": "uncertified; author version differences alone do not establish correct formulas",
        "precision": None, "coverage": None, "final_validation_eligible": False,
    }
    save(RUN / "pair_audit_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
