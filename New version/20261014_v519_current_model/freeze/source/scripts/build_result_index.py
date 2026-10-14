from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description="Build a hash-backed index of experiment outputs")
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output = args.output or args.results / "result_index.json"
    records = []
    for path in args.results.rglob("*"):
        if not path.is_file() or path.resolve() == output.resolve():
            continue
        records.append({
            "path": path.relative_to(args.results).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "results_root": str(args.results.resolve()),
        "files": sorted(records, key=lambda row: row["path"]),
    }
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()

