"""One-time scorer for the locked V5-PSL 240+120 confirmation corpus."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import random
import statistics
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl_protocol import (
    CASE_FIELDS,
    PREDICTION_METHODS,
    audit_design,
    canonical_cell,
    parse_source_cells,
    read_sha256_commitments,
    sha256,
    source_rank,
    validate_public_manifest,
)
from scripts.build_v5_psl_third_party_pack import (
    SECRET_COMPONENTS,
    validate_case_pair,
)
from scripts.run_v5_psl_predictions import (
    FORBIDDEN_SECRET_NAMES,
    audit_prediction_shard,
    verify_candidate_lock,
)
from scripts.verify_v5_psl_prediction_lock import verify_prediction_run

BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_SEED = 20260830


def _read_csv_bytes(data: bytes, fields: Sequence[str]) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
    if tuple(reader.fieldnames or ()) != tuple(fields):
        raise ValueError(
            f"Secret CSV fields differ: expected={list(fields)}, observed={reader.fieldnames}"
        )
    return list(reader)


def _archive_bytes(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError as exc:
        raise ValueError(f"SECRET archive is missing {name}") from exc


def _verify_prediction_lock(
    public_root: Path,
    candidate_lock: Path,
    predictions: Path,
    lock_path: Path,
) -> dict[str, object]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("protocol") != "v5_psl_prediction_lock_v1" or lock.get("locked") is not True:
        raise ValueError("Prediction lock is absent or invalid")
    recomputed = verify_prediction_run(
        public_root,
        candidate_lock,
        predictions,
        prediction_lock_path=lock_path,
    )
    stable_fields = (
        "candidate_id", "git_commit", "instances", "methods",
        "candidate_lock_sha256", "manifest_sha256", "public_metadata_sha256",
        "secret_precommit_sha256", "secret_archive_commitment",
        "public_archive_commitment",
        "prediction_metadata_sha256", "prediction_completion_sha256",
        "combined_shards_sha256", "full_ranking_audit_passed",
        "labels_read", "secret_files_read", "secret_release_authorized",
        "post_lock_prediction_changes_forbidden",
    )
    if set(lock) != set(recomputed):
        raise ValueError("Prediction lock schema differs from the verified protocol")
    for field in stable_fields:
        if lock.get(field) != recomputed.get(field):
            raise ValueError(f"Prediction lock verification failed: {field}")
    return lock


def _verify_secret(
    secret_zip: Path,
    commitments: Mapping[str, str],
) -> tuple[zipfile.ZipFile, dict[str, bytes]]:
    if sha256(secret_zip) != commitments["SECRET.zip"]:
        raise ValueError("SECRET archive does not match its public precommitment")
    archive = zipfile.ZipFile(secret_zip)
    names = archive.namelist()
    if len(names) != len(set(names)):
        archive.close()
        raise ValueError("SECRET archive contains duplicate member names")
    for name in names:
        path = Path(name)
        if not name or "\\" in name or path.is_absolute() or ".." in path.parts:
            archive.close()
            raise ValueError(f"SECRET archive contains an unsafe path: {name!r}")
    components = {name: _archive_bytes(archive, name) for name in SECRET_COMPONENTS}
    for name, data in components.items():
        if hashlib.sha256(data).hexdigest() != commitments[name]:
            archive.close()
            raise ValueError(f"Secret component changed after precommitment: {name}")
    extras = set(names) - set(SECRET_COMPONENTS)
    if not extras or any(not name.startswith("originals/") or not name.endswith(".xlsx") for name in extras):
        archive.close()
        raise ValueError("SECRET archive may contain only committed ledgers and original .xlsx files")
    return archive, components


def _mean(values: Iterable[float | int]) -> float:
    rows = list(values)
    return statistics.fmean(rows) if rows else 0.0


def summarize_method(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    identifiable = [row for row in errors if row["identifiability"] == "identifiable"]
    ambiguous = [row for row in errors if row["identifiability"] == "ambiguous"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    legal = [row for row in controls if row["control_subtype"] == "legal_exception"]
    localized_identifiable = [row for row in identifiable if row["state"] == "localized"]
    supported_identifiable = [row for row in identifiable if row["state"] != "unsupported"]
    inspected = sum(int(row["inspected_cells"]) for row in rows)
    found = sum(int(row["action_hit"]) for row in errors)
    states = Counter(str(row["state"]) for row in rows)
    return {
        "cases": len(rows),
        "error_cases": len(errors),
        "control_cases": len(controls),
        "state_counts": dict(sorted(states.items())),
        "overall_error_top1": _mean(int(row["top1"]) for row in errors),
        "overall_error_top5": _mean(int(row["top5"]) for row in errors),
        "overall_error_mrr": _mean(float(row["mrr"]) for row in errors),
        "identifiable_error_denominator": len(identifiable),
        "localized_coverage": len(localized_identifiable) / max(1, len(identifiable)),
        "localized_top1": _mean(int(row["top1"]) for row in localized_identifiable),
        "localized_top5": _mean(int(row["top5"]) for row in localized_identifiable),
        "overall_identifiable_top1": sum(
            int(row["top1"])
            for row in supported_identifiable
        ) / max(1, len(identifiable)),
        "overall_identifiable_top5": sum(
            int(row["top5"])
            for row in supported_identifiable
        ) / max(1, len(identifiable)),
        "actionable_control_fpr": _mean(int(row["actionable"]) for row in controls),
        "localized_control_fpr": _mean(
            int(row["state"] == "localized") for row in controls
        ),
        "legal_exception_actionable_fpr": _mean(int(row["actionable"]) for row in legal),
        "ambiguous_abstention_rate": _mean(
            int(row["state"] == "abstain_unidentifiable") for row in ambiguous
        ),
        "ambiguous_localization_rate": _mean(
            int(row["state"] == "localized") for row in ambiguous
        ),
        "inspected_cells": inspected,
        "source_cases_found": found,
        "review_efficiency_per_100_cells": 100.0 * found / inspected if inspected else 0.0,
        "unsupported_cases_retained": states.get("unsupported", 0),
    }


def summarize_all(events: Sequence[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    return {
        method: summarize_method([row for row in events if row["method"] == method])
        for method in PREDICTION_METHODS
    }


def promotion_metrics(summary: Mapping[str, Mapping[str, object]]) -> dict[str, float | str]:
    psl = summary["v5_psl_dev1"]
    baselines = {
        method: float(summary[method]["review_efficiency_per_100_cells"])
        for method in PREDICTION_METHODS[:-1]
    }
    best_method = max(baselines, key=lambda method: (baselines[method], method))
    best_efficiency = baselines[best_method]
    psl_efficiency = float(psl["review_efficiency_per_100_cells"])
    improvement = (
        psl_efficiency / best_efficiency - 1.0
        if best_efficiency > 0 else 0.0
    )
    return {
        "localized_coverage": float(psl["localized_coverage"]),
        "localized_top1": float(psl["localized_top1"]),
        "localized_top5": float(psl["localized_top5"]),
        "overall_identifiable_top1": float(psl["overall_identifiable_top1"]),
        "overall_identifiable_top5": float(psl["overall_identifiable_top5"]),
        "actionable_control_fpr": float(psl["actionable_control_fpr"]),
        "localized_control_fpr": float(psl["localized_control_fpr"]),
        "legal_exception_actionable_fpr": float(psl["legal_exception_actionable_fpr"]),
        "ambiguous_abstention_rate": float(psl["ambiguous_abstention_rate"]),
        "ambiguous_localization_rate": float(psl["ambiguous_localization_rate"]),
        "review_efficiency_per_100_cells": psl_efficiency,
        "best_baseline": best_method,
        "best_baseline_review_efficiency_per_100_cells": best_efficiency,
        "review_efficiency_relative_improvement": improvement,
    }


def promotion_gates(metrics: Mapping[str, float | str]) -> dict[str, bool]:
    return {
        "localized_coverage_at_least_30_percent": float(metrics["localized_coverage"]) >= 0.30,
        "localized_top1_at_least_75_percent": float(metrics["localized_top1"]) >= 0.75,
        "localized_top5_at_least_95_percent": float(metrics["localized_top5"]) >= 0.95,
        "actionable_control_fpr_at_most_10_percent": float(metrics["actionable_control_fpr"]) <= 0.10,
        "localized_control_fpr_at_most_5_percent": float(metrics["localized_control_fpr"]) <= 0.05,
        "legal_exception_actionable_fpr_at_most_10_percent": float(metrics["legal_exception_actionable_fpr"]) <= 0.10,
        "ambiguous_abstention_at_least_70_percent": float(metrics["ambiguous_abstention_rate"]) >= 0.70,
        "ambiguous_localization_at_most_10_percent": float(metrics["ambiguous_localization_rate"]) <= 0.10,
        "review_efficiency_improvement_at_least_15_percent": float(metrics["review_efficiency_relative_improvement"]) >= 0.15,
    }


def _percentile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    return ordered[int(probability * (len(ordered) - 1))]


def clustered_bootstrap(
    events: Sequence[Mapping[str, object]],
    *,
    draws: int = BOOTSTRAP_DRAWS,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, list[float]]:
    by_template: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in events:
        by_template[str(row["template_id"])].append(row)
    templates = sorted(by_template)
    if len(templates) != 30:
        raise ValueError("Clustered bootstrap requires exactly 30 templates")
    names = (
        "localized_coverage", "localized_top1", "localized_top5",
        "actionable_control_fpr", "localized_control_fpr",
        "legal_exception_actionable_fpr", "ambiguous_abstention_rate",
        "ambiguous_localization_rate", "review_efficiency_relative_improvement",
    )
    samples: dict[str, list[float]] = {name: [] for name in names}
    rng = random.Random(seed)
    for _ in range(draws):
        sampled: list[Mapping[str, object]] = []
        for _index in templates:
            sampled.extend(by_template[rng.choice(templates)])
        metrics = promotion_metrics(summarize_all(sampled))
        for name in names:
            samples[name].append(float(metrics[name]))
    return {
        name: [_percentile(values, 0.025), _percentile(values, 0.975)]
        for name, values in samples.items()
    }


def _score_events(
    cases: Sequence[Mapping[str, str]],
    predictions: Path,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for case in cases:
        record = json.loads(
            (predictions / "shards" / f"{case['instance_id']}.json").read_text(encoding="utf-8")
        )
        sources = set(parse_source_cells(case["source_cells"]))
        for method in PREDICTION_METHODS:
            payload = record["methods"][method]
            ranking = payload["ranking"]
            rank = source_rank(ranking, sources) if sources else None
            action_cells = {canonical_cell(value) for value in payload["action_cells"]}
            action_hit = bool(sources & action_cells)
            events.append({
                "instance_id": case["instance_id"],
                "template_id": case["template_id"],
                "method": method,
                "case_kind": case["case_kind"],
                "error_type": case["error_type"],
                "identifiability": case["identifiability"],
                "control_subtype": case["control_subtype"],
                "challenge_stratum": case["challenge_stratum"],
                "state": payload["state"],
                "formula_count": record["formula_count"],
                "inspected_cells": len(action_cells),
                "actionable": int(bool(action_cells)),
                "action_hit": int(action_hit),
                "source_rank": rank if rank is not None else "",
                "top1": int(rank is not None and rank <= 1) if sources else "",
                "top5": int(rank is not None and rank <= 5) if sources else "",
                "mrr": 1.0 / rank if rank is not None else "",
            })
    return events


def _write_events(path: Path, events: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(events[0]))
        writer.writeheader()
        writer.writerows(events)


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the one-time V5-PSL prediction lock")
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--candidate-lock", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--prediction-lock", type=Path)
    parser.add_argument("--secret-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    public_root = args.public.resolve()
    candidate_lock_path = args.candidate_lock.resolve()
    predictions = args.predictions.resolve()
    prediction_lock_path = (
        args.prediction_lock.resolve()
        if args.prediction_lock else predictions / "prediction_lock.json"
    )
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"One-time scoring output already exists: {output}")

    archive: zipfile.ZipFile | None = None
    try:
        candidate = verify_candidate_lock(candidate_lock_path)
        prediction_lock = _verify_prediction_lock(
            public_root, candidate_lock_path, predictions, prediction_lock_path,
        )
        public_rows = validate_public_manifest(public_root / "manifest.csv", public_root)
        commitments = read_sha256_commitments(
            public_root / "secret_precommit_sha256.txt",
            required_names=FORBIDDEN_SECRET_NAMES,
        )
        if sha256(args.secret_zip.resolve()) != commitments["SECRET.zip"]:
            raise ValueError("SECRET archive does not match its public precommitment")
        locked_commitments = candidate["third_party_commitments_received_before_lock"]
        if sha256(args.secret_zip.resolve()) != locked_commitments["secret_archive_sha256"]:
            raise ValueError("SECRET archive does not match the candidate lock")
    except (OSError, ValueError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"V5-PSL blind scoring refused before label access: {exc}") from exc

    output.mkdir(parents=True, exist_ok=True)
    started = {
        "protocol": "v5_psl_one_time_scoring_start_v2",
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "secret_archive_sha256": sha256(args.secret_zip.resolve()),
        "prediction_lock_verified_before_secret_open": True,
        "rerun_for_tuning_forbidden": True,
    }
    start_path = output / "scoring_started.json"
    try:
        with start_path.open("x", encoding="utf-8") as handle:
            json.dump(started, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise SystemExit("One-time scoring was already started") from exc

    try:
        archive, components = _verify_secret(args.secret_zip.resolve(), commitments)
        cases = _read_csv_bytes(components["cases.csv"], CASE_FIELDS)
        declaration = json.loads(components["third_party_declaration.json"].decode("utf-8"))
        recorded_design = json.loads(components["design_audit.json"].decode("utf-8"))
        design = audit_design(cases, declaration)
        if recorded_design != design:
            raise ValueError("Secret design audit does not reproduce")
        public_pairs = {(row["instance_id"], row["workbook"]) for row in public_rows}
        secret_pairs = {(row["instance_id"], row["workbook"]) for row in cases}
        if public_pairs != secret_pairs:
            raise ValueError("Secret cases do not match the public manifest")
        validation_reader = csv.DictReader(
            io.StringIO(components["case_validation.csv"].decode("utf-8-sig"))
        )
        validation_rows = list(validation_reader)
        validation_by_id = {row["instance_id"]: row for row in validation_rows}
        if len(validation_rows) != 360 or set(validation_by_id) != {row["instance_id"] for row in cases}:
            raise ValueError("Secret case validation inventory is incomplete")
        development_signatures = set(candidate.get("development_formula_change_signatures", []))
        if not development_signatures:
            raise ValueError("Candidate lock lacks the development transformation inventory")

        with tempfile.TemporaryDirectory(prefix="v5_psl_secret_") as directory:
            secret_root = Path(directory)
            expected_originals = {row["original_workbook"] for row in cases}
            observed_originals = {
                name for name in archive.namelist() if name.startswith("originals/")
            }
            if observed_originals != expected_originals:
                raise ValueError("SECRET originals do not match cases.csv")
            for name in sorted(expected_originals):
                target = secret_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_archive_bytes(archive, name))
            for index, case in enumerate(cases, 1):
                evidence = validate_case_pair(
                    case, secret_root,
                    workbook_root=public_root,
                    original_root=secret_root,
                    development_signatures=development_signatures,
                )
                recorded = validation_by_id[case["instance_id"]]
                for field in (
                    "workbook_sha256", "original_sha256", "formula_count",
                    "changed_formula_count", "formula_change_signature",
                ):
                    if str(evidence[field]) != recorded[field]:
                        raise ValueError(
                            f"Post-release workbook re-audit differs for {case['instance_id']}: {field}"
                        )
                if index % 50 == 0 or index == len(cases):
                    print(f"[{index}/{len(cases)}] secret workbook pairs re-audited", flush=True)
        archive.close()
        archive = None

        rows_by_id = {row["instance_id"]: row for row in public_rows}
        for path in sorted((predictions / "shards").glob("*.json")):
            audit_prediction_shard(path, rows_by_id[path.stem], public_root)
        events = _score_events(cases, predictions)
        summary = summarize_all(events)
        metrics = promotion_metrics(summary)
        gates = promotion_gates(metrics)
        intervals = clustered_bootstrap(events)
        promotion_allowed = all(gates.values())
        _write_events(output / "independent_360_events.csv", events)
        result = {
            "protocol": "v5_psl_single_custodian_240_120_scored_once_v2",
            "candidate_id": candidate["candidate_id"],
            "current_model_name": "V5-PSL-dev1",
            "formal_name_authorized_if_promoted": "V5-R1" if promotion_allowed else None,
            "events": len(cases),
            "method_events": len(events),
            "design": design,
            "summary": summary,
            "promotion_metrics": metrics,
            "clustered_bootstrap_95_ci": intervals,
            "bootstrap": {
                "unit": "template_id", "clusters": 30,
                "draws": BOOTSTRAP_DRAWS, "seed": BOOTSTRAP_SEED,
            },
            "promotion_gates": gates,
            "promotion_allowed": promotion_allowed,
            "all_unsupported_cases_retained_in_denominators": True,
            "all_360_cases_retained": len(cases) == 360,
            "prediction_lock_sha256": sha256(prediction_lock_path),
            "candidate_lock_sha256": sha256(candidate_lock_path),
            "public_manifest_sha256": sha256(public_root / "manifest.csv"),
            "public_archive_sha256": locked_commitments["public_archive_sha256"],
            "secret_archive_sha256": sha256(args.secret_zip.resolve()),
            "labels_opened_only_after_prediction_lock": prediction_lock["locked"] is True,
            "post_result_tuning_forbidden": True,
        }
        result_path = output / "independent_360_summary.json"
        result_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        receipt = {
            "protocol": "v5_psl_one_time_score_receipt_v2",
            "summary_sha256": sha256(result_path),
            "events_sha256": sha256(output / "independent_360_events.csv"),
            "promotion_allowed": promotion_allowed,
            "formal_version_not_created_by_scorer": True,
        }
        (output / "score_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
    except Exception as exc:
        if archive is not None:
            archive.close()
        failure = {
            "protocol": "v5_psl_one_time_scoring_failure_v2",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "rerun_without_custodian_review_forbidden": True,
        }
        (output / "scoring_failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        raise SystemExit(f"V5-PSL blind scoring failed after one-time secret open: {exc}") from exc
    print(output / "independent_360_summary.json")


if __name__ == "__main__":
    main()
