"""Predict, lock, and score the one-shot V4 static-fifth confirmation corpus."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import io
import json
import os
import random
import statistics
import subprocess
import sys
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v4_static_fifth import (
    ARCHITECTURE,
    MODEL_VERSION,
    REVIEW_BUDGET,
    V4_PREFIX,
    static_fifth_decision,
    v4_static_fifth_scores,
)
from formulaguard.v5_psl_protocol import (
    CASE_FIELDS,
    DEFAULT_WORKERS,
    audit_design,
    canonical_cell,
    combined_shards_sha256,
    deterministic_zip_sha256,
    parse_source_cells,
    read_csv,
    read_sha256_commitments,
    safe_path,
    sha256,
    source_rank,
    validate_complete_ranking,
    validate_public_manifest,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_v5_psl_third_party_pack import validate_case_pair
from scripts.run_v5_psl_predictions import FORBIDDEN_SECRET_NAMES, _validate_public_metadata
from scripts.score_v5_psl_blind import _archive_bytes, _read_csv_bytes, _verify_secret


CANDIDATE_PROTOCOL = "v4_static_fifth_blind_candidate_lock_v1"
PREDICTION_PROTOCOL = "v4_static_fifth_blind_prediction_shard_v1"
RUN_PROTOCOL = "v4_static_fifth_blind_prediction_run_v1"
COMPLETION_PROTOCOL = "v4_static_fifth_blind_prediction_completion_v1"
LOCK_PROTOCOL = "v4_static_fifth_blind_prediction_lock_v1"
COMMITMENT_PROTOCOL = "v4_static_fifth_blind_git_prediction_commitment_v1"
SCORE_PROTOCOL = "v4_static_fifth_blind_score_v1"
METHODS = ("v4_r1", "static_anchor", "v4_static_fifth")
BOOTSTRAP_DRAWS = 20_000
BOOTSTRAP_SEED = 20260831


def git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


def verify_candidate_lock(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != CANDIDATE_PROTOCOL or payload.get("candidate_locked") is not True:
        raise ValueError("static-fifth candidate lock is absent or invalid")
    expected = {
        "model_version": MODEL_VERSION,
        "architecture": ARCHITECTURE,
        "review_budget": REVIEW_BUDGET,
        "immutable_v4_prefix": V4_PREFIX,
    }
    if payload.get("model") != expected:
        raise ValueError("candidate lock model contract differs from the implementation")
    if payload.get("formal_version") is not None or payload.get("post_lock_tuning_forbidden") is not True:
        raise ValueError("candidate lock promotion or tuning boundary is invalid")
    if payload.get("protected_data_read_before_lock") is not False:
        raise ValueError("candidate lock does not preserve the protected-data boundary")
    sources = payload.get("source_sha256")
    if not isinstance(sources, dict) or not sources:
        raise ValueError("candidate lock source inventory is empty")
    for relative, expected_hash in sources.items():
        source = safe_path(ROOT, str(relative))
        if sha256(source) != expected_hash:
            raise ValueError(f"candidate source changed after lock: {relative}")
    receipt = safe_path(ROOT, str(payload["public_development_prediction_receipt"]))
    if sha256(receipt) != payload.get("public_development_prediction_receipt_sha256"):
        raise ValueError("public development prediction receipt changed after lock")
    signatures = safe_path(ROOT, str(payload["development_signature_inventory"]))
    if sha256(signatures) != payload.get("development_signature_inventory_sha256"):
        raise ValueError("development transformation inventory changed after lock")
    source_commit = str(payload.get("model_source_commit", ""))
    public_commit = str(payload.get("public_prediction_commit", ""))
    if git("merge-base", "--is-ancestor", source_commit, "HEAD") != "":
        raise ValueError("model source commit is not an ancestor of HEAD")
    if git("merge-base", "--is-ancestor", public_commit, "HEAD") != "":
        raise ValueError("public prediction commit is not an ancestor of HEAD")
    gates = payload.get("blind_promotion_gates")
    required_gates = {
        "minimum_top5_gain_pp": 5.0,
        "bootstrap_delta_lower_bound_strictly_positive": True,
        "minimum_mrr_delta": 0.0,
        "minimum_v4_miss_recovery_rate": 0.15,
        "maximum_v4_hit_loss_rate": 0.02,
        "maximum_error_type_regression_pp": 5.0,
        "minimum_nonnegative_template_fraction": 0.80,
        "review_budget_equal_to_v4": True,
    }
    if gates != required_gates:
        raise ValueError("blind promotion gates differ from the frozen contract")
    return payload


def _public_context(public_root: Path) -> tuple[list[dict[str, str]], dict[str, object], dict[str, str]]:
    rows = validate_public_manifest(public_root / "manifest.csv", public_root)
    metadata = _validate_public_metadata(public_root, rows)
    commitments = read_sha256_commitments(
        public_root / "secret_precommit_sha256.txt",
        required_names=FORBIDDEN_SECRET_NAMES,
    )
    if any((public_root / name).exists() for name in FORBIDDEN_SECRET_NAMES):
        raise ValueError("secret material is present in the PUBLIC directory")
    return rows, metadata, commitments


def _ranking(cells: Sequence[str]) -> list[dict[str, object]]:
    return [{"rank": rank, "cell": cell} for rank, cell in enumerate(cells, start=1)]


def _validate_method_inventory(methods: object, shard_name: str) -> dict[str, object]:
    if not isinstance(methods, dict) or set(methods) != set(METHODS):
        raise ValueError(f"prediction method inventory differs: {shard_name}")
    return methods


def predict_workbook(workbook: Path, instance_id: str, workbook_label: str) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(workbook)
    candidate = v4_static_fifth_scores(model, candidate_limit=15)
    candidate_cells = [row.cell_label for row in candidate]
    v4_cells = [
        row.cell_label
        for row in sorted(candidate, key=lambda row: int(row.evidence["original_v4_rank"]))
    ]
    static_cells = [
        row.cell_label
        for row in sorted(candidate, key=lambda row: int(row.evidence["static_anchor_rank"]))
    ]
    decision = static_fifth_decision(v4_cells, static_cells)
    if list(decision.ranking) != candidate_cells:
        raise AssertionError("runtime candidate differs from the static-fifth contract")
    return {
        "protocol": PREDICTION_PROTOCOL,
        "instance_id": instance_id,
        "workbook": workbook_label,
        "workbook_sha256": sha256(workbook),
        "formula_count": len(model.formulas),
        "methods": {
            "v4_r1": {"model_version": "v4-dev-r1", "ranking": _ranking(v4_cells)},
            "static_anchor": {"model_version": "formulaguard-static-v1", "ranking": _ranking(static_cells)},
            "v4_static_fifth": {"model_version": MODEL_VERSION, "ranking": _ranking(candidate_cells)},
        },
        "changed": decision.changed,
        "label_inputs": [],
        "secret_inputs": [],
    }


def audit_prediction_shard(
    path: Path,
    public_row: Mapping[str, str],
    public_root: Path,
    *,
    recompute: bool,
) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("protocol") != PREDICTION_PROTOCOL:
        raise ValueError(f"invalid prediction shard protocol: {path.name}")
    if (
        record.get("instance_id") != public_row["instance_id"]
        or record.get("workbook") != public_row["workbook"]
        or record.get("label_inputs") != []
        or record.get("secret_inputs") != []
    ):
        raise ValueError(f"prediction input boundary failed: {path.name}")
    workbook = safe_path(public_root, public_row["workbook"])
    if record.get("workbook_sha256") != sha256(workbook):
        raise ValueError(f"prediction workbook hash changed: {path.name}")
    model = WorkbookModel.from_xlsx(workbook)
    formula_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    if record.get("formula_count") != len(formula_cells):
        raise ValueError(f"prediction formula count differs: {path.name}")
    methods = _validate_method_inventory(record.get("methods"), path.name)
    expected_versions = {
        "v4_r1": "v4-dev-r1",
        "static_anchor": "formulaguard-static-v1",
        "v4_static_fifth": MODEL_VERSION,
    }
    for method, version in expected_versions.items():
        payload = methods[method]
        if payload.get("model_version") != version:
            raise ValueError(f"prediction model version differs: {method} {path.name}")
        validate_complete_ranking(payload["ranking"], formula_cells)
    v4_cells = [canonical_cell(row["cell"]) for row in methods["v4_r1"]["ranking"]]
    static_cells = [canonical_cell(row["cell"]) for row in methods["static_anchor"]["ranking"]]
    candidate_cells = [canonical_cell(row["cell"]) for row in methods["v4_static_fifth"]["ranking"]]
    decision = static_fifth_decision(v4_cells, static_cells)
    if candidate_cells != list(decision.ranking) or record.get("changed") is not decision.changed:
        raise ValueError(f"prediction violates the four-plus-one rule: {path.name}")
    if recompute:
        expected = predict_workbook(workbook, public_row["instance_id"], public_row["workbook"])
        if record != expected:
            raise ValueError(f"prediction does not reproduce from frozen source: {path.name}")
    return record


def _predict_task(task: tuple[str, str, str, str]) -> str:
    public_text, output_text, instance_id, workbook_label = task
    public_root, output = Path(public_text), Path(output_text)
    shard = output / "shards" / f"{instance_id}.json"
    if shard.exists():
        audit_prediction_shard(
            shard,
            {"instance_id": instance_id, "workbook": workbook_label},
            public_root,
            recompute=False,
        )
        return instance_id
    record = predict_workbook(
        safe_path(public_root, workbook_label), instance_id, workbook_label,
    )
    temporary = shard.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, shard)
    return instance_id


def predict_run(
    public_root: Path,
    candidate_lock_path: Path,
    output: Path,
    *,
    workers: int,
) -> Path:
    candidate = verify_candidate_lock(candidate_lock_path)
    rows, metadata, commitments = _public_context(public_root)
    if output.exists() and any(
        path.name not in {"prediction_metadata.json"} for path in output.iterdir()
    ):
        allowed = {"shards", "prediction_metadata.json"}
        if {path.name for path in output.iterdir()} - allowed:
            raise ValueError("prediction output contains unexpected pre-existing files")
    (output / "shards").mkdir(parents=True, exist_ok=True)
    public_archive_sha = deterministic_zip_sha256(public_root)
    metadata_payload = {
        "protocol": RUN_PROTOCOL,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "public_metadata_sha256": sha256(public_root / "public_metadata.json"),
        "secret_precommit_sha256": sha256(public_root / "secret_precommit_sha256.txt"),
        "public_archive_sha256": public_archive_sha,
        "secret_archive_commitment": commitments["SECRET.zip"],
        "package_protocol": metadata["protocol"],
        "methods": list(METHODS),
        "instances": len(rows),
        "workers": workers,
        "label_inputs": [],
        "secret_inputs": [],
    }
    metadata_path = output / "prediction_metadata.json"
    encoded_metadata = (json.dumps(metadata_payload, ensure_ascii=False, indent=2) + "\n").encode()
    if metadata_path.exists() and metadata_path.read_bytes() != encoded_metadata:
        raise ValueError("prediction metadata differs from the existing run")
    metadata_path.write_bytes(encoded_metadata)

    tasks = [
        (str(public_root), str(output), row["instance_id"], row["workbook"])
        for row in rows
    ]
    with concurrent.futures.ProcessPoolExecutor(max_workers=min(workers, len(tasks))) as executor:
        futures = [executor.submit(_predict_task, task) for task in tasks]
        for index, future in enumerate(concurrent.futures.as_completed(futures), start=1):
            future.result()
            if index % 25 == 0 or index == len(tasks):
                print(f"static-fifth blind predictions {index}/{len(tasks)}", flush=True)
    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((output / "shards").glob("*.json"))
    if len(shards) != len(rows) or {path.stem for path in shards} != set(rows_by_id):
        raise ValueError("prediction shards do not cover PUBLIC exactly")
    for path in shards:
        audit_prediction_shard(path, rows_by_id[path.stem], public_root, recompute=False)
    completion = {
        "protocol": COMPLETION_PROTOCOL,
        "complete": True,
        "instances": len(rows),
        "methods": list(METHODS),
        "metadata_sha256": sha256(metadata_path),
        "combined_shards_sha256": combined_shards_sha256(shards),
        "full_ranking_audit_passed": True,
        "labels_read": [],
        "secret_files_read": [],
    }
    completion_path = output / "prediction_complete.json"
    completion_bytes = (json.dumps(completion, ensure_ascii=False, indent=2) + "\n").encode()
    if completion_path.exists() and completion_path.read_bytes() != completion_bytes:
        raise ValueError("prediction completion differs from the existing run")
    completion_path.write_bytes(completion_bytes)
    return completion_path


def verify_prediction_run(
    public_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    *,
    recompute: bool,
) -> dict[str, object]:
    candidate = verify_candidate_lock(candidate_lock_path)
    rows, metadata, commitments = _public_context(public_root)
    metadata_path = predictions / "prediction_metadata.json"
    completion_path = predictions / "prediction_complete.json"
    run_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    completion = json.loads(completion_path.read_text(encoding="utf-8"))
    if run_metadata.get("protocol") != RUN_PROTOCOL or completion.get("protocol") != COMPLETION_PROTOCOL:
        raise ValueError("prediction run metadata protocol differs")
    required_metadata = {
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "manifest_sha256": sha256(public_root / "manifest.csv"),
        "public_metadata_sha256": sha256(public_root / "public_metadata.json"),
        "secret_precommit_sha256": sha256(public_root / "secret_precommit_sha256.txt"),
        "public_archive_sha256": deterministic_zip_sha256(public_root),
        "secret_archive_commitment": commitments["SECRET.zip"],
        "package_protocol": metadata["protocol"],
        "methods": list(METHODS),
        "instances": len(rows),
        "label_inputs": [],
        "secret_inputs": [],
    }
    for field, expected in required_metadata.items():
        if run_metadata.get(field) != expected:
            raise ValueError(f"prediction metadata changed: {field}")
    expected_files = {
        "prediction_metadata.json", "prediction_complete.json",
        *(f"shards/{row['instance_id']}.json" for row in rows),
    }
    observed_files = {
        path.relative_to(predictions).as_posix()
        for path in predictions.rglob("*") if path.is_file() or path.is_symlink()
    }
    if any(path.is_symlink() for path in predictions.rglob("*")) or observed_files != expected_files:
        raise ValueError("prediction file inventory differs")
    rows_by_id = {row["instance_id"]: row for row in rows}
    shards = sorted((predictions / "shards").glob("*.json"))
    for index, path in enumerate(shards, start=1):
        audit_prediction_shard(path, rows_by_id[path.stem], public_root, recompute=recompute)
        if recompute and (index % 25 == 0 or index == len(shards)):
            print(f"static-fifth lock reproduction {index}/{len(shards)}", flush=True)
    combined = combined_shards_sha256(shards)
    if (
        completion.get("complete") is not True
        or completion.get("instances") != len(rows)
        or completion.get("methods") != list(METHODS)
        or completion.get("metadata_sha256") != sha256(metadata_path)
        or completion.get("combined_shards_sha256") != combined
        or completion.get("labels_read") != []
        or completion.get("secret_files_read") != []
    ):
        raise ValueError("prediction completion receipt differs")
    return {
        "protocol": LOCK_PROTOCOL,
        "locked": True,
        "candidate_id": candidate["candidate_id"],
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "instances": len(rows),
        "methods": list(METHODS),
        "public_archive_sha256": required_metadata["public_archive_sha256"],
        "secret_archive_commitment": commitments["SECRET.zip"],
        "manifest_sha256": required_metadata["manifest_sha256"],
        "prediction_metadata_sha256": sha256(metadata_path),
        "prediction_completion_sha256": sha256(completion_path),
        "combined_shards_sha256": combined,
        "full_ranking_reproduction_passed": recompute,
        "labels_read": [],
        "secret_files_read": [],
        "secret_open_authorized_after_git_commitment": True,
        "post_lock_prediction_changes_forbidden": True,
    }


def write_prediction_lock(
    public_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    output: Path,
) -> Path:
    if output.exists():
        raise ValueError("prediction lock already exists")
    payload = verify_prediction_run(
        public_root, candidate_lock_path, predictions, recompute=True,
    )
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output


def _completed_reproduction_lock(payload: Mapping[str, object]) -> dict[str, object]:
    completed = dict(payload)
    completed["full_ranking_reproduction_passed"] = True
    return completed


def _verify_git_commitment(
    path: Path,
    prediction_lock: Path,
    lock: Mapping[str, object],
) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    expected = {
        "protocol": COMMITMENT_PROTOCOL,
        "candidate_id": lock["candidate_id"],
        "prediction_lock_sha256": sha256(prediction_lock),
        "combined_shards_sha256": lock["combined_shards_sha256"],
        "public_archive_sha256": lock["public_archive_sha256"],
        "secret_archive_commitment": lock["secret_archive_commitment"],
        "labels_read_before_commitment": [],
        "post_commitment_tuning_forbidden": True,
    }
    if payload != expected:
        raise ValueError("Git prediction commitment differs from the external lock")
    relative = path.resolve().relative_to(ROOT)
    git("cat-file", "-e", f"HEAD:{relative.as_posix()}")
    if subprocess.run(
        ["git", "diff", "--quiet", "HEAD", "--", str(relative)], cwd=ROOT,
    ).returncode:
        raise ValueError("Git prediction commitment has uncommitted changes")
    return payload


def _mean(rows: Sequence[Mapping[str, object]], field: str) -> float:
    return statistics.fmean(float(row[field]) for row in rows) if rows else 0.0


def _template_macro(rows: Sequence[Mapping[str, object]], field: str) -> float:
    groups: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        groups[str(row["template_id"])].append(float(row[field]))
    return statistics.fmean(statistics.fmean(values) for values in groups.values())


def _method_summary(rows: Sequence[Mapping[str, object]], prefix: str) -> dict[str, float]:
    return {
        "top1": _template_macro(rows, f"{prefix}_top1"),
        "top5": _template_macro(rows, f"{prefix}_top5"),
        "mrr": _template_macro(rows, f"{prefix}_mrr"),
    }


def _bootstrap(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_template: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        by_template[str(row["template_id"])].append(row)
    templates = sorted(by_template)
    if len(templates) != 30:
        raise ValueError("blind bootstrap requires exactly 30 templates")
    rng = random.Random(BOOTSTRAP_SEED)
    samples = []
    for _ in range(BOOTSTRAP_DRAWS):
        sampled = []
        for _index in templates:
            sampled.extend(by_template[rng.choice(templates)])
        samples.append(_mean(sampled, "candidate_top5") - _mean(sampled, "v4_top5"))
    samples.sort()
    return {
        "unit": "template_id",
        "clusters": len(templates),
        "draws": BOOTSTRAP_DRAWS,
        "seed": BOOTSTRAP_SEED,
        "delta_pp_ci95": [100.0 * samples[500], 100.0 * samples[19_499]],
    }


def score_rows(
    cases: Sequence[Mapping[str, str]],
    predictions: Path,
) -> tuple[dict[str, object], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    controls_changed = 0
    controls = 0
    for case in cases:
        record = json.loads(
            (predictions / "shards" / f"{case['instance_id']}.json").read_text(encoding="utf-8")
        )
        if case["case_kind"] == "control":
            controls += 1
            controls_changed += int(bool(record["changed"]))
            continue
        sources = set(parse_source_cells(case["source_cells"]))
        ranks = {
            method: source_rank(record["methods"][method]["ranking"], sources)
            for method in METHODS
        }
        row: dict[str, object] = {
            "instance_id": case["instance_id"],
            "template_id": case["template_id"],
            "error_type": case["error_type"],
            "identifiability": case["identifiability"],
        }
        for method, prefix in (
            ("v4_r1", "v4"),
            ("static_anchor", "static"),
            ("v4_static_fifth", "candidate"),
        ):
            rank = ranks[method]
            row.update({
                f"{prefix}_rank": rank if rank is not None else "",
                f"{prefix}_top1": int(rank is not None and rank <= 1),
                f"{prefix}_top5": int(rank is not None and rank <= REVIEW_BUDGET),
                f"{prefix}_mrr": 1.0 / rank if rank is not None else 0.0,
            })
        rows.append(row)
    v4_hits = sum(int(row["v4_top5"]) for row in rows)
    candidate_hits = sum(int(row["candidate_top5"]) for row in rows)
    recovered = sum(
        int(row["candidate_top5"]) > int(row["v4_top5"]) for row in rows
    )
    lost = sum(int(row["candidate_top5"]) < int(row["v4_top5"]) for row in rows)
    summaries = {
        "v4_r1": _method_summary(rows, "v4"),
        "static_anchor": _method_summary(rows, "static"),
        "v4_static_fifth": _method_summary(rows, "candidate"),
    }
    by_error_type = {}
    for error_type in sorted({str(row["error_type"]) for row in rows}):
        selected = [row for row in rows if row["error_type"] == error_type]
        by_error_type[error_type] = {
            "cases": len(selected),
            "v4_top5": _mean(selected, "v4_top5"),
            "candidate_top5": _mean(selected, "candidate_top5"),
            "delta_pp": 100.0 * (
                _mean(selected, "candidate_top5") - _mean(selected, "v4_top5")
            ),
        }
    template_deltas = []
    for template_id in sorted({str(row["template_id"]) for row in rows}):
        selected = [row for row in rows if row["template_id"] == template_id]
        template_deltas.append(
            _mean(selected, "candidate_top5") - _mean(selected, "v4_top5")
        )
    bootstrap = _bootstrap(rows)
    top5_delta = summaries["v4_static_fifth"]["top5"] - summaries["v4_r1"]["top5"]
    mrr_delta = summaries["v4_static_fifth"]["mrr"] - summaries["v4_r1"]["mrr"]
    recovery_rate = recovered / max(1, len(rows) - v4_hits)
    loss_rate = lost / max(1, v4_hits)
    gates = {
        "top5_gain_at_least_5pp": top5_delta >= 0.05,
        "bootstrap_delta_lower_bound_positive": bootstrap["delta_pp_ci95"][0] > 0.0,
        "mrr_nonnegative": mrr_delta >= 0.0,
        "v4_miss_recovery_at_least_15pct": recovery_rate >= 0.15,
        "v4_hit_loss_at_most_2pct": loss_rate <= 0.02,
        "every_error_type_regression_within_5pp": all(
            row["delta_pp"] >= -5.0 for row in by_error_type.values()
        ),
        "nonnegative_template_fraction_at_least_80pct": (
            sum(delta >= 0.0 for delta in template_deltas) / len(template_deltas) >= 0.80
        ),
        "review_budget_equal_to_v4": True,
    }
    return {
        "error_cases": len(rows),
        "control_cases": controls,
        "review_budget_per_workbook": REVIEW_BUDGET,
        "automatic_corrections": False,
        "control_extra_review_cost_vs_v4": 0,
        "control_changed_fifth_rate_diagnostic": controls_changed / max(1, controls),
        "methods": summaries,
        "top5_delta_pp": 100.0 * top5_delta,
        "mrr_delta": mrr_delta,
        "v4_hits": v4_hits,
        "candidate_hits": candidate_hits,
        "recovered_events": recovered,
        "lost_events": lost,
        "v4_miss_recovery_rate": recovery_rate,
        "v4_hit_loss_rate": loss_rate,
        "by_error_type": by_error_type,
        "nonnegative_template_fraction": sum(delta >= 0.0 for delta in template_deltas) / len(template_deltas),
        "template_delta_counts": {
            "positive": sum(delta > 0.0 for delta in template_deltas),
            "zero": sum(delta == 0.0 for delta in template_deltas),
            "negative": sum(delta < 0.0 for delta in template_deltas),
        },
        "template_cluster_bootstrap": bootstrap,
        "promotion_gates": gates,
        "promotion_allowed": all(gates.values()),
    }, rows


def _write_private_events(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _development_signatures(candidate: Mapping[str, object]) -> set[str]:
    path = safe_path(ROOT, str(candidate["development_signature_inventory"]))
    return {
        line.strip() for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def score_once(
    public_root: Path,
    candidate_lock_path: Path,
    predictions: Path,
    prediction_lock_path: Path,
    git_commitment_path: Path,
    secret_zip: Path,
    output: Path,
) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("one-time score output is not empty")
    candidate = verify_candidate_lock(candidate_lock_path)
    external_lock = json.loads(prediction_lock_path.read_text(encoding="utf-8"))
    verified_lock = verify_prediction_run(
        public_root, candidate_lock_path, predictions, recompute=False,
    )
    if (
        external_lock != _completed_reproduction_lock(verified_lock)
        or external_lock.get("protocol") != LOCK_PROTOCOL
    ):
        raise ValueError("external prediction lock does not reproduce")
    _verify_git_commitment(git_commitment_path, prediction_lock_path, external_lock)
    rows, _metadata, commitments = _public_context(public_root)
    if sha256(secret_zip) != commitments["SECRET.zip"]:
        raise ValueError("SECRET archive differs from the PUBLIC precommitment")

    output.mkdir(parents=True, exist_ok=True)
    start = {
        "protocol": "v4_static_fifth_blind_scoring_started_v1",
        "candidate_lock_sha256": sha256(candidate_lock_path),
        "prediction_lock_sha256": sha256(prediction_lock_path),
        "git_commitment_sha256": sha256(git_commitment_path),
        "secret_archive_sha256": sha256(secret_zip),
        "prediction_lock_verified_before_secret_open": True,
        "post_result_tuning_forbidden": True,
    }
    start_path = output / "scoring_started.json"
    with start_path.open("x", encoding="utf-8") as handle:
        json.dump(start, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    archive: zipfile.ZipFile | None = None
    try:
        archive, components = _verify_secret(secret_zip, commitments)
        cases = _read_csv_bytes(components["cases.csv"], CASE_FIELDS)
        declaration = json.loads(components["third_party_declaration.json"].decode("utf-8"))
        design = audit_design(cases, declaration)
        recorded_design = json.loads(components["design_audit.json"].decode("utf-8"))
        if design != recorded_design:
            raise ValueError("secret design audit does not reproduce")
        if {(row["instance_id"], row["workbook"]) for row in rows} != {
            (row["instance_id"], row["workbook"]) for row in cases
        }:
            raise ValueError("SECRET cases do not match PUBLIC instances")
        validation_rows = list(csv.DictReader(io.StringIO(
            components["case_validation.csv"].decode("utf-8-sig")
        )))
        validation_by_id = {row["instance_id"]: row for row in validation_rows}
        if len(validation_by_id) != 360:
            raise ValueError("secret case validation inventory is incomplete")

        with tempfile.TemporaryDirectory(prefix="v4_static_fifth_secret_") as directory:
            secret_root = Path(directory)
            originals = {row["original_workbook"] for row in cases}
            observed = {name for name in archive.namelist() if name.startswith("originals/")}
            if originals != observed:
                raise ValueError("SECRET original inventory differs from cases")
            for name in sorted(originals):
                target = secret_root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_archive_bytes(archive, name))
            signatures = _development_signatures(candidate)
            for index, case in enumerate(cases, start=1):
                evidence = validate_case_pair(
                    case,
                    secret_root,
                    workbook_root=public_root,
                    original_root=secret_root,
                    development_signatures=signatures,
                )
                recorded = validation_by_id[case["instance_id"]]
                for field in (
                    "workbook_sha256", "original_sha256", "formula_count",
                    "changed_formula_count", "formula_change_signature",
                ):
                    if str(evidence[field]) != recorded[field]:
                        raise ValueError(
                            f"post-release case audit differs: {case['instance_id']} {field}"
                        )
                if index % 50 == 0 or index == len(cases):
                    print(f"static-fifth secret audit {index}/{len(cases)}", flush=True)
        archive.close()
        archive = None

        summary, event_rows = score_rows(cases, predictions)
        _write_private_events(output / "blind_events.csv", event_rows)
        result = {
            "protocol": SCORE_PROTOCOL,
            "candidate_id": candidate["candidate_id"],
            "model_version": MODEL_VERSION,
            "design": design,
            "summary": summary,
            "candidate_lock_sha256": sha256(candidate_lock_path),
            "prediction_lock_sha256": sha256(prediction_lock_path),
            "public_archive_sha256": external_lock["public_archive_sha256"],
            "secret_archive_sha256": sha256(secret_zip),
            "labels_opened_only_after_committed_prediction_lock": True,
            "all_360_cases_retained": len(cases) == 360,
            "formal_model_name_authorized": "V5-R1" if summary["promotion_allowed"] else None,
            "post_result_tuning_forbidden": True,
        }
        result_path = output / "blind_summary.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipt = {
            "protocol": "v4_static_fifth_blind_score_receipt_v1",
            "summary_sha256": sha256(result_path),
            "private_events_sha256": sha256(output / "blind_events.csv"),
            "promotion_allowed": summary["promotion_allowed"],
            "formal_name": result["formal_model_name_authorized"],
        }
        (output / "score_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result_path
    except Exception as exc:
        if archive is not None:
            archive.close()
        failure = {
            "protocol": "v4_static_fifth_blind_scoring_failure_v1",
            "error_type": type(exc).__name__,
            "message": str(exc),
            "rerun_without_custodian_review_forbidden": True,
        }
        (output / "scoring_failure.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    predict_parser = subparsers.add_parser("predict")
    predict_parser.add_argument("--public", type=Path, required=True)
    predict_parser.add_argument("--candidate-lock", type=Path, required=True)
    predict_parser.add_argument("--output", type=Path, required=True)
    predict_parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    lock_parser = subparsers.add_parser("lock")
    lock_parser.add_argument("--public", type=Path, required=True)
    lock_parser.add_argument("--candidate-lock", type=Path, required=True)
    lock_parser.add_argument("--predictions", type=Path, required=True)
    lock_parser.add_argument("--output", type=Path, required=True)
    score_parser = subparsers.add_parser("score")
    score_parser.add_argument("--public", type=Path, required=True)
    score_parser.add_argument("--candidate-lock", type=Path, required=True)
    score_parser.add_argument("--predictions", type=Path, required=True)
    score_parser.add_argument("--prediction-lock", type=Path, required=True)
    score_parser.add_argument("--git-commitment", type=Path, required=True)
    score_parser.add_argument("--secret-zip", type=Path, required=True)
    score_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "predict":
            if args.workers < 1:
                raise ValueError("workers must be positive")
            path = predict_run(
                args.public.resolve(), args.candidate_lock.resolve(), args.output.resolve(),
                workers=args.workers,
            )
        elif args.command == "lock":
            path = write_prediction_lock(
                args.public.resolve(), args.candidate_lock.resolve(),
                args.predictions.resolve(), args.output.resolve(),
            )
        else:
            path = score_once(
                args.public.resolve(), args.candidate_lock.resolve(),
                args.predictions.resolve(), args.prediction_lock.resolve(),
                args.git_commitment.resolve(), args.secret_zip.resolve(), args.output.resolve(),
            )
    except (OSError, ValueError, KeyError, AssertionError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise SystemExit(f"static-fifth blind {args.command} refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
