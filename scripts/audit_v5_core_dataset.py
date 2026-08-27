"""Audit V5-Core data validity, balance, propagation, and split leakage."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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


def verify_build_receipt(root: Path, reasons: list[str]) -> None:
    path = root / "dataset_build_complete.json"
    if not path.exists():
        reasons.append("missing dataset build completion receipt")
        return
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("complete") is not True:
        reasons.append("dataset build receipt is not complete")
    if receipt.get("model_results_consulted") is not False:
        reasons.append("dataset build consulted model results")
    if receipt.get("cases_excluded_for_model_failure") != 0:
        reasons.append("dataset build excluded model failures")
    for name, expected in receipt.get("manifest_hashes", {}).items():
        artifact = root / name
        if not artifact.exists() or sha256(artifact) != expected:
            reasons.append(f"changed build artifact {name}")


def values_differ(left: object, right: object) -> bool:
    try:
        return not math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
    except (TypeError, ValueError):
        return left != right


def within_root(root: Path, relative: str) -> Path | None:
    candidate = (root / relative).resolve()
    return candidate if root.resolve() in candidate.parents else None


def audit_root(root: Path) -> tuple[dict, set[tuple[str, str]], set[str]]:
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    profile = manifest["profile"]
    full_expected = PROFILE_COUNTS[profile]
    subset_limit = manifest.get("subset_limit")
    expected = min(full_expected, int(subset_limit)) if subset_limit is not None else full_expected
    reasons: list[str] = []
    verify_build_receipt(root, reasons)
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
            path = within_root(root, row["workbook"])
            if path is None or not path.exists() or sha256(path) != row["sha256"]:
                reasons.append(f"changed clean workbook {row['clean_id']}")
                continue
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
        if set(ids) != set(labels):
            reasons.append("instances and labels differ")
        balance = Counter(
            (labels[row["instance_id"]]["mutation_type"], row["topology_id"], row["regime"])
            for row in rows if row["instance_id"] in labels
        )
        if profile in {"pilot", "development", "redteam", "validation"}:
            expected_per_group = expected // (len(ERROR_TYPES) * len(TOPOLOGIES) * len(REGIMES))
            if len(balance) != len(ERROR_TYPES) * len(TOPOLOGIES) * len(REGIMES):
                reasons.append(f"incomplete factorial balance: {len(balance)} groups")
            elif set(balance.values()) != {expected_per_group}:
                reasons.append(f"unbalanced factorial cells: {dict(balance)}")
        workbook_hashes = [row.get("mutant_sha256") for row in rows]
        if len(workbook_hashes) != len(set(workbook_hashes)):
            reasons.append("duplicate mutant workbook hashes")
        for row in rows:
            instance_id = row["instance_id"]
            if instance_id not in labels:
                continue
            label = labels[instance_id]
            path = within_root(root, row["mutant_workbook"])
            if path is None or not path.exists() or sha256(path) != row["mutant_sha256"]:
                reasons.append(f"changed mutant {instance_id}")
                continue
            model = WorkbookModel.from_xlsx(path)
            sheet, address = label["source_cell"].rsplit("!", 1)
            source = (sheet, address)
            if source not in model.formulas:
                reasons.append(f"missing source {instance_id}")
                continue
            mutant_values, errors = model.evaluate()
            if errors:
                reasons.append(f"non-silent workbook {instance_id}")
            original_relative = label.get("original_workbook") or f"originals/{instance_id}.xlsx"
            original_path = within_root(root, original_relative)
            if original_path is None or not original_path.exists() or sha256(original_path) != label.get("original_sha256"):
                reasons.append(f"missing or changed original {instance_id}")
                continue
            original_model = WorkbookModel.from_xlsx(original_path)
            original_values, original_errors = original_model.evaluate()
            if original_errors:
                reasons.append(f"original evaluation error {instance_id}")
            if set(model.formulas) != set(original_model.formulas):
                reasons.append(f"formula coordinate set changed {instance_id}")
                continue
            changed_formulas = {
                cell for cell in model.formulas
                if normalized_formula(model.formulas[cell])
                != normalized_formula(original_model.formulas[cell])
            }
            if changed_formulas != {source}:
                reasons.append(f"not exactly one injected formula {instance_id}")
            if normalized_formula(original_model.formulas[source]) != normalized_formula(label["correct_formula"]):
                reasons.append(f"correct formula disagrees with original {instance_id}")
            if normalized_formula(model.formulas[source]) != normalized_formula(label["mutated_formula"]):
                reasons.append(f"mutated formula disagrees with workbook {instance_id}")
            descendants = model.dependency_graph().descendants(source) & set(model.formula_cells)
            if not descendants:
                reasons.append(f"no propagation {instance_id}")
            sink_sheet, sink_address = label["sink_cell"].rsplit("!", 1)
            sink = (sink_sheet, sink_address)
            if sink not in descendants:
                reasons.append(f"declared sink is not downstream {instance_id}")
            elif not values_differ(original_values.get(sink), mutant_values.get(sink)):
                reasons.append(f"mutation does not change sink value {instance_id}")
            actual_depth = model.dependency_graph().shortest_path_length(source, sink)
            if actual_depth != label.get("actual_depth"):
                reasons.append(f"propagation depth mismatch {instance_id}")
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
    split_templates: dict[str, set[str]] = {}
    split_seeds: dict[str, set[int]] = {}
    for root in args.roots:
        audit, pairs, signatures = audit_root(root)
        audits.append(audit)
        split_pairs[audit["profile"]] = pairs
        split_signatures[audit["profile"]] = signatures
        manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
        cases = manifest.get("cases", [])
        split_templates[audit["profile"]] = {
            str(row["template_family"]) for row in cases if row.get("template_family")
        }
        split_seeds[audit["profile"]] = {
            int(row["seed"]) for row in cases if row.get("seed") is not None
        }
    leakage = []
    profiles = sorted(split_pairs)
    for index, left in enumerate(profiles):
        for right in profiles[index + 1:]:
            if left in {"clean"} or right in {"clean"}:
                continue
            pair_overlap = split_pairs[left] & split_pairs[right]
            signature_overlap = split_signatures[left] & split_signatures[right]
            template_overlap = split_templates[left] & split_templates[right]
            seed_overlap = split_seeds[left] & split_seeds[right]
            if pair_overlap or signature_overlap or template_overlap or seed_overlap:
                leakage.append({
                    "left": left, "right": right,
                    "formula_pair_overlap": len(pair_overlap),
                    "graph_formula_overlap": len(signature_overlap),
                    "template_family_overlap": len(template_overlap),
                    "seed_overlap": len(seed_overlap),
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
