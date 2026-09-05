"""Verify the precommitted secret archive and score locked R2 confirmation predictions."""

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
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula
from formulaguard.v5_core import build_candidate_portfolio, discover_formula_regimes
from formulaguard.workbook import WorkbookModel

ERROR_STRATA = {
    "traditional": 420,
    "withheld_mutation": 90,
    "candidate_absent": 60,
    "unsupported_ambiguous": 30,
}
TRADITIONAL_TYPES = {
    "range_boundary", "operator", "function_replacement",
    "copy_offset", "absolute_reference", "reference_shift",
}
CLEAN_STRUCTURES = {"regular", "legal_exception", "periodic_2d", "cross_sheet"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_commitments(path: Path) -> dict[str, str]:
    return dict(
        line.strip().split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )


def read_csv_bytes(value: bytes) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(value.decode("utf-8-sig"))))


def normalize_cell(value: str) -> str:
    if "!" not in value:
        return value.replace("$", "").upper()
    sheet, address = value.rsplit("!", 1)
    return f"{sheet.strip(chr(39))}!{address.replace('$', '').upper()}"


def parse_sources(value: str) -> set[str]:
    return {normalize_cell(item.strip()) for item in value.split(";") if item.strip()}


def mean(values) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(len(ordered) - 1, lower + 1)
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def verify_predictions(locked: Path, lock: dict) -> list[Path]:
    completion_path = locked / "predictions/prediction_complete.json"
    if sha256(completion_path) != lock.get("prediction_completion_sha256"):
        raise SystemExit("Scoring refused: prediction completion receipt changed after lock")
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    metadata_path = locked / "predictions/prediction_metadata.json"
    if sha256(metadata_path) != completion.get("metadata_sha256"):
        raise SystemExit("Scoring refused: prediction metadata changed after lock")
    shards = sorted((locked / "predictions/shards").glob("*.json"))
    digest = hashlib.sha256()
    for shard in shards:
        digest.update(shard.name.encode("utf-8"))
        digest.update(bytes.fromhex(sha256(shard)))
    if len(shards) != 780 or digest.hexdigest() != lock.get("prediction_shards_sha256"):
        raise SystemExit("Scoring refused: prediction shards changed or are incomplete")
    return shards


