#!/usr/bin/env python3
"""Build the frozen PCRC input-only corpus with resumable 24-worker shards."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.pcrc import (  # noqa: E402
    CORPUS_PROTOCOL,
    MAX_TARGETS_PER_WORKBOOK,
    PCRCVocabulary,
    PEER_CONFIG,
    PROTOCOL,
    workbook_examples,
)
from formulaguard.workbook import WorkbookModel  # noqa: E402
from scripts.build_fcrl_u1_corpus import (  # noqa: E402
    DEFAULT_CORPUS_MANIFEST,
    DEFAULT_CORPUS_RECEIPT,
    DEFAULT_INPUT_ROOT,
    DEFAULT_INTAKE_MANIFEST,
    EXPECTED_GROUPS,
    EXPECTED_WORKBOOKS,
    load_sources,
    sha256_file,
    stable_hash,
    write_json_atomic,
)


MAX_WORKERS = 24
DEFAULT_OUTPUT = ROOT / "results/pcrc_corpus_v1"
PREREGISTRATION = ROOT / "research/V5_PCRC_PREREGISTRATION.json"


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, capture_output=True, text=True
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
        raise ValueError("tracked worktree must be clean before PCRC corpus construction")


def shard_name(workbook_id: str) -> str:
    return hashlib.sha256(workbook_id.encode("utf-8")).hexdigest() + ".json"


def _worker(source: Mapping[str, object]) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(str(source["path"]))
    examples = workbook_examples(
        model,
        workbook_id=str(source["workbook_id"]),
        structure_group=str(source["structure_group"]),
        split=str(source["split"]),
    )
    return {
        "protocol": CORPUS_PROTOCOL,
        "workbook_id": source["workbook_id"],
        "source_sha256": source["source_sha256"],
        "structure_group": source["structure_group"],
        "split": source["split"],
        "selected_targets": len(examples),
        "hard_negative_targets": sum(bool(item["repair_candidates"]) for item in examples),
        "hard_negative_candidates": sum(len(item["repair_candidates"]) for item in examples),
        "examples": examples,
        "fault_labels_read": [],
        "answer_workbooks_read": [],
        "protected_data_inputs": [],
    }


def _validate_shard(path: Path, source: Mapping[str, object]) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    examples = payload.get("examples")
    if (
        payload.get("protocol") != CORPUS_PROTOCOL
        or payload.get("workbook_id") != source["workbook_id"]
        or payload.get("source_sha256") != source["source_sha256"]
        or payload.get("structure_group") != source["structure_group"]
        or payload.get("split") != source["split"]
        or not isinstance(examples, list)
        or payload.get("selected_targets") != len(examples)
        or len(examples) > MAX_TARGETS_PER_WORKBOOK
        or payload.get("hard_negative_targets") != sum(bool(item.get("repair_candidates")) for item in examples)
        or payload.get("hard_negative_candidates") != sum(len(item.get("repair_candidates", [])) for item in examples)
        or payload.get("fault_labels_read") != []
        or payload.get("answer_workbooks_read") != []
        or payload.get("protected_data_inputs") != []
    ):
        raise ValueError(f"PCRC shard is invalid: {path.name}")
    seen = set()
    for example in examples:
        target_id = str(example.get("target_id", ""))
        repairs = example.get("repair_candidates")
        if (
            example.get("protocol") != CORPUS_PROTOCOL
            or not target_id.startswith("pcrc-target:")
            or target_id in seen
            or example.get("workbook_id") != source["workbook_id"]
            or example.get("structure_group") != source["structure_group"]
            or example.get("split") != source["split"]
            or not isinstance(example.get("context_tokens"), list)
            or not isinstance(example.get("observed_tokens"), list)
            or not isinstance(repairs, list)
            or len(repairs) > PEER_CONFIG.max_hypotheses
            or example.get("raw_formula_strings_persisted") is not False
            or example.get("raw_numeric_values_persisted") is not False
            or example.get("target_formula_tokens_entered_context") is not False
        ):
            raise ValueError(f"PCRC example is invalid: {target_id}")
        seen.add(target_id)
    return payload


def build(
    *,
    corpus_manifest: Path,
    corpus_receipt: Path,
    intake_manifest: Path,
    input_root: Path,
    output: Path,
    workers: int,
) -> Path:
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    require_clean_tracked_worktree()
    preregistration = json.loads(PREREGISTRATION.read_text(encoding="ascii"))
    if preregistration.get("protocol") != PROTOCOL or preregistration.get("formal_version_authorized") is not False:
        raise ValueError("PCRC preregistration identity mismatch")
    sources = load_sources(corpus_manifest, corpus_receipt, intake_manifest, input_root)
    if len(sources) != EXPECTED_WORKBOOKS:
        raise ValueError("PCRC source workbook count changed")

    output = output.resolve()
    shards = output / "workbook_shards"
    shards.mkdir(parents=True, exist_ok=True)
    allowed = {"workbook_shards", "metadata.json", "vocabulary.json", "corpus_receipt.json"}
    if {path.name for path in output.iterdir()} - allowed:
        raise ValueError("PCRC output contains unexpected files")
    metadata = {
        "protocol": CORPUS_PROTOCOL,
        "git_commit": git_commit(),
        "preregistration_sha256": sha256_file(PREREGISTRATION),
        "corpus_manifest_sha256": sha256_file(corpus_manifest),
        "corpus_receipt_sha256": sha256_file(corpus_receipt),
        "intake_manifest_sha256": sha256_file(intake_manifest),
        "source_workbooks": len(sources),
        "max_targets_per_workbook": MAX_TARGETS_PER_WORKBOOK,
        "peer_configuration": PEER_CONFIG.as_dict(),
        "workers": workers,
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
        "protected_data_inputs": [],
    }
    metadata_path = output / "metadata.json"
    if metadata_path.exists() and json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
        raise ValueError("PCRC corpus metadata differs")
    write_json_atomic(metadata_path, metadata)

    pending = [source for source in sources if not (shards / shard_name(str(source["workbook_id"]))).exists()]
    if pending:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_worker, source): source for source in pending}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                source = futures[future]
                payload = future.result()
                path = shards / shard_name(str(source["workbook_id"]))
                temporary = path.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n", encoding="ascii")
                os.replace(temporary, path)
                if index % 25 == 0 or index == len(pending):
                    print(f"PCRC corpus workbooks {index}/{len(pending)}", flush=True)

    source_by_id = {str(source["workbook_id"]): source for source in sources}
    expected = {shard_name(workbook_id) for workbook_id in source_by_id}
    observed = {path.name for path in shards.glob("*.json")}
    if expected != observed:
        raise ValueError("PCRC shard inventory differs")
    payloads = [
        _validate_shard(shards / shard_name(workbook_id), source_by_id[workbook_id])
        for workbook_id in sorted(source_by_id)
    ]
    examples = [example for payload in payloads for example in payload["examples"]]
    if len({str(example["target_id"]) for example in examples}) != len(examples):
        raise ValueError("PCRC target IDs are not unique")
    groups: dict[str, set[str]] = defaultdict(set)
    for payload in payloads:
        groups[str(payload["split"])].add(str(payload["structure_group"]))
    if {split: len(groups[split]) for split in EXPECTED_GROUPS} != EXPECTED_GROUPS:
        raise ValueError("PCRC structure-group splits changed")

    train_tokens = []
    for example in examples:
        if example["split"] != "train":
            continue
        train_tokens.extend((example["context_tokens"], example["observed_tokens"]))
        train_tokens.extend(candidate["tokens"] for candidate in example["repair_candidates"])
    vocabulary = PCRCVocabulary.build(train_tokens)
    vocabulary_path = output / "vocabulary.json"
    write_json_atomic(vocabulary_path, {
        "protocol": CORPUS_PROTOCOL,
        "train_only": True,
        "tokens": list(vocabulary.tokens),
    })

    split_targets = Counter(str(example["split"]) for example in examples)
    split_hard_targets = Counter(
        str(example["split"]) for example in examples if example["repair_candidates"]
    )
    split_hard_candidates = Counter()
    for example in examples:
        split_hard_candidates[str(example["split"])] += len(example["repair_candidates"])
    receipt = {
        **metadata,
        "complete": True,
        "selected_targets": len(examples),
        "split_targets": dict(sorted(split_targets.items())),
        "split_hard_negative_targets": dict(sorted(split_hard_targets.items())),
        "split_hard_negative_candidates": dict(sorted(split_hard_candidates.items())),
        "split_structure_groups": {split: len(groups[split]) for split in EXPECTED_GROUPS},
        "workbooks_with_targets": sum(bool(payload["examples"]) for payload in payloads),
        "vocabulary_size": len(vocabulary.tokens),
        "vocabulary_sha256": sha256_file(vocabulary_path),
        "combined_shards_sha256": stable_hash([
            [path.name, sha256_file(path)] for path in sorted(shards.glob("*.json"))
        ]),
        "raw_formula_strings_persisted": False,
        "raw_numeric_values_persisted": False,
        "target_formula_tokens_entered_context": False,
    }
    receipt_path = output / "corpus_receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-manifest", type=Path, default=DEFAULT_CORPUS_MANIFEST)
    parser.add_argument("--corpus-receipt", type=Path, default=DEFAULT_CORPUS_RECEIPT)
    parser.add_argument("--intake-manifest", type=Path, default=DEFAULT_INTAKE_MANIFEST)
    parser.add_argument("--input-root", type=Path, default=DEFAULT_INPUT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    args = parser.parse_args(argv)
    try:
        path = build(
            corpus_manifest=args.corpus_manifest,
            corpus_receipt=args.corpus_receipt,
            intake_manifest=args.intake_manifest,
            input_root=args.input_root,
            output=args.output,
            workers=args.workers,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"PCRC corpus refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
