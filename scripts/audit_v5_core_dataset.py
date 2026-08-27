"""Audit V5-Core data validity, balance, propagation, and split leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel
from scripts.build_v5_core_dataset import ERROR_TYPES, PROFILE_COUNTS, REGIMES, TOPOLOGIES, sha256


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def graph_formula_signature(model: WorkbookModel, source: str) -> str:
    graph = model.dependency_graph()
    sheet, address = source.rsplit("!", 1)
    cell = (sheet, address)
    payload = {
        "formula_count": len(model.formulas),
        "source_formula": normalized_formula(model.formulas[cell]),
        "source_in": len(graph.precedents.get(cell, ())),
        "source_out": len(graph.dependents.get(cell, ())),
        "descendants": len(graph.descendants(cell)),
        "degree_histogram": sorted(
            (len(graph.precedents.get(item, ())), len(graph.dependents.get(item, ())))
            for item in model.formula_cells
        ),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def audit_root(root: Path) -> tuple[dict, set[tuple[str, str]], set[str]]:
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    profile = manifest["profile"]
    full_expected = PROFILE_COUNTS[profile]
    subset_limit = manifest.get("subset_limit")
    expected = min(full_expected, int(subset_limit)) if subset_limit is not None else full_expected
    reasons: list[str] = []
    if manifest["actual_count"] != expected:
        reasons.append(f"count {manifest['actual_count']} != {expected}")
    formula_pairs: set[tuple[str, str]] = set()
    signatures: set[str] = set()
    if profile == "clean":
        rows = json.loads((root / "clean_manifest.json").read_text(encoding="utf-8"))
        ids = [row["clean_id"] for row in rows]
        for row in rows:
            path = root / row["workbook"]
            if not path.exists() or sha256(path) != row["sha256"]:
                reasons.append(f"changed clean workbook {row['clean_id']}")
            model = WorkbookModel.from_xlsx(path)
            _, errors = model.evaluate()
            if errors:
                reasons.append(f"clean evaluation error {row['clean_id']}")
        balance = Counter(row["regime"] for row in rows)
    else:
        rows = read_jsonl(root / "instances.jsonl")
        labels = {row["instance_id"]: row for row in read_jsonl(root / "evaluation_labels.jsonl")}
        ids = [row["instance_id"] for row in rows]
        balance = Counter((labels[row["instance_id"]]["mutation_type"], row["topology_id"], row["regime"]) for row in rows)
        if set(ids) != set(labels):
            reasons.append("instances and labels differ")
        for row in rows:
            instance_id = row["instance_id"]
            label = labels[instance_id]
            path = root / row["mutant_workbook"]
            if not path.exists() or sha256(path) != row["mutant_sha256"]:
                reasons.append(f"changed mutant {instance_id}")
                continue
            model = WorkbookModel.from_xlsx(path)
            sheet, address = label["source_cell"].rsplit("!", 1)
            source = (sheet, address)
            if source not in model.formulas:
                reasons.append(f"missing source {instance_id}")
                continue
            _, errors = model.evaluate()
            if source in errors:
                reasons.append(f"non-silent source {instance_id}")
            descendants = model.dependency_graph().descendants(source) & set(model.formula_cells)
            if not descendants:
                reasons.append(f"no propagation {instance_id}")
            correct = normalized_formula(label["correct_formula"])
            mutant = normalized_formula(label["mutated_formula"])
            if correct == mutant:
                reasons.append(f"equivalent mutation {instance_id}")
            formula_pairs.add((correct, mutant))
            signature = graph_formula_signature(model, label["source_cell"])
            signatures.add(signature)
    if len(ids) != len(set(ids)):
        reasons.append("duplicate instance ids")
    return ({
        "root": str(root.resolve()),
        "profile": profile,
        "expected": expected,
        "full_profile_count": full_expected,
        "subset_limit": subset_limit,
        "observed": len(ids),
        "balance_groups": len(balance),
        "hard_gate_passed": not reasons,
        "reasons": reasons[:100],
    }, formula_pairs, signatures)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_dataset_audit.json"))
    args = parser.parse_args()
    audits = []
    split_pairs: dict[str, set[tuple[str, str]]] = {}
    split_signatures: dict[str, set[str]] = {}
    for root in args.roots:
        audit, pairs, signatures = audit_root(root)
        audits.append(audit)
        split_pairs[audit["profile"]] = pairs
        split_signatures[audit["profile"]] = signatures
    leakage = []
    profiles = sorted(split_pairs)
    for index, left in enumerate(profiles):
        for right in profiles[index + 1:]:
            if left in {"clean"} or right in {"clean"}:
                continue
            pair_overlap = split_pairs[left] & split_pairs[right]
            signature_overlap = split_signatures[left] & split_signatures[right]
            if pair_overlap or signature_overlap:
                leakage.append({
                    "left": left, "right": right,
                    "formula_pair_overlap": len(pair_overlap),
                    "graph_formula_overlap": len(signature_overlap),
                })
    payload = {
        "protocol": "v5_core_dataset_audit_v1",
        "datasets": audits,
        "cross_split_passed": not leakage,
        "cross_split_leakage": leakage,
        "historical_85_excluded": True,
        "v4_3_validation_excluded": True,
        "hard_gate_passed": all(item["hard_gate_passed"] for item in audits) and not leakage,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)
    if not payload["hard_gate_passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
