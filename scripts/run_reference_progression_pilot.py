#!/usr/bin/env python3
"""Evaluate exact reference progressions on the public input-only corpus."""

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

from formulaguard.a1 import parse_address  # noqa: E402
from formulaguard.formula_compatibility_pilot import candidate_rows  # noqa: E402
from formulaguard.pcrc import selected_targets, stable_hash, workbook_examples  # noqa: E402
from formulaguard.reference_progression import (  # noqa: E402
    directional_progression_peers,
    progression_decision,
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
    write_json_atomic,
)


PROTOCOL = "formulaguard_reference_progression_pilot_v1"
MAX_WORKERS = 24
DEFAULT_OUTPUT = ROOT / "results/reference_progression_pilot_v1"


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
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
        raise ValueError("tracked worktree must be clean before progression evaluation")


def shard_name(workbook_id: str) -> str:
    return hashlib.sha256(workbook_id.encode("utf-8")).hexdigest() + ".json"


def target_id(workbook_id: str, target: tuple[str, str]) -> str:
    address = parse_address(target[1])
    return "pcrc-target:" + stable_hash({
        "workbook_id": workbook_id,
        "sheet": target[0],
        "row": address.row,
        "col": address.col,
    })


def candidate_key(tokens: Sequence[str]) -> str:
    return stable_hash(list(tokens))


def workbook_rows(
    model: WorkbookModel,
    *,
    workbook_id: str,
    structure_group: str,
    split: str,
) -> list[dict[str, object]]:
    examples = {
        str(item["target_id"]): item
        for item in workbook_examples(
            model,
            workbook_id=workbook_id,
            structure_group=structure_group,
            split=split,
        )
    }
    rows = []
    for target in selected_targets(model, workbook_id=workbook_id):
        opaque_target = target_id(workbook_id, target)
        example = examples[opaque_target]
        candidates = candidate_rows(example)
        if len(candidates) < 2:
            continue
        tokens = [tuple(str(value) for value in candidate["tokens"]) for candidate in candidates]
        keys = [candidate_key(candidate) for candidate in tokens]
        if len(keys) != len(set(keys)):
            raise ValueError("reference progression candidate keys are not unique")
        peers = directional_progression_peers(model, target)
        support = [sum(candidate == peer.tokens for peer in peers) for candidate in tokens]
        decision = progression_decision(tokens, peers)
        entries = sorted(
            (
                {
                    "candidate_key": key,
                    "kind": str(candidate["kind"]),
                    "exact_peer_support": count,
                }
                for key, candidate, count in zip(keys, candidates, support, strict=True)
            ),
            key=lambda item: str(item["candidate_key"]),
        )
        rows.append({
            "target_id": opaque_target,
            "observed_candidate_key": keys[0],
            "candidates": entries,
            "progression_candidate_key": (
                keys[decision.candidate_index]
                if decision.candidate_index is not None
                else None
            ),
            "progression_reason": decision.reason,
            "progression_axes": list(decision.axes),
            "progression_peer_count": decision.peer_count,
            "progression_slopes": list(decision.slopes),
            "raw_formula_strings_persisted": False,
            "raw_cell_addresses_persisted": False,
            "target_formula_tokens_entered_peer_context": False,
        })
    return sorted(rows, key=lambda item: str(item["target_id"]))


def _worker(source: Mapping[str, object]) -> dict[str, object]:
    model = WorkbookModel.from_xlsx(str(source["path"]))
    rows = workbook_rows(
        model,
        workbook_id=str(source["workbook_id"]),
        structure_group=str(source["structure_group"]),
        split=str(source["split"]),
    )
    return {
        "protocol": PROTOCOL,
        "workbook_id": source["workbook_id"],
        "source_sha256": source["source_sha256"],
        "structure_group": source["structure_group"],
        "split": source["split"],
        "targets": len(rows),
        "rows": rows,
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
        "protected_data_inputs": [],
    }


