#!/usr/bin/env python3
"""Build the input-only semantic compatibility target corpus with 24 workers."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.semantic_compatibility import (
    FormulaVocabulary,
    canonical_formula_role,
    semantic_candidate_roles,
)
from formulaguard.workbook import WorkbookModel
from scripts.build_fcrl_u1_corpus import (
    DEFAULT_CORPUS_MANIFEST,
    DEFAULT_CORPUS_RECEIPT,
    DEFAULT_INPUT_ROOT,
    DEFAULT_INTAKE_MANIFEST,
    EXPECTED_GROUPS,
    load_sources,
    sha256_file,
    stable_hash,
    write_json_atomic,
)


PROTOCOL = "formulaguard_semantic_compatibility_corpus_v2"
MAX_TARGETS_PER_WORKBOOK = 32
MAX_WORKERS = 24
DEFAULT_OUTPUT = ROOT / "results/semantic_compatibility_corpus_v2"


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def target_id(workbook_id: str, sheet_index: int, address: str) -> str:
    material = f"{workbook_id}\0{sheet_index}\0{address.upper()}"
    return "semantic-target:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _process_source(source: Mapping[str, object]) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(str(source["path"]))
    sheets = list(model.sheet_visibility)
    sheet_indices = {sheet: index for index, sheet in enumerate(sheets)}
    candidates = []
    for key in model.formula_cells:
        if key[0] not in sheet_indices or not model.is_visible(key):
            continue
        identifier = target_id(str(source["workbook_id"]), sheet_indices[key[0]], key[1])
        candidates.append((identifier, key))
    candidates.sort()
    selected = candidates[:MAX_TARGETS_PER_WORKBOOK]
    targets = []
    fallback_roles = 0
    for identifier, key in selected:
        role = canonical_formula_role(model.formulas[key], key[1], key[0])
        fallback_roles += int(role.startswith("LEX("))
        targets.append({
            "target_id": identifier,
            "workbook_id": source["workbook_id"],
            "structure_group": source["structure_group"],
            "split": source["split"],
            "sheet_index": sheet_indices[key[0]],
            "address": key[1],
            "role": role,
            "role_sha256": hashlib.sha256(role.encode("utf-8")).hexdigest(),
            "local_candidate_roles": list(semantic_candidate_roles(model, key)),
        })
    return {
        "protocol": PROTOCOL,
        "workbook_id": source["workbook_id"],
        "source_sha256": source["source_sha256"],
        "structure_group": source["structure_group"],
        "split": source["split"],
        "visible_formula_count": len(candidates),
        "selected_targets": len(targets),
        "fallback_roles": fallback_roles,
        "targets": targets,
        "raw_cell_text_persisted": False,
        "raw_numeric_values_persisted": False,
        "raw_formula_strings_persisted": False,
        "fault_labels_read": [],
    }


def _shard_name(workbook_id: str) -> str:
    return hashlib.sha256(workbook_id.encode("utf-8")).hexdigest() + ".json"


def _validate_shard(path: Path, source: Mapping[str, object]) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    targets = payload.get("targets")
    visible_formula_count = payload.get("visible_formula_count")
    if (
        payload.get("protocol") != PROTOCOL
        or payload.get("workbook_id") != source["workbook_id"]
        or payload.get("source_sha256") != source["source_sha256"]
        or payload.get("structure_group") != source["structure_group"]
        or payload.get("split") != source["split"]
        or not isinstance(targets, list)
        or payload.get("selected_targets") != len(targets)
        or not isinstance(visible_formula_count, int)
        or visible_formula_count < 0
        or len(targets) != min(visible_formula_count, MAX_TARGETS_PER_WORKBOOK)
        or payload.get("raw_cell_text_persisted") is not False
        or payload.get("raw_numeric_values_persisted") is not False
        or payload.get("raw_formula_strings_persisted") is not False
        or payload.get("fault_labels_read") != []
    ):
        raise ValueError(f"semantic corpus shard is invalid: {path.name}")
    for target in targets:
        if (
            not str(target.get("target_id", "")).startswith("semantic-target:")
            or target.get("workbook_id") != source["workbook_id"]
            or target.get("structure_group") != source["structure_group"]
            or target.get("split") != source["split"]
            or not isinstance(target.get("role"), str)
            or hashlib.sha256(str(target["role"]).encode("utf-8")).hexdigest()
            != target.get("role_sha256")
            or not isinstance(target.get("local_candidate_roles"), list)
            or len(target["local_candidate_roles"]) > 4
            or len(target["local_candidate_roles"])
            != len(set(target["local_candidate_roles"]))
        ):
            raise ValueError(f"semantic target is invalid: {path.name}")
    return payload


def _structure_group_audit(
    payloads: Sequence[Mapping[str, object]],
) -> tuple[dict[str, int], dict[str, int], dict[str, list[str]]]:
    source_groups: dict[str, set[str]] = defaultdict(set)
    applicable_groups: dict[str, set[str]] = defaultdict(set)
    target_groups: dict[str, set[str]] = defaultdict(set)
    for payload in payloads:
        split = str(payload["split"])
        group = str(payload["structure_group"])
        source_groups[split].add(group)
        if int(payload["visible_formula_count"]) > 0:
            applicable_groups[split].add(group)
        for target in payload["targets"]:  # type: ignore[union-attr]
            target_groups[str(target["split"])].add(str(target["structure_group"]))

    source_counts = {split: len(source_groups[split]) for split in EXPECTED_GROUPS}
    target_counts = {split: len(target_groups[split]) for split in EXPECTED_GROUPS}
    if source_counts != EXPECTED_GROUPS:
        raise ValueError(f"semantic corpus lost source structure groups: {source_counts}")
    if any(target_groups[split] != applicable_groups[split] for split in EXPECTED_GROUPS):
        raise ValueError(f"semantic corpus lost formula-bearing structure groups: {target_counts}")
    formula_free = {
        split: sorted(source_groups[split] - applicable_groups[split])
        for split in EXPECTED_GROUPS
    }
    return source_counts, target_counts, formula_free


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
    sources = load_sources(corpus_manifest, corpus_receipt, intake_manifest, input_root)
    output = output.resolve()
    shards_dir = output / "workbook_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    allowed = {"workbook_shards", "metadata.json", "target_manifest.json", "vocabulary.json", "corpus_receipt.json"}
    if {path.name for path in output.iterdir()} - allowed:
        raise ValueError("semantic corpus output contains unexpected files")
    metadata = {
        "protocol": PROTOCOL,
        "git_commit": git_commit(),
        "source_corpus_manifest_sha256": sha256_file(corpus_manifest),
        "source_corpus_receipt_sha256": sha256_file(corpus_receipt),
        "source_intake_manifest_sha256": sha256_file(intake_manifest),
        "source_workbooks": len(sources),
        "max_targets_per_workbook": MAX_TARGETS_PER_WORKBOOK,
        "workers": workers,
        "protected_data_inputs": [],
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
    }
    metadata_path = output / "metadata.json"
    if metadata_path.exists() and json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
        raise ValueError("semantic corpus metadata differs")
    write_json_atomic(metadata_path, metadata)

    pending = [
        source for source in sources
        if not (shards_dir / _shard_name(str(source["workbook_id"]))).exists()
    ]
    if pending:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            future_to_source = {
                executor.submit(_process_source, source): source for source in pending
            }
            for index, future in enumerate(concurrent.futures.as_completed(future_to_source), 1):
                source = future_to_source[future]
                payload = future.result()
                path = shards_dir / _shard_name(str(source["workbook_id"]))
                temporary = path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
                    encoding="ascii",
                )
                os.replace(temporary, path)
                if index % 25 == 0 or index == len(pending):
                    print(f"semantic corpus workbooks {index}/{len(pending)}", flush=True)

    source_by_id = {str(source["workbook_id"]): source for source in sources}
    expected_paths = {
        _shard_name(workbook_id) for workbook_id in source_by_id
    }
    observed_paths = {path.name for path in shards_dir.glob("*.json")}
    if observed_paths != expected_paths:
        raise ValueError("semantic corpus shard inventory differs")
    payloads = [
        _validate_shard(shards_dir / _shard_name(workbook_id), source_by_id[workbook_id])
        for workbook_id in sorted(source_by_id)
    ]
    targets = sorted(
        (target for payload in payloads for target in payload["targets"]),
        key=lambda target: str(target["target_id"]),
    )
    if len({str(target["target_id"]) for target in targets}) != len(targets):
        raise ValueError("semantic target IDs are not unique")
    split_counts = Counter(str(target["split"]) for target in targets)
    source_groups, target_groups, formula_free_groups = _structure_group_audit(payloads)

    train_roles = [str(target["role"]) for target in targets if target["split"] == "train"]
    vocabulary = FormulaVocabulary.build(train_roles)
    vocabulary_payload = {
        "protocol": PROTOCOL,
        "train_only": True,
        "tokens": list(vocabulary.tokens),
    }
    vocabulary_path = output / "vocabulary.json"
    write_json_atomic(vocabulary_path, vocabulary_payload)
    manifest = {
        "protocol": PROTOCOL,
        "targets": targets,
        "target_inventory_sha256": stable_hash(targets),
    }
    manifest_path = output / "target_manifest.json"
    write_json_atomic(manifest_path, manifest)
    receipt = {
        **metadata,
        "complete": True,
        "selected_targets": len(targets),
        "split_targets": dict(sorted(split_counts.items())),
        "source_split_structure_groups": source_groups,
        "split_structure_groups": target_groups,
        "formula_free_structure_groups": formula_free_groups,
        "workbooks_with_targets": sum(bool(payload["targets"]) for payload in payloads),
        "fallback_roles": sum(int(payload["fallback_roles"]) for payload in payloads),
        "local_candidate_count_distribution": dict(sorted(Counter(
            len(target["local_candidate_roles"]) for target in targets
        ).items())),
        "vocabulary_size": len(vocabulary.tokens),
        "vocabulary_sha256": sha256_file(vocabulary_path),
        "target_manifest_sha256": sha256_file(manifest_path),
        "target_inventory_sha256": manifest["target_inventory_sha256"],
        "raw_cell_text_persisted": False,
        "raw_numeric_values_persisted": False,
        "raw_formula_strings_persisted": False,
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
        raise SystemExit(f"semantic compatibility corpus refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
