"""Generate a label-free frozen V4-R1 baseline for model-discovery scoring.

The baseline is intentionally a separate run from the signal audit.  It uses
the same observed-workbook profile, records a complete ranking for every
formula cell, and never opens a label manifest.  The Gate 2 scorer verifies
both completion receipts before it reads any revealed labels.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.formula import normalized_formula  # noqa: E402
from formulaguard.localize import v4_default_parameters, v4_scores  # noqa: E402
from formulaguard.workbook import WorkbookModel  # noqa: E402
from scripts.run_model_discovery_signals import (  # noqa: E402
    REQUIRED_PROFILE_FIELDS,
    read_profiles,
    shard_name,
)


RUN_PROTOCOL = "formulaguard_model_discovery_v4_baseline_run_v1"
DEFAULT_PROFILES = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
DEFAULT_OUTPUT = ROOT / "results/model_discovery_v4_baseline"
FROZEN_CONFIG = ROOT / "research/frozen_config_v4.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def git_commit() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _combined_shards(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.name):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _verify_frozen_config() -> tuple[dict[str, object], dict[str, str]]:
    frozen = json.loads(FROZEN_CONFIG.read_text(encoding="utf-8"))
    expected = frozen.get("v4_parameters")
    if expected != v4_default_parameters():
        raise ValueError("current V4 parameters differ from research/frozen_config_v4.json")
    source_hashes = frozen.get("model_source_sha256")
    if not isinstance(source_hashes, dict) or "formulaguard/localize.py" not in source_hashes:
        raise ValueError("frozen V4 source hashes are incomplete")
    observed: dict[str, str] = {}
    for relative, expected_hash in source_hashes.items():
        path = ROOT / str(relative)
        if not path.is_file() or sha256(path) != str(expected_hash):
            raise ValueError(f"frozen V4 source hash mismatch: {relative}")
        observed[str(relative)] = sha256(path)
    return frozen, observed


def _predict(payload: tuple[str, str, str, str]) -> str:
    path_text, unit_id, expected_hash, output_text = payload
    path = Path(path_text)
    model = WorkbookModel.from_xlsx(path)
    started = time.perf_counter()
    parameters = v4_default_parameters()
    ranking = v4_scores(
        model,
        candidate_limit=int(parameters["candidate_limit"]) if "candidate_limit" in parameters else 15,
        max_intervention_cells=100,
        rrf_k=int(parameters["rrf_k"]),
        scope_depth=int(parameters["scope_depth"]),
        scope_decay=float(parameters["scope_decay"]),
    )
    cells = [item.cell_label for item in ranking]
    expected_cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
    if set(cells) != set(expected_cells) or len(cells) != len(set(cells)):
        raise ValueError(f"V4 ranking is incomplete or duplicated for {unit_id}")
    records = []
    for rank, item in enumerate(ranking, 1):
        records.append({
            "cell": item.cell_label,
            "rank": rank,
            "score": float(item.score),
            "candidate_formula": item.candidate_formula or "",
            "evidence": dict(item.evidence),
        })
    audit = {
        "protocol": RUN_PROTOCOL,
        "unit_id": unit_id,
        "workbook_sha256": expected_hash,
        "formula_count": len(model.formula_cells),
        "label_inputs": [],
        "parameters": parameters,
        "ranking": records,
        "runtime_seconds": time.perf_counter() - started,
    }
    audit["audit_sha256"] = stable_hash(audit)
    output = Path(output_text) / "shards" / shard_name(unit_id)
    _write_json_atomic(output, audit)
    return unit_id


def _validate_shard(path: Path, expected: Mapping[str, str]) -> dict[str, object]:
    record = json.loads(path.read_text(encoding="utf-8"))
    if record.get("protocol") != RUN_PROTOCOL:
        raise ValueError(f"invalid V4 baseline protocol: {path.name}")
    if record.get("unit_id") != expected["unit_id"]:
        raise ValueError(f"V4 baseline unit mismatch: {path.name}")
    if record.get("workbook_sha256") != expected["workbook_sha256"]:
        raise ValueError(f"V4 baseline hash mismatch: {path.name}")
    if record.get("label_inputs") != []:
        raise ValueError(f"labels reached V4 baseline: {path.name}")
    ranking = record.get("ranking")
    if not isinstance(ranking, list) or len(ranking) != int(record.get("formula_count", -1)):
        raise ValueError(f"V4 baseline ranking malformed: {path.name}")
    cells = [str(item.get("cell")) for item in ranking if isinstance(item, dict)]
    if len(cells) != len(set(cells)) or any(not cell or "!" not in cell for cell in cells):
        raise ValueError(f"V4 baseline ranking cells malformed: {path.name}")
    unhashed = dict(record)
    recorded = unhashed.pop("audit_sha256", None)
    if recorded != stable_hash(unhashed):
        raise ValueError(f"V4 baseline audit hash mismatch: {path.name}")
    return record


def run(*, profiles_path: Path, output_dir: Path, workers: int) -> Path:
    frozen, source_hashes = _verify_frozen_config()
    profiles = read_profiles(profiles_path)
    output_dir = output_dir.resolve()
    shards_dir = output_dir / "shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "protocol": RUN_PROTOCOL,
        "profiles_path": profiles_path.resolve().relative_to(ROOT).as_posix()
        if profiles_path.resolve().is_relative_to(ROOT)
        else str(profiles_path.resolve()),
        "profiles_sha256": sha256(profiles_path),
        "profile_count": len(profiles),
        "frozen_config_path": FROZEN_CONFIG.relative_to(ROOT).as_posix(),
        "frozen_config_sha256": sha256(FROZEN_CONFIG),
        "frozen_v4_parameters": frozen["v4_parameters"],
        "source_hashes": source_hashes,
        "git_commit": git_commit(),
        "workers_requested": workers,
        "label_inputs_to_prediction": [],
        "forbidden_label_fields": [
            "correct_formula", "source_cell", "source_cells", "error_type", "case_kind",
            "corpus_id", "template_id", "secret_labels", "expected_output", "pass_fail",
        ],
    }
    metadata_path = output_dir / "metadata.json"
    if metadata_path.exists():
        existing = json.loads(metadata_path.read_text(encoding="utf-8"))
        comparable = dict(metadata)
        comparable["workers_requested"] = existing.get("workers_requested")
        if existing != comparable:
            raise ValueError("existing V4 baseline metadata differs; choose a new output directory")
        if (output_dir / "complete.json").exists():
            raise ValueError("V4 baseline run is complete; choose a new output directory")
    else:
        _write_json_atomic(metadata_path, metadata)

    expected = {row["unit_id"]: row for row in profiles}
    pending = []
    for row in profiles:
        target = shards_dir / shard_name(row["unit_id"])
        if target.exists():
            _validate_shard(target, row)
        else:
            pending.append(row)
    workers = max(1, min(int(workers), len(profiles)))
    tasks = [
        (str((ROOT / row["path"]).resolve()), row["unit_id"], row["workbook_sha256"], str(output_dir))
        for row in pending
    ]
    print(f"V4-R1 baseline scheduling: workers={workers}; pending={len(tasks)}; resumed={len(profiles)-len(tasks)}", flush=True)
    if workers == 1:
        for index, task in enumerate(tasks, 1):
            print(f"[{index}/{len(tasks)}] {_predict(task)}", flush=True)
    elif tasks:
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_predict, task) for task in tasks]
            for index, future in enumerate(concurrent.futures.as_completed(futures), 1):
                print(f"[{index}/{len(tasks)}] {future.result()}", flush=True)

    shards = sorted(shards_dir.glob("*.json"))
    if len(shards) != len(profiles):
        raise ValueError(f"V4 baseline incomplete: {len(shards)} of {len(profiles)} shards")
    for shard in shards:
        unit_id = json.loads(shard.read_text(encoding="utf-8"))["unit_id"]
        if unit_id not in expected:
            raise ValueError(f"unexpected V4 baseline shard: {shard.name}")
        _validate_shard(shard, expected[unit_id])
    complete = {
        "protocol": RUN_PROTOCOL,
        "complete": True,
        "profile_count": len(profiles),
        "shard_count": len(shards),
        "metadata_sha256": sha256(metadata_path),
        "profiles_sha256": sha256(profiles_path),
        "combined_shards_sha256": _combined_shards(shards),
        "label_inputs_to_prediction": [],
        "source_hashes": source_hashes,
    }
    complete_path = output_dir / "complete.json"
    _write_json_atomic(complete_path, complete)
    print(complete_path)
    return complete_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--workers", type=int, default=24)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    try:
        run(profiles_path=args.profiles.resolve(), output_dir=args.output, workers=args.workers)
    except (OSError, ValueError, KeyError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"V4 baseline run refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
