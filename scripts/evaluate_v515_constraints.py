"""Frozen, label-separated experiment for approved aggregate constraints."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import secrets
import shutil
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_4_development import compose_edge_diagnosis
from formulaguard.v5_1_5_development import compose_constraint_diagnosis
from scripts.build_v515_constraint_cases import build_cases
from scripts.evaluate_v514_edges import verify_source
from scripts.run_v512_evaluation import load_workbook, write_json
from scripts.score_v512_confirmation import (
    canonical_formula,
    safe_path,
    score_case,
    sha256,
    summarize,
    validate_ranking,
)

MODES = ("baseline", "structural_edge", "trusted", "unapproved", "review_only", "reject_all")
AS_OF = date(2026, 9, 6)


def freeze(output):
    output.mkdir(parents=True, exist_ok=False)
    files = sorted([*ROOT.glob("formulaguard/*.py"), *ROOT.glob("scripts/*.py"), *ROOT.glob("tests/*.py"),
                    ROOT / "pyproject.toml", ROOT / "research/V515_TRUSTED_CONSTRAINT_PROTOCOL.md"])
    hashes = {}
    for path in files:
        name = path.relative_to(ROOT)
        target = output / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[name.as_posix()] = sha256(target)
    write_json(output / "source_lock.json", {
        "protocol": "v515_trusted_constraints_v1", "artifacts": hashes,
        "python": platform.python_version(),
        "dependencies": {n: importlib.metadata.version(n) for n in ("numpy", "openpyxl")},
        "frozen_at": datetime.now(UTC).isoformat(), "as_of": AS_OF.isoformat(),
        "modes": MODES, "constraint_authority": "simulated externally approved ledger",
        "gates": {"unsafe_groups_max": 0, "group_precision_min": .95, "rank_changes_max": 0,
                  "paired_legal_actions_max": 0, "coverage_strictly_increases": True},
    })
    print(json.dumps({"files": len(hashes), "source_lock_sha256": sha256(output / "source_lock.json")}))


def build(output, lock=None):
    if lock:
        verify_source(lock)
    output.mkdir(parents=True, exist_ok=False)
    seed = secrets.token_hex(24) if lock else "v515-development-01"
    rows, labels, approval_registry = [], [], {}
    for case, raw, document, approvals, label in build_cases(seed, 5 if lock else 2):
        workbook_path, document_path = f"workbooks/{case}.json", f"documents/{case}.json"
        write_json(output / "PUBLIC" / workbook_path, raw)
        # Parse/re-encode identically through the normal artifact writer; pin the
        # actual saved bytes rather than the generator's temporary serialization.
        write_json(output / "PUBLIC" / document_path, json.loads(document))
        doc_hash = sha256(output / "PUBLIC" / document_path)
        if approvals:
            approvals = {issuer: doc_hash for issuer in approvals}
        approval_registry[case] = approvals
        row = {"case_id": case, "cluster_id": label["cluster_id"], "workbook_path": workbook_path,
               "workbook_sha256": sha256(output / "PUBLIC" / workbook_path), "format": "model_json",
               "document_path": document_path, "document_sha256": doc_hash}
        rows.append(row)
        labels.append({**label, "workbook_sha256": row["workbook_sha256"]})
    write_json(output / "PUBLIC/manifest.json", {"cases": rows, "as_of": AS_OF.isoformat()})
    write_json(output / "APPROVALS.json", approval_registry)
    write_json(output / "labels.json", {"cases": labels, "seed": seed})
    write_json(output / "release_receipt.json", {
        "source_lock_sha256": sha256(lock) if lock else None,
        "manifest_sha256": sha256(output / "PUBLIC/manifest.json"),
        "approvals_sha256": sha256(output / "APPROVALS.json"), "labels_sha256": sha256(output / "labels.json"),
        "generated_at": datetime.now(UTC).isoformat(), "cases": len(rows),
        "trust_scope": "simulated external approval; not real business authentication",
    })
    print(json.dumps({"cases": len(rows), "labels_displayed": False}))


def compute(task):
    public, row, approval = task
    model = load_workbook(safe_path(Path(public), row["workbook_path"]), "model_json")
    doc = safe_path(Path(public), row["document_path"]).read_bytes()
    before = dict(model.formulas)
    output = {}
    for backend in ("v4", "v511"):
        ranker = v4_scores if backend == "v4" else v5_1_1_development_scores
        ranking = ranker(model)
        identity = [(r.cell, float(r.score).hex()) for r in ranking]
        for mode in MODES:
            def diagnose(mode=mode, ranking=ranking, backend=backend):
                if mode in {"baseline", "structural_edge"}:
                    return compose_edge_diagnosis(model, ranking, backend=backend,
                                                  edge_mode="orthogonal" if mode == "structural_edge" else "propose_only")
                return compose_constraint_diagnosis(
                    model, ranking, backend=backend, documents=[doc],
                    approvals={} if mode == "unapproved" else approval, as_of=AS_OF,
                    repair_policy=mode if mode in {"review_only", "reject_all"} else "structural",
                )
            diagnosis = diagnose()
            if asdict(diagnosis) != asdict(diagnose()):
                raise ValueError("constraint diagnosis is nondeterministic")
            results = diagnosis.to_results()
            if [(r.cell, float(r.score).hex()) for r in results] != identity or {r.cell for r in results} != set(model.formulas):
                raise ValueError("localization changed")
            portfolio = {}
            for c in diagnosis.candidates:
                portfolio.setdefault(json.dumps(c.cell), []).append(c.formula)
            name = f"{backend}_{mode}"
            output[name] = {
                "case_id": row["case_id"], "cluster_id": row["cluster_id"], "model": name,
                "workbook_sha256": row["workbook_sha256"], "document_sha256": row["document_sha256"],
                "formula_count": len(results), "localization_sha256": diagnosis.localization_sha256,
                "constraint_status": getattr(diagnosis, "constraint_status", "not_used"),
                "accepted_group_count": len({d.group_id for d in diagnosis.decisions if d.accepted_formula}),
                "candidates": portfolio,
                "ranking": [{"sheet": r.cell[0], "cell": r.cell[1], "rank": i,
                             "score": r.score, "candidate_formula": r.candidate_formula,
                             "evidence": {k: r.evidence[k] for k in ("group_id", "group_size", "group_state", "group_reason", "decision")}}
                            for i, r in enumerate(results, 1)],
            }
    if model.formulas != before:
        raise ValueError("workbook formulas mutated")
    return row["case_id"], output


def predict(release, output, lock=None):
    if lock:
        verify_source(lock)
    output.mkdir(parents=True, exist_ok=False)
    public = release / "PUBLIC"
    manifest = json.loads((public / "manifest.json").read_text())
    receipt = json.loads((release / "release_receipt.json").read_text())
    if sha256(public / "manifest.json") != receipt["manifest_sha256"] or sha256(release / "APPROVALS.json") != receipt["approvals_sha256"]:
        raise ValueError("public inputs/approval binding mismatch")
    approvals = json.loads((release / "APPROVALS.json").read_text())
    tasks = []
    for row in manifest["cases"]:
        for path_key, hash_key in (("workbook_path", "workbook_sha256"), ("document_path", "document_sha256")):
            if sha256(safe_path(public, row[path_key])) != row[hash_key]:
                raise ValueError("input identity mismatch")
        tasks.append((str(public), row, approvals[row["case_id"]]))
    hashes = {}
    with ProcessPoolExecutor(max_workers=min(24, len(tasks))) as executor:
        for index, (case, variants) in enumerate(executor.map(compute, tasks), 1):
            for name, shard in variants.items():
                path = output / name / f"{case}.json"
                write_json(path, shard)
                hashes[path.relative_to(output).as_posix()] = sha256(path)
            if index % 25 == 0 or index == len(tasks):
                print(f"{index}/{len(tasks)} cases committed", flush=True)
    if lock:
        verify_source(lock)
    write_json(output / "prediction_lock.json", {
        "source_lock_sha256": sha256(lock) if lock else None,
        "manifest_sha256": receipt["manifest_sha256"], "approvals_sha256": receipt["approvals_sha256"],
        "shards": hashes, "labels_read": [], "rank_changes": 0, "score_bit_changes": 0,
        "coverage_changes": 0, "double_run_identical": True, "completed_at": datetime.now(UTC).isoformat(),
    })


def score(release, predictions, output, lock=None):
    if lock:
        verify_source(lock)
    output.mkdir(parents=True, exist_ok=False)
    receipt = json.loads((release / "release_receipt.json").read_text())
    pred = json.loads((predictions / "prediction_lock.json").read_text())
    digest = sha256(lock) if lock else None
    if pred["source_lock_sha256"] != digest or receipt["source_lock_sha256"] != digest or pred["labels_read"]:
        raise ValueError("source/label protocol mismatch")
    for field, path in (("manifest_sha256", release / "PUBLIC/manifest.json"), ("approvals_sha256", release / "APPROVALS.json")):
        if sha256(path) != receipt[field] or pred[field] != receipt[field]:
            raise ValueError("release binding mismatch")
    manifest = json.loads((release / "PUBLIC/manifest.json").read_text())["cases"]
    variants = {f"{b}_{m}" for b in ("v4", "v511") for m in MODES}
    expected_paths = {f"{v}/{r['case_id']}.json" for v in variants for r in manifest}
    if expected_paths != set(pred["shards"]) or expected_paths != {p.relative_to(predictions).as_posix() for p in predictions.glob("*/*.json")}:
        raise ValueError("incomplete prediction population")
    shards = {v: {} for v in variants}
    for name, expected_hash in pred["shards"].items():
        path = safe_path(predictions, name)
        if sha256(path) != expected_hash:
            raise ValueError("prediction hash mismatch")
        shard = json.loads(path.read_text())
        if name != f"{shard['model']}/{shard['case_id']}.json":
            raise ValueError("shard identity mismatch")
        shards[shard["model"]][shard["case_id"]] = shard
    for row in manifest:
        public = release / "PUBLIC"
        for p, h in (("workbook_path", "workbook_sha256"), ("document_path", "document_sha256")):
            if sha256(safe_path(public, row[p])) != row[h]:
                raise ValueError("input changed")
        model = load_workbook(safe_path(public, row["workbook_path"]), "model_json")
        for variant in variants:
            shard = shards[variant][row["case_id"]]
            validate_ranking(shard, model.formulas)
            if shard["workbook_sha256"] != row["workbook_sha256"] or shard["document_sha256"] != row["document_sha256"]:
                raise ValueError("shard input mismatch")
            reference = shards[variant.split("_")[0] + "_baseline"][row["case_id"]]
            identity = lambda s: [(r["sheet"], r["cell"], r["rank"], float(r["score"]).hex()) for r in s["ranking"]]
            if identity(shard) != identity(reference):
                raise ValueError("ranking invariant violated")
    if sha256(release / "labels.json") != receipt["labels_sha256"]:
        raise ValueError("label identity mismatch")
    write_json(output / "reveal_authorization.json", {"source_lock_sha256": digest,
        "prediction_lock_sha256": sha256(predictions / "prediction_lock.json"),
        "release_receipt_sha256": sha256(release / "release_receipt.json"), "authorized_at": datetime.now(UTC).isoformat()})
    labels = json.loads((release / "labels.json").read_text())["cases"]
    if len(labels) != len(manifest) or {r["case_id"] for r in labels} != {r["case_id"] for r in manifest}:
        raise ValueError("label population mismatch")
    summary = {}
    for variant in variants:
        rows = []
        for label in labels:
            shard = shards[variant][label["case_id"]]
            result = score_case(shard, label)
            result["constraint_qualified"] = label["constraint_qualified"]
            result["constraint_status"] = shard["constraint_status"]
            result["oracle_candidate_covered"] = sum(
                any(canonical_formula(p) == canonical_formula(e["expected_formula"])
                    for p in shard["candidates"].get(json.dumps((e["sheet"], e["cell"])), [])) for e in label["errors"])
            rows.append(result)
        summary[variant] = {**summarize(rows),
                            "constraint_status_counts": dict(Counter(r["constraint_status"] for r in rows)),
                            "qualified_cases": sum(r["constraint_qualified"] for r in rows),
                            "qualified": summarize([r for r in rows if r["constraint_qualified"]]),
                            "by_cohort": {c: summarize([r for r in rows if r["cohort"] == c]) for c in sorted({r["cohort"] for r in rows})},
                            "candidate_oracle_covered": sum(r["oracle_candidate_covered"] for r in rows if r["decision"] == "detect_and_repair")}
        write_json(output / f"{variant}_cases.json", rows)
    pairs = []
    for cluster in sorted({l["pair_id"] for l in labels}):
        error = next(l for l in labels if l["pair_id"] == cluster and l["cohort"] == "error")
        legal = next(l for l in labels if l["pair_id"] == cluster and l["cohort"] == "legal_exception")
        if error["workbook_sha256"] != legal["workbook_sha256"]:
            raise ValueError("paired workbook bytes differ")
        pairs.append({"pair_id": cluster, "error_case": error["case_id"], "legal_case": legal["case_id"], "identical_workbook": True})
    gates = {}
    for b in ("v4", "v511"):
        value = summary[b + "_trusted"]
        gates[b] = {"coverage_increased": value["exact_candidate_coverage"] > summary[b + "_baseline"]["exact_candidate_coverage"],
                    "zero_unsafe": value["unsafe_accepted_groups_all_workbooks"] == 0,
                    "precision": (value["accepted_group_precision"] or 0) >= .95,
                    "legal_pairs_preserved": value["by_cohort"]["legal_exception"]["control_workbook_candidate_fpr"] == 0}
    result = {"scope": "new-instance synthetic constraint confirmation" if lock else "development",
              "variants": summary, "pairs": pairs, "gates": gates,
              "decision": "PASS_CONDITIONAL_SYNTHETIC_EXPERIMENT" if all(all(v.values()) for v in gates.values()) else "DO_NOT_PROMOTE",
              "source_lock_sha256": digest, "case_count": len(labels), "real_business_safety_proven": False}
    write_json(output / "result.json", result)
    if lock:
        verify_source(lock)
    print(json.dumps({k: result[k] for k in ("decision", "case_count", "gates")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("freeze", "build", "predict", "score"))
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-lock", type=Path)
    p.add_argument("--release", type=Path)
    p.add_argument("--predictions", type=Path)
    args = p.parse_args()
    if args.action == "freeze":
        freeze(args.output)
    elif args.action == "build":
        build(args.output, args.source_lock)
    elif args.action == "predict":
        predict(args.release, args.output, args.source_lock)
    else:
        score(args.release, args.predictions, args.output, args.source_lock)
