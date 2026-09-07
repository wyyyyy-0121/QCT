"""Read-only raw-evidence audit; outputs a separate compact delivery bundle.

Run from the repository root: python -m research.V519_FINAL_AUDIT --output PATH.
Labels are accessed only after checking the persisted reveal authorization.
This audit does not rerun the scorer or alter any frozen execution source.
"""

import argparse
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path

from scripts.evaluate_v519_confirmation import (
    BACKENDS,
    MODES,
    configuration,
    context,
    environment,
    specifications,
    verify_lock,
)
from scripts.score_v512_confirmation import canonical_formula, safe_path
from scripts.v518_validation_common import sha256, write_json
from scripts.v519_validation_common import ROOT, sources


def read(path):
    return json.loads(path.read_text())


def require(condition, message):
    if not condition:
        raise ValueError(message)


def raw_actions(raw):
    decisions = raw["decisions"]
    require(len({tuple(d["cell"]) for d in decisions}) == len(decisions), "duplicate decisions")
    accepted = [d for d in decisions if d["state"] == "accepted"]
    require(all((d["accepted_formula"] is not None) == (d["state"] == "accepted")
                for d in decisions), "acceptance state/formula mismatch")
    actions = {tuple(d["cell"]): d["accepted_formula"] for d in accepted}
    if accepted:
        search = raw["search"]
        require(search["status"] == "unique_solution" and search["complete"]
                and search["solutions_seen"] == 1, "unproved accepted group")
        require(raw["repair_policy"] == "structural", "nonaccepting policy accepted")
        payload = [search["binding"], sorted(actions.items())]
        is_v519 = "proof_version" in search
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
                   if is_v519 else json.dumps(payload))
        group = ("v519_" if is_v519 else "v518_") + hashlib.sha256(encoded.encode()).hexdigest()
        require(all(d["group_id"] == group and d["group_size"] == len(actions)
                    for d in accepted), "atomic group identity/size mismatch")
    return actions


def correct_actions(raw, label):
    actual = raw_actions(raw)
    truth = {(e["sheet"], e["cell"]): canonical_formula(e["expected_formula"])
             for e in label["errors"]}
    require(len(truth) == len(label["errors"]), "duplicate truth cells")
    correct = sum(truth.get(c) == canonical_formula(f) for c, f in actual.items())
    require(not actual or (correct == len(actual) and label["decision"] not in {"abstain", "no_action"}),
            "unsafe raw accepted transaction")
    return actual, truth


