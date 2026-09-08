"""Create the explicit, label-free authorization required for SECRET reveal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-lock", type=Path, required=True)
    parser.add_argument("--prediction-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model_lock = json.loads(args.model_lock.read_text(encoding="utf-8"))
    if not model_lock.get("models_frozen_before_dataset_generation"):
        raise SystemExit("model lock is not frozen")
    names = ("v4_r1", "v5_v1", "v5_r2", "v5_1_development")
    locks = {}
    for name in names:
        for run in ("run_a", "run_b"):
            path = args.prediction_root / name / run / "prediction_lock.json"
            if not path.is_file():
                raise SystemExit(f"missing prediction lock: {path}")
        first = args.prediction_root / name / "run_a" / "prediction_lock.json"
        second = args.prediction_root / name / "run_b" / "prediction_lock.json"
        if sha256(first) != sha256(second):
            raise SystemExit(f"double-run mismatch: {name}")
        locks[name] = sha256(first)
        metadata = json.loads(
            (args.prediction_root / name / "run_a" / "prediction_metadata.json")
            .read_text(encoding="utf-8")
        )
        if metadata.get("labels_read") != []:
            raise SystemExit(f"labels were read by {name}")
    authorization = {
        "protocol": "v51_natural_confirmation_reveal_authorization_v1",
        "model_lock_sha256": sha256(args.model_lock),
        "prediction_locks": locks,
        "labels_read_before_authorization": [],
        "double_run_identical": True,
        "authorized": True,
    }
    args.output.write_text(
        json.dumps(authorization, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
