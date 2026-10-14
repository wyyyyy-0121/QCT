"""Verify immutable V6/V4 source and selection hashes before post-freeze work."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return digest


def verify(config_path: Path | None = None):
    path = config_path or ROOT / "research/frozen_config_v6.json"
    if not path.exists():
        raise SystemExit("V6 reproducibility lock missing")
    config = json.loads(path.read_text(encoding="utf-8"))
    if sha256(ROOT / "formulaguard/localize.py") != config["v4_source_sha256"]:
        raise SystemExit("V6 lock failed: V4 source changed")
    for relative, expected in config["source_sha256"].items():
        if sha256(ROOT / relative) != expected:
            raise SystemExit(f"V6 lock failed: source changed: {relative}")
    receipt = ROOT / "research/V6_SELECTION_RECEIPT.json"
    if not receipt.exists() or sha256(receipt) != config["selection_receipt_sha256"]:
        raise SystemExit("V6 lock failed: selection receipt changed or missing")
    for letter, expected in config["round_audit_sha256"].items():
        audit = ROOT / f"research/V6_ROUND_{letter.upper()}_AUDIT.json"
        if not audit.exists() or sha256(audit) != expected:
            raise SystemExit(f"V6 lock failed: round {letter.upper()} audit changed or missing")
    return config


if __name__ == "__main__":
    config = verify()
    print(f"V6 reproducibility lock verified: {config['implementation_commit']}")
