"""Check the complete saved G1 inventory and source snapshots after execution."""

import json
import math
import sys
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.v518_validation_common import sha256, write_json
from scripts.validate_v519_components import SPECS


def read(path):
    return json.loads(path.read_text())


def main():
    output = ROOT / "research/V519_G1_V1"
    lock = read(output / "run_lock.json")
    result = read(output / "result.json")
    assert lock["specifications"] == [list(s) for s in SPECS]
    for name, digest in lock["sources"].items():
        assert sha256(ROOT / name) == digest
        assert sha256(ROOT / "results/v519_g1_source_v1/source" / name) == digest
    old = read(ROOT / "research/V518_VALIDATION_V1/source_lock.json")
    assert all(sha256(ROOT / name) == digest for name, digest in old["artifacts"].items())
    expected = {f"{f}_{s}_{n}_{seed}" for f, s, n, seed in SPECS}
    assert {p.name for p in (output / "cases").iterdir()} == expected
    assert len(result["records"]) == len(expected) == 72
    assert {r["name"] for r in result["records"]} == expected
    artifact_hashes = {}
    for record in result["records"]:
        folder = output / "cases" / record["name"]
        assert {p.name for p in folder.iterdir()} == {"input.json", "tables.json", "result.json"}
        assert read(folder / "result.json") == record and record["passed"]
        assert sha256(folder / "input.json") == record["input_sha256"]
        assert sha256(folder / "tables.json") == record["tables_sha256"]
        raw, tables = read(folder / "input.json"), read(folder / "tables.json")
        groups = tables["components"]
        assert sorted(i for g in groups for i in g["indices"]) == list(range(len(tables["cells"])))
        for group in groups:
            expected_rows = [list(a) for a in product(*(range(len(tables["options"][i])) for i in group["indices"]))]
            assert group["assignments"] == expected_rows
            assert len(group["values"]) == len(expected_rows)
            assert all(len(row) == len(group["members"]) for row in group["values"])
        member_list = [tuple(c) for c, _ in tables["fixed"]] + [tuple(c) for g in groups for c in g["members"]]
        expected_members = {tuple(c) for a in raw["document"]["aggregates"] for c in a["members"]}
        assert len(member_list) == len(set(member_list)) and set(member_list) == expected_members
        assert record["space_size"] == math.prod(len(o) for o in tables["options"])
        assert record["space_size"] == math.prod(len(g["assignments"]) for g in groups)
        assert record["global_assignments_evaluated"] == record["space_size"]
        assert record["coupling_witness"]["before"] != record["coupling_witness"]["after"]
        for path in sorted(folder.iterdir()):
            artifact_hashes[path.relative_to(output).as_posix()] = sha256(path)
    assert result["passed"] and result["sources_unchanged"]
    for key in ("global_assignments_evaluated", "member_comparisons", "prefix_checks"):
        assert result[key] == sum(r[key] for r in result["records"])
    assert result["global_assignments_evaluated"] == 104832
    write_json(output / "artifact_hashes.json", artifact_hashes)
    write_json(output / "final_audit.json", {"passed": True, "workbooks": 72,
               "case_artifacts": len(artifact_hashes), "frozen_sources": len(lock["sources"]),
               "v518_frozen_sources_unchanged": len(old["artifacts"]),
               "scope": "archive hashes, exact population, saved table partition and source snapshots; exhaustive numeric checks executed by locked G1 runner"})
    print("G1 archive audit passed: 72 workbooks, 216 case artifacts, 434 source files; 428 V518 source hashes unchanged")


if __name__ == "__main__":
    main()
