"""Create deterministic file inventory and SHA-256 checksums for handoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    excluded = {"SHA256SUMS.txt", "handoff_manifest.json"}
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix()
        if path.name in excluded or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rows.append({"path": relative, "bytes": path.stat().st_size, "sha256": sha256(path)})
    (root / "handoff_manifest.json").write_text(
        json.dumps({"version": "0.3.0", "file_count": len(rows), "files": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (root / "SHA256SUMS.txt").write_text(
        "".join(f"{row['sha256']}  {row['path']}\n" for row in rows),
        encoding="utf-8",
    )
    print(json.dumps({"root": str(root), "file_count": len(rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
