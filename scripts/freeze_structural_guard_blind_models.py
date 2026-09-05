"""Create the machine-readable model and protocol lock before data generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MODEL_SPECS = {
    "v4_r1": {"name": "V4-R1", "git_object": "freeze-v4-r1", "kind": "v4_r1"},
    "v5_v1": {
        "name": "V5-v1",
        "git_object": "ce7576354c0a4298019ee8bbbfc575fd68cff4da",
        "kind": "v5_v1",
    },
    "v5_r2": {
        "name": "V5-R2",
        "git_object": "2232a870e3be089650ccd1676049e6c5c35cd692",
        "kind": "v5_r2",
    },
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str, binary: bool = False):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=not binary
    )
    return result.stdout


def extract(commit: str, destination: Path) -> None:
    raw = git("archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=BytesIO(raw), mode="r:") as archive:
        for member in archive.getmembers():
            if (
                member.issym()
                or member.islnk()
                or ".." in PurePosixPath(member.name).parts
            ):
                raise ValueError("unsafe git archive")
        archive.extractall(destination, filter="data")


def inspect_model(source: Path, kind: str) -> dict:
    if kind == "v4_r1":
        expression = (
            "import importlib,inspect,json;m=importlib.import_module('formulaguard.localize');"
            "print(json.dumps({'entry_point':'formulaguard.localize.v4_scores',"
            "'signature':str(inspect.signature(m.v4_scores)),'parameters':{"
            "'candidate_limit':15,'max_intervention_cells':m.V4_INTERVENTION_BUDGET,"
            "'rrf_k':m.V4_RRF_K,'scope_depth':m.V4_SCOPE_DEPTH,'scope_decay':m.V4_SCOPE_DECAY,"
            "'strong_min_controls':m.V4_STRONG_MIN_CONTROLS,'strong_min_delta':m.V4_STRONG_MIN_DELTA,"
            "'strong_min_irg':m.V4_STRONG_MIN_IRG,'strong_promotion':m.V4_STRONG_PROMOTION,"
            "'moderate_min_controls':m.V4_MODERATE_MIN_CONTROLS,'moderate_min_delta':m.V4_MODERATE_MIN_DELTA,"
            "'moderate_min_irg':m.V4_MODERATE_MIN_IRG,'moderate_promotion':m.V4_MODERATE_PROMOTION}}))"
        )
    else:
        expression = (
            "import importlib,inspect,json;m=importlib.import_module('formulaguard.v5_structural_guard');"
            "print(json.dumps({'entry_point':'formulaguard.v5_structural_guard.v5_structural_guard_scores',"
            "'signature':str(inspect.signature(m.v5_structural_guard_scores)),"
            "'parameters':m.v5_structural_guard_default_parameters()}))"
        )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(source)
    completed = subprocess.run(
        [sys.executable, "-c", expression],
        cwd=source,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip())
    return json.loads(completed.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    models = {}
    for key, spec in MODEL_SPECS.items():
        commit = git("rev-parse", spec["git_object"]).strip()
        tree = git("rev-parse", f"{commit}^{{tree}}").strip()
        with tempfile.TemporaryDirectory(prefix=f"freeze-{key}-") as temporary:
            extract(commit, Path(temporary))
            inspected = inspect_model(Path(temporary), spec["kind"])
        models[key] = {
            **spec,
            "resolved_commit": commit,
            "source_tree": tree,
            **inspected,
        }
    lock = {
        "protocol": "structural_guard_fresh_blind_model_lock_v1_1",
        "models_frozen_before_dataset_generation": True,
        "models": models,
        "artifacts": {
            relative: sha256(ROOT / relative)
            for relative in (
                "research/STRUCTURAL_GUARD_FRESH_BLIND_PROTOCOL_V1.md",
                "research/STRUCTURAL_GUARD_FRESH_BLIND_PROTOCOL_V1_1.md",
                "research/STRUCTURAL_GUARD_FRESH_BLIND_ATTEMPT1_ABORT.json",
                "scripts/build_structural_guard_fresh_blind.py",
                "scripts/run_frozen_structural_guard_predictions.py",
                "scripts/score_structural_guard_fresh_blind.py",
            )
        },
        "promotion_gates": {
            "bootstrap_draws": 10000,
            "bootstrap_seed": 20260904,
            "macro_ap_delta_ci95_lower_gt": 0.0,
            "exact_coverage_noninferiority_margin": -0.05,
            "control_workbook_candidate_fpr_max": 0.20,
            "accepted_group_exact_coverage_min": 0.50,
            "accepted_group_precision_min": 0.95,
            "unsafe_accepted_groups_max": 0,
        },
    }
    args.output.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
