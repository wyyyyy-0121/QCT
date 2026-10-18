#!/usr/bin/env python3
"""Audit case-insensitive sheet identity without assuming row/column alignment."""
from pathlib import Path
from collections import Counter
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT.parent / "followup_20261014/development/natural_weights_dev33_v1"
source = RUN / "author_diff.local.json.gz"
target = RUN / "alignment_audit_summary.json"
if target.exists():
    raise SystemExit("Preserve existing alignment audit")
data = json.loads(gzip.decompress(source.read_bytes()))
mapped = {}
for name in ("before", "after"):
    sheets = data[name]["sheets"]
    assert len(sheets) == len({sheet.casefold() for sheet in sheets})
    mapped[name] = {field: {key.casefold(): value for key, value in data[name][field].items()}
                    for field in ("values", "formulas")}
b, a = mapped["before"], mapped["after"]
counts = Counter()
for key in b["values"].keys() | a["values"].keys():
    if b["values"].get(key) != a["values"].get(key):
        counts["formula_changed" if key in b["formulas"] and key in a["formulas"]
               else "formula_removed" if key in b["formulas"]
               else "formula_added" if key in a["formulas"] else "nonformula_changed"] += 1
payload = {"local_inventory_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
           "case_insensitive_sheet_identity_only": True,
           "coordinate_alignment_verified": False,
           "change_counts_after_case_normalization": dict(sorted(counts.items())),
           "decision": "not a certified natural correction pair; rows, input fields and formula columns changed",
           "certified_natural_errors": 0, "precision": None, "coverage": None,
           "final_validation_eligible": False}
target.write_text(json.dumps(payload, indent=2) + "\n")
print(json.dumps(payload, indent=2))
