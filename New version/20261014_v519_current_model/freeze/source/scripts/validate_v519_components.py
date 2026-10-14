"""Predeclared G1 exhaustive comparison of component tables and original evaluation."""

import argparse
import hashlib
import json
import math
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from time import perf_counter

from formulaguard.v5_1_5_development import _satisfaction, approved_aggregates
from formulaguard.v5_1_7_development import _domain
from formulaguard.v518_numeric_bounds import runtime_identity, runtime_supported
from formulaguard.v519_components import build_component_tables, component_bounds
from scripts.build_v519_component_cases import (
    FAMILIES,
    SEEDS,
    STRUCTURES,
    build_component_case,
)
from scripts.evaluate_v518_numeric import source_files
from scripts.v518_validation_common import (
    AS_OF,
    load_model,
    sha256,
    snapshot,
    write_json,
)

ROOT = Path(__file__).resolve().parents[1]
SPECS = tuple(product(FAMILIES, STRUCTURES, (4,8,12), SEEDS))


def check_case(task):
    output, spec = task
    family, structure, count, seed = spec
    name = f"{family}_{structure}_{count}_{seed}"
    output = Path(output) / "cases" / name
    started = perf_counter()
    try:
        raw, document, approvals, label = build_component_case(count, family, structure, seed)
        write_json(output / "input.json", {"workbook": raw, "document": json.loads(document),
                                          "approvals": approvals, "label": label})
        model = load_model(raw)
        aggregates = approved_aggregates(model, [document], approvals, AS_OF)
        cells, options = _domain(model, aggregates)
        if len(cells) != count or any(len(o) != 2 for o in options):
            raise ValueError("predeclared candidate domain mismatch")
        tables = build_component_tables(model, aggregates, cells, options)
        bounds = component_bounds(tables, aggregates)
        write_json(output / "tables.json", asdict(tables))
        baseline, errors = model.evaluate(targets=cells)
        changed, changed_errors = model.evaluate(overrides={cells[0]: options[0][1]}, targets=cells)
        assert not errors and not changed_errors
        witnesses = [c for c in cells[1:] if float(baseline[c]).hex() != float(changed[c]).hex()]
        assert witnesses, "no true numerical coupling"
        witness = {"upstream": cells[0], "changed_formula": options[0][1], "downstream": witnesses[0],
                   "before": float(baseline[witnesses[0]]).hex(), "after": float(changed[witnesses[0]]).hex()}
        seen, solutions, digest, intervals = set(), [], hashlib.sha256(), {}
        member_comparisons = prefix_checks = 0
        members = tuple(sorted(c for a in aggregates for c in a.members))
        members = tuple(dict.fromkeys(members))
        for original in product(*(range(len(o)) for o in options)):
            selection = tables.from_original(original)
            assert selection not in seen and tables.to_original(selection) == original
            seen.add(selection)
            overrides = {c: o[v] for c, o, v in zip(cells, options, original, strict=True) if v}
            values, errors = model.evaluate(overrides=overrides, targets=members)
            assert not errors
            rebuilt = tables.member_values(selection)
            assert set(rebuilt) == set(members)
            actual_hex = [float(values[c]).hex() for c in members]
            assert actual_hex == [rebuilt[c].hex() for c in members]
            member_comparisons += len(members)
            satisfied = _satisfaction(model, aggregates, overrides)
            for a, bound in zip(aggregates, bounds, strict=True):
                actual = math.fsum(float(values[c]) for c in a.members)
                restored = math.fsum(rebuilt[c] for c in a.members)
                assert actual.hex() == restored.hex()
                assert math.isclose(restored, a.total, rel_tol=1e-10, abs_tol=1e-8) == satisfied[a.identifier]
                for length in range(len(selection)+1):
                    prefix = selection[:length]
                    key = (a.identifier, prefix)
                    if key not in intervals:
                        intervals[key] = (*bound.interval(prefix), bound.excludes(prefix))
                    low, high, excluded = intervals[key]
                    assert low <= actual <= high
                    assert not (satisfied[a.identifier] and excluded)
                    prefix_checks += 1
            if all(satisfied.values()):
                solutions.append(original)
            digest.update(json.dumps([original, actual_hex, satisfied], sort_keys=True).encode() + b"\n")
        assert len(seen) == tables.space_size == 2**count
        assert seen == set(product(*(range(len(c.assignments)) for c in tables.components)))
        truth = {(e["sheet"], e["cell"]): e["expected_formula"] for e in label["errors"]}
        intended = tuple(o.index(truth[c]) for c, o in zip(cells, options, strict=True))
        assert intended in solutions
        result = {"name": name, "passed": True, "specification": spec, "space_size": tables.space_size,
                  "component_sizes": [len(c.indices) for c in tables.components],
                  "component_states": [len(c.assignments) for c in tables.components],
                  "preparation_evaluations": tables.preparation_evaluations,
                  "global_assignments_evaluated": len(seen), "global_evaluate_calls": 2*len(seen),
                  "coupling_probe_evaluate_calls": 2,
                  "member_comparisons": member_comparisons, "prefix_checks": prefix_checks,
                  "distinct_constraint_prefixes": len(intervals), "satisfying_assignments": solutions,
                  "coupling_witness": witness, "global_trace_sha256": digest.hexdigest(),
                  "input_sha256": sha256(output / "input.json"), "tables_sha256": sha256(output / "tables.json"),
                  "seconds": perf_counter()-started}
    except Exception as exc:  # noqa: BLE001 - preserve every failed experimental case
        result = {"name": name, "passed": False, "specification": spec,
                  "error": f"{type(exc).__name__}: {exc}", "seconds": perf_counter()-started}
    write_json(output / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    assert runtime_supported()
    args.output.mkdir(parents=True, exist_ok=False)
    args.snapshot.mkdir(parents=True, exist_ok=False)
    files = sorted([*source_files(), ROOT / "research/V519_G1_PROTOCOL.md", ROOT / "research/V519_DEVELOPMENT_PLAN.md"])
    hashes = snapshot(ROOT, args.snapshot, files)
    old_lock = json.loads((ROOT / "research/V518_VALIDATION_V1/source_lock.json").read_text())
    assert all(sha256(ROOT / name) == value for name, value in old_lock["artifacts"].items())
    write_json(args.output / "run_lock.json", {"specifications": SPECS, "sources": hashes,
               "runtime": runtime_identity(), "started_at": datetime.now(UTC).isoformat(),
               "workers": args.workers, "scope": "G1 component prototype, not repair acceptance"})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for record in pool.map(check_case, ((str(args.output), spec) for spec in SPECS)):
            records.append(record)
            print(f"{len(records)}/{len(SPECS)} {record['name']}: {record['passed']}", flush=True)
    unchanged = hashes == {p.relative_to(ROOT).as_posix(): sha256(p) for p in files}
    passed = len(records) == 72 and all(r["passed"] for r in records) and unchanged
    write_json(args.output / "result.json", {"gate": "G1", "passed": passed, "sources_unchanged": unchanged,
               "workbooks": len(records), "global_assignments_evaluated": sum(r.get("global_assignments_evaluated", 0) for r in records),
               "member_comparisons": sum(r.get("member_comparisons", 0) for r in records),
               "prefix_checks": sum(r.get("prefix_checks", 0) for r in records), "records": records,
               "completed_at": datetime.now(UTC).isoformat()})
    if not passed:
        raise ValueError("G1 failed; full population and failures retained")


if __name__ == "__main__":
    main()
