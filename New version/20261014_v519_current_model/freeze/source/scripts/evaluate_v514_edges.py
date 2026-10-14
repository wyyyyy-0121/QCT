"""Development, source freeze, label-free prediction and confirmation scoring."""

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
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from formulaguard.localize import LocalizationResult, v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_4_development import EdgeParameters, compose_edge_diagnosis
from scripts.build_v514_edge_cases import build_cases
from scripts.run_v512_evaluation import load_workbook, write_json
from scripts.score_v512_confirmation import (
    canonical_formula,
    safe_path,
    score_case,
    sha256,
    summarize,
    validate_ranking,
)
from scripts.validate_v513_composition import verify_baseline_cache

MODES = ("off", "propose_only", "orthogonal")
POLICIES = ("structural", "review_only", "reject_all")


def verify_source(path):
    lock = json.loads(path.read_text())
    if platform.python_version() != lock["python"]:
        raise ValueError("Python changed")
    for name, version in lock["dependencies"].items():
        if importlib.metadata.version(name) != version:
            raise ValueError("dependency changed")
    for name, digest in lock["artifacts"].items():
        if sha256(ROOT / name) != digest or sha256(path.parent / "source" / name) != digest:
            raise ValueError(f"frozen source changed: {name}")
    return lock


def freeze(output):
    output.mkdir(parents=True, exist_ok=False)
    files = sorted([*ROOT.glob("formulaguard/*.py"), *ROOT.glob("scripts/*.py"),
                    *ROOT.glob("tests/*.py"), ROOT / "pyproject.toml", ROOT / "research/V514_EDGE_PROTOCOL.md"])
    artifacts = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = output / "source" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        artifacts[relative.as_posix()] = sha256(target)
    write_json(output / "source_lock.json", {
        "protocol": "v514_edge_confirmation_v1", "frozen_at": datetime.now(UTC).isoformat(),
        "artifacts": artifacts, "parameters": asdict(EdgeParameters()),
        "python": platform.python_version(),
        "dependencies": {name: importlib.metadata.version(name) for name in ("numpy", "openpyxl")},
        "gates": {"unsafe_groups_max": 0, "group_precision_min": .95,
                  "control_fpr_max": .10, "abstention_rate_max": .10, "rank_changes_max": 0},
    })
    print(json.dumps({"source_lock_sha256": sha256(output / "source_lock.json"), "files": len(artifacts)}))


def build(output, lock_path=None):
    if lock_path:
        verify_source(lock_path)
    output.mkdir(parents=True, exist_ok=False)
    seed = secrets.token_hex(24) if lock_path else "v514-development-v1"
    cases = build_cases(seed, 4 if lock_path else 2)
    manifest, labels = [], []
    for case, model, label in cases:
        relative = f"workbooks/{case}.json"
        path = output / "PUBLIC" / relative
        write_json(path, model)
        label["workbook_sha256"] = sha256(path)
        labels.append(label)
        manifest.append({"case_id": case, "cluster_id": label["cluster_id"],
                         "workbook_path": relative, "workbook_sha256": sha256(path), "format": "model_json"})
    write_json(output / "PUBLIC/manifest.json", {"protocol": "v514_public_v1", "cases": manifest})
    write_json(output / "labels.json", {"seed": seed, "cases": labels})
    write_json(output / "release_receipt.json", {
        "source_lock_sha256": sha256(lock_path) if lock_path else None,
        "public_manifest_sha256": sha256(output / "PUBLIC/manifest.json"),
        "labels_sha256": sha256(output / "labels.json"), "cases": len(cases),
        "generated_at": datetime.now(UTC).isoformat(),
    })
    if lock_path:
        verify_source(lock_path)
    print(json.dumps({"release": str(output), "cases": len(cases), "labels_displayed": False}))


def compute(task):
    path, row, cache = task
    model = load_workbook(Path(path), row["format"])
    before = dict(model.formulas)
    variants = {}
    for backend in ("v4", "v511"):
        if cache:
            ranked = [LocalizationResult((r["sheet"], r["cell"]), r["score"], r["candidate_formula"], r["evidence"])
                      for r in cache[backend]["ranking"]]
        else:
            ranked = (v4_scores if backend == "v4" else v5_1_1_development_scores)(model)
        expected = [(r.cell, float(r.score).hex()) for r in ranked]
        for mode in MODES:
            for policy in POLICIES:
                variant = f"{backend}_{mode}_{policy}"
                a = compose_edge_diagnosis(model, ranked, backend=backend, edge_mode=mode, repair_policy=policy)
                b = compose_edge_diagnosis(model, ranked, backend=backend, edge_mode=mode, repair_policy=policy)
                if asdict(a) != asdict(b):
                    raise ValueError("nondeterministic composition")
                results = a.to_results()
                if [(r.cell, float(r.score).hex()) for r in results] != expected or set(model.formulas) != {r.cell for r in results}:
                    raise ValueError("rank, score bits or coverage changed")
                portfolio = {}
                for proposal in a.candidates:
                    key = json.dumps(proposal.cell)
                    portfolio.setdefault(key, []).append({"formula": proposal.formula, "source": proposal.source})
                variants[variant] = {
                    "case_id": row["case_id"], "cluster_id": row["cluster_id"], "model": variant,
                    "workbook_sha256": row["workbook_sha256"], "formula_count": len(results),
                    "localization_sha256": a.localization_sha256,
                    "accepted_group_count": len({d.group_id for d in a.decisions if d.accepted_formula}),
                    "candidates": portfolio,
                    "ranking": [{"sheet": r.cell[0], "cell": r.cell[1], "rank": i,
                                 "score": r.score, "score_hex": float(r.score).hex(),
                                 "candidate_formula": r.candidate_formula,
                                 "evidence": {k: r.evidence[k] for k in ("group_state", "group_id", "group_size", "group_reason", "decision")}}
                                for i, r in enumerate(results, 1)],
                }
    if model.formulas != before:
        raise ValueError("model changed workbook formulas")
    return row["case_id"], variants


