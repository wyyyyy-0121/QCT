"""Inventory V518 dependency and budget cases without changing frozen sources."""

import csv
import json
import math
import sys
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from formulaguard.v5_1_5_development import approved_aggregates
from formulaguard.v5_1_7_development import _domain
from scripts.evaluate_v518_numeric import release_context
from scripts.v518_validation_common import AS_OF, load_model, sha256, write_json

OUTPUT = ROOT / "research/V519_FEASIBILITY_V1"


def read(path):
    return json.loads(path.read_text())


def structure(model, aggregates):
    cells, options = _domain(model, aggregates)
    candidates = set(cells)
    graph = {c: set(refs) for c, refs in model.dependency_graph().precedents.items()}
    for cell, values in zip(cells, options, strict=True):
        for formula in values[1:]:
            graph.setdefault(cell, set()).update(model.dependency_graph({cell: formula}).precedents[cell])
    neighbors = {c: set() for c in cells}
    supports = {}
    for target in {c for a in aggregates for c in a.members}:
        pending, seen = [target], set()
        while pending:
            cell = pending.pop()
            if cell in seen:
                continue
            seen.add(cell)
            pending.extend(graph.get(cell, ()))
        support = seen & candidates
        supports[target] = support
        for cell in support:
            neighbors[cell].update(support - {cell})
    components, unseen = [], set(cells)
    while unseen:
        pending, component = [min(unseen)], set()
        while pending:
            cell = pending.pop()
            if cell in component:
                continue
            component.add(cell)
            pending.extend(neighbors[cell] - component)
        unseen -= component
        components.append(sorted(component))
    sizes = [math.prod(len(options[cells.index(c)]) for c in group) for group in components]
    coupled = [g for g in components if len(g) > 1]
    observations = []
    # Finite local evaluations describe these existing fixtures only; they do not
    # prove that arbitrary zero-coefficient references can be deleted safely.
    for group in coupled:
        assert len(group) == 2
        domains = [options[cells.index(c)] for c in group]
        values = {}
        for assignment in product(*(range(len(o)) for o in domains)):
            overrides = {c: domains[i][v] for i, (c, v) in enumerate(zip(group, assignment, strict=True)) if v}
            evaluated, errors = model.evaluate(overrides=overrides, targets=set(group))
            assert not errors
            values[assignment] = {c: float(evaluated[c]).hex() for c in group}
        cross_effect = any(
            values[a][target] != values[b][target]
            for target in group for a in values for b in values
            if a[group.index(target)] == b[group.index(target)]
        )
        observations.append({"cells": group, "assignments_evaluated": len(values),
                             "cross_effect_observed": cross_effect})
    assert math.prod(sizes) == math.prod(map(len, options))
    return {"candidate_cells": len(cells), "option_counts": list(map(len, options)),
            "space_size": math.prod(sizes), "component_sizes": list(map(len, components)),
            "component_states": sizes, "table_rows_estimate": sum(sizes),
            "multi_candidate_targets": sum(len(s) > 1 for s in supports.values()),
            "coupling_observations": observations}


