"""Audit V5-Core data validity, balance, propagation, and split leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.a1 import parse_address
from formulaguard.formula import formula_fingerprint, normalized_formula
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
    clean_probe_signatures: dict[str, set[str]] = {}
    if profile == "clean":
        rows = json.loads((root / "clean_manifest.json").read_text(encoding="utf-8"))
        ids = [row["clean_id"] for row in rows]
        probe_sets: dict[str, set[str]] = defaultdict(set)
        structure_counts = Counter(row["structure"] for row in rows)
        partition_counts = Counter(row.get("control_partition") for row in rows)
        if expected % 12 == 0 and set(structure_counts.values()) != {expected // 12}:
            reasons.append(f"clean structures are not balanced: {dict(structure_counts)}")
        if expected == 360 and partition_counts != Counter({"calibration": 240, "locked_control": 120}):
            reasons.append(f"clean control partition mismatch: {dict(partition_counts)}")
        for row in rows:
            path = root / row["workbook"]
            if not path.exists() or sha256(path) != row["sha256"]:
                reasons.append(f"changed clean workbook {row['clean_id']}")
            model = WorkbookModel.from_xlsx(path)
            _, errors = model.evaluate()
            if errors:
                reasons.append(f"clean evaluation error {row['clean_id']}")
            probe = []
            for (sheet, address), formula in model.formulas.items():
                parsed = parse_address(address)
                if sheet == "Model" and 23 <= parsed.col <= 28:  # W:AB
                    probe.append((parsed.row, parsed.col, formula_fingerprint(formula, address)))
            if not probe:
                reasons.append(f"missing structural probe {row['clean_id']}")
            else:
                min_row = min(item[0] for item in probe)
                min_col = min(item[1] for item in probe)
                normalized_probe = sorted(
                    (row_number - min_row, column - min_col, fingerprint)
                    for row_number, column, fingerprint in probe
                )
                signature = hashlib.sha256(
                    json.dumps(normalized_probe, sort_keys=True).encode("utf-8")
                ).hexdigest()
                probe_sets[row["structure"]].add(signature)
        balance = Counter(row["regime"] for row in rows)
        structures = sorted(probe_sets)
        for index, left in enumerate(structures):
            for right in structures[index + 1:]:
                if probe_sets[left] & probe_sets[right]:
                    reasons.append(f"clean probe collision {left} vs {right}")
        clean_probe_signatures = {
            structure: sorted(values) for structure, values in sorted(probe_sets.items())
        }
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
        "clean_structure_probe_signatures": clean_probe_signatures,
        "clean_structure_probe_disjoint": not any("clean probe collision" in reason for reason in reasons),
        "clean_structure_counts": dict(structure_counts) if profile == "clean" else {},
        "clean_control_partition_counts": dict(partition_counts) if profile == "clean" else {},
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