def predict(public, output, lock_path=None, cache=None):
    if lock_path:
        verify_source(lock_path)
    output.mkdir(parents=True, exist_ok=False)
    manifest_path = public / "manifest.json"
    rows = json.loads(manifest_path.read_text())["cases"]
    tasks = []
    for row in rows:
        path = safe_path(public, row["workbook_path"])
        if sha256(path) != row["workbook_sha256"]:
            raise ValueError("workbook identity mismatch")
        tasks.append((str(path), row, {name: cache[name][row["case_id"]] for name in ("v4", "v511")} if cache else None))
    hashes = {}
    with ProcessPoolExecutor(max_workers=min(24, len(tasks))) as executor:
        for index, (case, variants) in enumerate(executor.map(compute, tasks), 1):
            for name, shard in variants.items():
                path = output / name / f"{case}.json"
                write_json(path, shard)
                hashes[path.relative_to(output).as_posix()] = sha256(path)
            if index % 25 == 0 or index == len(tasks):
                print(f"{index}/{len(tasks)} completed", flush=True)
    if lock_path:
        verify_source(lock_path)
    write_json(output / "prediction_lock.json", {
        "source_lock_sha256": sha256(lock_path) if lock_path else None,
        "public_manifest_sha256": sha256(manifest_path), "shards": hashes,
        "workbooks": len(rows), "variants": 18, "labels_read": [],
        "rank_changes": 0, "score_bit_changes": 0, "coverage_changes": 0,
        "double_composition_identical": True, "baseline_cache_reused": cache is not None,
        "completed_at": datetime.now(UTC).isoformat(),
    })


