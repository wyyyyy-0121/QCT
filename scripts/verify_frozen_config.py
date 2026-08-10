from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Reject full evaluation when frozen quick code has changed")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--git", required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    environment = json.loads(args.environment.read_text(encoding="utf-8"))
    current = {row["path"]: row["sha256"] for row in environment.get("source_files", [])}
    changed = sorted(
        path for path, expected in config["core_source_hashes"].items()
        if current.get(path) != expected
    )
    if changed:
        raise SystemExit("Frozen core code changed after quick: " + ", ".join(changed))
    if environment.get("git_commit") != config.get("git_commit"):
        raise SystemExit(
            f"Git commit differs from frozen quick run: {environment.get('git_commit')} != {config.get('git_commit')}"
        )
    status = subprocess.check_output(
        [args.git, "status", "--porcelain", "--untracked-files=no"],
        cwd=args.root,
        text=True,
        stderr=subprocess.STDOUT,
        timeout=15,
    ).strip()
    if status:
        raise SystemExit("Tracked worktree changes are present; commit or resolve them before full evaluation.")
    print("Frozen configuration, source hashes, Git commit, and tracked worktree are consistent.")


if __name__ == "__main__":
    main()