def _validate_shard(path: Path, source: Mapping[str, object]) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="ascii"))
    rows = payload.get("rows")
    if (
        payload.get("protocol") != PROTOCOL
        or payload.get("workbook_id") != source["workbook_id"]
        or payload.get("source_sha256") != source["source_sha256"]
        or payload.get("structure_group") != source["structure_group"]
        or payload.get("split") != source["split"]
        or not isinstance(rows, list)
        or payload.get("targets") != len(rows)
        or payload.get("fault_label_inputs") != []
        or payload.get("answer_workbook_inputs") != []
        or payload.get("protected_data_inputs") != []
    ):
        raise ValueError(f"reference progression shard is invalid: {path.name}")
    seen = set()
    for row in rows:
        candidates = row.get("candidates")
        keys = [item.get("candidate_key") for item in candidates] if isinstance(candidates, list) else []
        if (
            not str(row.get("target_id", "")).startswith("pcrc-target:")
            or row.get("target_id") in seen
            or len(keys) < 2
            or len(keys) != len(set(keys))
            or row.get("observed_candidate_key") not in keys
            or row.get("progression_candidate_key") not in {*keys, None}
            or row.get("raw_formula_strings_persisted") is not False
            or row.get("raw_cell_addresses_persisted") is not False
            or row.get("target_formula_tokens_entered_peer_context") is not False
        ):
            raise ValueError("reference progression row is invalid")
        seen.add(row["target_id"])
    return payload


def baseline_candidate(row: Mapping[str, object], frequency: Mapping[str, int]) -> str:
    candidates = row["candidates"]
    if not isinstance(candidates, list):
        raise ValueError("reference progression candidates are malformed")
    selected = max(
        candidates,
        key=lambda item: (
            int(item["exact_peer_support"]),
            int(frequency.get(str(item["candidate_key"]), 0)),
            str(item["candidate_key"]),
        ),
    )
    return str(selected["candidate_key"])


def summarize(
    rows: Sequence[Mapping[str, object]],
    frequency: Mapping[str, int],
) -> dict[str, object]:
    groups: dict[str, list[tuple[bool, bool]]] = defaultdict(list)
    baseline_hits = []
    progression_hits = []
    issued = changed = rescues = harms = 0
    changed_kinds: Counter[str] = Counter()
    for row in rows:
        baseline = baseline_candidate(row, frequency)
        progression = row.get("progression_candidate_key")
        selected = str(progression) if progression is not None else baseline
        observed = str(row["observed_candidate_key"])
        baseline_hit = baseline == observed
        progression_hit = selected == observed
        baseline_hits.append(baseline_hit)
        progression_hits.append(progression_hit)
        groups[str(row["structure_group"])].append((baseline_hit, progression_hit))
        issued += progression is not None
        if progression is not None and selected != baseline:
            changed += 1
            rescues += not baseline_hit and progression_hit
            harms += baseline_hit and not progression_hit
            candidates = row["candidates"]
            if isinstance(candidates, list):
                kind = next(
                    str(item["kind"])
                    for item in candidates
                    if str(item["candidate_key"]) == selected
                )
                changed_kinds[kind] += 1
    count = len(rows)
    baseline_accuracy = sum(baseline_hits) / count
    progression_accuracy = sum(progression_hits) / count
    baseline_group_macro = sum(
        sum(left for left, _ in values) / len(values) for values in groups.values()
    ) / len(groups)
    progression_group_macro = sum(
        sum(right for _, right in values) / len(values) for values in groups.values()
    ) / len(groups)
    return {
        "targets": count,
        "structure_groups": len(groups),
        "peer_frequency_candidate_accuracy": baseline_accuracy,
        "progression_candidate_accuracy": progression_accuracy,
        "candidate_accuracy_delta": progression_accuracy - baseline_accuracy,
        "peer_frequency_group_macro_accuracy": baseline_group_macro,
        "progression_group_macro_accuracy": progression_group_macro,
        "group_macro_accuracy_delta": progression_group_macro - baseline_group_macro,
        "progression_decisions": issued,
        "progression_coverage": issued / count,
        "changed_decisions": changed,
        "rescues": rescues,
        "harms": harms,
        "net_rescues": rescues - harms,
        "changed_selected_kinds": dict(sorted(changed_kinds.items())),
    }