def bootstrap_comparison(
    by_instance: dict[str, dict[str, dict]],
    method: str,
    baseline: str,
    *,
    iterations: int = 10_000,
) -> dict:
    rng = random.Random(20260827)
    events = list(by_instance.values())
    mrr_values: list[float] = []
    macro_values: list[float] = []
    for _ in range(iterations):
        sample = [events[rng.randrange(len(events))] for _ in events]
        mrr_values.append(mean(item[method]["mrr"] - item[baseline]["mrr"] for item in sample))
        grouped: dict[str, list[dict]] = defaultdict(list)
        for item in sample:
            grouped[item[method]["analysis_stratum"]].append(item)
        macro_values.append(mean(
            mean(item[method]["top5"] - item[baseline]["top5"] for item in values)
            for values in grouped.values()
        ))
    grouped_point: dict[str, list[dict]] = defaultdict(list)
    for item in events:
        grouped_point[item[method]["analysis_stratum"]].append(item)
    return {
        "mrr_point": mean(item[method]["mrr"] - item[baseline]["mrr"] for item in events),
        "mrr_ci95": [percentile(mrr_values, 0.025), percentile(mrr_values, 0.975)],
        "macro_top5_point": mean(
            mean(item[method]["top5"] - item[baseline]["top5"] for item in values)
            for values in grouped_point.values()
        ),
        "macro_top5_ci95": [percentile(macro_values, 0.025), percentile(macro_values, 0.975)],
        "iterations": iterations,
        "seed": 20260827,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--secret-zip", type=Path,
        default=Path(r"D:\FormulaGuard_R2_ThirdParty\FormulaGuard_R2_SECRET_780.zip"),
    )
    parser.add_argument("--frozen-config", type=Path, default=Path("research/frozen_config_v5_core_r2.json"))
    parser.add_argument("--public-root", type=Path, default=Path("data/v5_core_r2_confirmation/public"))
    parser.add_argument("--locked", type=Path, default=Path("results/v5_core_r2_confirmation_locked"))
    parser.add_argument("--output", type=Path, default=Path("results/v5_core_r2_confirmation_scored"))
    args = parser.parse_args()
    lock_path = args.locked / "prediction_lock.json"
    if not lock_path.is_file():
        raise SystemExit("Scoring refused: R2 confirmation prediction lock is missing")
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if sha256(args.frozen_config) != lock.get("frozen_config_sha256"):
        raise SystemExit("Scoring refused: frozen R2 configuration changed after lock")
    frozen = json.loads(args.frozen_config.read_text(encoding="utf-8"))
    for relative, expected in frozen.get("source_sha256", {}).items():
        if sha256(ROOT / relative) != expected:
            raise SystemExit(f"Scoring refused: frozen source changed: {relative}")
    shards = verify_predictions(args.locked, lock)
    commitment_path = args.public_root / "secret_precommit_sha256.txt"
    if sha256(commitment_path) != lock.get("precommit_text_sha256"):
        raise SystemExit("Scoring refused: public secret commitment changed after prediction lock")
    commitments = parse_commitments(commitment_path)
    if sha256(args.secret_zip) != commitments.get("secret_zip_sha256"):
        raise SystemExit("SECRET.zip differs from the precommitted hash")

    with zipfile.ZipFile(args.secret_zip) as archive:
        names = {item.filename for item in archive.infolist() if not item.is_dir()}
        if any("\\" in name or ".." in PurePosixPath(name).parts for name in names):
            raise SystemExit("SECRET.zip contains unsafe member names")
        required = {
            "labels.csv", "exceptions.csv", "design_ledger.csv", "provenance.csv",
            "third_party_declaration.json",
        }
        if not required <= names:
            raise SystemExit(f"SECRET.zip lacks required files: {sorted(required-names)}")
        content = {name: archive.read(name) for name in required}
    hash_keys = {
        "labels.csv": "labels_csv_sha256",
        "exceptions.csv": "exceptions_csv_sha256",
        "design_ledger.csv": "design_ledger_csv_sha256",
        "provenance.csv": "provenance_csv_sha256",
        "third_party_declaration.json": "declaration_json_sha256",
    }
    for name, key in hash_keys.items():
        if hash_bytes(content[name]) != commitments.get(key):
            raise SystemExit(f"{name} differs from the precommitted hash")
    declaration = json.loads(content["third_party_declaration.json"].decode("utf-8"))
    required_declarations = (
        "prepared_by_independent_person", "project_model_results_not_seen",
        "templates_unseen_by_project", "all_valid_cases_retained",
        "secret_labels_withheld", "development_overlap_checked",
    )
    if any(declaration.get(key) is not True for key in required_declarations):
        raise SystemExit("Independent-preparer declarations are incomplete or false")
    if not str(declaration.get("preparer_role", "")).strip():
        raise SystemExit("Independent-preparer role is missing")
    labels = read_csv_bytes(content["labels.csv"])
    ledger = read_csv_bytes(content["design_ledger.csv"])
    provenance = read_csv_bytes(content["provenance.csv"])
    if len(labels) != 780 or len({row.get("instance_id") for row in labels}) != 780:
        raise SystemExit("labels.csv must contain 780 unique instance_id rows")
    label_ids = {row["instance_id"] for row in labels}
    locked_ids = {json.loads(path.read_text(encoding="utf-8"))["instance_id"] for path in shards}
    if label_ids != locked_ids:
        raise SystemExit("Secret labels and locked public identifiers differ")
    kind_counts = Counter(row.get("case_kind") for row in labels)
    if kind_counts != Counter({"error": 600, "clean": 180}):
        raise SystemExit(f"Expected 600 errors and 180 clean controls: {dict(kind_counts)}")
    errors = [row for row in labels if row["case_kind"] == "error"]
    clean = [row for row in labels if row["case_kind"] == "clean"]
    stratum_counts = Counter(row.get("challenge_stratum") for row in errors)
    if stratum_counts != Counter(ERROR_STRATA):
        raise SystemExit(f"Error challenge strata differ from protocol: {dict(stratum_counts)}")
    traditional = [row for row in errors if row["challenge_stratum"] == "traditional"]
    type_counts = Counter(row.get("error_type") for row in traditional)
    if set(type_counts) != TRADITIONAL_TYPES or set(type_counts.values()) != {70}:
        raise SystemExit(f"Traditional error types must be six groups of 70: {dict(type_counts)}")
    clean_counts = Counter(row.get("clean_structure") for row in clean)
    if set(clean_counts) != CLEAN_STRUCTURES or set(clean_counts.values()) != {45}:
        raise SystemExit(f"Clean controls must be four groups of 45: {dict(clean_counts)}")
    if any(not parse_sources(row.get("source_cells", "")) for row in errors):
        raise SystemExit("Every error event requires at least one source cell")
    if any(row.get("source_cells", "").strip() for row in clean):
        raise SystemExit("Clean controls must not contain source-cell labels")

    for name, rows in (("design_ledger", ledger), ("provenance", provenance)):
        ids = [row.get("instance_id") for row in rows]
        if len(rows) != 780 or set(ids) != label_ids or len(set(ids)) != 780:
            raise SystemExit(f"{name}.csv must cover every public identifier exactly once")
    if any(
        not row.get("license_or_permission", "").strip()
        or row.get("anonymized", "").lower() not in {"1", "true", "yes"}
        for row in provenance
    ):
        raise SystemExit("Provenance lacks permission or anonymization confirmation")
    ledger_by_id = {row["instance_id"]: row for row in ledger}
    real_count = sum(row.get("real_structure", "").lower() in {"1", "true", "yes"} for row in ledger)
    manual_error_count = sum(
        ledger_by_id[row["instance_id"]].get("construction_mode", "").lower()
        in {"manual", "semi_manual", "semimanual"}
        for row in errors
    )
    if real_count < 150 or manual_error_count < 120:
        raise SystemExit(
            f"Design ledger misses authenticity floors: real={real_count}, manual_error={manual_error_count}"
        )

    label_by_id = {row["instance_id"]: row for row in labels}
    shard_by_id = {}
    for path in shards:
        record = json.loads(path.read_text(encoding="utf-8"))
        shard_by_id[record["instance_id"]] = record
    candidate_absent_checks = []
    for label in errors:
        if label["challenge_stratum"] != "candidate_absent":
            continue
        sources = parse_sources(label["source_cells"])
        correct = label.get("correct_formula", "")
        if len(sources) != 1 or not correct:
            candidate_absent_checks.append(False)
            continue
        shard = shard_by_id[label["instance_id"]]
        workbook = args.public_root / shard["workbook"]
        if not workbook.is_file() or sha256(workbook) != shard.get("workbook_sha256"):
            raise SystemExit(
                f"Public workbook changed after prediction lock: {shard['workbook']}"
            )
        model = WorkbookModel.from_xlsx(workbook)
        source_label = next(iter(sources))
        source_sheet, source_address = source_label.rsplit("!", 1)
        source = (source_sheet, source_address)
        if source not in model.formulas:
            candidate_absent_checks.append(False)
            continue
        try:
            regimes = discover_formula_regimes(model)
            portfolio = build_candidate_portfolio(
                model, source, candidate_limit=24, regime=regimes.get(source),
            )
            correct_key = normalized_formula(correct)
            candidate_absent_checks.append(all(
                normalized_formula(candidate.formula) != correct_key for candidate in portfolio
            ))
        except Exception:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
            candidate_absent_checks.append(False)
    candidate_absent_verified_rate = mean(candidate_absent_checks)
    raw_error: list[dict] = []
    raw_clean: list[dict] = []
    for shard_path in shards:
        shard = json.loads(shard_path.read_text(encoding="utf-8"))
        label = label_by_id[shard["instance_id"]]
        for method, ranking in shard["rankings"].items():
            status = str(ranking[0].get("evidence", {}).get("diagnostic_status", "")) if ranking else "unsupported_coverage"
            if label["case_kind"] == "clean":
                raw_clean.append({
                    "instance_id": shard["instance_id"], "method": method,
                    "clean_structure": label["clean_structure"], "diagnostic_status": status,
                    "alarm": int(method.startswith("r2_") and status in {"localized", "review"}),
                    "formula_count": shard["formula_count"],
                    "real_structure": int(
                        ledger_by_id[shard["instance_id"]].get("real_structure", "").lower()
                        in {"1", "true", "yes"}
                    ),
                })
                continue
            sources = parse_sources(label["source_cells"])
            source_rows = [item for item in ranking if normalize_cell(str(item["cell"])) in sources]
            if not source_rows:
                raise SystemExit(f"No labeled source formula in locked ranking: {shard['instance_id']} {method}")
            source = min(source_rows, key=lambda item: int(item["rank"]))
            analysis_stratum = (
                label.get("error_type", "")
                if label["challenge_stratum"] == "traditional"
                else label["challenge_stratum"]
            )
            rank = int(source["rank"])
            raw_error.append({
                "instance_id": shard["instance_id"], "method": method,
                "challenge_stratum": label["challenge_stratum"],
                "error_type": label.get("error_type", ""),
                "analysis_stratum": analysis_stratum,
                "rank": rank, "top1": int(rank == 1), "top3": int(rank <= 3),
                "top5": int(rank <= 5), "mrr": 1 / rank,
                "exam": (rank - 1) / max(1, int(shard["formula_count"])),
                "diagnostic_status": status,
                "alarm": int(method.startswith("r2_") and status in {"localized", "review"}),
                "real_structure": int(
                    ledger_by_id[shard["instance_id"]].get("real_structure", "").lower()
                    in {"1", "true", "yes"}
                ),
            })

    error_summary: dict[str, dict] = {}
    for method in sorted({row["method"] for row in raw_error}):
        rows = [row for row in raw_error if row["method"] == method]
        grouped: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            grouped[row["analysis_stratum"]].append(row)
        error_summary[method] = {
            "events": len(rows), "top1": mean(row["top1"] for row in rows),
            "top3": mean(row["top3"] for row in rows), "top5": mean(row["top5"] for row in rows),
            "mrr": mean(row["mrr"] for row in rows), "exam": mean(row["exam"] for row in rows),
            "macro_top5": mean(mean(row["top5"] for row in values) for values in grouped.values()),
            "weakest_stratum_top5": min(mean(row["top5"] for row in values) for values in grouped.values()),
            "by_stratum": {
                key: {"events": len(values), "top5": mean(row["top5"] for row in values),
                      "mrr": mean(row["mrr"] for row in values)}
                for key, values in sorted(grouped.items())
            },
        }
    clean_summary: dict[str, dict] = {}
    for method in ("r2_source", "r2_full"):
        rows = [row for row in raw_clean if row["method"] == method]
        clean_summary[method] = {
            "events": len(rows),
            "false_alarm_rate": mean(row["alarm"] for row in rows),
            "status_counts": dict(Counter(row["diagnostic_status"] for row in rows)),
            "by_structure_fpr": {
                structure: mean(row["alarm"] for row in rows if row["clean_structure"] == structure)
                for structure in sorted(CLEAN_STRUCTURES)
            },
        }
    by_instance: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in raw_error:
        by_instance[row["instance_id"]][row["method"]] = row
    comparisons = {
        f"{method}_minus_{baseline}": bootstrap_comparison(by_instance, method, baseline)
        for method in ("r2_source", "r2_full")
        for baseline in ("v4", "v4_3")
    }
    candidate_absent = {
        method: [row for row in raw_error if row["method"] == method and row["challenge_stratum"] == "candidate_absent"]
        for method in ("v4", "r2_source")
    }
    localized = [row for row in raw_error if row["method"] == "r2_full" and row["diagnostic_status"] == "localized"]
    all_r2 = [row for row in raw_error if row["method"] == "r2_full"]
    selective = {
        "localized_coverage": len(localized) / len(all_r2),
        "localized_wrong_top1_risk": mean(1 - row["top1"] for row in localized),
        "forced_top1_wrong_risk": mean(1 - row["top1"] for row in all_r2),
    }
    real = {
        method: [row for row in raw_error if row["method"] == method and row["real_structure"]]
        for method in ("v4", "r2_full")
    }
    benefit_strata = sum(
        error_summary["r2_full"]["by_stratum"][name]["mrr"]
        > error_summary["v4"]["by_stratum"][name]["mrr"]
        for name in error_summary["r2_full"]["by_stratum"]
    )
    gates = {
        "r2_full_mrr_superior_to_v4": comparisons["r2_full_minus_v4"]["mrr_ci95"][0] > 0,
        "r2_full_mrr_superior_to_v4_3": comparisons["r2_full_minus_v4_3"]["mrr_ci95"][0] > 0,
        "r2_full_macro_top5_superior_to_v4": comparisons["r2_full_minus_v4"]["macro_top5_ci95"][0] > 0,
        "r2_full_macro_top5_superior_to_v4_3": comparisons["r2_full_minus_v4_3"]["macro_top5_ci95"][0] > 0,
        "candidate_absent_source_top5_not_below_v4_by_0_05": (
            mean(row["top5"] for row in candidate_absent["r2_source"]) + 0.05
            >= mean(row["top5"] for row in candidate_absent["v4"])
        ),
        "candidate_absent_design_verified": candidate_absent_verified_rate == 1.0,
        "clean_false_alarm_at_most_0_10": clean_summary["r2_full"]["false_alarm_rate"] <= 0.10,
        "selective_localization_coverage_at_least_0_10": selective["localized_coverage"] >= 0.10,
        "selective_top1_risk_below_forced_top1": (
            selective["localized_wrong_top1_risk"] < selective["forced_top1_wrong_risk"]
        ),
        "benefit_spans_at_least_four_strata": benefit_strata >= 4,
        "real_structure_mrr_not_below_v4_by_0_02": (
            mean(row["mrr"] for row in real["r2_full"]) + 0.02 >= mean(row["mrr"] for row in real["v4"])
        ),
    }
    payload = {
        "protocol": "v5_core_r2_independent_confirmation_score_v1",
        "independent_evidence": True,
        "events": 600,
        "clean_controls": 180,
        "secret_precommit_verified": True,
        "design_quality": {"real_structure_cases": real_count, "manual_error_cases": manual_error_count},
        "error_summary": error_summary,
        "clean_summary": clean_summary,
        "comparisons": comparisons,
        "candidate_absent": {
            method: {"events": len(rows), "top5": mean(row["top5"] for row in rows),
                     "mrr": mean(row["mrr"] for row in rows)}
            for method, rows in candidate_absent.items()
        },
        "candidate_absent_verified_rate": candidate_absent_verified_rate,
        "selective_diagnosis": selective,
        "benefit_strata": benefit_strata,
        "gates": gates,
        "final_promotion_passed": all(gates.values()),
        "no_post_confirmation_tuning_allowed": True,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    summary_path = args.output / "confirmation_summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    for name, rows in (("error_event_metrics.csv", raw_error), ("clean_event_metrics.csv", raw_clean)):
        with (args.output / name).open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(summary_path)
    print(f"R2 independent promotion passed: {payload['final_promotion_passed']}")
    if not payload["final_promotion_passed"]:
        print("Failed gates: " + ", ".join(name for name, value in gates.items() if not value))


if __name__ == "__main__":
    main()
