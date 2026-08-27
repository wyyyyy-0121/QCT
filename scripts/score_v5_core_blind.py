"""Verify the precommitted secret pack and score locked V5-Core predictions."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_locked_predictions(locked: Path, lock: dict) -> None:
    completion_path = locked / "predictions/prediction_complete.json"
    if sha256(completion_path) != lock.get("prediction_completion_sha256"):
        raise SystemExit("Prediction completion receipt changed after blind lock")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    metadata_path = locked / "predictions/prediction_metadata.json"
    if sha256(metadata_path) != completion.get("metadata_sha256"):
        raise SystemExit("Prediction metadata changed after completion")
    digest = hashlib.sha256()
    shards = sorted((locked / "predictions/shards").glob("*.json"))
    for shard in shards:
        digest.update(shard.name.encode("utf-8"))
        digest.update(bytes.fromhex(sha256(shard)))
    if len(shards) != 600 or digest.hexdigest() != completion.get("combined_shards_sha256"):
        raise SystemExit("Locked prediction shards changed or are incomplete")


def parse_precommit(path: Path) -> dict[str, str]:
    return dict(
        line.strip().split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def percentile(values, p):
    ordered = sorted(values); position = p * (len(ordered) - 1)
    lower = int(position); upper = min(len(ordered) - 1, lower + 1); fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--secret-zip", type=Path, default=Path(r"D:\FormulaGuard_V5_ThirdParty\FormulaGuard_V5_SECRET_600.zip"))
    parser.add_argument("--public-root", type=Path, default=Path("data/v5_core_blind/public"))
    parser.add_argument("--locked", type=Path, default=Path("results/v5_core_blind_locked"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_blind_score"))
    args = parser.parse_args()
    if not (args.locked / "prediction_lock.json").exists():
        raise SystemExit("Scoring refused: prediction lock is missing")
    lock = json.loads((args.locked / "prediction_lock.json").read_text(encoding="utf-8"))
    verify_locked_predictions(args.locked, lock)
    if sha256(args.public_root / "secret_precommit_sha256.txt") != lock.get("precommit_text_sha256"):
        raise SystemExit("Secret precommit text changed after prediction lock")
    precommit = parse_precommit(args.public_root / "secret_precommit_sha256.txt")
    if sha256(args.secret_zip) != precommit["secret_zip_sha256"]:
        raise SystemExit("Secret archive does not match the precommitted hash")
    with zipfile.ZipFile(args.secret_zip) as archive:
        labels_bytes = archive.read("labels.csv")
        if hashlib.sha256(labels_bytes).hexdigest() != precommit["labels_csv_sha256"]:
            raise SystemExit("labels.csv does not match the precommitted hash")
        labels = list(csv.DictReader(io.StringIO(labels_bytes.decode("utf-8-sig"))))
    if len(labels) != 600:
        raise SystemExit("Secret pack must contain all 600 labels")
    label_by_id = {row["instance_id"]: row for row in labels}
    raw = []
    for shard_path in sorted((args.locked / "predictions/shards").glob("*.json")):
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        label = label_by_id[shard["instance_id"]]
        for method, ranking in shard["rankings"].items():
            source = next(row for row in ranking if row["cell"] == label["source_cell"])
            raw.append({
                "instance_id": shard["instance_id"], "method": method,
                "mutation_type": label["mutation_type"], "rank": source["rank"],
                "formula_count": shard["formula_count"],
                "top5": int(source["rank"] <= 5), "mrr": 1 / source["rank"],
                "exam": (source["rank"] - 1) / max(1, shard["formula_count"]),
                "exact_repair": int(
                    bool(source.get("candidate_formula"))
                    and normalized_formula(source["candidate_formula"]) == normalized_formula(label["correct_formula"])
                ),
            })
    if len({row["instance_id"] for row in raw}) != 600:
        raise SystemExit("Locked prediction set is incomplete")
    summary = {}
    for method in sorted({row["method"] for row in raw}):
        rows = [row for row in raw if row["method"] == method]
        by_type = defaultdict(list)
        for row in rows: by_type[row["mutation_type"]].append(row)
        type_top5 = {key: mean(item["top5"] for item in values) for key, values in by_type.items()}
        summary[method] = {
            "events": len(rows), "top1": mean(row["rank"] <= 1 for row in rows),
            "top3": mean(row["rank"] <= 3 for row in rows), "top5": mean(row["top5"] for row in rows),
            "mrr": mean(row["mrr"] for row in rows), "exam": mean(row["exam"] for row in rows),
            "exact_repair": mean(row["exact_repair"] for row in rows),
            "macro_top5": mean(type_top5.values()), "weakest_type_top5": min(type_top5.values()),
            "by_type_top5": type_top5,
        }
    comparisons = {}
    rng = random.Random(20260827)
    by_instance = defaultdict(dict)
    for row in raw: by_instance[row["instance_id"]][row["method"]] = row
    for method in ("v5_rule", "v5_learned"):
        values = []
        events = list(by_instance.values())
        for _ in range(10_000):
            sample = [events[rng.randrange(len(events))] for _ in events]
            values.append(mean(item[method]["mrr"] - item["v4"]["mrr"] for item in sample))
        comparisons[f"{method}_minus_v4_mrr"] = {
            "point": mean(item[method]["mrr"] - item["v4"]["mrr"] for item in events),
            "ci95": [percentile(values, 0.025), percentile(values, 0.975)],
        }
    payload = {
        "protocol": "v5_core_third_party_blind_score_v1",
        "summary": summary, "comparisons": comparisons,
        "secret_precommit_verified": True,
        "no_post_blind_tuning_allowed": True,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "blind_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (args.output / "blind_raw.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0])); writer.writeheader(); writer.writerows(raw)
    print(args.output / "blind_summary.json")


if __name__ == "__main__":
    main()
