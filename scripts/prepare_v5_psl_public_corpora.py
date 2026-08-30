"""Acquire or adapt the six preregistered V5-PSL public corpora."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl_corpora import (
    CORPUS_IDS,
    acquire_corpus,
    adapt_corpus,
    load_registry,
    write_inventory,
)
from formulaguard.v5_psl_protocol import sha256


DEFAULT_REGISTRY = ROOT / "data/external/v5_psl/corpus_registry.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare V5-PSL public development corpora")
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    subparsers = parser.add_subparsers(dest="command", required=True)

    show = subparsers.add_parser("show", help="Validate and print the tracked registry")
    show.add_argument("--json", action="store_true")

    acquire = subparsers.add_parser("download", help="Acquire one pinned corpus locally")
    acquire.add_argument("--corpus", choices=CORPUS_IDS, required=True)
    acquire.add_argument("--root", type=Path, required=True)
    acquire.add_argument("--accept-terms", action="store_true")
    acquire.add_argument("--no-extract", action="store_true")

    adapt = subparsers.add_parser("adapt", help="Create a hash-only normalized inventory")
    adapt.add_argument("--corpus", choices=CORPUS_IDS, required=True)
    adapt.add_argument("--source", type=Path, required=True)
    adapt.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    try:
        registry_path = args.registry.resolve()
        registry = load_registry(registry_path)
        if args.command == "show":
            payload = {
                "protocol": "v5_psl_public_registry_audit_v1",
                "registry_sha256": sha256(registry_path),
                "corpora": list(CORPUS_IDS),
                "raw_redistribution_enabled": False,
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else "\n".join(CORPUS_IDS))
            return
        if args.command == "download":
            receipt = acquire_corpus(
                registry[args.corpus], args.root.resolve(),
                accept_terms=args.accept_terms, extract=not args.no_extract,
            )
            print(json.dumps(receipt, ensure_ascii=False, indent=2))
            return
        rows, audit = adapt_corpus(
            args.corpus, args.source.resolve(), registry[args.corpus],
        )
        write_inventory(args.output.resolve(), rows, audit)
        print(args.output / "inventory_audit.json")
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5-PSL corpus preparation refused: {exc}") from exc


if __name__ == "__main__":
    main()
