"""Authorize SECRET reveal after five-model double-run locking."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MODEL_NAMES = ("v4_r1", "v5_v1", "v5_r2", "v5_1_development", "v5_1_1_development")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--prediction-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lock = json.loads(args.model_lock.read_text(encoding="utf-8"))
    if not lock.get("models_frozen_before_dataset_generation"):
        raise SystemExit("model lock is not frozen")
    prediction_locks = {}
    for name in MODEL_NAMES:
        first = args.prediction_root / name / "run_a" / "prediction_lock.json"
        second = args.prediction_root / name / "run_b" / "prediction_lock.json"
        if not first.is_file() or not second.is_file():
            raise SystemExit(f"missing prediction lock: {name}")
        if sha256(first) != sha256(second):
            raise SystemExit(f"double-run mismatch: {name}")
        prediction_locks[name] = sha256(first)
        for run in ("run_a", "run_b"):
            metadata = json.loads(
                (args.prediction_root / name / run / "prediction_metadata.json")
                .read_text(encoding="utf-8")
            )
            if metadata.get("labels_read") != []:
                raise SystemExit(f"labels were read by {name} {run}")
    result = {
        "protocol": "v511_natural_confirmation_reveal_authorization_v1",
        "model_lock_sha256": sha256(args.model_lock),
        "prediction_locks": prediction_locks,
        "labels_read_before_authorization": [],
        "double_run_identical": True,
        "authorized": True,
    }
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
