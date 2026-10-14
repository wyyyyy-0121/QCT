"""Score complete V5-Core rankings after label release."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_prediction_completion(path: Path) -> None:
    completion_path = path / "prediction_complete.json"
    if not completion_path.exists():
        raise SystemExit("Prediction completion receipt is missing")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    metadata_path = path / "prediction_metadata.json"
    if hash_file(metadata_path) != completion.get("metadata_sha256"):
        raise SystemExit("Prediction metadata changed after completion")
    digest = hashlib.sha256()
    shards = sorted((path / "shards").glob("*.json"))
    for shard in shards:
        digest.update(shard.name.encode("utf-8"))
        digest.update(bytes.fromhex(hash_file(shard)))
    if len(shards) != int(completion.get("instances", -1)):
        raise SystemExit("Prediction shard count does not match completion receipt")
    if digest.hexdigest() != completion.get("combined_shards_sha256"):
        raise SystemExit("Prediction shards changed after completion")


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def method_summary(rows: list[dict]) -> dict:
    by_type: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_type[row["mutation_type"]].append(row)
    type_top5 = {key: mean(item["rank"] <= 5 for item in values) for key, values in by_type.items()}
    type_mrr = {key: mean(1.0 / item["rank"] for item in values) for key, values in by_type.items()}
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_regime[row["regime"]].append(row)
    return {
        "events": len(rows),
        "top1": mean(row["rank"] <= 1 for row in rows),
        "top3": mean(row["rank"] <= 3 for row in rows),
        "top5": mean(row["rank"] <= 5 for row in rows),
        "mrr": mean(1.0 / row["rank"] for row in rows),
        "exam": mean((row["rank"] - 1) / max(1, row["formula_count"]) for row in rows),
        "macro_top5": mean(type_top5.values()),
        "weakest_type_top5": min(type_top5.values(), default=0.0),
        "candidate_coverage_32": mean(row["candidate_covered"] for row in rows),
        "exact_repair": mean(row["exact_repair"] for row in rows),
        "median_localization_seconds": statistics.median(row["localization_seconds"] for row in rows),
        "by_type_top5": type_top5,
        "by_type_mrr": type_mrr,
        "by_regime_top5": {
            key: mean(item["rank"] <= 5 for item in values)
            for key, values in by_regime.items()
        },
    }


def bootstrap_difference(rows: list[dict], left: str, right: str, *, iterations: int = 10_000) -> dict:
    by_instance: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        by_instance[row["instance_id"]][row["method"]] = row
    paired = [values for values in by_instance.values() if left in values and right in values]
    rng = random.Random(20260827)
    mrr_values, top5_values = [], []
    for _ in range(iterations):
        sample = [paired[rng.randrange(len(paired))] for _ in range(len(paired))]
        mrr_values.append(mean(1 / item[left]["rank"] - 1 / item[right]["rank"] for item in sample))
        type_rows: dict[str, list[dict]] = defaultdict(list)
        for item in sample:
            type_rows[item[left]["mutation_type"]].append(item)
        left_macro = mean(mean(item[left]["rank"] <= 5 for item in values) for values in type_rows.values())
        right_macro = mean(mean(item[right]["rank"] <= 5 for item in values) for values in type_rows.values())
        top5_values.append(left_macro - right_macro)
    return {
        "left": left,
        "right": right,
        "pairs": len(paired),
        "mrr_difference": mean(1 / item[left]["rank"] - 1 / item[right]["rank"] for item in paired),
        "mrr_ci95": [percentile(mrr_values, 0.025), percentile(mrr_values, 0.975)],
        "macro_top5_ci95": [percentile(top5_values, 0.025), percentile(top5_values, 0.975)],
        "iterations": iterations,
        "seed": 20260827,
    }


def clean_summary(path: Path | None) -> dict:
    if path is None:
        return {}
    records = [json.loads(item.read_text(encoding="utf-8")) for item in sorted((path / "shards").glob("*.json"))]
    metadata = json.loads((path / "prediction_metadata.json").read_text(encoding="utf-8"))
    clean_manifest_path = Path(metadata["benchmark"]) / "clean_manifest.json"
    declared = {
        row["clean_id"]: row
        for row in json.loads(clean_manifest_path.read_text(encoding="utf-8"))
    }
    methods = sorted(set.intersection(*(set(record["rankings"]) for record in records))) if records else []
    result = {}
    for method in methods:
        alarms = []
        structures: dict[str, list[bool]] = defaultdict(list)
        declared_structures: dict[str, list[bool]] = defaultdict(list)
        for record in records:
            ranking = record["rankings"][method]
            if not ranking or not ranking[0].get("evidence"):
                continue
            alarm = ranking[0]["evidence"].get("alarm_status") == "alarm"
            alarms.append(alarm)
            structures[ranking[0]["evidence"].get("regime_type", "unknown")].append(alarm)
            declared_structures[declared[record["instance_id"]]["structure"]].append(alarm)
        if alarms:
            legitimate = [
                alarm
                for structure, values in declared_structures.items()
                if structure not in {"regular_row", "regular_column", "two_dimensional"}
                for alarm in values
            ]
            result[method] = {
                "instances": len(alarms),
                "false_alarm_rate": mean(alarms),
                "by_regime": {key: mean(values) for key, values in structures.items()},
                "by_declared_structure": {key: mean(values) for key, values in declared_structures.items()},
                "legitimate_exception_instances": len(legitimate),
                "legitimate_exception_false_alarm_rate": mean(legitimate),
            }
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--clean-predictions", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify_prediction_completion(args.predictions)
    if args.clean_predictions is not None:
        verify_prediction_completion(args.clean_predictions)
    metadata = json.loads((args.predictions / "prediction_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("label_files_read") != []:
        raise SystemExit("Prediction metadata does not prove label isolation")
    labels = {row["instance_id"]: row for row in read_jsonl(args.benchmark / "evaluation_labels.jsonl")}
    instances = {row["instance_id"]: row for row in read_jsonl(args.benchmark / "instances.jsonl")}
    rows = []
    for shard_path in sorted((args.predictions / "shards").glob("*.json")):
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        instance_id = shard["instance_id"]
        label = labels[instance_id]
        for method, ranking in shard["rankings"].items():
            source = next(item for item in ranking if item["cell"] == label["source_cell"])
            evidence = source.get("evidence", {})
            portfolio = evidence.get("candidate_portfolio", [])
            correct = normalized_formula(label["correct_formula"])
            covered = any(normalized_formula(item["formula"]) == correct for item in portfolio)
            exact = normalized_formula(source.get("candidate_formula", "")) == correct if source.get("candidate_formula") else False
            rows.append({
                "instance_id": instance_id,
                "method": method,
                "mutation_type": label["mutation_type"],
                "regime": instances[instance_id]["regime"],
                "topology": instances[instance_id]["topology_id"],
                "rank": int(source["rank"]),
                "formula_count": int(shard["formula_count"]),
                "localization_seconds": float(shard.get("method_seconds", {}).get(method, 0.0)),
                "candidate_covered": bool(covered),
                "exact_repair": bool(exact),
            })
    methods = sorted({row["method"] for row in rows})
    summary = {method: method_summary([row for row in rows if row["method"] == method]) for method in methods}
    comparisons = []
    for method in ("v5_rule", "v5_learned"):
        if method in methods and "v4" in methods:
            comparisons.append(bootstrap_difference(rows, method, "v4"))
    if "v5_rule" in methods and "v5_learned" in methods:
        comparisons.append(bootstrap_difference(rows, "v5_learned", "v5_rule"))
    payload = {
        "protocol": "v5_core_scoring_v1",
        "summary": summary,
        "clean": clean_summary(args.clean_predictions),
        "paired_bootstrap": comparisons,
        "labels_read_after_prediction_completion": True,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "event_results.csv").open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [])
        if rows:
            writer.writeheader(); writer.writerows(rows)
    print(args.output / "summary.json")


if __name__ == "__main__":
    main()
