from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

TRACKED_SUFFIXES = {".py", ".mjs", ".ps1", ".cmd", ".toml", ".json", ".md"}
EXCLUDED_PARTS = {"node_modules", "results", "outputs", ".tmp_render", "__pycache__"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def command_output(command):
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=10).strip()
    except Exception as exc:  # noqa: BLE001 intentional compatibility or fallback boundary; preserve runtime behavior
        return f"unavailable:{type(exc).__name__}:{exc}"


def main():
    parser = argparse.ArgumentParser(description="Record reproducibility environment and source hashes")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--node")
    parser.add_argument("--git")
    args = parser.parse_args()
    root = args.root.resolve()
    files = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TRACKED_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if any(part in EXCLUDED_PARTS for part in relative.parts):
            continue
        files.append({"path": relative.as_posix(), "sha256": sha256(path)})
    payload = {
        "recorded_at": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "python_version": sys.version,
        "python_executable": sys.executable,
        "node_version": command_output([args.node, "--version"]) if args.node else "not supplied",
        "git_commit": command_output([args.git or "git", "rev-parse", "HEAD"]),
        "source_files": sorted(files, key=lambda row: row["path"]),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
