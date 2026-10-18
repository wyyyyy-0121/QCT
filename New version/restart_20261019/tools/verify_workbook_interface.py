#!/usr/bin/env python3
"""Compare new interface output to historical paper/dev11 evidence.

All non-floating fields match exactly; score roundoff is separately bounded.
No score or output is rewritten to manufacture byte identity.
"""
from pathlib import Path
import gzip
import hashlib
import json
import math

ROOT = Path(__file__).resolve().parents[1]
LEGACY = ROOT.parent / "followup_20261014"
TARGET = ROOT / "WORKBOOK_INTERFACE_PARITY.json"
float_differences = []


def compare(current, prior, location):
    if type(current) is float and type(prior) is float:
        assert math.isclose(current, prior, rel_tol=1e-12, abs_tol=1e-12), location
        if current != prior:
            float_differences.append(dict(field=location, current=current, historical=prior,
                                          absolute_difference=abs(current - prior)))
    elif isinstance(current, dict):
        assert current.keys() == prior.keys(), location
        for key in current:
            compare(current[key], prior[key], location + "/" + key)
    elif isinstance(current, list):
        assert len(current) == len(prior), location
        for index, (a, b) in enumerate(zip(current, prior)):
            compare(a, b, location + "/" + str(index))
    else:
        assert type(current) == type(prior) and current == prior, location


if TARGET.exists():
    raise SystemExit("Preserve existing parity audit")
rows = []
for task in sorted((ROOT / "workbook_benchmark_v3/workers_1/tasks").iterdir()):
    current = json.loads((task / "prediction.json").read_text())
    paper_path = LEGACY / "development/crossdomain_dev1/predictions" / (task.name + ".json.gz")
    dev11_path = LEGACY / "development/selector_dev11_complete_ast_v1/predictions/crossdomain" / (task.name + ".json.gz")
    paper = json.loads(gzip.decompress(paper_path.read_bytes()))["paper"]
    dev11 = json.loads(gzip.decompress(dev11_path.read_bytes()))
    compare(current["paper"], paper, task.name + "/paper")
    compare(current["dev11"], dev11, task.name + "/dev11")
    rows.append(dict(case=task.name, nonfloating_fields_exact=True,
                     paper_byte_semantic_identity=current["paper"] == paper,
                     dev11_byte_semantic_identity=current["dev11"] == dev11,
                     paper_sha256=hashlib.sha256(paper_path.read_bytes()).hexdigest(),
                     dev11_sha256=hashlib.sha256(dev11_path.read_bytes()).hexdigest()))
summary = dict(cases=rows, all_nonfloating_fields_exact=True,
               all_float_scores_within_1e_12=True, float_difference_count=len(float_differences),
               maximum_absolute_score_difference=max((d["absolute_difference"] for d in float_differences), default=0),
               floating_differences=float_differences,
               final_validation_eligible=False)
TARGET.write_text(json.dumps(summary, indent=2) + "\n")
print("Verified", len(rows), "paper/dev11 cases; float roundoff fields:", len(float_differences))