def run(
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
    sources = load_sources(corpus_manifest, corpus_receipt, intake_manifest, input_root)
    if len(sources) != EXPECTED_WORKBOOKS:
        raise ValueError("reference progression source workbook count changed")
    output = output.resolve()
    shards = output / "workbook_shards"
    shards.mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": PROTOCOL,
        "status": "retrospective_revealed_development",
        "git_commit": git_commit(),
        "corpus_manifest_sha256": sha256_file(corpus_manifest),
        "corpus_receipt_sha256": sha256_file(corpus_receipt),
        "intake_manifest_sha256": sha256_file(intake_manifest),
        "source_workbooks": len(sources),
        "workers": workers,
        "minimum_progression_peers": 3,
        "fault_label_inputs": [],
        "answer_workbook_inputs": [],
        "protected_data_inputs": [],
    }
    metadata_path = output / "metadata.json"
    if metadata_path.exists() and json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
        raise ValueError("reference progression metadata differs")
    write_json_atomic(metadata_path, metadata)

    pending = [
        source for source in sources
        if not (shards / shard_name(str(source["workbook_id"]))).exists()
    ]
    if pending:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(_worker, source): source for source in pending}
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                source = futures[future]
                payload = future.result()
                path = shards / shard_name(str(source["workbook_id"]))
                temporary = path.with_suffix(".json.tmp")
                temporary.write_text(
                    json.dumps(payload, sort_keys=True, ensure_ascii=True) + "\n",
                    encoding="ascii",
                )
                os.replace(temporary, path)
                if index % 25 == 0 or index == len(pending):
                    print(f"reference progression workbooks {index}/{len(pending)}", flush=True)

    source_by_id = {str(source["workbook_id"]): source for source in sources}
    expected = {shard_name(workbook_id) for workbook_id in source_by_id}
    observed = {path.name for path in shards.glob("*.json")}
    if expected != observed:
        raise ValueError("reference progression shard inventory differs")
    payloads = [
        _validate_shard(shards / shard_name(workbook_id), source_by_id[workbook_id])
        for workbook_id in sorted(source_by_id)
    ]
    rows = []
    for payload in payloads:
        for row in payload["rows"]:
            rows.append({
                **row,
                "workbook_id": payload["workbook_id"],
                "structure_group": payload["structure_group"],
                "split": payload["split"],
            })
    frequency = Counter(
        str(row["observed_candidate_key"])
        for row in rows
        if row["split"] == "train"
    )
    source_split_groups = {
        split: {
            str(payload["structure_group"])
            for payload in payloads
            if payload["split"] == split
        }
        for split in EXPECTED_GROUPS
    }
    if {
        split: len(groups) for split, groups in source_split_groups.items()
    } != EXPECTED_GROUPS:
        raise ValueError("reference progression source structure-group splits changed")
    eligible_split_groups = {
        split: {str(row["structure_group"]) for row in rows if row["split"] == split}
        for split in EXPECTED_GROUPS
    }
    if any(not groups for groups in eligible_split_groups.values()):
        raise ValueError("reference progression has an empty eligible split")
    metrics = {
        split: summarize([row for row in rows if row["split"] == split], frequency)
        for split in EXPECTED_GROUPS
    }
    receipt = {
        **metadata,
        "complete": True,
        "targets": len(rows),
        "source_structure_groups": {
            split: len(groups) for split, groups in source_split_groups.items()
        },
        "eligible_structure_groups": {
            split: len(groups) for split, groups in eligible_split_groups.items()
        },
        "metrics": metrics,
        "combined_shards_sha256": stable_hash([
            [path.name, sha256_file(path)] for path in sorted(shards.glob("*.json"))
        ]),
        "formal_version_authorized": False,
        "external_evaluation_authorized": False,
    }
    receipt_path = output / "receipt.json"
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
        path = run(
            corpus_manifest=args.corpus_manifest.resolve(),
            corpus_receipt=args.corpus_receipt.resolve(),
            intake_manifest=args.intake_manifest.resolve(),
            input_root=args.input_root.resolve(),
            output=args.output.resolve(),
            workers=args.workers,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"reference progression pilot refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
