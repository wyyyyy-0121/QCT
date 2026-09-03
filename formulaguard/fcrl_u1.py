"""Shared metrics and fail-closed contracts for the frozen FCRL U1 gate."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

U1_TOP5_MINIMUM = 0.50
U1_TOP1_MINIMUM = 0.25
U1_GLOBAL_GAIN_MINIMUM = 0.10
U1_LOCAL_GAIN_MINIMUM = 0.05
U1_REACHABILITY_MINIMUM = 0.70


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("ascii")).hexdigest()


def prediction_metrics(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not rows:
        raise ValueError("cannot score an empty FCRL split")
    methods = ("model_top1", "model_top5", "global_top5", "local_peer_top5")
    group_values: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    workbook_values: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    micro: Counter[str] = Counter()
    for row in rows:
        group = str(row["structure_group"])
        workbook = str(row["workbook_id"])
        for method in methods:
            hit = int(bool(row[method]))
            group_values[group][method].append(hit)
            workbook_values[workbook][method].append(hit)
            micro[method] += hit

    def macro(values: Mapping[str, Mapping[str, Sequence[int]]], method: str) -> float:
        per_unit = [sum(unit[method]) / len(unit[method]) for unit in values.values()]
        return sum(per_unit) / len(per_unit)

    target_count = len(rows)
    return {
        "targets": target_count,
        "workbooks": len(workbook_values),
        "structure_groups": len(group_values),
        "structure_group_macro": {
            method: macro(group_values, method) for method in methods
        },
        "workbook_macro": {
            method: macro(workbook_values, method) for method in methods
        },
        "target_micro": {
            method: micro[method] / target_count for method in methods
        },
    }


def prediction_content(rows: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for row in rows:
        target_id = str(row.get("target_id", ""))
        predictions = row.get("predictions")
        if not target_id or target_id in seen:
            raise ValueError("FCRL predictions contain an empty or duplicate target ID")
        if not isinstance(predictions, list) or len(predictions) > 5:
            raise ValueError("FCRL prediction list is invalid")
        if any(not isinstance(value, str) or not value for value in predictions):
            raise ValueError("FCRL prediction keys must be nonempty strings")
        if len(predictions) != len(set(predictions)):
            raise ValueError("FCRL prediction list contains duplicate keys")
        seen.add(target_id)
        normalized.append({"target_id": target_id, "predictions": predictions})
    return sorted(normalized, key=lambda row: str(row["target_id"]))


def score_u1_predictions(
    targets: Sequence[Mapping[str, object]],
    global_top5: Sequence[str],
    predictions: Sequence[Mapping[str, object]],
    *,
    repeated_prediction_hash_match: bool,
    expected_structure_groups: int = 33,
) -> dict[str, object]:
    internal = [target for target in targets if target.get("split") == "internal_test"]
    if not internal:
        raise ValueError("FCRL target manifest has no internal-test targets")
    target_by_id = {str(target["target_id"]): target for target in internal}
    if len(target_by_id) != len(internal):
        raise ValueError("FCRL internal-test target IDs are not unique")
    content = prediction_content(predictions)
    if {str(row["target_id"]) for row in content} != set(target_by_id):
        raise ValueError("FCRL predictions do not cover the exact internal-test target set")
    if len({str(target["structure_group"]) for target in internal}) != expected_structure_groups:
        raise ValueError("FCRL internal-test structure-group count changed")
    if len(global_top5) > 5 or any(not isinstance(value, str) for value in global_top5):
        raise ValueError("FCRL global-frequency baseline is invalid")

    rows: list[dict[str, object]] = []
    for prediction in content:
        target = target_by_id[str(prediction["target_id"])]
        predicted = list(prediction["predictions"])
        gold = str(target["gold_key"])
        local = target.get("local_peer_top5")
        if not isinstance(local, list) or len(local) > 5:
            raise ValueError("FCRL local-peer baseline is invalid")
        rows.append(
            {
                "target_id": prediction["target_id"],
                "workbook_id": target["workbook_id"],
                "structure_group": target["structure_group"],
                "model_top1": bool(predicted and predicted[0] == gold),
                "model_top5": gold in predicted,
                "global_top5": gold in global_top5,
                "local_peer_top5": gold in local,
            }
        )
    metrics = prediction_metrics(rows)
    macro = metrics["structure_group_macro"]
    model_top1 = float(macro["model_top1"])
    model_top5 = float(macro["model_top5"])
    global_gain = model_top5 - float(macro["global_top5"])
    local_gain = model_top5 - float(macro["local_peer_top5"])
    reachable = sum(int(target["reachable_references"]) for target in internal)
    total = sum(int(target["total_references"]) for target in internal)
    if total <= 0 or reachable < 0 or reachable > total:
        raise ValueError("FCRL internal-test reference counts are invalid")
    reachability = reachable / total
    gates = {
        "top5_at_least_50_percent": model_top5 >= U1_TOP5_MINIMUM,
        "top1_at_least_25_percent": model_top1 >= U1_TOP1_MINIMUM,
        "top5_global_gain_at_least_10pp": global_gain >= U1_GLOBAL_GAIN_MINIMUM,
        "top5_local_peer_gain_at_least_5pp": local_gain >= U1_LOCAL_GAIN_MINIMUM,
        "reference_reachability_at_least_70_percent": (
            reachability >= U1_REACHABILITY_MINIMUM
        ),
        "independent_prediction_hashes_identical": repeated_prediction_hash_match,
    }
    return {
        "metrics": metrics,
        "global_top5_gain": global_gain,
        "local_peer_top5_gain": local_gain,
        "reference_reachability": {
            "reachable": reachable,
            "total": total,
            "fraction": reachability,
        },
        "gates": gates,
        "passed": all(gates.values()),
        "prediction_sha256": stable_hash(content),
    }
