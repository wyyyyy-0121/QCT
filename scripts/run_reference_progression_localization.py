#!/usr/bin/env python3
"""Run strict reference-progression localization on revealed public cases."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import subprocess
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.pcrc import formula_tokens, stable_hash  # noqa: E402
from formulaguard.reference_progression import (  # noqa: E402
    directional_progression_peers,
    progression_residual,
)
from formulaguard.v5_psl_protocol import (  # noqa: E402
    canonical_cell,
    combined_shards_sha256,
    parse_source_cells,
    safe_path,
    sha256,
    source_rank,
    validate_complete_ranking,
)
from formulaguard.workbook import WorkbookModel  # noqa: E402
from scripts.run_v5_psl_public_pressure import read_manifest  # noqa: E402
from scripts.tune_v5_psl_parameters import assign_group_folds  # noqa: E402


PROTOCOL = "formulaguard_reference_progression_localization_v1"
MAX_WORKERS = 24
DEFAULT_MANIFEST = ROOT / "results/v5_psl_pressure_inputs/public_pressure_manifest.csv"
DEFAULT_V4_RUN = ROOT / "results/v5_successor_baseline_diagnostic"
DEFAULT_OUTPUT = ROOT / "results/reference_progression_localization_v1"


def git_commit() -> str:
    return subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=ROOT, check=True, capture_output=True, text=True
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
        raise ValueError("tracked worktree must be clean before progression localization")


def write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


def progression_rankings(
    model: WorkbookModel,
    v4_ranking: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    rows = []
    for target in model.formula_cells:
        if not model.is_visible(target):
            continue
        cell = f"{target[0]}!{target[1]}"
        try:
            tokens = formula_tokens(model.formulas[target], target[1], target[0])
            residual = progression_residual(
                tokens, directional_progression_peers(model, target)
            )
        except (TypeError, ValueError):
            tokens = ("UNSUPPORTED_FORMULA",)
            residual = None
        supported = residual is not None and residual.supported
        value = residual.residual if residual is not None else 0.0
        rows.append({
            "cell": cell,
            "residual": value,
            "supported": supported,
            "anomaly": supported and value > 0,
            "axes": list(residual.axes) if residual is not None else [],
            "peer_count": residual.peer_count if residual is not None else 0,
            "slopes": list(residual.slopes) if residual is not None else [],
            "reason": residual.reason if residual is not None else "unsupported_formula",
            "formula_key": stable_hash(list(tokens)),
        })
    formula_cells = [str(row["cell"]) for row in rows]
    validate_complete_ranking(v4_ranking, formula_cells)
    ordered = sorted(
        rows,
        key=lambda row: (
            not bool(row["anomaly"]),
            -float(row["residual"]),
            -int(row["peer_count"]),
            not bool(row["supported"]),
            str(row["formula_key"]),
            canonical_cell(str(row["cell"])),
        ),
    )
    standalone = [
        {
            "rank": rank,
            "cell": row["cell"],
            "score": row["residual"],
            "evidence": {
                "supported": row["supported"],
                "axes": row["axes"],
                "peer_count": row["peer_count"],
                "slopes": row["slopes"],
                "reason": row["reason"],
            },
        }
        for rank, row in enumerate(ordered, 1)
    ]
    anomaly_cells = [str(row["cell"]) for row in ordered if row["anomaly"]]
    v4_cells = [str(row["cell"]) for row in v4_ranking]
    canonical_anomalies = {canonical_cell(value) for value in anomaly_cells}
    fusion_cells = [
        *anomaly_cells,
        *(cell for cell in v4_cells if canonical_cell(cell) not in canonical_anomalies),
    ]
    fusion = [
        {"rank": rank, "cell": cell}
        for rank, cell in enumerate(fusion_cells, 1)
    ]
    validate_complete_ranking(standalone, formula_cells)
    validate_complete_ranking(fusion, formula_cells)
    return {
        "formula_count": len(formula_cells),
        "supported_cells": sum(bool(row["supported"]) for row in rows),
        "anomaly_cells": len(anomaly_cells),
        "action_cells": anomaly_cells[:5],
        "standalone_ranking": standalone,
        "v4_fusion_ranking": fusion,
        "v4_ranking": [
            {"rank": rank, "cell": cell}
            for rank, cell in enumerate(v4_cells, 1)
        ],
    }


def _predict(
    workbook: Path,
    *,
    instance_id: str,
    workbook_label: str,
    v4_shard: Path,
) -> dict[str, object]:
    workbook_sha256 = sha256(workbook)
    prior = json.loads(v4_shard.read_text(encoding="utf-8"))
    if (
        prior.get("instance_id") != instance_id
        or prior.get("workbook") != workbook_label
        or prior.get("workbook_sha256") != workbook_sha256
    ):
        raise ValueError("reference progression V4 shard identity differs")
    methods = prior.get("methods")
    if not isinstance(methods, Mapping) or not isinstance(methods.get("v4_r1"), Mapping):
        raise ValueError("reference progression V4 method is missing")
    v4_ranking = methods["v4_r1"].get("ranking")
    if not isinstance(v4_ranking, list):
        raise ValueError("reference progression V4 ranking is missing")
    model = WorkbookModel.from_xlsx(workbook)
    predictions = progression_rankings(model, v4_ranking)
    return {
        "protocol": PROTOCOL,
        "instance_id": instance_id,
        "workbook": workbook_label,
        "workbook_sha256": workbook_sha256,
        "v4_shard_sha256": sha256(v4_shard),
        **predictions,
        "label_inputs_to_prediction": [],
        "protected_data_inputs": [],
    }


def _task(payload: tuple[str, str, str, str, str]) -> str:
    root_text, output_text, v4_text, instance_id, workbook_label = payload
    root, output, v4_run = Path(root_text), Path(output_text), Path(v4_text)
    record = _predict(
        safe_path(root, workbook_label),
        instance_id=instance_id,
        workbook_label=workbook_label,
        v4_shard=v4_run / "shards" / f"{instance_id}.json",
    )
    write_json_atomic(output / "shards" / f"{instance_id}.json", record)
    return instance_id


def audit_shard(
    path: Path,
    row: Mapping[str, str],
    root: Path,
    v4_run: Path,
) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="ascii"))
    workbook = safe_path(root, row["workbook"])
    if (
        record.get("protocol") != PROTOCOL
        or record.get("instance_id") != row["instance_id"]
        or record.get("workbook") != row["workbook"]
        or record.get("workbook_sha256") != sha256(workbook)
        or record.get("v4_shard_sha256")
        != sha256(v4_run / "shards" / f"{row['instance_id']}.json")
        or record.get("label_inputs_to_prediction") != []
        or record.get("protected_data_inputs") != []
    ):
        raise ValueError(f"reference progression localization shard differs: {path.name}")
    model = WorkbookModel.from_xlsx(workbook)
    formula_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    if record.get("formula_count") != len(formula_cells):
        raise ValueError("reference progression formula inventory differs")
    for key in ("standalone_ranking", "v4_fusion_ranking", "v4_ranking"):
        ranking = record.get(key)
        if not isinstance(ranking, list):
            raise ValueError("reference progression ranking is missing")
        validate_complete_ranking(ranking, formula_cells)
    actions = record.get("action_cells")
    if (
        not isinstance(actions, list)
        or len(actions) > 5
        or len(actions) != len(set(map(canonical_cell, actions)))
        or not set(map(canonical_cell, actions)) <= set(map(canonical_cell, formula_cells))
    ):
        raise ValueError("reference progression action set is invalid")
    return record


def ranking_summary(
    records: Mapping[str, Mapping[str, object]],
    rows: Sequence[Mapping[str, str]],
    ranking_key: str,
    groups: Mapping[str, str],
) -> dict[str, object]:
    ranks = []
    by_group: dict[str, list[bool]] = defaultdict(list)
    for row in rows:
        if row["case_kind"] != "error":
            continue
        sources = set(parse_source_cells(row["source_cells"]))
        ranking = records[row["instance_id"]][ranking_key]
        if not isinstance(ranking, list):
            raise ValueError("reference progression score ranking is malformed")
        rank = source_rank(ranking, sources)
        ranks.append(rank)
        by_group[groups[row["instance_id"]]].append(rank is not None and rank <= 5)
    return {
        "errors": len(ranks),
        "top1": sum(rank == 1 for rank in ranks) / len(ranks),
        "top5": sum(rank is not None and rank <= 5 for rank in ranks) / len(ranks),
        "mrr": sum(1.0 / rank if rank else 0.0 for rank in ranks) / len(ranks),
        "structure_groups": len(by_group),
        "structure_group_macro_top5": sum(
            sum(values) / len(values) for values in by_group.values()
        ) / len(by_group),
    }


def selective_summary(
    records: Mapping[str, Mapping[str, object]],
    rows: Sequence[Mapping[str, str]],
) -> dict[str, object]:
    errors = [row for row in rows if row["case_kind"] == "error"]
    controls = [row for row in rows if row["case_kind"] == "control"]
    acted_errors = hits = acted_controls = inspected = 0
    for row in rows:
        actions = records[row["instance_id"]]["action_cells"]
        if not isinstance(actions, list):
            raise ValueError("reference progression actions are malformed")
        inspected += len(actions)
        if row["case_kind"] == "error":
            acted_errors += bool(actions)
            sources = set(map(canonical_cell, parse_source_cells(row["source_cells"])))
            hits += bool(set(map(canonical_cell, actions)) & sources)
        else:
            acted_controls += bool(actions)
    return {
        "errors": len(errors),
        "controls": len(controls),
        "error_action_coverage": acted_errors / len(errors),
        "error_source_hit_rate": hits / len(errors),
        "acted_error_case_precision": hits / acted_errors if acted_errors else 0.0,
        "control_actionable_rate": acted_controls / len(controls),
        "inspected_cells": inspected,
        "source_cases_found": hits,
        "review_efficiency_per_100_cells": 100 * hits / inspected if inspected else 0.0,
    }


def paired_top5(
    records: Mapping[str, Mapping[str, object]],
    rows: Sequence[Mapping[str, str]],
) -> dict[str, int]:
    rescues = harms = shared_hits = shared_misses = 0
    for row in rows:
        if row["case_kind"] != "error":
            continue
        sources = set(parse_source_cells(row["source_cells"]))
        v4_rank = source_rank(records[row["instance_id"]]["v4_ranking"], sources)  # type: ignore[arg-type]
        fusion_rank = source_rank(
            records[row["instance_id"]]["v4_fusion_ranking"], sources  # type: ignore[arg-type]
        )
        v4_hit = v4_rank is not None and v4_rank <= 5
        fusion_hit = fusion_rank is not None and fusion_rank <= 5
        rescues += not v4_hit and fusion_hit
        harms += v4_hit and not fusion_hit
        shared_hits += v4_hit and fusion_hit
        shared_misses += not v4_hit and not fusion_hit
    return {
        "rescues": rescues,
        "harms": harms,
        "net_rescues": rescues - harms,
        "shared_hits": shared_hits,
        "shared_misses": shared_misses,
    }


def run(
    *,
    manifest: Path,
    v4_run: Path,
    output: Path,
    workers: int,
    resume: bool,
) -> Path:
    if workers < 1 or workers > MAX_WORKERS:
        raise ValueError(f"workers must be in [1, {MAX_WORKERS}]")
    require_clean_tracked_worktree()
    root = manifest.parent
    rows = [row for row in read_manifest(manifest) if row["include"] == "1"]
    v4_completion_path = v4_run / "diagnostic_complete.json"
    v4_metadata_path = v4_run / "diagnostic_metadata.json"
    v4_completion = json.loads(v4_completion_path.read_text(encoding="utf-8"))
    v4_metadata = json.loads(v4_metadata_path.read_text(encoding="utf-8"))
    if (
        v4_completion.get("complete") is not True
        or v4_completion.get("cases") != len(rows)
        or v4_metadata.get("manifest_sha256") != sha256(manifest)
    ):
        raise ValueError("reference progression V4 run is incomplete")
    metadata = {
        "protocol": PROTOCOL,
        "status": "revealed_public_development_only",
        "git_commit": git_commit(),
        "manifest_sha256": sha256(manifest),
        "v4_completion_sha256": sha256(v4_completion_path),
        "v4_metadata_sha256": sha256(v4_metadata_path),
        "v4_combined_shards_sha256": v4_completion["combined_shards_sha256"],
        "source_sha256": {
            "formulaguard/reference_progression.py": sha256(
                ROOT / "formulaguard/reference_progression.py"
            ),
            "scripts/run_reference_progression_localization.py": sha256(
                ROOT / "scripts/run_reference_progression_localization.py"
            ),
        },
        "workers": workers,
        "minimum_progression_peers": 3,
        "progression_threshold": 0.0,
        "label_inputs_to_prediction": [],
        "labels_used_only_after_predictions": ["case_kind", "source_cells"],
        "protected_data_inputs": [],
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "shards").mkdir(exist_ok=True)
    metadata_path = output / "metadata.json"
    if metadata_path.exists():
        if json.loads(metadata_path.read_text(encoding="ascii")) != metadata:
            raise ValueError("reference progression localization metadata differs")
        if not resume:
            raise ValueError("reference progression output exists; pass --resume")
    else:
        write_json_atomic(metadata_path, metadata)
    pending = [
        row for row in rows
        if not (output / "shards" / f"{row['instance_id']}.json").exists()
    ]
    payloads = [
        (str(root), str(output), str(v4_run), row["instance_id"], row["workbook"])
        for row in pending
    ]
    if payloads:
        with concurrent.futures.ProcessPoolExecutor(
            max_workers=min(workers, len(payloads))
        ) as executor:
            futures = [executor.submit(_task, payload) for payload in payloads]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"reference progression localization {index}/{len(futures)} {future.result()}", flush=True)
    records = {
        row["instance_id"]: audit_shard(
            output / "shards" / f"{row['instance_id']}.json", row, root, v4_run
        )
        for row in rows
    }
    groups, folds = assign_group_folds(rows, root)
    events_path = output / "events.csv"
    with events_path.open("w", encoding="utf-8-sig", newline="") as handle:
        fields = (
            "instance_id", "corpus_id", "case_kind", "group_sha256", "fold",
            "supported_cells", "anomaly_cells", "action_count", "action_hit",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            record = records[row["instance_id"]]
            actions = record["action_cells"]
            sources = set(map(canonical_cell, parse_source_cells(row["source_cells"])))
            writer.writerow({
                "instance_id": row["instance_id"],
                "corpus_id": row["corpus_id"],
                "case_kind": row["case_kind"],
                "group_sha256": groups[row["instance_id"]],
                "fold": folds[row["instance_id"]],
                "supported_cells": record["supported_cells"],
                "anomaly_cells": record["anomaly_cells"],
                "action_count": len(actions),
                "action_hit": int(bool(set(map(canonical_cell, actions)) & sources)),
            })
    receipt = {
        **metadata,
        "complete": True,
        "cases": len(rows),
        "combined_shards_sha256": combined_shards_sha256(
            (output / "shards").glob("*.json")
        ),
        "events_sha256": sha256(events_path),
        "ranking_summaries": {
            key: ranking_summary(records, rows, key, groups)
            for key in ("v4_ranking", "standalone_ranking", "v4_fusion_ranking")
        },
        "selective_summary": selective_summary(records, rows),
        "paired_v4_fusion_top5": paired_top5(records, rows),
        "formal_version_authorized": False,
        "external_evaluation_authorized": False,
    }
    receipt_path = output / "receipt.json"
    write_json_atomic(receipt_path, receipt)
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--v4-run", type=Path, default=DEFAULT_V4_RUN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=MAX_WORKERS)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        path = run(
            manifest=args.manifest.resolve(),
            v4_run=args.v4_run.resolve(),
            output=args.output.resolve(),
            workers=args.workers,
            resume=args.resume,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"reference progression localization refused: {exc}") from exc
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
