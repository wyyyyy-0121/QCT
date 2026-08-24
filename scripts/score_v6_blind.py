"""Verify secret precommit and score the immutable 600-case V4/V6 lock."""

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
from scripts.verify_v6_freeze import verify


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, p):
    values = sorted(values); return values[int(p * (len(values) - 1))]


def bootstrap(values, draws=10000, seed=20260819):
    rng = random.Random(seed)
    estimates = [statistics.fmean(rng.choice(values) for _ in values) for _ in range(draws)]
    return [percentile(estimates, .025), percentile(estimates, .975)]


def macro_top5_bootstrap_difference(v6, v4, draws=10000, seed=20260819):
    by_type = defaultdict(list)
    for instance_id, row in v6.items():
        by_type[row["error_type"]].append((row["top5"], v4[instance_id]["top5"]))
    rng = random.Random(seed); estimates = []
    for _ in range(draws):
        estimates.append(statistics.fmean(
            statistics.fmean(a - b for a, b in (rng.choice(pairs) for _ in pairs))
            for pairs in by_type.values()
        ))
    return [percentile(estimates, .025), percentile(estimates, .975)]


def parse_commitments(path: Path):
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            digest, name = digest.lower(), name.strip()
            if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                raise SystemExit(f"Invalid SHA-256 commitment for {name}")
            result[name] = digest
    if set(result) != {"labels.csv", "exceptions.csv", "SECRET.zip"}:
        raise SystemExit("Precommit file must contain exactly labels.csv, exceptions.csv, and SECRET.zip")
    return result


def canonical_cell(text: str) -> str:
    sheet, address = text.rsplit("!", 1)
    return f"{sheet.strip(chr(39))}!{address.replace('$', '').upper()}"


