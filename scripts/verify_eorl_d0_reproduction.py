"""Verify two independent EORL D0 runs and issue the final D0 decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.eorl import D0_PROTOCOL, PROTOCOL  # noqa: E402
from scripts.run_model_discovery_signals import sha256, stable_hash  # noqa: E402


PROTOCOL_REPRODUCTION = "formulaguard_eorl_d0_reproduction_v1"
ARTIFACTS = ("tasks.jsonl", "scoring.jsonl", "cross_engine.jsonl", "receipt.json")


def _load_receipt(directory: Path) -> dict[str, object]:
    path = directory / "receipt.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("protocol") != D0_PROTOCOL or payload.get("eorl_protocol") != PROTOCOL:
        raise ValueError(f"EORL D0 receipt protocol mismatch: {path}")
    recorded = dict(payload)
    receipt_hash = recorded.pop("receipt_sha256", None)
    if receipt_hash != stable_hash(recorded):
        raise ValueError(f"EORL D0 receipt hash mismatch: {path}")
    return payload


def verify(primary: Path, recheck: Path, output: Path) -> Path:
    primary = primary.resolve()
    recheck = recheck.resolve()
    if primary == recheck:
        raise ValueError("independent EORL D0 directories must differ")
    left = _load_receipt(primary)
    right = _load_receipt(recheck)
    comparisons = {}
    for name in ARTIFACTS:
        left_path = primary / name
        right_path = recheck / name
        left_hash = sha256(left_path)
        right_hash = sha256(right_path)
        comparisons[name] = {
            "primary_sha256": left_hash,
            "recheck_sha256": right_hash,
            "byte_identical": left_path.read_bytes() == right_path.read_bytes(),
        }
    scientific_receipt_match = left == right
    independent_reproduction = scientific_receipt_match and all(
        row["byte_identical"] for row in comparisons.values()
    )
    pre_gates = left.get("pre_reproduction_gates")
    if not isinstance(pre_gates, dict):
        raise ValueError("EORL D0 pre-reproduction gates are malformed")
    gates = dict(pre_gates)
    gates["independent_process_byte_identical"] = independent_reproduction
    gates["protected_and_forbidden_inputs_absent"] = (
        gates.get("protected_and_forbidden_inputs_absent") is True
        and left.get("protected_data_inputs") == []
        and left.get("label_inputs_to_prediction") == []
        and right.get("protected_data_inputs") == []
        and right.get("label_inputs_to_prediction") == []
    )
    result: dict[str, object] = {
        "protocol": PROTOCOL_REPRODUCTION,
        "eorl_protocol": PROTOCOL,
        "primary_receipt_sha256": sha256(primary / "receipt.json"),
        "recheck_receipt_sha256": sha256(recheck / "receipt.json"),
        "scientific_receipts_equal": scientific_receipt_match,
        "artifact_comparisons": comparisons,
        "gates": gates,
        "d0_passed": all(gates.values()),
        "summary": left.get("summary"),
        "protected_data_inputs": [],
        "label_inputs_to_prediction": [],
    }
    result["receipt_sha256"] = stable_hash(result)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if output.exists():
        if output.read_bytes() != data:
            raise ValueError(f"completed EORL reproduction receipt differs: {output}")
    else:
        temporary = output.with_suffix(output.suffix + ".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, output)
    return output


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--recheck", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(verify(args.primary, args.recheck, args.output))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"EORL D0 reproduction refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
