#!/usr/bin/env python3
"""Extract label-free semantic anomaly margins for frozen V4 Top-100 cells."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import multiprocessing
import subprocess
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import torch

from formulaguard.fcrl import build_masked_context_input
from formulaguard.fcrl_torch import (
    FCRLTensorBatch,
    FCRLTokenizerRuntime,
    load_runtime,
    load_tokenizer_runtime,
    tensorize_tables,
)
from formulaguard.semantic_compatibility import (
    FormulaVocabulary,
    canonical_formula_role,
    semantic_candidate_roles,
)
from formulaguard.semantic_compatibility_torch import (
    SemanticCompatibilityHead,
    frozen_context_states,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_fcrl_u1_corpus import (
    DEFAULT_FORTAP_SOURCE,
    sha256_file,
    stable_hash,
    write_json_atomic,
)
from scripts.extract_semantic_compatibility_embeddings import DEFAULT_CHECKPOINT
from scripts.run_model_discovery_signals import read_profiles, shard_name
from scripts.train_semantic_compatibility import (
    DEFAULT_TARGET_RECEIPT,
    DEFAULT_VOCABULARY,
    load_vocabulary,
)
from scripts.train_semantic_compatibility import PROTOCOL as TRAINING_PROTOCOL

PROTOCOL = "formulaguard_semantic_public_scores_v3"
MAX_WORKERS = 24
GPU_BATCH_SIZE = 16
V4_SCOPE = 100
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_V4 = ROOT / "results/model_discovery_v4_baseline"
DEFAULT_TRAINING_RECEIPT = ROOT / "results/semantic_compatibility_training_v2/receipt.json"
DEFAULT_SELECTED_MODEL = ROOT / "results/semantic_compatibility_training_v2/selected_model.pt"
DEFAULT_OUTPUT = ROOT / "results/semantic_public_scores_v3"

_TOKENIZER_RUNTIME: FCRLTokenizerRuntime | None = None


def git_commit(path: Path = ROOT) -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def require_clean_tracked_worktree() -> None:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if completed.stdout.strip():
        raise ValueError("tracked worktree must be clean before public semantic extraction")


def _split_cell_key(cell: str) -> tuple[str, str]:
    if "!" not in cell:
        raise ValueError("V4 cell has no sheet separator")
    sheet, address = cell.rsplit("!", 1)
    if not sheet or not address:
        raise ValueError("V4 cell identity is incomplete")
    return sheet, address.upper()


def _load_v4_rows(
    profiles_path: Path,
    profiles: Sequence[Mapping[str, str]],
    v4_dir: Path,
) -> dict[str, tuple[str, ...]]:
    complete = json.loads((v4_dir / "complete.json").read_text(encoding="utf-8"))
    if (
        complete.get("protocol") != "formulaguard_model_discovery_v4_baseline_run_v1"
        or complete.get("complete") is not True
        or complete.get("profiles_sha256") != sha256_file(profiles_path)
        or complete.get("profile_count") != len(profiles)
        or complete.get("shard_count") != len(profiles)
        or complete.get("label_inputs_to_prediction") != []
    ):
        raise ValueError("frozen V4 baseline violates the semantic extraction contract")
    result = {}
    for profile in profiles:
        path = v4_dir / "shards" / shard_name(str(profile["unit_id"]))
        payload = json.loads(path.read_text(encoding="utf-8"))
        ranking = payload.get("ranking")
        if (
            payload.get("unit_id") != profile["unit_id"]
            or payload.get("workbook_sha256") != profile["workbook_sha256"]
            or payload.get("label_inputs") != []
            or not isinstance(ranking, list)
            or len(ranking) != payload.get("formula_count")
        ):
            raise ValueError("frozen V4 shard violates the semantic extraction contract")
        cells = tuple(str(row["cell"]) for row in ranking[:V4_SCOPE])
        if len(cells) != len(set(cells)):
            raise ValueError("frozen V4 Top-100 contains duplicate cells")
        result[str(profile["unit_id"])] = cells
    return result


def _init_worker(fortap_source: str) -> None:
    global _TOKENIZER_RUNTIME
    torch.set_num_threads(1)
    _TOKENIZER_RUNTIME = load_tokenizer_runtime(Path(fortap_source))


def _process_profile(
    profile: Mapping[str, str],
    v4_cells: Sequence[str],
) -> dict[str, object]:
    if _TOKENIZER_RUNTIME is None:
        raise RuntimeError("semantic public tokenizer worker is not initialized")
    model = WorkbookModel.from_xlsx(ROOT / profile["path"])
    tables = []
    records: list[dict[str, object]] = []
    batches: list[tuple[tuple[dict[str, object], ...], FCRLTensorBatch]] = []
    skipped_invisible = 0
    skipped_without_alternatives = 0
    for rank, cell in enumerate(v4_cells, 1):
        key = _split_cell_key(cell)
        if key not in model.formulas:
            raise ValueError(
                f"frozen V4 candidate is no longer a formula: "
                f"{profile['unit_id']} rank={rank} cell={cell}"
            )
        if not model.is_visible(key):
            skipped_invisible += 1
            continue
        observed_role = canonical_formula_role(model.formulas[key], key[1], key[0])
        alternatives = semantic_candidate_roles(model, key)
        if not alternatives:
            skipped_without_alternatives += 1
            continue
        candidate_roles = tuple(sorted({observed_role, *alternatives}))
        record = {
            "cell": cell,
            "v4_rank": rank,
            "observed_role": observed_role,
            "candidate_roles": candidate_roles,
            "observed_index": candidate_roles.index(observed_role),
            "fallback_role": observed_role.startswith("LEX("),
        }
        tables.append(build_masked_context_input(model, key))
        records.append(record)
        if len(tables) == GPU_BATCH_SIZE:
            batches.append((tuple(records), tensorize_tables(tables, _TOKENIZER_RUNTIME)))
            tables, records = [], []
    if tables:
        batches.append((tuple(records), tensorize_tables(tables, _TOKENIZER_RUNTIME)))
    return {
        "unit_id": profile["unit_id"],
        "workbook_sha256": profile["workbook_sha256"],
        "v4_scope_cells": len(v4_cells),
        "skipped_invisible": skipped_invisible,
        "skipped_without_alternatives": skipped_without_alternatives,
        "batches": batches,
    }


def _candidate_tensors(
    records: Sequence[Mapping[str, object]],
    vocabulary: FormulaVocabulary,
    device: torch.device,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    encoded = [
        [vocabulary.encode(str(role)) for role in record["candidate_roles"]]
        for record in records
    ]
    candidate_count = max(len(rows) for rows in encoded)
    sequence_length = max(len(tokens) for rows in encoded for tokens in rows)
    token_ids = torch.zeros(
        (len(records), candidate_count, sequence_length),
        dtype=torch.long,
        device=device,
    )
    lengths = torch.ones(
        (len(records), candidate_count),
        dtype=torch.long,
        device=device,
    )
    mask = torch.zeros(
        (len(records), candidate_count),
        dtype=torch.bool,
        device=device,
    )
    for row, candidates in enumerate(encoded):
        for column, tokens in enumerate(candidates):
            token_ids[row, column, : len(tokens)] = torch.tensor(tokens, device=device)
            lengths[row, column] = len(tokens)
            mask[row, column] = True
    return token_ids, lengths, mask


def _validate_score_shard(
    payload: Mapping[str, object],
    profile: Mapping[str, str],
    expected_v4_cells: Sequence[str],
) -> None:
    allowed_payload = {
        "protocol",
        "unit_id",
        "workbook_sha256",
        "v4_scope_cells",
        "scored_cells",
        "skipped_invisible",
        "skipped_without_alternatives",
        "scores",
        "label_inputs",
        "raw_formula_strings_persisted",
        "formula_roles_persisted",
    }
    scores = payload.get("scores")
    if (
        set(payload) != allowed_payload
        or payload.get("protocol") != PROTOCOL
        or payload.get("unit_id") != profile["unit_id"]
        or payload.get("workbook_sha256") != profile["workbook_sha256"]
        or payload.get("v4_scope_cells") != len(expected_v4_cells)
        or payload.get("label_inputs") != []
        or payload.get("raw_formula_strings_persisted") is not False
        or payload.get("formula_roles_persisted") is not False
        or not isinstance(scores, list)
        or not isinstance(payload.get("scored_cells"), int)
        or isinstance(payload.get("scored_cells"), bool)
        or payload.get("scored_cells") != len(scores)
        or not isinstance(payload.get("skipped_invisible"), int)
        or isinstance(payload.get("skipped_invisible"), bool)
        or int(payload["skipped_invisible"]) < 0
        or not isinstance(payload.get("skipped_without_alternatives"), int)
        or isinstance(payload.get("skipped_without_alternatives"), bool)
        or int(payload["skipped_without_alternatives"]) < 0
        or len(scores)
        + int(payload["skipped_invisible"])
        + int(payload["skipped_without_alternatives"])
        != len(expected_v4_cells)
    ):
        raise ValueError("semantic public score shard is invalid")
    allowed = {
        "cell",
        "v4_rank",
        "candidate_count",
        "semantic_anomaly_margin",
        "semantic_anomaly_confidence",
        "semantic_decision_margin",
        "semantic_observed_score",
        "semantic_best_alternative_score",
        "semantic_prefers_alternative",
        "fallback_role",
    }
    cells = set()
    ranks = set()
    previous_rank = 0
    for row in scores:
        rank = row.get("v4_rank") if isinstance(row, Mapping) else None
        candidate_count = row.get("candidate_count") if isinstance(row, Mapping) else None
        cell = row.get("cell") if isinstance(row, Mapping) else None
        margin = row.get("semantic_anomaly_margin") if isinstance(row, Mapping) else None
        anomaly_confidence = (
            row.get("semantic_anomaly_confidence") if isinstance(row, Mapping) else None
        )
        decision_margin = (
            row.get("semantic_decision_margin") if isinstance(row, Mapping) else None
        )
        observed_score = row.get("semantic_observed_score") if isinstance(row, Mapping) else None
        alternative_score = (
            row.get("semantic_best_alternative_score") if isinstance(row, Mapping) else None
        )
        if (
            not isinstance(row, Mapping)
            or set(row) != allowed
            or not isinstance(cell, str)
            or cell in cells
            or not isinstance(rank, int)
            or isinstance(rank, bool)
            or not 1 <= rank <= len(expected_v4_cells)
            or rank in ranks
            or rank <= previous_rank
            or cell != expected_v4_cells[rank - 1]
            or not isinstance(candidate_count, int)
            or isinstance(candidate_count, bool)
            or candidate_count < 2
            or not all(
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
                for value in (
                    margin,
                    anomaly_confidence,
                    decision_margin,
                    observed_score,
                    alternative_score,
                )
            )
            or not math.isclose(
                float(margin),
                float(alternative_score) - float(observed_score),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or float(decision_margin) < 0.0
            or not isinstance(row["semantic_prefers_alternative"], bool)
            or row["semantic_prefers_alternative"] is not (float(margin) > 0.0)
            or not math.isclose(
                float(anomaly_confidence),
                float(decision_margin)
                if row["semantic_prefers_alternative"]
                else -float(decision_margin),
                rel_tol=1e-12,
                abs_tol=1e-12,
            )
            or (
                row["semantic_prefers_alternative"]
                and float(decision_margin) > float(margin) + 1e-12
            )
            or (
                not row["semantic_prefers_alternative"]
                and not math.isclose(
                    float(decision_margin),
                    -float(margin),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            )
            or (
                candidate_count == 2
                and not math.isclose(
                    float(decision_margin),
                    abs(float(margin)),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                )
            )
            or not isinstance(row["fallback_role"], bool)
        ):
            raise ValueError("semantic public score row is invalid")
        cells.add(cell)
        ranks.add(rank)
        previous_rank = rank


def _completed_results(
    executor: concurrent.futures.ProcessPoolExecutor,
    tasks: Sequence[tuple[Mapping[str, str], Sequence[str]]],
    *,
    window: int,
) -> Iterable[dict[str, object]]:
    iterator = iter(tasks)
    pending: set[concurrent.futures.Future] = set()
    for _ in range(min(window, len(tasks))):
        profile, cells = next(iterator)
        pending.add(executor.submit(_process_profile, profile, cells))
    while pending:
        done, pending = concurrent.futures.wait(
            pending,
            return_when=concurrent.futures.FIRST_COMPLETED,
        )
        for future in done:
            yield future.result()
            try:
                profile, cells = next(iterator)
            except StopIteration:
                continue
            pending.add(executor.submit(_process_profile, profile, cells))


def extract(
    *,
    profiles_path: Path,
    v4_dir: Path,
    target_receipt: Path,
    vocabulary_path: Path,
    training_receipt_path: Path,
    selected_model_path: Path,
    fortap_source: Path,
    checkpoint: Path,
    output: Path,
    workers: int,
    resume: bool,
) -> Path:
    require_clean_tracked_worktree()
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    if not torch.cuda.is_available():
        raise ValueError("semantic public extraction requires CUDA")
    profiles = read_profiles(profiles_path)
    v4_cells = _load_v4_rows(profiles_path, profiles, v4_dir)
    vocabulary = load_vocabulary(vocabulary_path, target_receipt)
    training_receipt = json.loads(training_receipt_path.read_text(encoding="ascii"))
    if (
        training_receipt.get("protocol") != TRAINING_PROTOCOL
        or training_receipt.get("complete") is not True
        or training_receipt.get("selected_model_sha256") != sha256_file(selected_model_path)
        or training_receipt.get("protected_data_inputs") != []
        or training_receipt.get("fault_label_inputs") != []
        or training_receipt.get("v4_rank_inputs") != []
    ):
        raise ValueError("semantic training receipt violates public extraction")

    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "profiles_sha256": sha256_file(profiles_path),
        "v4_complete_sha256": sha256_file(v4_dir / "complete.json"),
        "target_receipt_sha256": sha256_file(target_receipt),
        "vocabulary_sha256": sha256_file(vocabulary_path),
        "training_receipt_sha256": sha256_file(training_receipt_path),
        "selected_model_sha256": sha256_file(selected_model_path),
        "fortap_source_commit": git_commit(fortap_source),
        "checkpoint_sha256": sha256_file(checkpoint),
        "profile_count": len(profiles),
        "v4_scope": V4_SCOPE,
        "workers": workers,
        "gpu_batch_size": GPU_BATCH_SIZE,
        "source_model_gate_passed": False,
        "status": "exploratory_label_free_feature_extraction",
        "label_inputs": [],
        "protected_data_inputs": [],
        "raw_formula_strings_persisted": False,
        "formula_roles_persisted": False,
    }
    output = output.resolve()
    metadata_path = output / "metadata.json"
    if output.exists():
        if not resume or not metadata_path.is_file():
            raise ValueError("semantic public output exists; pass --resume after audit")
        if json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
            raise ValueError("semantic public resume metadata differs")
    else:
        output.mkdir(parents=True)
        write_json_atomic(metadata_path, metadata)
    shards = output / "shards"
    shards.mkdir(exist_ok=True)
    profiles_by_id = {str(profile["unit_id"]): profile for profile in profiles}
    pending = []
    for profile in profiles:
        path = shards / shard_name(str(profile["unit_id"]))
        if path.exists():
            payload = json.loads(path.read_text(encoding="ascii"))
            _validate_score_shard(payload, profile, v4_cells[str(profile["unit_id"])])
        else:
            pending.append((profile, v4_cells[str(profile["unit_id"])]))

    if pending:
        device = torch.device("cuda:0")
        fortap_runtime = load_runtime(fortap_source, checkpoint)
        fortap_runtime.model.to(device).eval()
        head = SemanticCompatibilityHead(len(vocabulary.tokens)).to(device)
        selected_model = torch.load(selected_model_path, map_location=device, weights_only=True)
        if (
            selected_model.get("protocol") != TRAINING_PROTOCOL
            or selected_model.get("vocabulary_sha256") != sha256_file(vocabulary_path)
        ):
            raise ValueError("selected semantic model identity changed")
        head.load_state_dict(selected_model["model_state"], strict=True)
        head.eval()
        context = multiprocessing.get_context("spawn")
        completed = len(profiles) - len(pending)
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers,
            mp_context=context,
            initializer=_init_worker,
            initargs=(str(fortap_source.resolve()),),
        ) as executor:
            for result in _completed_results(executor, pending, window=workers):
                score_rows = []
                with torch.no_grad():
                    for records, cpu_batch in result["batches"]:  # type: ignore[union-attr]
                        states = frozen_context_states(fortap_runtime, cpu_batch.to(device))
                        token_ids, lengths, mask = _candidate_tensors(records, vocabulary, device)
                        logits = head.candidate_logits(states, token_ids, lengths, mask)
                        for index, record in enumerate(records):
                            count = len(record["candidate_roles"])
                            observed_index = int(record["observed_index"])
                            candidate_scores = [
                                float(logits[index, position].item())
                                for position in range(count)
                            ]
                            observed_score = candidate_scores[observed_index]
                            alternative_score = max(
                                score
                                for position, score in enumerate(candidate_scores)
                                if position != observed_index
                            )
                            margin = alternative_score - observed_score
                            ordered_scores = sorted(candidate_scores, reverse=True)
                            decision_margin = ordered_scores[0] - ordered_scores[1]
                            prefers_alternative = margin > 0.0
                            score_rows.append({
                                "cell": record["cell"],
                                "v4_rank": record["v4_rank"],
                                "candidate_count": count,
                                "semantic_anomaly_margin": margin,
                                "semantic_anomaly_confidence": (
                                    decision_margin if prefers_alternative else -decision_margin
                                ),
                                "semantic_decision_margin": decision_margin,
                                "semantic_observed_score": observed_score,
                                "semantic_best_alternative_score": alternative_score,
                                "semantic_prefers_alternative": prefers_alternative,
                                "fallback_role": record["fallback_role"],
                            })
                score_rows.sort(key=lambda row: int(row["v4_rank"]))
                payload = {
                    "protocol": PROTOCOL,
                    "unit_id": result["unit_id"],
                    "workbook_sha256": result["workbook_sha256"],
                    "v4_scope_cells": result["v4_scope_cells"],
                    "scored_cells": len(score_rows),
                    "skipped_invisible": result["skipped_invisible"],
                    "skipped_without_alternatives": result["skipped_without_alternatives"],
                    "scores": score_rows,
                    "label_inputs": [],
                    "raw_formula_strings_persisted": False,
                    "formula_roles_persisted": False,
                }
                profile = profiles_by_id[str(result["unit_id"])]
                _validate_score_shard(payload, profile, v4_cells[str(result["unit_id"])])
                write_json_atomic(shards / shard_name(str(result["unit_id"])), payload)
                completed += 1
                if completed % 10 == 0 or completed == len(profiles):
                    print(f"semantic public workbooks {completed}/{len(profiles)}", flush=True)

    paths = sorted(shards.glob("*.json"))
    if len(paths) != len(profiles):
        raise ValueError("semantic public score shard inventory is incomplete")
    payloads = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="ascii"))
        unit_id = str(payload["unit_id"])
        if unit_id not in profiles_by_id:
            raise ValueError("semantic public score shard has unknown unit")
        _validate_score_shard(payload, profiles_by_id[unit_id], v4_cells[unit_id])
        payloads.append(payload)
    complete = {
        **metadata,
        "complete": True,
        "workbooks": len(payloads),
        "v4_scope_cells": sum(int(payload["v4_scope_cells"]) for payload in payloads),
        "scored_cells": sum(int(payload["scored_cells"]) for payload in payloads),
        "skipped_invisible": sum(
            int(payload["skipped_invisible"]) for payload in payloads
        ),
        "skipped_without_alternatives": sum(
            int(payload["skipped_without_alternatives"]) for payload in payloads
        ),
        "combined_shards_sha256": stable_hash([
            (path.name, sha256_file(path)) for path in paths
        ]),
        "label_inputs": [],
        "protected_data_inputs": [],
    }
    complete_path = output / "complete.json"
    write_json_atomic(complete_path, complete)
    return complete_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--v4", type=Path, default=DEFAULT_V4)
    parser.add_argument("--target-receipt", type=Path, default=DEFAULT_TARGET_RECEIPT)
    parser.add_argument("--vocabulary", type=Path, default=DEFAULT_VOCABULARY)
    parser.add_argument("--training-receipt", type=Path, default=DEFAULT_TRAINING_RECEIPT)
    parser.add_argument("--selected-model", type=Path, default=DEFAULT_SELECTED_MODEL)
    parser.add_argument("--fortap-source", type=Path, default=DEFAULT_FORTAP_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        complete = extract(
            profiles_path=args.profiles.resolve(),
            v4_dir=args.v4.resolve(),
            target_receipt=args.target_receipt.resolve(),
            vocabulary_path=args.vocabulary.resolve(),
            training_receipt_path=args.training_receipt.resolve(),
            selected_model_path=args.selected_model.resolve(),
            fortap_source=args.fortap_source.resolve(),
            checkpoint=args.checkpoint.resolve(),
            output=args.output,
            workers=args.workers,
            resume=args.resume,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"semantic public extraction refused: {exc}") from exc
    print(complete)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