def mean(values):
    return statistics.fmean(values) if values else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--locked", type=Path, default=Path("results/v6_independent_600_locked"))
    parser.add_argument("--public", type=Path, default=Path("data/v6_third_party_public"))
    parser.add_argument("--secret-zip", type=Path, default=Path(r"D:\FormulaGuard_V6_Blind_Labels\FormulaGuard_V6_SECRET_600.zip"))
    parser.add_argument("--output", type=Path, default=Path("results/v6_independent_600_scored"))
    args = parser.parse_args()
    config = verify()
    lock_path = args.locked / "prediction_lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
    if not lock.get("locked") or not lock.get("full_ranking_audit_passed"):
        raise SystemExit("Blind scoring refused: prediction lock missing")
    metadata_path = args.locked / "joint_prediction_metadata.json"
    if sha256(metadata_path) != lock["metadata_sha256"]:
        raise SystemExit("Blind scoring refused: metadata changed after lock")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if metadata.get("selected_variant") != config["selected_variant"]:
        raise SystemExit("Blind scoring refused: locked variant differs from frozen configuration")
    if metadata.get("frozen_config_sha256") != sha256(ROOT / "research/frozen_config_v6.json"):
        raise SystemExit("Blind scoring refused: frozen configuration changed")
    manifest_path = args.public / "manifest.csv"
    precommit_path = args.public / "secret_precommit_sha256.txt"
    if sha256(manifest_path) != metadata.get("manifest_sha256") or sha256(precommit_path) != metadata.get("precommit_sha256_file"):
        raise SystemExit("Blind scoring refused: public manifest or precommit changed after prediction lock")
    shard_paths = sorted((args.locked / "shards").glob("*.json"))
    combined = hashlib.sha256()
    for path in shard_paths:
        combined.update(path.name.encode()); combined.update(bytes.fromhex(sha256(path)))
    if len(shard_paths) != 600 or combined.hexdigest() != lock["combined_shards_sha256"]:
        raise SystemExit("Blind scoring refused: prediction shards changed")
    commitments = parse_commitments(args.public / "secret_precommit_sha256.txt")
    if sha256(args.secret_zip) != commitments["SECRET.zip"]:
        raise SystemExit("Blind scoring refused: SECRET.zip does not match precommit")
    with zipfile.ZipFile(args.secret_zip) as archive:
        labels_bytes = archive.read("labels.csv")
        exceptions_bytes = archive.read("exceptions.csv")
        design_bytes = archive.read("design_ledger.csv")
        design_gates = json.loads(archive.read("design_gates.json").decode("utf-8"))
    if hashlib.sha256(labels_bytes).hexdigest() != commitments["labels.csv"]:
        raise SystemExit("Blind scoring refused: labels.csv does not match precommit")
    if hashlib.sha256(exceptions_bytes).hexdigest() != commitments["exceptions.csv"]:
        raise SystemExit("Blind scoring refused: exceptions.csv does not match precommit")
    label_rows = list(csv.DictReader(io.StringIO(labels_bytes.decode("utf-8-sig"))))
    labels = {row["instance_id"]: row for row in label_rows}
    exception_rows = list(csv.DictReader(io.StringIO(exceptions_bytes.decode("utf-8-sig"))))
    design_rows = list(csv.DictReader(io.StringIO(design_bytes.decode("utf-8-sig"))))
    design_by_id = {row["instance_id"]: row for row in design_rows}
    if len(label_rows) != 600 or len(labels) != 600:
        raise SystemExit("Blind scoring refused: labels do not contain 600 unique cases")
    if len(design_rows) != 600 or {row["instance_id"] for row in design_rows} != set(labels):
        raise SystemExit("Blind scoring refused: design ledger does not match all 600 labels")
    if not design_gates.get("final") or not all(design_gates.get("gates", {}).values()):
        raise SystemExit("Blind scoring refused: third-party final design gates are absent or failed")
    if any(row.get("instance_id") not in labels for row in exception_rows):
        raise SystemExit("Blind scoring refused: exception ledger contains unknown instances")
    if set(path.stem for path in shard_paths) != set(labels):
        raise SystemExit("Blind scoring refused: labels and locked prediction IDs differ")
    type_counts = {error: sum(row.get("error_type") == error for row in label_rows) for error in (
        "reference_shift", "range_boundary", "operator", "function_replacement",
        "absolute_reference", "copy_offset",
    )}
    if any(count != 100 for count in type_counts.values()):
        raise SystemExit(f"Blind scoring refused: error types are not 100 each: {type_counts}")
    raw = []
    for path in shard_paths:
        record = json.loads(path.read_text(encoding="utf-8")); label = labels[record["instance_id"]]
        if set(record.get("rankings", {})) != {"v4", "v6"}:
            raise SystemExit(f"Blind scoring refused: incomplete methods in {path}")
        source = canonical_cell(label["source_cell"])
        for method, ranking in record["rankings"].items():
            source_row = next((row for row in ranking if canonical_cell(row["cell"]) == source), None)
            if source_row is None:
                raise SystemExit(f"Blind scoring refused: source absent from ranking {record['instance_id']} {method}")
            rank = source_row["rank"]
            candidate = source_row["candidate_formula"]
            correct_formula = normalized_formula(label["correct_formula"])
            candidate_formulas = source_row.get("evidence", {}).get("candidate_formulas", [])
            design_row = design_by_id[record["instance_id"]]
            formula_count = int(record["formula_count"])
            size_bucket = "small_lt_100" if formula_count < 100 else "medium_100_499" if formula_count < 500 else "large_ge_500"
            raw.append({
                "instance_id": record["instance_id"], "method": method, "error_type": label["error_type"],
                "topology": design_row["topology"], "complexity": design_row["complexity"],
                "depth": design_row["declared_depth"], "construction_mode": design_row["construction_mode"],
                "formula_count": formula_count, "size_bucket": size_bucket,
                "rank": rank, "top1": int(rank <= 1), "top3": int(rank <= 3), "top5": int(rank <= 5),
                "mrr": 1 / rank, "exam": rank / record["formula_count"],
                "repair_exact": int(bool(candidate) and normalized_formula(candidate) == correct_formula),
                "candidate_coverage_at_25": int(
                    method == "v6" and any(normalized_formula(item) == correct_formula for item in candidate_formulas)
                ) if method == "v6" else "",
            })
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "independent_600_events.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw[0])); writer.writeheader(); writer.writerows(raw)
    summary = {}; grouped_rows = {}
    for method in ("v4", "v6"):
        rows = [row for row in raw if row["method"] == method]
        by_error = {}
        for error in sorted({row["error_type"] for row in rows}):
            items = [row for row in rows if row["error_type"] == error]
            by_error[error] = {"events": len(items), "top5": statistics.fmean(row["top5"] for row in items), "mrr": statistics.fmean(row["mrr"] for row in items)}
        grouped_rows[method] = {row["instance_id"]: row for row in rows}
        summary[method] = {
            "events": len(rows), "top1": statistics.fmean(row["top1"] for row in rows),
            "top3": statistics.fmean(row["top3"] for row in rows), "top5": statistics.fmean(row["top5"] for row in rows),
            "top5_bootstrap_95_ci": bootstrap([row["top5"] for row in rows]),
            "macro_top5": statistics.fmean(item["top5"] for item in by_error.values()),
            "worst_type_top5": min(item["top5"] for item in by_error.values()),
            "mrr": statistics.fmean(row["mrr"] for row in rows), "exam": statistics.fmean(row["exam"] for row in rows),
            "repair_exact": statistics.fmean(row["repair_exact"] for row in rows),
            "candidate_coverage_at_25": mean([
                row["candidate_coverage_at_25"] for row in rows if row["candidate_coverage_at_25"] != ""
            ]),
            "by_error": by_error,
        }
    stratum_rows = []
    for method in ("v4", "v6"):
        method_rows = [row for row in raw if row["method"] == method]
        for field in ("error_type", "topology", "complexity", "depth", "construction_mode", "size_bucket"):
            for value in sorted({row[field] for row in method_rows}):
                items = [row for row in method_rows if row[field] == value]
                stratum_rows.append({
                    "method": method, "stratum": field, "value": value, "events": len(items),
                    "top1": mean([row["top1"] for row in items]),
                    "top5": mean([row["top5"] for row in items]),
                    "mrr": mean([row["mrr"] for row in items]),
                    "repair_exact": mean([row["repair_exact"] for row in items]),
                })
    with (args.output / "independent_600_by_stratum.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(stratum_rows[0]))
        writer.writeheader(); writer.writerows(stratum_rows)
    ids = sorted(labels)
    mrr_diff = [grouped_rows["v6"][item]["mrr"] - grouped_rows["v4"][item]["mrr"] for item in ids]
    top5_diff = [grouped_rows["v6"][item]["top5"] - grouped_rows["v4"][item]["top5"] for item in ids]
    macro_ci = macro_top5_bootstrap_difference(grouped_rows["v6"], grouped_rows["v4"])
    paired = {"mrr_difference": statistics.fmean(mrr_diff), "mrr_bootstrap_95_ci": bootstrap(mrr_diff), "top5_difference": statistics.fmean(top5_diff), "top5_bootstrap_95_ci": bootstrap(top5_diff), "macro_top5_bootstrap_95_ci": macro_ci}
    v6 = summary["v6"]
    clean_rate = config.get("selected_clean_false_alarm_rate")
    strong_gates = {
        "overall_top5_at_least_75_percent": v6["top5"] >= .75,
        "top5_ci_lower_at_least_70_percent": v6["top5_bootstrap_95_ci"][0] >= .70,
        "macro_top5_at_least_75_percent": v6["macro_top5"] >= .75,
        "worst_type_top5_at_least_60_percent": v6["worst_type_top5"] >= .60,
        "mrr_at_least_0_55": v6["mrr"] >= .55,
        "repair_at_least_70_percent": v6["repair_exact"] >= .70,
        "clean_false_alarm_at_most_10_percent": clean_rate is not None and clean_rate <= .10,
        "mrr_improvement_ci_excludes_zero": paired["mrr_bootstrap_95_ci"][0] > 0,
        "macro_top5_improvement_ci_excludes_zero": paired["macro_top5_bootstrap_95_ci"][0] > 0,
    }
    payload = {
        "protocol": "v6_third_party_600_scored_after_hash_lock", "events": 600,
        "summary": summary, "paired_v6_minus_v4": paired, "clean_false_alarm_rate": clean_rate, "strong_claim_gates": strong_gates,
        "strong_claim_allowed": all(strong_gates.values()), "post_result_tuning_forbidden": True,
        "labels_sha256": commitments["labels.csv"], "secret_archive_sha256": commitments["SECRET.zip"],
        "design_ledger_sha256": hashlib.sha256(design_bytes).hexdigest(),
        "exceptions_recorded": len(exception_rows),
        "all_600_retained": len(raw) == 1200,
    }
    (args.output / "independent_600_summary.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output / "independent_600_summary.json")


if __name__ == "__main__":
    main()
