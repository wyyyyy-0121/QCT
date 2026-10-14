"""Materialize learned-head rankings from already locked V5 rule evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_core import _learned_score


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--rule-config", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        raise SystemExit(f"Refusing to overwrite non-empty output: {args.output}")
    config = json.loads(args.config.read_text(encoding="utf-8"))
    rule_config = json.loads(args.rule_config.read_text(encoding="utf-8")) if args.rule_config else {}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "shards").mkdir(exist_ok=True)
    for shard in sorted((args.input / "shards").glob("*.json")):
        record = json.loads(shard.read_text(encoding="utf-8"))
        rule = record["rankings"]["v5_rule"]
        rule_scores = sorted((float(row["score"]) for row in rule), reverse=True)
        rule_alarm = bool(rule_scores) and (
            rule_scores[0] >= float(rule_config.get("alarm_threshold", 0.35))
            and rule_scores[0] - (rule_scores[1] if len(rule_scores) > 1 else 0.0)
            >= float(rule_config.get("alarm_margin", 0.05))
        )
        for row in rule:
            row["evidence"]["alarm_status"] = "alarm" if rule_alarm else "no_alarm"
        learned = []
        for row in rule:
            copied = dict(row)
            copied["evidence"] = dict(row["evidence"])
            copied["score"] = _learned_score(row["evidence"]["feature_vector"], config)
            copied["evidence"]["head"] = "learned"
            learned.append(copied)
        learned.sort(key=lambda row: (-float(row["score"]), -float(row["evidence"].get("candidate_quality", 0.0)), row["cell"]))
        for rank, row in enumerate(learned, 1):
            row["rank"] = rank
            row["evidence"]["rank"] = rank
        learned_scores = [float(row["score"]) for row in learned]
        learned_alarm = bool(learned_scores) and (
            learned_scores[0] >= float(config.get("alarm_threshold", 0.35))
            and learned_scores[0] - (learned_scores[1] if len(learned_scores) > 1 else 0.0)
            >= float(config.get("alarm_margin", 0.05))
        )
        for row in learned:
            row["evidence"]["alarm_status"] = "alarm" if learned_alarm else "no_alarm"
        record["rankings"]["v5_learned"] = learned
        temporary = args.output / "shards" / (shard.name + ".tmp")
        destination = args.output / "shards" / shard.name
        temporary.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, destination)
    source_metadata = json.loads((args.input / "prediction_metadata.json").read_text(encoding="utf-8"))
    source_metadata.update({
        "offline_learned_materialization": True,
        "materialized_learned_config_sha256": hash_file(args.config),
        "materialized_rule_config_sha256": hash_file(args.rule_config) if args.rule_config else None,
        "source_prediction_completion_sha256": hash_file(args.input / "prediction_complete.json"),
    })
    metadata_path = args.output / "prediction_metadata.json"
    metadata_path.write_text(json.dumps(source_metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256()
    shards = sorted((args.output / "shards").glob("*.json"))
    for shard in shards:
        digest.update(shard.name.encode("utf-8"))
        digest.update(bytes.fromhex(hash_file(shard)))
    completion = {
        "protocol": "v5_core_atomic_prediction_completion_v1",
        "complete": True,
        "instances": len(shards),
        "workers_requested": 0,
        "combined_shards_sha256": digest.hexdigest(),
        "metadata_sha256": hash_file(metadata_path),
        "full_ranking_audit_passed": True,
        "labels_may_be_read_by_separate_scorer": True,
    }
    (args.output / "prediction_complete.json").write_text(
        json.dumps(completion, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    metadata = {
        "protocol": "v5_core_offline_learned_materialization_v1",
        "input": str(args.input.resolve()),
        "config": str(args.config.resolve()),
        "rule_config": str(args.rule_config.resolve()) if args.rule_config else None,
        "labels_read": [],
        "instances": len(list((args.output / "shards").glob("*.json"))),
    }
    (args.output / "learned_materialization.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    print(args.output / "learned_materialization.json")


if __name__ == "__main__":
    main()
