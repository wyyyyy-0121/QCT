#!/usr/bin/env python3
"""Train and audit the preregistered FoRepBench formula-pair ranker."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import os
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.fspr import (
    ARCHITECTURE,
    DIMENSIONS,
    PROTOCOL,
    TOKENIZER_VERSION,
    V4_PREFIX,
    FSPRModel,
    forepbench_value_lookup,
    formula_feature_tokens,
    hashed_features,
    workbook_logits,
)
from formulaguard.localize import v4_scores
from formulaguard.workbook import WorkbookModel

PREREGISTRATION = ROOT / "research/V5_FSPR_PREREGISTRATION.json"
DEFAULT_DATASET = (
    ROOT
    / "data/external/v5_psl/raw/forepbench/repository/FoRepBench/dataset"
    / "FoRepBenchmarks.json"
)
DEFAULT_CORPUS_MANIFEST = ROOT / "results/drfv_corpus_v1/corpus_manifest.json"
DEFAULT_CORPUS_RECEIPT = ROOT / "results/drfv_corpus_v1/corpus_receipt.json"
DEFAULT_INTAKE_MANIFEST = ROOT / "results/drfv_spreadsheetbench_v1_intake/input_manifest.json"
DEFAULT_INPUT_ROOT = ROOT / "data/external/model_discovery/corpus/drfv_spreadsheetbench_v1_inputs"
DEFAULT_OUTPUT = ROOT / "results/fspr_v1"
EXPECTED_DATASET_SHA256 = "7dc32841e8b243653a2325b38fd651415ce00257780815d1785d25ac41fb28fb"
EXPECTED_CORPUS_MANIFEST_SHA256 = "0e1228992fccf6b13961e397b944133db83dcde72b5372af5c36cd54306e71ed"
EXPECTED_CORPUS_RECEIPT_SHA256 = "743461a31faf9734d38cbcb43dbf2a23cc1cf30076b8d83ffe22d3d7d6d5e789"
EXPECTED_INTAKE_MANIFEST_SHA256 = "bb01edd4a58f80a7f26f6b3051f3bdbc6983b2a5a47a23d185bcd07cf2a4f42d"
EXPECTED_PAIRS = 618
C_VALUES = (0.1, 1.0, 10.0)
C_TIE_ORDER = (1.0, 0.1, 10.0)
FOLDS = 5
SEED = 260903
MAX_WORKERS = 24
THRESHOLD_QUANTILE = 0.9
MODEL_FIELDS = {"data", "faulty_formula", "correct_formula"}
FORBIDDEN_MODEL_FIELDS = {
    "utterance",
    "explanation",
    "runtime_errors",
    "validity_explanation",
    "confidence_level",
    "difficulty_level_human",
    "difficulty_level_LLM",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def canonical_formula(value: object) -> str:
    return "".join(str(value).upper().split())


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_clean_tracked_worktree() -> None:
    result = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        raise ValueError("tracked worktree must be clean before FSPR training")


class DisjointSet:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def leakage_groups(rows: Sequence[Mapping[str, object]]) -> tuple[list[str], list[int]]:
    """Group every shared context or formula identity into one stable fold."""

    disjoint = DisjointSet(len(rows))
    owners: dict[str, int] = {}
    row_fingerprints: list[str] = []
    for index, row in enumerate(rows):
        data = row.get("data")
        faulty = canonical_formula(row.get("faulty_formula"))
        correct = canonical_formula(row.get("correct_formula"))
        if not isinstance(data, Mapping) or not faulty or not correct or faulty == correct:
            raise ValueError(f"invalid FoRepBench pair at index {index}")
        context = stable_hash(data)
        row_fingerprints.append(stable_hash([context, faulty, correct]))
        for identity in ("context:" + context, "formula:" + faulty, "formula:" + correct):
            if identity in owners:
                disjoint.union(index, owners[identity])
            else:
                owners[identity] = index
    members: dict[int, list[int]] = defaultdict(list)
    for index in range(len(rows)):
        members[disjoint.find(index)].append(index)
    component_ids = {
        root: stable_hash(sorted(row_fingerprints[index] for index in indices))
        for root, indices in members.items()
    }
    group_ids = [component_ids[disjoint.find(index)] for index in range(len(rows))]
    folds = [int(group_id[:16], 16) % FOLDS for group_id in group_ids]
    return group_ids, folds


def load_pairs(path: Path) -> tuple[list[dict[str, object]], list[str], list[int]]:
    if sha256_file(path) != EXPECTED_DATASET_SHA256:
        raise ValueError("FoRepBench dataset hash changed")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != EXPECTED_PAIRS:
        raise ValueError("FoRepBench pair count changed")
    rows = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, Mapping) or not MODEL_FIELDS.issubset(raw):
            raise ValueError(f"malformed FoRepBench row at index {index}")
        if FORBIDDEN_MODEL_FIELDS.intersection(MODEL_FIELDS):
            raise AssertionError("FSPR model field policy is inconsistent")
        rows.append({field: raw[field] for field in sorted(MODEL_FIELDS)})
    group_ids, folds = leakage_groups(rows)
    if set(folds) != set(range(FOLDS)):
        raise ValueError("stable FSPR grouping left an empty fold")
    return rows, group_ids, folds


def tokenized_examples(
    rows: Sequence[Mapping[str, object]],
) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    examples: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    for row in rows:
        data = row["data"]
        if not isinstance(data, Mapping):
            raise TypeError("FoRepBench data context is malformed")
        lookup = forepbench_value_lookup(data)
        examples.append(
            formula_feature_tokens(str(row["faulty_formula"]), value_lookup=lookup)
        )
        examples.append(
            formula_feature_tokens(str(row["correct_formula"]), value_lookup=lookup)
        )
    return examples


def dense_matrix(
    tokenized: Sequence[tuple[Sequence[str], Sequence[str]]],
    *,
    view: str,
) -> np.ndarray:
    matrix = np.zeros((len(tokenized), DIMENSIONS), dtype=np.float64)
    for row_index, (syntax, context) in enumerate(tokenized):
        for column, value in hashed_features(syntax, context, view=view).items():
            matrix[row_index, column] = value
    return matrix


def fit_classifier(matrix: np.ndarray, labels: np.ndarray, c_value: float) -> LogisticRegression:
    classifier = LogisticRegression(
        C=c_value,
        class_weight="balanced",
        max_iter=2000,
        random_state=SEED,
        solver="liblinear",
    )
    classifier.fit(matrix, labels)
    return classifier


def cross_validate(
    matrix: np.ndarray,
    labels: np.ndarray,
    pair_folds: Sequence[int],
    *,
    c_value: float,
) -> tuple[dict[str, object], np.ndarray]:
    example_folds = np.repeat(np.asarray(pair_folds, dtype=np.int64), 2)
    scores = np.zeros(len(labels), dtype=np.float64)
    fold_metrics = []
    for fold in range(FOLDS):
        train = example_folds != fold
        test = example_folds == fold
        classifier = fit_classifier(matrix[train], labels[train], c_value)
        scores[test] = classifier.decision_function(matrix[test])
        pair_indices = np.flatnonzero(np.asarray(pair_folds) == fold)
        correct = [scores[index * 2] > scores[index * 2 + 1] for index in pair_indices]
        fold_metrics.append(
            {
                "fold": fold,
                "pairs": len(pair_indices),
                "pairwise_accuracy": sum(correct) / len(correct),
            }
        )
    pair_correct = scores[0::2] > scores[1::2]
    metrics = {
        "c": c_value,
        "pairwise_accuracy": float(np.mean(pair_correct)),
        "roc_auc": float(roc_auc_score(labels, scores)),
        "folds_at_or_above_0_70": sum(
            float(row["pairwise_accuracy"]) >= 0.70 for row in fold_metrics
        ),
        "fold_metrics": fold_metrics,
    }
    return metrics, scores


def select_c(metrics: Sequence[Mapping[str, object]]) -> float:
    tie_rank = {value: -index for index, value in enumerate(C_TIE_ORDER)}
    selected = max(
        metrics,
        key=lambda row: (
            float(row["pairwise_accuracy"]),
            tie_rank[float(row["c"])],
        ),
    )
    return float(selected["c"])


def nearest_higher_quantile(values: Sequence[float], quantile: float) -> float:
    if not values or not 0 <= quantile <= 1:
        raise ValueError("invalid quantile input")
    ordered = sorted(float(value) for value in values)
    index = max(0, math.ceil(quantile * len(ordered)) - 1)
    return ordered[index]


_WORKER_CLASSIFIER: FSPRModel | None = None


def _init_calibration_worker(weights: Sequence[float], intercept: float) -> None:
    global _WORKER_CLASSIFIER
    _WORKER_CLASSIFIER = FSPRModel(
        weights=tuple(float(value) for value in weights),
        intercept=float(intercept),
        threshold=0.0,
        selected_c=0.0,
        model_sha256="prelock",
    )


def _calibration_worker(item: tuple[dict[str, object], str]) -> dict[str, object]:
    record, input_root = item
    if _WORKER_CLASSIFIER is None:
        raise RuntimeError("FSPR calibration worker was not initialized")
    path = Path(input_root) / str(record["relative_path"])
    if sha256_file(path) != record["workbook_sha256"]:
        raise ValueError(f"SpreadsheetBench v1 workbook hash changed: {record['workbook_id']}")
    model = WorkbookModel.from_xlsx(path)
    v4 = v4_scores(model)
    ranking = [row.cell_label for row in v4]
    logits = workbook_logits(model, _WORKER_CLASSIFIER)
    v4_rank = {cell: index for index, cell in enumerate(ranking)}
    eligible = [cell for cell in ranking[V4_PREFIX:] if cell in logits]
    candidate = (
        min(eligible, key=lambda cell: (-float(logits[cell]), v4_rank[cell]))
        if eligible
        else None
    )
    return {
        "workbook_id": record["workbook_id"],
        "workbook_sha256": record["workbook_sha256"],
        "structure_group": record["template_group_id"],
        "split": record["split"],
        "formula_count": len(ranking),
        "eligible_formula_count": len(eligible),
        "candidate": candidate,
        "candidate_logit": float(logits[candidate]) if candidate else None,
        "v4_fifth": ranking[V4_PREFIX] if len(ranking) > V4_PREFIX else None,
        "candidate_differs_from_v4_fifth": bool(
            candidate is not None
            and len(ranking) > V4_PREFIX
            and candidate != ranking[V4_PREFIX]
        ),
    }


def load_calibration_sources(
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
) -> list[dict[str, object]]:
    expected = {
        corpus_manifest: EXPECTED_CORPUS_MANIFEST_SHA256,
        corpus_receipt: EXPECTED_CORPUS_RECEIPT_SHA256,
        intake_manifest: EXPECTED_INTAKE_MANIFEST_SHA256,
    }
    for path, digest in expected.items():
        if sha256_file(path) != digest:
            raise ValueError(f"frozen SpreadsheetBench v1 input changed: {path.name}")
    receipt = json.loads(corpus_receipt.read_text(encoding="ascii"))
    if receipt.get("fault_label_inputs") != [] or receipt.get("answer_workbook_inputs") != []:
        raise ValueError("SpreadsheetBench v1 corpus receipt violates input-only boundary")
    manifest = json.loads(corpus_manifest.read_text(encoding="ascii"))
    rows = manifest.get("workbooks")
    if not isinstance(rows, list):
        raise TypeError("SpreadsheetBench v1 corpus manifest is malformed")
    selected = [
        dict(row)
        for row in rows
        if row.get("status") == "eligible"
        and row.get("split") in {"calibration", "internal_test"}
    ]
    groups: dict[str, set[str]] = defaultdict(set)
    for row in selected:
        groups[str(row["split"])].add(str(row["template_group_id"]))
    if {split: len(values) for split, values in groups.items()} != {
        "calibration": 33,
        "internal_test": 33,
    }:
        raise ValueError("SpreadsheetBench v1 calibration group counts changed")
    return selected


def write_json(path: Path, payload: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


def write_jsonl(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="ascii", newline="\n") as handle:
        for row in rows:
            handle.write(
                json.dumps(row, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
                + "\n"
            )
    os.replace(temporary, path)


def train(
    *,
    dataset: Path,
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
    input_root: Path,
    output: Path,
    workers: int,
) -> dict[str, object]:
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    require_clean_tracked_worktree()
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="ascii"))
    if preregistration.get("protocol") != PROTOCOL:
        raise ValueError("FSPR preregistration protocol changed")
    if preregistration.get("formal_version_authorized") is not False:
        raise ValueError("FSPR preregistration improperly authorizes a version")

    rows, group_ids, pair_folds = load_pairs(dataset)
    tokenized = tokenized_examples(rows)
    labels = np.tile(np.asarray((1, 0), dtype=np.int64), len(rows))
    matrices = {
        view: dense_matrix(tokenized, view=view)
        for view in ("full", "syntax_only", "context_only")
    }
    c_metrics = []
    c_scores: dict[float, np.ndarray] = {}
    for c_value in C_VALUES:
        metrics, scores = cross_validate(
            matrices["full"], labels, pair_folds, c_value=c_value
        )
        c_metrics.append(metrics)
        c_scores[c_value] = scores
    selected_c = select_c(c_metrics)
    view_metrics = {}
    view_scores = {}
    for view, matrix in matrices.items():
        metrics, scores = cross_validate(
            matrix, labels, pair_folds, c_value=selected_c
        )
        view_metrics[view] = metrics
        view_scores[view] = scores

    classifier = fit_classifier(matrices["full"], labels, selected_c)
    weights = classifier.coef_[0].astype(np.float64)
    intercept = float(classifier.intercept_[0])
    pure = FSPRModel(
        weights=tuple(float(value) for value in weights),
        intercept=intercept,
        threshold=0.0,
        selected_c=selected_c,
        model_sha256="prelock",
    )
    reproduced = np.asarray(
        [pure.decision_value(*tokens) for tokens in tokenized],
        dtype=np.float64,
    )
    sklearn_scores = classifier.decision_function(matrices["full"])
    maximum_inference_delta = float(np.max(np.abs(reproduced - sklearn_scores)))

    sources = load_calibration_sources(corpus_manifest, corpus_receipt, intake_manifest)
    with concurrent.futures.ProcessPoolExecutor(
        max_workers=workers,
        initializer=_init_calibration_worker,
        initargs=(weights, intercept),
    ) as executor:
        records = list(
            executor.map(
                _calibration_worker,
                [(record, str(input_root.resolve())) for record in sources],
            )
        )
    records.sort(key=lambda row: str(row["workbook_id"]))
    calibration_scores = [
        float(row["candidate_logit"])
        for row in records
        if row["split"] == "calibration" and row["candidate_logit"] is not None
    ]
    threshold = nearest_higher_quantile(calibration_scores, THRESHOLD_QUANTILE)
    for row in records:
        row["would_change"] = bool(
            row["candidate_differs_from_v4_fifth"]
            and row["candidate_logit"] is not None
            and float(row["candidate_logit"]) >= threshold
        )
    split_counts = Counter(str(row["split"]) for row in records)
    action_counts = Counter(
        str(row["split"]) for row in records if bool(row["would_change"])
    )
    internal_action_rate = action_counts["internal_test"] / split_counts["internal_test"]
    group_fold_sets: dict[str, set[int]] = defaultdict(set)
    for group_id, fold in zip(group_ids, pair_folds):
        group_fold_sets[group_id].add(fold)

    full_metrics = view_metrics["full"]
    gate = {
        "g1_all_pairs_and_groups_retained": len(rows) == EXPECTED_PAIRS
        and len(group_ids) == EXPECTED_PAIRS
        and all(len(folds) == 1 for folds in group_fold_sets.values()),
        "g2_pairwise_accuracy": float(full_metrics["pairwise_accuracy"]) >= 0.75,
        "g2_roc_auc": float(full_metrics["roc_auc"]) >= 0.80,
        "g2_fold_stability": int(full_metrics["folds_at_or_above_0_70"]) >= 4,
        "g3_full_not_lower_than_ablations": all(
            float(full_metrics["pairwise_accuracy"])
            >= float(view_metrics[view]["pairwise_accuracy"])
            for view in ("syntax_only", "context_only")
        ),
        "g4_pure_python_inference": maximum_inference_delta <= 1e-10,
        "g5_internal_test_action_rate": internal_action_rate <= 0.15,
        "g5_zero_forbidden_inputs": True,
    }
    gate["all_single_process_gates_passed"] = all(gate.values())

    output.mkdir(parents=True, exist_ok=True)
    allowed = {
        "calibration_records.jsonl",
        "label_free_receipt.json",
        "model.json",
        "oof_predictions.jsonl",
    }
    if {path.name for path in output.iterdir()} - allowed:
        raise ValueError("FSPR output directory contains unexpected files")
    oof_rows = []
    selected_scores = view_scores["full"]
    for index, (group_id, fold) in enumerate(zip(group_ids, pair_folds)):
        oof_rows.append(
            {
                "pair_id": "fspr-pair:" + stable_hash(index),
                "leakage_group": group_id,
                "fold": fold,
                "faulty_logit": float(selected_scores[index * 2]),
                "correct_logit": float(selected_scores[index * 2 + 1]),
                "pairwise_correct": bool(
                    selected_scores[index * 2] > selected_scores[index * 2 + 1]
                ),
            }
        )
    write_jsonl(output / "oof_predictions.jsonl", oof_rows)
    write_jsonl(output / "calibration_records.jsonl", records)

    model_payload = {
        "protocol": PROTOCOL,
        "model_version": "v5-fspr1-candidate",
        "architecture": ARCHITECTURE,
        "tokenizer_version": TOKENIZER_VERSION,
        "dimensions": DIMENSIONS,
        "selected_c": selected_c,
        "intercept": intercept,
        "weights": [float(value) for value in weights],
        "threshold": threshold,
        "threshold_quantile": THRESHOLD_QUANTILE,
        "threshold_quantile_method": "higher",
        "training_dataset_sha256": EXPECTED_DATASET_SHA256,
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "git_commit": git_commit(),
    }
    write_json(output / "model.json", model_payload)
    receipt = {
        "protocol": "formulaguard_fspr_label_free_gate_v1",
        "complete": True,
        "git_commit": git_commit(),
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "training_dataset_sha256": EXPECTED_DATASET_SHA256,
        "pairs": len(rows),
        "leakage_groups": len(set(group_ids)),
        "fold_pair_counts": dict(sorted(Counter(pair_folds).items())),
        "model_input_fields": sorted(MODEL_FIELDS),
        "forbidden_model_input_fields": [],
        "c_metrics": c_metrics,
        "selected_c": selected_c,
        "view_metrics": view_metrics,
        "maximum_pure_python_inference_delta": maximum_inference_delta,
        "calibration": {
            "workbooks": split_counts["calibration"],
            "threshold_samples": len(calibration_scores),
            "threshold": threshold,
            "action_workbooks": action_counts["calibration"],
            "action_rate": action_counts["calibration"] / split_counts["calibration"],
        },
        "internal_test": {
            "workbooks": split_counts["internal_test"],
            "action_workbooks": action_counts["internal_test"],
            "action_rate": internal_action_rate,
        },
        "model_sha256": sha256_file(output / "model.json"),
        "oof_predictions_sha256": sha256_file(output / "oof_predictions.jsonl"),
        "calibration_records_sha256": sha256_file(output / "calibration_records.jsonl"),
        "gates": gate,
        "fault_label_inputs": [],
        "revealed_localization_inputs": [],
        "answer_workbook_inputs": [],
        "task_text_inputs": [],
        "protected_data_inputs": [],
    }
    write_json(output / "label_free_receipt.json", receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS_MANIFEST)
    parser.add_argument("--corpus-receipt", type=Path, default=DEFAULT_CORPUS_RECEIPT)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args()
    receipt = train(
        dataset=args.dataset.resolve(),
        corpus_manifest=args.corpus_manifest.resolve(),
        corpus_receipt=args.corpus_receipt.resolve(),
        intake_manifest=args.intake_manifest.resolve(),
        input_root=args.input_root.resolve(),
        output=args.output.resolve(),
        workers=args.workers,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
