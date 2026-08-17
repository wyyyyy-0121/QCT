"""Verify the frozen v3-real sources and untouched test manifest before use."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--test-manifest", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    failures = []
    expected_manifest = config["untouched_test"]["manifest_sha256"]
    if sha256(args.test_manifest) != expected_manifest:
        failures.append("untouched test manifest hash changed")
    for relative, expected in config["source_hashes"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path) != expected:
            failures.append(f"frozen source changed: {relative}")
    if config.get("candidate_limit") != 15:
        failures.append("candidate limit is not the frozen value 15")
    if failures:
        raise SystemExit("Freeze verification failed:\n- " + "\n- ".join(failures))
    print(f"v3-real freeze verified: {config['implementation_commit']}")
    print(f"untouched external events: {config['untouched_test']['event_count']}")


if __name__ == "__main__":
    main()
