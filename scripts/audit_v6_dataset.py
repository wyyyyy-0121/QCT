"""Quality, structural-diversity, and cross-split leakage audit for V6."""

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

from formulaguard.benchmark import load_jsonl, parse_cell_label, values_differ
from formulaguard.formula import normalized_formula
from formulaguard.workbook import WorkbookModel


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def graph_formula_signature(model: WorkbookModel) -> str:
    graph = model.dependency_graph()
    edges = sorted(
        (f"{a[0]}!{a[1]}", f"{b[0]}!{b[1]}")
        for b, precedents in graph.precedents.items()
        if b in model.formulas
        for a in precedents
    )
    formulas = sorted((f"{s}!{a}", normalized_formula(f)) for (s, a), f in model.formulas.items())
    return hashlib.sha256(json.dumps([edges, formulas], sort_keys=True).encode()).hexdigest()


def audit_root(root: Path) -> tuple[dict, set[str], set[str], set[str]]:
    instances = list(load_jsonl(root / "instances.jsonl")) if (root / "instances.jsonl").is_file() else []
    labels = {row["instance_id"]: row for row in load_jsonl(root / "evaluation_labels.jsonl")} if (root / "evaluation_labels.jsonl").is_file() else {}
    clean_manifest = json.loads((root / "clean_manifest.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / "dataset_manifest.json").read_text(encoding="utf-8"))
    reasons, records = [], []
    completion_path = root / "dataset_build_complete.json"
    completion = json.loads(completion_path.read_text(encoding="utf-8")) if completion_path.exists() else {}
    if not completion.get("complete"):
        reasons.append("dataset_completion_missing")
    if completion.get("dataset_manifest_sha256") != file_hash(root / "dataset_manifest.json"):
        reasons.append("dataset_manifest_hash_mismatch")
    recorded_files = {
        "instances_sha256": root / "instances.jsonl",
        "evaluation_labels_sha256": root / "evaluation_labels.jsonl",
        "clean_manifest_sha256": root / "clean_manifest.json",
        "dataset_summary_sha256": root / "dataset_summary.csv",
    }
    for field, path in recorded_files.items():
        if manifest.get(field) != file_hash(path):
            reasons.append(f"recorded_file_hash_mismatch:{field}")
    if manifest.get("generator_source_sha256") != file_hash(ROOT / "scripts/build_v6_dataset.py"):
        reasons.append("generator_source_hash_mismatch")
    ids = [row["instance_id"] for row in instances]
    if len(ids) != len(set(ids)):
        reasons.append("duplicate_instance_id")
    if len(instances) + len(clean_manifest) != int(manifest["expected_count"]):
        reasons.append("count_mismatch")
    hashes, pairs, signatures, templates = [], set(), set(), set()
    for row in instances:
        label = labels.get(row["instance_id"])
        if label is None:
            reasons.append(f"missing_label:{row['instance_id']}")
            continue
        clean_path, mutant_path = root / row["clean_workbook"], root / row["mutant_workbook"]
        clean, mutant = WorkbookModel.from_xlsx(clean_path), WorkbookModel.from_xlsx(mutant_path)
        source, sink = parse_cell_label(label["source_cell"]), parse_cell_label(label["sink_cell"])
        correct, changed = label["correct_formula"], label["mutated_formula"]
        item_reasons = []
        if normalized_formula(correct) == normalized_formula(changed):
            item_reasons.append("equivalent_mutation")
        if normalized_formula(clean.formulas.get(source, "")) != normalized_formula(correct):
            item_reasons.append("clean_formula_mismatch")
        if normalized_formula(mutant.formulas.get(source, "")) != normalized_formula(changed):
            item_reasons.append("mutant_formula_mismatch")
        clean_values, clean_errors = clean.evaluate()
        mutant_values, mutant_errors = mutant.evaluate()
        if clean_errors:
            item_reasons.append("clean_evaluation_error")
        if mutant_errors:
            item_reasons.append("mutant_evaluation_error")
        depth = mutant.dependency_graph().shortest_path_length(source, sink)
        if depth is None or depth < 1:
            item_reasons.append("no_downstream_propagation")
        expected_numeric_depth = {"shallow": 2, "medium": 4, "deep": 7}[label["expected_depth"]]
        if depth != expected_numeric_depth:
            item_reasons.append(f"depth_stratum_mismatch:{depth}!={expected_numeric_depth}")
        if not values_differ(clean_values.get(sink), mutant_values.get(sink)):
            item_reasons.append("sink_value_unchanged")
        current_hashes = [file_hash(clean_path), file_hash(mutant_path)]
        hashes.extend(current_hashes)
        pair = label["mutation_type"] + "|" + normalized_formula(correct) + "|" + normalized_formula(changed)
        pairs.add(pair)
        signature = graph_formula_signature(mutant)
        signatures.add(signature)
        templates.add(row["template_family"])
        records.append({
            "instance_id": row["instance_id"],
            "valid": not item_reasons,
            "reasons": item_reasons,
            "actual_depth": depth,
            "depth_bin": label["expected_depth"] if depth == expected_numeric_depth else "invalid",
            "formula_count": len(mutant.formulas),
            "graph_formula_signature": signature,
        })
    for row in clean_manifest:
        path = root / row["workbook"]
        hashes.append(file_hash(path))
        model = WorkbookModel.from_xlsx(path)
        if model.evaluate()[1]:
            reasons.append(f"clean_control_evaluation_error:{row['clean_id']}")
    if len(hashes) != len(set(hashes)):
        reasons.append("duplicate_workbook_hash")
    invalid = [record for record in records if not record["valid"]]
    if invalid:
        reasons.append(f"invalid_instances:{len(invalid)}")
    counts = {
        "error_type": dict(Counter(labels[row["instance_id"]]["mutation_type"] for row in instances)),
        "topology": dict(Counter(row["topology_id"] for row in instances)),
        "complexity": dict(Counter(row["complexity"] for row in instances)),
        "depth": dict(Counter(labels[row["instance_id"]]["expected_depth"] for row in instances)),
    }
    profile = manifest["profile"]
    if instances and not manifest.get("limited_generation", False):
        if len(counts["error_type"]) != 6 or len(set(counts["error_type"].values())) != 1:
            reasons.append("error_type_balance_mismatch")
        if profile != "smoke" and (len(counts["topology"]) != 5 or len(set(counts["topology"].values())) != 1):
            reasons.append("topology_balance_mismatch")
        if len(counts["complexity"]) != 4 or len(set(counts["complexity"].values())) != 1:
            reasons.append("complexity_balance_mismatch")
        if profile in {"validation", "redteam"} and (len(counts["depth"]) != 3 or len(set(counts["depth"].values())) != 1):
            reasons.append("depth_balance_mismatch")
        seeds = [row["seed"] for row in instances]
        if len(seeds) != len(set(seeds)):
            reasons.append("duplicate_seed")
    quality = {
        "profile": manifest["profile"],
        "expected_count": manifest["expected_count"],
        "observed_instances": len(instances),
        "observed_clean": len(clean_manifest),
        "valid_instances": len(records) - len(invalid),
        "valid_rate": (len(records) - len(invalid)) / max(1, len(records)),
        "hard_gate_passed": not reasons,
        "reasons": reasons,
        "records": records,
    }
    validation = root / "validation"
    validation.mkdir(exist_ok=True)
    (validation / "dataset_quality.json").write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")
    diversity = {
        "counts": counts,
        "unique_templates": len(templates),
        "unique_graph_formula_signatures": len(signatures),
        "unique_formula_pairs": len(pairs),
    }
    (validation / "structural_diversity.json").write_text(json.dumps(diversity, ensure_ascii=False, indent=2), encoding="utf-8")
    return quality, templates, pairs, signatures


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="+", type=Path)
    args = parser.parse_args()
    audits = []
    cross_reasons = []
    sets = []
    for root in args.roots:
        quality, templates, pairs, signatures = audit_root(root)
        audits.append({"root": str(root), "hard_gate_passed": quality["hard_gate_passed"]})
        sets.append((root, templates, pairs, signatures))
    for index, (left_root, left_templates, left_pairs, left_signatures) in enumerate(sets):
        for right_root, right_templates, right_pairs, right_signatures in sets[index + 1:]:
            if left_templates & right_templates:
                cross_reasons.append(f"template_overlap:{left_root}:{right_root}")
            if left_pairs & right_pairs:
                cross_reasons.append(f"formula_pair_overlap:{left_root}:{right_root}")
            if left_signatures & right_signatures:
                cross_reasons.append(f"graph_formula_overlap:{left_root}:{right_root}")
    payload = {
        "protocol": "v6_cross_split_leakage_audit",
        "roots": audits,
        "cross_split_passed": not cross_reasons,
        "reasons": cross_reasons,
        "historical_100_excluded": True,
        "seed_spaces_declared_disjoint": True,
    }
    for root in args.roots:
        validation = root / "validation"
        validation.mkdir(exist_ok=True)
        (validation / "leakage_audit.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if any(not row["hard_gate_passed"] for row in audits) or cross_reasons:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
