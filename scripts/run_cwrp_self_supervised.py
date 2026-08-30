"""Run the preregistered CWRP masked-formula feasibility gates."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from statistics import fmean
from typing import Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.cwrp import (  # noqa: E402
    MASKED_EXAMPLE_PROTOCOL,
    MAX_TARGETS_PER_WORKBOOK,
    masked_formula_examples,
    stable_hash,
)
from formulaguard.workbook import WorkbookModel  # noqa: E402
from scripts.acquire_cwrp_sheetjs import sha256  # noqa: E402
from scripts.build_cwrp_corpus import PROTOCOL as CORPUS_PROTOCOL  # noqa: E402
from scripts.convert_cwrp_sheetjs import write_json_atomic  # noqa: E402


PROTOCOL = "formulaguard_cwrp_self_supervised_v1"
DEFAULT_CORPUS = ROOT / "results/cwrp_corpus_v1"
DEFAULT_SOURCE = ROOT / "data/external/model_discovery/converted/sheetjs_enron"
DEFAULT_OUTPUT = ROOT / "results/cwrp_self_supervised_v1"
MAX_WORKERS = 24
LEVELS = ("exact", "role", "coarse")
MIN_CONTEXT_GROUP_SUPPORT = 3
MIN_CONTEXT_EXAMPLES = 5
SMOOTHING_ALPHA = 1.0
CALIBRATION_TARGET_TOP5 = 0.60
EXAMPLE_FIELDS = {
    "protocol",
    "example_id",
    "workbook_id",
    "template_group_id",
    "outer_fold",
    "target_fingerprint",
    "context_keys",
    "local_peer_candidates",
    "locally_unsupported",
    "sensitive_text_features",
    "raw_numeric_features",
    "sheet_name_features",
    "target_formula_features",
}


def _git_commit() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True,
        capture_output=True, text=True,
    )
    return completed.stdout.strip()


def _safe_path(value: str, source_root: Path) -> Path:
    if not value or "\\" in value:
        raise ValueError(f"invalid corpus path: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower() != ".xlsx":
        raise ValueError(f"unsafe corpus path: {value!r}")
    if not relative.parts or relative.parts[0] != "nuix":
        raise ValueError(f"corpus path is outside nuix/: {value!r}")
    path = source_root.joinpath(*relative.parts).resolve()
    if source_root.resolve() not in path.parents or not path.is_file() or path.is_symlink():
        raise ValueError(f"corpus workbook is missing or unsafe: {value!r}")
    return path


def read_corpus(corpus_dir: Path, source_root: Path) -> tuple[list[dict[str, object]], dict[str, object]]:
    receipt_path = corpus_dir / "corpus_receipt.json"
    manifest_path = corpus_dir / "corpus_manifest.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if receipt.get("protocol") != CORPUS_PROTOCOL or not receipt.get("complete"):
        raise ValueError("corpus receipt is incomplete or has the wrong protocol")
    if receipt.get("corpus_manifest_sha256") != sha256(manifest_path):
        raise ValueError("corpus manifest hash differs from receipt")
    workbooks = manifest.get("workbooks")
    if not isinstance(workbooks, list):
        raise ValueError("corpus manifest has no workbook list")
    rows = []
    seen: set[str] = set()
    group_folds: dict[str, int] = {}
    for item in workbooks:
        if not isinstance(item, dict) or item.get("excluded_target_overlap_component"):
            continue
        workbook_id = str(item.get("workbook_id", ""))
        group_id = str(item.get("template_group_id", ""))
        fold = item.get("outer_fold")
        if not workbook_id or workbook_id in seen or not group_id or fold not in range(5):
            raise ValueError(f"invalid retained corpus row: {workbook_id!r}")
        seen.add(workbook_id)
        if group_id in group_folds and group_folds[group_id] != fold:
            raise ValueError(f"template group crosses outer folds: {group_id}")
        group_folds[group_id] = int(fold)
        path = _safe_path(str(item.get("relative_path", "")), source_root)
        if sha256(path) != item.get("workbook_sha256"):
            raise ValueError(f"retained workbook hash mismatch: {workbook_id}")
        rows.append({
            "workbook_id": workbook_id,
            "template_group_id": group_id,
            "outer_fold": int(fold),
            "path": path,
            "relative_path": str(item["relative_path"]),
            "workbook_sha256": str(item["workbook_sha256"]),
            "parseable_formula_count": int(item["parseable_formula_count"]),
        })
    if len(rows) != receipt.get("retained_workbooks"):
        raise ValueError("retained workbook count differs from corpus receipt")
    return sorted(rows, key=lambda row: str(row["workbook_id"])), receipt


def _shard_name(workbook_id: str) -> str:
    return hashlib.sha256(workbook_id.encode("utf-8")).hexdigest() + ".json"


def _example_worker(payload: tuple[dict[str, object], int]) -> dict[str, object]:
    row, max_targets = payload
    path = Path(str(row["path"]))
    if sha256(path) != row["workbook_sha256"]:
        raise ValueError(f"workbook changed before example extraction: {row['workbook_id']}")
    examples = masked_formula_examples(
        WorkbookModel.from_xlsx(path),
        workbook_id=str(row["workbook_id"]),
        template_group_id=str(row["template_group_id"]),
        outer_fold=int(row["outer_fold"]),
        max_targets=max_targets,
    )
    return {
        "protocol": PROTOCOL,
        "workbook_id": row["workbook_id"],
        "workbook_sha256": row["workbook_sha256"],
        "examples": examples,
    }


def _validate_example(example: Mapping[str, object], expected: Mapping[str, object]) -> None:
    if set(example) != EXAMPLE_FIELDS:
        unexpected = sorted(set(example) - EXAMPLE_FIELDS)
        missing = sorted(EXAMPLE_FIELDS - set(example))
        raise ValueError(
            f"masked example schema mismatch: unexpected={unexpected}; missing={missing}"
        )
    if (
        example.get("protocol") != MASKED_EXAMPLE_PROTOCOL
        or example.get("workbook_id") != expected["workbook_id"]
        or example.get("template_group_id") != expected["template_group_id"]
        or example.get("outer_fold") != expected["outer_fold"]
    ):
        raise ValueError(f"masked example identity mismatch: {example.get('example_id')}")
    keys = example.get("context_keys")
    if not isinstance(keys, dict) or set(keys) != set(LEVELS):
        raise ValueError("masked example has invalid context keys")
    if any(not isinstance(keys[level], str) or len(keys[level]) != 64 for level in LEVELS):
        raise ValueError("masked example context key is not a SHA-256")
    if not isinstance(example.get("target_fingerprint"), str):
        raise ValueError("masked example target fingerprint is missing")
    local_candidates = example.get("local_peer_candidates")
    if not isinstance(local_candidates, list) or len(local_candidates) > 5:
        raise ValueError("masked example has invalid local peer candidates")
    for candidate in local_candidates:
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"fingerprint", "count"}
            or not isinstance(candidate.get("fingerprint"), str)
            or not isinstance(candidate.get("count"), int)
            or int(candidate["count"]) < 1
        ):
            raise ValueError("masked example has malformed local peer candidate")
    if not isinstance(example.get("locally_unsupported"), bool):
        raise ValueError("masked example has invalid sparse-target flag")
    if any(example.get(key) != 0 for key in (
        "sensitive_text_features", "raw_numeric_features", "sheet_name_features",
        "target_formula_features",
    )):
        raise ValueError("masked example exports a forbidden feature")


def _validate_shard(path: Path, expected: Mapping[str, object]) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if (
        record.get("protocol") != PROTOCOL
        or record.get("workbook_id") != expected["workbook_id"]
        or record.get("workbook_sha256") != expected["workbook_sha256"]
    ):
        raise ValueError(f"example shard identity mismatch: {path.name}")
    examples = record.get("examples")
    if not isinstance(examples, list) or len(examples) > MAX_TARGETS_PER_WORKBOOK:
        raise ValueError(f"example shard has invalid target count: {path.name}")
    ids = []
    for example in examples:
        if not isinstance(example, dict):
            raise ValueError(f"example shard row is malformed: {path.name}")
        _validate_example(example, expected)
        ids.append(str(example["example_id"]))
    if ids != sorted(ids) or len(ids) != len(set(ids)):
        raise ValueError(f"example IDs are not sorted and unique: {path.name}")
    return record


class HierarchicalRolePrior:
    """Template-balanced hierarchical count prior fixed by the protocol."""

    def __init__(self, examples: Sequence[Mapping[str, object]]):
        if not examples:
            raise ValueError("role prior requires training examples")
        self.by_level: dict[str, dict[str, dict[str, Counter[str]]]] = {
            level: defaultdict(lambda: defaultdict(Counter)) for level in LEVELS
        }
        self.global_by_group: dict[str, Counter[str]] = defaultdict(Counter)
        for example in sorted(examples, key=lambda row: str(row["example_id"])):
            group = str(example["template_group_id"])
            target = str(example["target_fingerprint"])
            self.global_by_group[group][target] += 1
            keys = example["context_keys"]
            for level in LEVELS:
                self.by_level[level][str(keys[level])][group][target] += 1  # type: ignore[index]
        self.global_probabilities = self._group_balanced(self.global_by_group)

    @staticmethod
    def _group_balanced(group_counts: Mapping[str, Counter[str]]) -> dict[str, float]:
        scores: Counter[str] = Counter()
        groups = 0
        for group in sorted(group_counts):
            counter = group_counts[group]
            total = sum(counter.values())
            if total <= 0:
                continue
            groups += 1
            for target, count in counter.items():
                scores[target] += count / total
        if not groups:
            return {}
        return {target: value / groups for target, value in scores.items()}

    def _distribution(self, level: str, key: str) -> tuple[dict[str, float], int, int]:
        group_counts = self.by_level[level].get(key, {})
        support = len(group_counts)
        examples = sum(sum(counter.values()) for counter in group_counts.values())
        contextual = self._group_balanced(group_counts)
        targets = set(contextual) | set(self.global_probabilities)
        probabilities = {
            target: (
                support * contextual.get(target, 0.0)
                + SMOOTHING_ALPHA * self.global_probabilities.get(target, 0.0)
            ) / (support + SMOOTHING_ALPHA)
            for target in targets
        }
        return probabilities, support, examples

    @staticmethod
    def _top5(probabilities: Mapping[str, float]) -> tuple[list[str], float]:
        ordered = sorted(probabilities, key=lambda target: (-probabilities[target], target))[:5]
        return ordered, sum(probabilities[target] for target in ordered)

    def predict(self, example: Mapping[str, object]) -> dict[str, object]:
        keys = example["context_keys"]
        for level in LEVELS:
            probabilities, support, count = self._distribution(level, str(keys[level]))  # type: ignore[index]
            if support >= MIN_CONTEXT_GROUP_SUPPORT and count >= MIN_CONTEXT_EXAMPLES:
                top5, confidence = self._top5(probabilities)
                return {
                    "top5": top5,
                    "top5_probability": round(confidence, 12),
                    "support_groups": support,
                    "support_examples": count,
                    "level": level,
                }
        top5, confidence = self._top5(self.global_probabilities)
        return {
            "top5": top5,
            "top5_probability": round(confidence, 12),
            "support_groups": 0,
            "support_examples": 0,
            "level": "global_fallback",
        }

    def predict_context_baseline(self, example: Mapping[str, object]) -> dict[str, object]:
        key = str(example["context_keys"]["coarse"])  # type: ignore[index]
        probabilities, support, count = self._distribution("coarse", key)
        if support:
            top5, confidence = self._top5(probabilities)
            return {
                "top5": top5, "top5_probability": round(confidence, 12),
                "support_groups": support, "support_examples": count,
            }
        top5, confidence = self._top5(self.global_probabilities)
        return {
            "top5": top5, "top5_probability": round(confidence, 12),
            "support_groups": 0, "support_examples": 0,
        }

    def predict_global_baseline(self) -> dict[str, object]:
        top5, confidence = self._top5(self.global_probabilities)
        return {"top5": top5, "top5_probability": round(confidence, 12)}


def permute_training_targets(
    examples: Sequence[Mapping[str, object]],
    *,
    seed: str,
) -> list[dict[str, object]]:
    ordered = sorted(examples, key=lambda row: str(row["example_id"]))
    if len(ordered) < 2:
        return [dict(row) for row in ordered]
    offset = int(stable_hash(seed)[:16], 16) % (len(ordered) - 1) + 1
    targets = [str(row["target_fingerprint"]) for row in ordered]
    rotated = targets[offset:] + targets[:offset]
    return [{**row, "target_fingerprint": target} for row, target in zip(ordered, rotated)]


def _is_hit(prediction: Mapping[str, object], target: str) -> int:
    return int(target in prediction.get("top5", []))


def select_support_threshold(
    predictions: Sequence[Mapping[str, object]],
    *,
    target_accuracy: float = CALIBRATION_TARGET_TOP5,
) -> dict[str, object]:
    if not predictions:
        raise ValueError("support calibration requires predictions")
    supports = sorted({int(row["candidate"]["support_groups"]) for row in predictions})  # type: ignore[index]
    supports = [value for value in supports if value > 0]
    candidates = []
    for threshold in supports:
        selected = [
            row for row in predictions
            if int(row["candidate"]["support_groups"]) >= threshold  # type: ignore[index]
        ]
        accuracy = fmean(int(row["candidate_hit"]) for row in selected) if selected else 0.0
        if accuracy >= target_accuracy:
            candidates.append((len(selected), accuracy, -threshold, threshold))
    if candidates:
        selected_count, accuracy, _, threshold = max(candidates)
        return {
            "threshold": threshold,
            "calibration_selected": selected_count,
            "calibration_coverage": selected_count / len(predictions),
            "calibration_top5": accuracy,
            "target_top5": target_accuracy,
            "feasible": True,
        }
    threshold = max(supports, default=0) + 1
    return {
        "threshold": threshold,
        "calibration_selected": 0,
        "calibration_coverage": 0.0,
        "calibration_top5": 0.0,
        "target_top5": target_accuracy,
        "feasible": False,
    }


def _predict_rows(
    model: HierarchicalRolePrior,
    examples: Sequence[Mapping[str, object]],
    *,
    placebo: HierarchicalRolePrior | None = None,
) -> list[dict[str, object]]:
    global_prediction = model.predict_global_baseline()
    rows = []
    for example in sorted(examples, key=lambda row: str(row["example_id"])):
        target = str(example["target_fingerprint"])
        candidate = model.predict(example)
        context = model.predict_context_baseline(example)
        local = {
            "top5": [
                str(item["fingerprint"])
                for item in example["local_peer_candidates"]  # type: ignore[union-attr]
            ]
        }
        placebo_prediction = placebo.predict(example) if placebo is not None else {"top5": []}
        rows.append({
            "example_id": example["example_id"],
            "workbook_id": example["workbook_id"],
            "template_group_id": example["template_group_id"],
            "outer_fold": example["outer_fold"],
            "locally_unsupported": example["locally_unsupported"],
            "target_fingerprint": target,
            "candidate": candidate,
            "candidate_hit": _is_hit(candidate, target),
            "global": global_prediction,
            "global_hit": _is_hit(global_prediction, target),
            "context": context,
            "context_hit": _is_hit(context, target),
            "local": local,
            "local_hit": _is_hit(local, target),
            "placebo": placebo_prediction,
            "placebo_hit": _is_hit(placebo_prediction, target),
        })
    return rows


def evaluate_examples(examples: Sequence[Mapping[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    folds = {int(row["outer_fold"]) for row in examples}
    if folds != set(range(5)):
        raise ValueError(f"masked examples do not cover five folds: {sorted(folds)}")
    predictions = []
    calibrations = []
    for test_fold in range(5):
        calibration_fold = (test_fold + 1) % 5
        train_folds = set(range(5)) - {test_fold, calibration_fold}
        training = [row for row in examples if int(row["outer_fold"]) in train_folds]
        calibration_examples = [row for row in examples if int(row["outer_fold"]) == calibration_fold]
        test_examples = [row for row in examples if int(row["outer_fold"]) == test_fold]
        train_groups = {str(row["template_group_id"]) for row in training}
        calibration_groups = {str(row["template_group_id"]) for row in calibration_examples}
        test_groups = {str(row["template_group_id"]) for row in test_examples}
        if train_groups & calibration_groups or train_groups & test_groups or calibration_groups & test_groups:
            raise ValueError("template group crosses train/calibration/test roles")
        model = HierarchicalRolePrior(training)
        placebo = HierarchicalRolePrior(
            permute_training_targets(training, seed=f"cwrp-placebo-fold-{test_fold}")
        )
        calibration_rows = _predict_rows(model, calibration_examples)
        threshold = select_support_threshold(calibration_rows)
        test_rows = _predict_rows(model, test_examples, placebo=placebo)
        for row in test_rows:
            row["selected"] = int(
                int(row["candidate"]["support_groups"]) >= int(threshold["threshold"])  # type: ignore[index]
            )
        predictions.extend(test_rows)
        calibrations.append({
            "test_fold": test_fold,
            "calibration_fold": calibration_fold,
            "train_folds": sorted(train_folds),
            "train_template_groups": len(train_groups),
            "calibration_template_groups": len(calibration_groups),
            "test_template_groups": len(test_groups),
            **threshold,
        })
    predictions.sort(key=lambda row: str(row["example_id"]))
    return predictions, calibrations


def _macro(rows: Sequence[Mapping[str, object]], group_key: str, hit_key: str) -> float:
    grouped: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        grouped[str(row[group_key])].append(int(row[hit_key]))
    return fmean(fmean(values) for values in grouped.values()) if grouped else 0.0


def _method_metrics(rows: Sequence[Mapping[str, object]], hit_key: str) -> dict[str, float]:
    return {
        "micro_top5": fmean(int(row[hit_key]) for row in rows) if rows else 0.0,
        "workbook_macro_top5": _macro(rows, "workbook_id", hit_key),
        "template_group_macro_top5": _macro(rows, "template_group_id", hit_key),
    }


def _ece(rows: Sequence[Mapping[str, object]]) -> float:
    if not rows:
        return 1.0
    bins: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for row in rows:
        confidence = float(row["candidate"]["top5_probability"])  # type: ignore[index]
        index = min(9, max(0, int(confidence * 10)))
        bins[index].append((confidence, int(row["candidate_hit"])))
    return sum(
        len(values) / len(rows)
        * abs(fmean(value[0] for value in values) - fmean(value[1] for value in values))
        for values in bins.values()
    )


def summarize(
    predictions: Sequence[Mapping[str, object]],
    calibrations: Sequence[Mapping[str, object]],
    *,
    corpus_receipt: Mapping[str, object],
    deterministic_repeat: bool,
) -> dict[str, object]:
    methods = {
        "cwrp": _method_metrics(predictions, "candidate_hit"),
        "global_frequency": _method_metrics(predictions, "global_hit"),
        "context_frequency": _method_metrics(predictions, "context_hit"),
        "local_peer": _method_metrics(predictions, "local_hit"),
        "permuted_target_placebo": _method_metrics(predictions, "placebo_hit"),
    }
    local_coverage = fmean(int(bool(row["local"]["top5"])) for row in predictions)  # type: ignore[index]
    selected = [row for row in predictions if row["selected"]]
    sparse = [row for row in predictions if row["locally_unsupported"]]
    sparse_selected = [row for row in sparse if row["selected"]]
    fold_deltas = []
    for fold in range(5):
        rows = [row for row in predictions if row["outer_fold"] == fold]
        candidate = _macro(rows, "workbook_id", "candidate_hit")
        baseline = _macro(rows, "workbook_id", "global_hit")
        fold_deltas.append({
            "fold": fold,
            "cwrp_workbook_macro_top5": candidate,
            "global_workbook_macro_top5": baseline,
            "delta": candidate - baseline,
        })
    cwrp = methods["cwrp"]
    global_frequency = methods["global_frequency"]
    context_frequency = methods["context_frequency"]
    placebo = methods["permuted_target_placebo"]
    sparse_workbooks = len({str(row["workbook_id"]) for row in sparse})
    retained = int(corpus_receipt["retained_workbooks"])
    retained_formulas = int(corpus_receipt["retained_parseable_formulas"])
    fold_groups_ok = all(
        int(values["template_groups"]) >= 10
        for values in corpus_receipt["folds"].values()  # type: ignore[union-attr]
    )
    u0 = {
        "min_100_workbooks": retained >= 100,
        "min_10000_parseable_formulas": retained_formulas >= 10000,
        "min_50_sparse_workbooks": sparse_workbooks >= 50,
        "min_1000_sparse_targets": len(sparse) >= 1000,
        "min_10_template_groups_each_test_fold": fold_groups_ok,
        "zero_sensitive_text_features": True,
        "zero_fault_label_inputs": True,
    }
    sparse_coverage = len(sparse_selected) / len(sparse) if sparse else 0.0
    sparse_accuracy = fmean(int(row["candidate_hit"]) for row in sparse_selected) if sparse_selected else 0.0
    u1 = {
        "top5_gain_vs_global_at_least_10pp": (
            cwrp["workbook_macro_top5"] - global_frequency["workbook_macro_top5"] >= 0.10
        ),
        "top5_gain_vs_context_at_least_5pp": (
            cwrp["workbook_macro_top5"] - context_frequency["workbook_macro_top5"] >= 0.05
        ),
        "sparse_coverage_at_least_20pct": sparse_coverage >= 0.20,
        "sparse_selective_top5_at_least_60pct": sparse_accuracy >= 0.60,
        "at_least_four_positive_outer_folds": sum(row["delta"] > 0 for row in fold_deltas) >= 4,
        "template_group_macro_direction_positive": (
            cwrp["template_group_macro_top5"] > global_frequency["template_group_macro_top5"]
        ),
    }
    selected_coverage = len(selected) / len(predictions) if predictions else 0.0
    selected_accuracy = fmean(int(row["candidate_hit"]) for row in selected) if selected else 0.0
    selected_ece = _ece(selected)
    u2 = {
        "selective_top5_at_least_60pct": selected_accuracy >= 0.60,
        "coverage_at_least_20pct": selected_coverage >= 0.20,
        "ece_at_most_0_10": selected_ece <= 0.10,
        "permutation_drop_at_least_10pp": (
            cwrp["workbook_macro_top5"] - placebo["workbook_macro_top5"] >= 0.10
        ),
        "deterministic_prediction_hash": deterministic_repeat,
    }
    return {
        "examples": len(predictions),
        "sparse_examples": len(sparse),
        "sparse_workbooks": sparse_workbooks,
        "methods": methods,
        "local_peer_coverage": local_coverage,
        "calibrations": list(calibrations),
        "selective": {
            "selected": len(selected),
            "coverage": selected_coverage,
            "top5": selected_accuracy,
            "ece_10_bins": selected_ece,
        },
        "sparse_selective": {
            "selected": len(sparse_selected),
            "coverage": sparse_coverage,
            "top5": sparse_accuracy,
        },
        "fold_deltas": fold_deltas,
        "gates": {
            "u0": {"checks": u0, "passed": all(u0.values())},
            "u1": {"checks": u1, "passed": all(u1.values())},
            "u2": {"checks": u2, "passed": all(u2.values())},
        },
    }


def _write_jsonl_atomic(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def run(
    *,
    corpus_dir: Path,
    source_root: Path,
    output_dir: Path,
    workers: int,
    resume: bool = False,
) -> Path:
    corpus_dir = corpus_dir.resolve()
    source_root = source_root.resolve()
    output_dir = output_dir.resolve()
    if not 1 <= workers <= MAX_WORKERS:
        raise ValueError(f"workers must be between 1 and {MAX_WORKERS}")
    workbooks, corpus_receipt = read_corpus(corpus_dir, source_root)
    complete_path = output_dir / "self_supervised_receipt.json"
    if complete_path.exists():
        raise ValueError("self-supervised run is complete; completed receipts are immutable")
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": _git_commit(),
        "corpus_receipt_sha256": sha256(corpus_dir / "corpus_receipt.json"),
        "corpus_manifest_sha256": corpus_receipt["corpus_manifest_sha256"],
        "workbooks": len(workbooks),
        "workers_requested": workers,
        "max_targets_per_workbook": MAX_TARGETS_PER_WORKBOOK,
        "levels": list(LEVELS),
        "min_context_group_support": MIN_CONTEXT_GROUP_SUPPORT,
        "min_context_examples": MIN_CONTEXT_EXAMPLES,
        "smoothing_alpha": SMOOTHING_ALPHA,
        "calibration_target_top5": CALIBRATION_TARGET_TOP5,
        "source_hashes": {
            "formulaguard/cwrp.py": sha256(ROOT / "formulaguard/cwrp.py"),
            "scripts/run_cwrp_self_supervised.py": sha256(Path(__file__).resolve()),
        },
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "v4_rank_inputs": [],
        "cell_text_features": False,
        "raw_numeric_features": False,
        "filename_features": False,
        "sheet_name_features": False,
    }
    metadata_path = output_dir / "metadata.json"
    if output_dir.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("partial self-supervised output exists; pass --resume after audit")
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("partial self-supervised metadata differs from this run")
    else:
        output_dir.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    shards = output_dir / "example_shards"
    shards.mkdir(exist_ok=True)
    records: dict[str, dict[str, object]] = {}
    pending = []
    for row in workbooks:
        shard = shards / _shard_name(str(row["workbook_id"]))
        if shard.exists():
            records[str(row["workbook_id"])] = _validate_shard(shard, row)
        else:
            pending.append(row)
    if pending:
        worker_count = min(workers, len(pending))
        print(
            f"CWRP masked-example scheduling: workers={worker_count}; "
            f"pending={len(pending)}; resumed={len(workbooks) - len(pending)}",
            flush=True,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = [
                executor.submit(_example_worker, (row, MAX_TARGETS_PER_WORKBOOK))
                for row in pending
            ]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                record = future.result()
                workbook_id = str(record["workbook_id"])
                row = next(item for item in workbooks if item["workbook_id"] == workbook_id)
                shard = shards / _shard_name(workbook_id)
                write_json_atomic(shard, record)
                records[workbook_id] = _validate_shard(shard, row)
                print(f"[{index}/{len(pending)}] {workbook_id}: {len(record['examples'])}", flush=True)
    examples = [
        example
        for row in workbooks
        for example in records[str(row["workbook_id"])]["examples"]  # type: ignore[union-attr]
    ]
    if not examples:
        raise ValueError("masked-example corpus is empty")
    example_ids = [str(row["example_id"]) for row in examples]
    if len(example_ids) != len(set(example_ids)):
        raise ValueError("masked example IDs are not globally unique")

    predictions, calibrations = evaluate_examples(examples)
    repeated_predictions, repeated_calibrations = evaluate_examples(examples)
    prediction_hash = stable_hash(predictions)
    repeated_hash = stable_hash(repeated_predictions)
    deterministic_repeat = (
        prediction_hash == repeated_hash
        and stable_hash(calibrations) == stable_hash(repeated_calibrations)
    )
    summary = summarize(
        predictions,
        calibrations,
        corpus_receipt=corpus_receipt,
        deterministic_repeat=deterministic_repeat,
    )
    predictions_path = output_dir / "predictions.jsonl"
    _write_jsonl_atomic(predictions_path, predictions)
    summary_path = output_dir / "gate_summary.json"
    write_json_atomic(summary_path, summary)
    receipt = {
        "protocol": PROTOCOL,
        "example_workbooks": len(workbooks),
        "examples": len(examples),
        "example_shards_sha256": stable_hash([
            (path.name, sha256(path)) for path in sorted(shards.glob("*.json"))
        ]),
        "prediction_sha256": sha256(predictions_path),
        "prediction_content_sha256": prediction_hash,
        "repeated_prediction_content_sha256": repeated_hash,
        "gate_summary_sha256": sha256(summary_path),
        "gates": summary["gates"],
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "v4_rank_inputs": [],
        "complete": len(predictions) == len(examples) and deterministic_repeat,
    }
    write_json_atomic(complete_path, receipt)
    return complete_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    try:
        receipt = run(
            corpus_dir=args.corpus,
            source_root=args.source,
            output_dir=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"CWRP self-supervised run refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