def main():
    OUTPUT.mkdir(exist_ok=True)
    inventory, details, source_hashes = [], {}, {}
    population = {}
    for stage in ("development", "confirmation"):
        release = ROOT / f"results/v518_{stage}_release_v1"
        predictions = ROOT / f"results/v518_{stage}_predictions_v1"
        result_path = ROOT / ("research/V518_VALIDATION_V1/result.json" if stage == "confirmation"
                              else "research/V518_DEVELOPMENT_VALIDATION_V1/result.json")
        lock = ROOT / "results/v518_freeze_v1/source_lock.json" if stage == "confirmation" else None
        receipt, rows, registry = release_context(release, lock)
        prediction = read(predictions / "prediction_lock.json")
        assert sha256(release / "labels.json") == receipt["labels_sha256"]
        assert prediction["release_receipt_sha256"] == sha256(release / "release_receipt.json")
        result = read(result_path)
        authorization = read(result_path.parent / "reveal_authorization.json")
        assert authorization["all_inputs_rankings_proofs_verified"]
        assert authorization["prediction_lock_sha256"] == sha256(predictions / "prediction_lock.json")
        source_hashes[result_path.relative_to(ROOT).as_posix()] = sha256(result_path)
        source_hashes[(predictions / "prediction_lock.json").relative_to(ROOT).as_posix()] = sha256(predictions / "prediction_lock.json")
        by_case = {r["case_id"]: r for r in rows}
        labels = {r["case_id"]: r for r in read(release / "labels.json")["cases"]}
        main_records = [r for r in result["records"] if r["mode"] == "numeric"]
        assert len(main_records) == 2 * len(rows)
        assert {(r["case_id"], r["backend"]) for r in main_records} == {
            (r["case_id"], b) for r in rows for b in ("v4", "v511")}
        population[stage] = {"workbooks": len(rows), "numeric_diagnoses": len(main_records),
                             "all_modes_diagnoses": result["diagnoses"]}
        for record in main_records:
            case_id, backend = record["case_id"], record["backend"]
            relative = f"shards/{backend}_numeric/{case_id}.json"
            assert sha256(predictions / relative) == prediction["shards"][relative]
            shard = read(predictions / relative)
            audit = shard["diagnosis"]["search"]
            for key in ("status", "engine", "fallback_reason", "space_size", "visited", "evaluated",
                        "preparation_evaluations", "pruned_states", "solutions_seen", "complete"):
                assert record[key] == audit[key]
            if audit["fallback_reason"] != "candidate_dependency" and audit["status"] != "budget_exceeded":
                continue
            assert not record["actions"] and not audit["complete"]
            assert not any(d["accepted_formula"] for d in shard["diagnosis"]["decisions"])
            assert record["required_cells"] == len(labels[case_id]["errors"])
            for key in ("kind", "count", "family"):
                assert record[key] == labels[case_id][key]
            key = stage + ":" + case_id
            if key not in details:
                row = by_case[case_id]
                model = load_model(read(release / "PUBLIC" / row["workbook_path"]))
                document = (release / "PUBLIC" / row["document_path"]).read_bytes()
                aggregates = approved_aggregates(model, [document], registry[case_id], AS_OF)
                details[key] = structure(model, aggregates)
            assert details[key]["space_size"] == record["space_size"]
            budget = shard["configuration"]
            exhausted = [name for name, field in (("max_nodes", "visited"), ("max_evaluations", "evaluated"),
                                                  ("max_preparations", "preparation_evaluations"))
                         if record[field] >= budget[name]]
            inventory.append({"stage": stage, **{k: record[k] for k in (
                "case_id", "backend", "family", "kind", "count", "status", "engine", "fallback_reason",
                "space_size", "visited", "evaluated", "preparation_evaluations", "pruned_states",
                "solutions_seen", "required_cells", "certificate_bytes", "diagnosis_seconds")},
                "exhausted_budget": ";".join(exhausted), "shard_path": str((predictions / relative).relative_to(ROOT)),
                "shard_sha256": prediction["shards"][relative]})
    groups = defaultdict(list)
    for row in inventory:
        groups[(row["stage"], row["backend"], row["kind"])].append(row)
    summaries = []
    for (stage, backend, kind), rows in sorted(groups.items()):
        summaries.append({"stage": stage, "backend": backend, "kind": kind, "workbooks": len(rows),
                          "required_cells": sum(r["required_cells"] for r in rows),
                          "exhausted_budgets": dict(Counter(r["exhausted_budget"] for r in rows)),
                          "ranges": {k: [min(r[k] for r in rows), max(r[k] for r in rows)] for k in (
                              "space_size", "visited", "evaluated", "preparation_evaluations", "pruned_states",
                              "certificate_bytes", "diagnosis_seconds")}})
    assert len(details) == 30 and len(inventory) == 60
    assert all(not observation["cross_effect_observed"] for d in details.values() for observation in d["coupling_observations"])
    with (OUTPUT / "cases.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]))
        writer.writeheader()
        writer.writerows(inventory)
    write_json(OUTPUT / "structure.json", details)
    write_json(OUTPUT / "summary.json", {"population": population, "selected_workbooks": len(details),
               "selected_numeric_diagnoses": len(inventory), "groups": summaries,
               "source_hashes": source_hashes, "audit_script_sha256": sha256(Path(__file__)),
               "scope": "existing revealed V518 development evidence; no V519 solver or new confirmation"})
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