def historical_gates():
    results = {}
    for stage, population in ((2, 144), (3, 384), (4, 24)):
        folder = ROOT / f"research/V519_G{stage}_V1"
        lock = read(folder / "source_lock.json")
        snapshot = ROOT / f"results/v519_g{stage}_source_v1/source"
        require(all(sha256(safe_path(snapshot, n)) == h for n, h in lock["files"].items()),
                f"G{stage} source snapshot changed")
        result = read(folder / "result.json")
        require(result[f"G{stage}_passed"] and len(result["records"]) == population,
                f"G{stage} incomplete gate")
        checked, unique_keys = 0, set()
        if stage == 2:
            oracle_path = ROOT / "research/V519_G1_V1/result.json"
            require(sha256(oracle_path) == lock["oracle_sha256"], "G1 oracle changed")
            oracle = {r["name"]: r for r in read(oracle_path)["records"]}
        if stage == 3:
            labels = {}
            for cohort in ("development", "confirmation"):
                release = ROOT / f"results/v518_{cohort}_release_v1"
                pred = ROOT / f"results/v518_{cohort}_predictions_v1"
                require(sha256(release / "release_receipt.json") == lock["receipts"][cohort]["release"]
                        and sha256(pred / "prediction_lock.json") == lock["receipts"][cohort]["prediction"],
                        "G3 historical receipts changed")
                score_path = ROOT / ("research/V518_VALIDATION_V1" if cohort == "confirmation"
                                     else "research/V518_DEVELOPMENT_VALIDATION_V1")
                require(read(score_path / "reveal_authorization.json")["prediction_lock_sha256"]
                        == sha256(pred / "prediction_lock.json"), "G3 missing label authorization")
                receipt = read(release / "release_receipt.json")
                require(sha256(release / "labels.json") == receipt["labels_sha256"], "G3 truth changed")
                labels[cohort] = {r["case_id"]: r for r in read(release / "labels.json")["cases"]}
        for row in result["records"]:
            require(row["ranking_changes"] == row["candidate_changes"] == 0, "historical identity changed")
            if stage == 2:
                name = row["case"]
                path = folder / "cases" / f"{name}_{row['backend']}.json"
                case_folder = ROOT / "research/V519_G1_V1/cases" / name
                require(sha256(case_folder / "input.json") == oracle[name]["input_sha256"]
                        and sha256(case_folder / "tables.json") == oracle[name]["tables_sha256"],
                        "G1 input/table changed")
                label = read(case_folder / "input.json")["label"]
                key = (name, row["backend"])
                require(len(oracle[name]["satisfying_assignments"]) == 1, "G1 oracle not unique")
            elif stage == 3:
                path = folder / "cases" / f"{row['stage']}_{row['case_id']}_{row['backend']}.json"
                label = labels[row["stage"]][row["case_id"]]
                key = (row["stage"], row["case_id"], row["backend"])
            else:
                name = f"{row['family']}_{row['structure']}_{row['seed']}_{row['backend']}"
                path = folder / "cases" / name / "diagnosis.json"
                label = read(path.parent / "input.json")["label"]
                key = (row["family"], row["structure"], row["seed"], row["backend"])
                require(row["passed"] and row["baseline_status"] == "budget_exceeded"
                        and row["oracle_evaluated"] == 8192, "G4 milestone failed")
            require(key not in unique_keys, "duplicate historical case")
            unique_keys.add(key)
            require(sha256(path) == row["diagnosis_sha256"], "historical diagnosis changed")
            raw = read(path)
            actual, truth = correct_actions(raw, label)
            require(len(actual) == row["accepted_cells"] and raw["search"]["status"] == row["status"],
                    "historical record mismatch")
            require(row["proof_replayed"] == (raw["search"]["status"] == "unique_solution"),
                    "historical replay receipt mismatch")
            if stage in {2, 4}:
                require(set(actual) == set(truth), "incomplete historical unique repair")
            if stage == 3 and row["old_accepted_preserved"]:
                pred = ROOT / f"results/v518_{row['stage']}_predictions_v1"
                old_name = f"shards/{row['backend']}_numeric/{row['case_id']}.json"
                require(sha256(pred / old_name) == read(pred / "prediction_lock.json")["shards"][old_name],
                        "old unique diagnosis hash changed")
                require(raw_actions(read(pred / old_name)["diagnosis"]) == actual, "old accepted group changed")
            if stage == 4:
                reference = read(path.parent / "reference.json")
                require({(s, c): f for s, c, f in reference["actions"]} == actual
                        and reference["search"]["complete"] and reference["search"]["evaluated"] == 8192,
                        "G4 oracle raw actions differ")
            checked += bool(actual)
        if stage == 2:
            require(sum(r["structure"] in {"pair", "chain"} and r["count"] in {4, 8}
                        and r["proof_replayed"] for r in result["records"]) == 48, "G2 minimum gate failed")
        if stage == 3:
            require(sum(r["old_accepted_preserved"] for r in result["records"]) == 84, "G3 preservation gate")
        if stage == 4:
            require(all(sha256(folder / n) == h for n, h in read(folder / "artifact_hashes.json").items()),
                    "G4 artifact changed")
        results[f"G{stage}"] = {"diagnoses": population, "accepted_groups_checked": checked,
                                 "snapshot_files_checked": len(lock["files"]), "passed": True}
    return results