def score(release, predictions, output, lock_path=None, known_history=False):
    if lock_path:
        verify_source(lock_path)
    output.mkdir(parents=True, exist_ok=False)
    pred_lock = json.loads((predictions / "prediction_lock.json").read_text())
    receipt = json.loads((release / "release_receipt.json").read_text())
    expected_source = sha256(lock_path) if lock_path else None
    historical_source = None
    if known_history:
        public, _, _, _, provenance = verify_baseline_cache("heldout")
        if public.resolve() != (release / "PUBLIC").resolve():
            raise ValueError("historical release mismatch")
        historical_source = provenance["source_lock_sha256"]
    if pred_lock["source_lock_sha256"] != expected_source or receipt.get("source_lock_sha256", historical_source) != (historical_source or expected_source):
        raise ValueError("source binding mismatch")
    if pred_lock["labels_read"] != [] or pred_lock["public_manifest_sha256"] != sha256(release / "PUBLIC/manifest.json"):
        raise ValueError("manifest binding or label protocol mismatch")
    if receipt["public_manifest_sha256"] != pred_lock["public_manifest_sha256"]:
        raise ValueError("release identity mismatch")
    actual_paths = {p.relative_to(predictions).as_posix() for p in predictions.glob("*/*.json")}
    if actual_paths != set(pred_lock["shards"]):
        raise ValueError("missing or extra predictions")
    shards = {}
    for name, digest in pred_lock["shards"].items():
        path = safe_path(predictions, name)
        if sha256(path) != digest:
            raise ValueError("prediction changed")
        shard = json.loads(path.read_text())
        if name != f"{shard['model']}/{shard['case_id']}.json":
            raise ValueError("shard path identity mismatch")
        shards.setdefault(shard["model"], {})[shard["case_id"]] = shard
    if len(pred_lock["shards"]) != 18 * pred_lock["workbooks"] or len(shards) != 18 or any(len(v) != pred_lock["workbooks"] for v in shards.values()):
        raise ValueError("incomplete variant predictions")
    expected_variants = {f"{b}_{m}_{p}" for b in ("v4", "v511") for m in MODES for p in POLICIES}
    manifest = json.loads((release / "PUBLIC/manifest.json").read_text())["cases"]
    if set(shards) != expected_variants or any(set(cases) != {r["case_id"] for r in manifest} for cases in shards.values()):
        raise ValueError("variant or case identities mismatch")
    for row in manifest:
        path = safe_path(release / "PUBLIC", row["workbook_path"])
        if sha256(path) != row["workbook_sha256"]:
            raise ValueError("workbook changed")
        model = load_workbook(path, row["format"])
        for variant in expected_variants:
            shard = shards[variant][row["case_id"]]
            validate_ranking(shard, model.formulas)
            if shard["workbook_sha256"] != row["workbook_sha256"]:
                raise ValueError("shard workbook identity mismatch")
            reference = shards[variant.split("_")[0] + "_off_structural"][row["case_id"]]
            identity = lambda s: [(r["sheet"], r["cell"], r["rank"], float(r["score"]).hex()) for r in s["ranking"]]
            if identity(shard) != identity(reference):
                raise ValueError("ranking policy invariant violated")
            if any(r["score_hex"] != float(r["score"]).hex() for r in shard["ranking"]):
                raise ValueError("score bit identity mismatch")
    if sha256(release / "labels.json") != receipt["labels_sha256"]:
        raise ValueError("label identity mismatch")
    # Durable authorization precedes reading labels and scoring outcomes.
    write_json(output / "reveal_authorization.json", {
        "prediction_lock_sha256": sha256(predictions / "prediction_lock.json"),
        "release_receipt_sha256": sha256(release / "release_receipt.json"),
        "source_lock_sha256": expected_source, "authorized_at": datetime.now(UTC).isoformat(),
    })
    labels = json.loads((release / "labels.json").read_text())["cases"]
    if len(labels) != len(manifest) or {l["case_id"] for l in labels} != {r["case_id"] for r in manifest}:
        raise ValueError("label case coverage mismatch")
    summary = {}
    for variant, cases in shards.items():
        scored = []
        for label in labels:
            shard = cases[label["case_id"]]
            result = score_case(shard, label)
            result["candidate_oracle_covered"] = sum(
                any(canonical_formula(p["formula"]) == canonical_formula(e["expected_formula"])
                    for p in shard["candidates"].get(json.dumps((e["sheet"], e["cell"])), []))
                for e in label["errors"]
            )
            scored.append(result)
        required = [r for r in scored if r["decision"] == "detect_and_repair"]
        covered = sum(r["candidate_oracle_covered"] for r in required)
        denominator = sum(r["errors"] for r in required)
        summary[variant] = {**summarize(scored), "candidate_oracle_covered": covered,
                            "candidate_oracle_denominator": denominator,
                            "candidate_oracle_coverage": covered / denominator if denominator else None,
                            "by_cohort": {name: summarize([r for r in scored if r["cohort"] == name])
                                          for name in sorted({r["cohort"] for r in scored})}}
        write_json(output / f"{variant}_cases.json", scored)
    gates = {}
    for backend in ("v4", "v511"):
        value = summary[f"{backend}_orthogonal_structural"]
        reference = summary[f"{backend}_off_structural"]
        gates[backend] = {
            "coverage_improved": value["exact_candidate_coverage"] > reference["exact_candidate_coverage"],
            "zero_unsafe_groups": value["unsafe_accepted_groups_all_workbooks"] == 0,
            "group_precision": (value["accepted_group_precision"] or 0) >= .95,
            "control_fpr": value["control_workbook_candidate_fpr"] <= .10,
            "abstention_rate": value["ambiguous_workbook_candidate_rate"] <= .10,
        }
    result = {"scope": "fresh-instance confirmation" if lock_path else "disclosed development",
              "variants": summary, "gates": gates,
              "decision": "PASS_SYNTHETIC_CONFIRMATION_ONLY" if all(all(v.values()) for v in gates.values()) else "DO_NOT_PROMOTE",
              "case_count": len(labels), "category_counts": dict(Counter(l["cohort"] for l in labels)),
              "prediction_lock_sha256": sha256(predictions / "prediction_lock.json"),
              "source_lock_sha256": expected_source}
    write_json(output / "result.json", result)
    if lock_path:
        verify_source(lock_path)
    print(json.dumps({k: result[k] for k in ("decision", "case_count", "gates")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "build", "predict", "score", "score_historical", "historical"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--cohort", choices=("heldout", "real"), default="heldout")
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.output)
    elif args.action == "build":
        build(args.output, args.source_lock)
    elif args.action == "predict":
        predict(args.release / "PUBLIC", args.output, args.source_lock)
    elif args.action in {"score", "score_historical"}:
        score(args.release, args.predictions, args.output, args.source_lock, args.action == "score_historical")
    else:
        public, _, cache, _, provenance = verify_baseline_cache(args.cohort)
        predict(public, args.output, cache=cache)
        write_json(args.output / "historical_provenance.json", provenance)
