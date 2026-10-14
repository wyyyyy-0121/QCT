"""Create held-out model fixtures and a label-free copy of the Enron inventory.

Fixture JSON is a direct serialization of WorkbookModel inputs. This isolates
formula reasoning from XLSX authoring; the separate real cohort exercises XLSX.
Run only after source freeze. Never import model scoring code here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.run_v512_evaluation import write_json
from scripts.score_v512_confirmation import sha256

KINDS = ("singleton", "block", "systematic", "no_anchors", "clean", "legal_discount",
         "legal_constant", "alternating", "one_side", "unsupported", "legal_regime", "short")
FAMILIES = ("weighted", "tax", "ratio", "cross_sheet", "range_sum", "horizontal")


def identifier(seed: str, value: str) -> str:
    return "k" + hashlib.sha256(f"{seed}:{value}".encode()).hexdigest()[:24]


def formula(family: str, index: int):
    if family == "weighted":
        return f"=(B{index}*C{index}+D{index}*E{index})/(C{index}+E{index})"
    if family == "tax":
        return f"=B{index}*C{index}*(1+D{index})"
    if family == "ratio":
        return f"=B{index}/C{index}"
    if family == "cross_sheet":
        return f"=B{index}*'Rates'!$B$1"
    if family == "range_sum":
        return f"=SUM(B{index}:E{index})"
    # Horizontal cases use existing Excel coordinates; no model helpers.
    column = chr(65 + index)
    return f"={column}2*$A$1"


def mutate(value: str) -> str:
    if value.startswith("=SUM"):
        return value.replace(":E", ":D")
    if "*" in value:
        return value.replace("*", "/", 1)
    return value.replace("/", "*", 1)


def build_case(family: str, kind: str, rng: random.Random):
    cells = []
    formulas = []
    start = rng.randrange(5, 14) if family != "horizontal" else 1
    count = 20 if family != "horizontal" else 22
    if kind == "short":
        count = 2
    indices = list(range(start, start + count))
    if family == "cross_sheet":
        cells.append(["Rates", "B1", .13])
    if family == "horizontal":
        cells.append(["Data", "A1", 1.2])
    for index in indices:
        if family == "horizontal":
            col = chr(65 + index)
            address = f"{col}4"
            cells.append(["Data", f"{col}2", rng.randrange(1, 100)])
        else:
            address = f"H{index}"
            for column in "BCDE":
                cells.append(["Data", f"{column}{index}", rng.randrange(1, 100)])
        formulas.append(["Data", address, formula(family, index)])
    position = rng.randrange(4, count - 4) if count > 8 else 0
    changed = []
    decision = "no_action"
    if kind == "singleton":
        changed = [position]
        decision = "detect_and_repair"
    elif kind == "block":
        changed = list(range(position, min(position + 4, count - 2)))
        decision = "detect_and_repair"
    elif kind == "systematic":
        changed = list(range(2, count - 2))
        decision = "detect_and_repair"
    elif kind == "no_anchors":
        changed = list(range(count))
        decision = "abstain"
    elif kind == "one_side":
        changed = [0]
        decision = "detect_and_repair"
    elif kind in {"alternating", "short"}:
        changed = list(range(0, count, 2))
        decision = "abstain"
    elif kind == "legal_discount":
        for row in formulas:
            row[2] = f"=({row[2][1:]})*0.9"
    elif kind == "legal_constant":
        formulas[position][2] = f"=({formulas[position][2][1:]})+1"
    elif kind == "unsupported":
        formulas[position][2] = '=XLOOKUP("a",A1:A3,B1:B3)'
    elif kind == "legal_regime":
        for row in formulas[count // 2:]:
            row[2] = f"=({row[2][1:]})*0.8"
    errors = []
    for offset in changed:
        sheet, address, expected = formulas[offset]
        injected = mutate(expected)
        assert injected != expected
        errors.append({"sheet": sheet, "cell": address, "expected_formula": expected})
        formulas[offset][2] = injected
    return {"cells": cells, "formulas": formulas}, errors, decision


def receipt(output: Path, source_lock: Path, mode: str):
    write_json(output / "release_receipt.json", {
        "protocol": "v512_release_v1", "mode": mode, "created_at": datetime.now(UTC).isoformat(),
        "source_lock_sha256": sha256(source_lock), "builder_sha256": sha256(Path(__file__)),
        "public_manifest_sha256": sha256(output / "PUBLIC/manifest.json"),
        "labels_sha256": sha256(output / "labels.json"),
    })


def build_fixtures(args):
    args.output.mkdir(parents=True, exist_ok=False)
    public = []
    labels = []
    for family in FAMILIES:
        for replicate in range(2):
            cluster = identifier(args.seed, f"{family}:{replicate}")
            for kind in KINDS:
                case = identifier(args.seed, f"{family}:{replicate}:{kind}")
                workbook, errors, decision = build_case(family, kind, random.Random(case))
                relative = f"workbooks/{case}.json"
                path = args.output / "PUBLIC" / relative
                write_json(path, workbook)
                digest = sha256(path)
                public.append({"case_id": case, "cluster_id": cluster, "workbook_path": relative,
                               "workbook_sha256": digest, "format": "model_json"})
                labels.append({"case_id": case, "cluster_id": cluster, "family": family,
                               "cohort": kind, "decision": decision, "workbook_sha256": digest,
                               "truth_completeness": "complete", "errors": errors})
    write_json(args.output / "PUBLIC/manifest.json", {"protocol": "v512_public_v1", "cases": public})
    write_json(args.output / "labels.json", {"cases": labels, "seed": args.seed})
    receipt(args.output, args.source_lock, "held_out_structure_fixtures")
    print(json.dumps({"cases": len(public), "families": len(FAMILIES), "release": str(args.output)}))


def build_real(args):
    args.output.mkdir(parents=True, exist_ok=False)
    source = ROOT / "data/external/enron"
    manifest = source / "manifest.csv"
    with manifest.open(encoding="utf-8-sig") as stream:
        all_events = list(csv.DictReader(stream))
    events = [row for row in all_events if row.get("include", "1") == "1"]
    public = []
    workbook_cases = {}
    for relative in sorted({row["workbook"] for row in events}):
        case = identifier("enron", relative)
        origin = source / relative
        destination = args.output / "PUBLIC/workbooks" / f"{case}.xlsx"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, destination)
        if sha256(origin) != sha256(destination):
            raise ValueError("Enron copy differs")
        workbook_cases[relative] = case
        public.append({"case_id": case, "cluster_id": case, "workbook_path": f"workbooks/{case}.xlsx",
                       "workbook_sha256": sha256(destination), "format": "xlsx"})
    write_json(args.output / "PUBLIC/manifest.json", {"protocol": "v512_public_v1", "cases": public})
    write_json(args.output / "labels.json", {
        "truth_completeness": "known_error_locations_only", "manifest_sha256": sha256(manifest),
        "events": [{**row, "case_id": workbook_cases[row["workbook"]]} for row in events],
        "excluded_events": [row for row in all_events if row not in events],
    })
    receipt(args.output, args.source_lock, "retrospective_enron")
    print(json.dumps({"events": len(events), "workbooks": len(public), "release": str(args.output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("fixtures", "real"))
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", default="v512-heldout-20260905-01")
    args = parser.parse_args()
    lock = json.loads(args.source_lock.read_text())
    if lock["protocol"] != "v512_source_lock_v1":
        raise ValueError("freeze V5.1.2 sources before data preparation")
    if args.mode == "fixtures":
        build_fixtures(args)
    else:
        build_real(args)


if __name__ == "__main__":
    main()