def experiment(stage, output):
    release = ROOT / f"results/v519_{stage}_release_v1"
    predictions = ROOT / f"results/v519_{stage}_predictions_v1"
    score_folder = ROOT / ("research/V519_VALIDATION_V1" if stage == "confirmation"
                           else "research/V519_DEVELOPMENT_VALIDATION_V1")
    lock_path = ROOT / "results/v519_freeze_v1/source_lock.json" if stage == "confirmation" else None
    frozen = verify_lock(lock_path) if lock_path else None
    receipt, rows, _ = context(release, lock_path)
    prediction = read(predictions / "prediction_lock.json")
    authorization = read(score_folder / "reveal_authorization.json")
    result = read(score_folder / "result.json")
    require(prediction["sources"] == sources() and prediction["environment"] == environment()
            and prediction["labels_read"] == [], "source/environment/label lock changed")
    require(prediction["release_receipt_sha256"] == sha256(release / "release_receipt.json")
            and prediction["source_lock_sha256"] == receipt["source_lock_sha256"], "release binding changed")
    require(authorization["prediction_lock_sha256"] == sha256(predictions / "prediction_lock.json")
            and authorization["all_inputs_rankings_proofs_verified"], "missing scoring authorization")
    times = ([frozen["frozen_at"]] if frozen else []) + [receipt["generated_at"], prediction["completed_at"],
                                                         authorization["authorized_at"], result["completed_at"]]
    require(all(datetime.fromisoformat(a) < datetime.fromisoformat(b) for a, b in pairwise(times)),
            "freeze/generate/lock/reveal/score chronology invalid")
    expected = {f"shards/{b}_{m}/{r['case_id']}.json" for r in rows for b in BACKENDS for m in MODES}
    actual = {p.relative_to(predictions).as_posix() for p in (predictions / "shards").rglob("*") if p.is_file()}
    require(set(prediction["shards"]) == actual == expected, "prediction population changed")
    require(sha256(release / "labels.json") == receipt["labels_sha256"], "label hash changed")
    labels = read(release / "labels.json")
    require(hashlib.sha256(labels["seed"].encode()).hexdigest() == receipt["seed_commitment"], "seed changed")
    truth = {r["case_id"]: r for r in labels["cases"]}
    require(len(truth) == len(labels["cases"]) == len(rows), "duplicate/missing labels")
    records = {(r["case_id"], r["backend"], r["mode"]): r for r in result["records"]}
    require(len(records) == len(result["records"]) == len(expected), "duplicate/missing score records")
    aggregates, strata, transactions = {}, defaultdict(Counter), []
    for row in rows:
        label = truth[row["case_id"]]
        require(label["slot"] == row["slot"] and (label["count"], label["family"], label["kind"])
                == specifications(stage)[row["slot"]][:3], "label stratum mismatch")
        for backend in BACKENDS:
            baseline_raw = None
            baseline_actions = None
            for mode in MODES:
                name = f"shards/{backend}_{mode}/{row['case_id']}.json"
                require(sha256(predictions / name) == prediction["shards"][name], "shard hash changed")
                shard = read(predictions / name)
                raw = shard["diagnosis"]
                actions, required = correct_actions(raw, label)
                config, policy = configuration(mode)
                require(shard["configuration"] == asdict(config) and shard["policy"] == policy
                        and raw["repair_policy"] == policy and raw["backend"] == backend,
                        "raw configuration/backend/policy mismatch")
                search = raw["search"]
                for field, maximum in (("visited", config.max_nodes), ("evaluated", config.max_evaluations),
                                       ("preparation_evaluations", config.max_preparations)):
                    require(type(search[field]) is int and 0 <= search[field] <= maximum,
                            "raw budget exceeded")
                if mode == "baseline":
                    baseline_raw, baseline_actions = raw, actions
                else:
                    require(raw["localization"] == baseline_raw["localization"]
                            and raw["candidates"] == baseline_raw["candidates"]
                            and search["space_size"] == baseline_raw["search"]["space_size"],
                            "raw complete ranking/candidates/domain differ")
                if mode == "components_off":
                    require(actions == baseline_actions and search["status"] == baseline_raw["search"]["status"],
                            "components-off ablation differs from baseline")
                if mode in {"low_budget", "review_only", "reject_all"}:
                    require(not actions, "restricted mode accepted in the fixed G5 population")
                record = records[(row["case_id"], backend, mode)]
                require(record["actions"] == [[*c, f] for c, f in sorted(actions.items())]
                        and record["required_cells"] == len(required)
                        and record["correct_cells"] == len(actions) and not record["unsafe_group"],
                        "raw transactions and scored denominator differ")
                status = raw["search"]["status"]
                require(record["status"] == status and record["proof_replayed"] == (status == "unique_solution"),
                        "status/proof receipt changed")
                key = f"{backend}_{mode}"
                summary = aggregates.setdefault(key, {"workbooks": 0, "required_cells": 0, "correct_cells": 0,
                    "accepted_cells": 0, "accepted_groups": 0, "unsafe_groups": 0, "statuses": Counter(), "paths": Counter()})
                summary["workbooks"] += 1
                summary["required_cells"] += len(required)
                summary["correct_cells"] += len(actions)
                summary["accepted_cells"] += len(actions)
                summary["accepted_groups"] += bool(actions)
                summary["statuses"][status] += 1
                summary["paths"][raw["search"]["engine"] + ":" + raw["search"]["fallback_reason"]] += 1
                stratum = strata[(backend, mode, label["kind"], label["count"])]
                stratum.update(workbooks=1, required_cells=len(required), correct_cells=len(actions), accepted_groups=bool(actions))
                stratum["status:" + status] += 1
                if actions:
                    transactions.append({"case_id": row["case_id"], "backend": backend, "mode": mode,
                        "source_shard": name, "source_sha256": prediction["shards"][name],
                        "search": raw["search"], "accepted_decisions": [d for d in raw["decisions"] if d["state"] == "accepted"]})
    for summary in aggregates.values():
        summary["coverage"] = summary["correct_cells"] / summary["required_cells"]
    require(aggregates == result["summaries"], "raw aggregate summaries differ")
    require(result["gate_passed"] and result["safe"] and result["coverage_improved"]
            and result["ranking_changes"] == result["candidate_changes"] == 0, "G5 gate not passed")
    require(all(aggregates[b + "_main"]["coverage"] > aggregates[b + "_baseline"]["coverage"]
                for b in BACKENDS), "no coverage improvement")
    bundle = output / stage
    shutil.copytree(release, bundle / "release")
    for src, dst in ((predictions / "prediction_lock.json", "prediction_lock.json"),
                     (score_folder / "reveal_authorization.json", "reveal_authorization.json")):
        shutil.copy2(src, bundle / dst)
    if lock_path:
        shutil.copy2(lock_path, bundle / "source_lock.json")
    write_json(bundle / "accepted_transactions.json", transactions)
    write_json(bundle / "strata.json", [{"backend": b, "mode": m, "kind": k, "count": n, **values}
                                        for (b, m, k, n), values in sorted(strata.items())])
    return {"workbooks": len(rows), "shards_checked": len(expected), "accepted_groups_checked": len(transactions),
            "unique_proofs_previously_replayed": sum(r["proof_replayed"] for r in result["records"]),
            "chronology": times, "raw_summaries_match": True, "passed": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "audit output already exists")
    gates = historical_gates()
    for stage in ("development", "confirmation"):
        gates[stage] = experiment(stage, args.output)
    benchmark = read(ROOT / "research/V519_SERIAL_BENCH_V1/result.json")
    require(benchmark["sources"] == sources() and len(benchmark["measurements"]) == 60
            and len(benchmark["profiles"]) == 2, "serial benchmark inventory/source changed")
    require(Counter((r["count"], r["backend"], r["mode"]) for r in benchmark["measurements"])
            == Counter({(n, b, m): 5 for n in (16, 24, 32) for b in BACKENDS for m in ("baseline", "main")}),
            "serial repetition population changed")
    write_json(args.output / "result.json", {"passed": True, "gates": gates,
               "source_files_checked": len(sources()), "serial_measurements_checked": 60,
               "audit_script_sha256": sha256(Path(__file__)), "completed_at": datetime.now(UTC).isoformat(),
               "scope": "raw integrity/atomic transactions/denominators; prior independent proof replay verified by receipts; tests and Git delivery recorded separately"})
    write_json(args.output / "artifact_hashes.json", {p.relative_to(args.output).as_posix(): sha256(p)
               for p in sorted(args.output.rglob("*")) if p.is_file()})
    print(json.dumps(gates, indent=2))


if __name__ == "__main__":
    main()
