"""Write the immutable V5-Core configuration after locked validation."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    executable = "git" if subprocess.run(["where", "git"], capture_output=True).returncode == 0 else str(bundled)
    return subprocess.check_output([executable, *args], cwd=ROOT, text=True).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, default=Path("results/v5_core_validation/selection_audit.json"))
    parser.add_argument("--rule-config", type=Path, default=Path("results/v5_core_development/config/v5_core_rule_config.json"))
    parser.add_argument("--learned-config", type=Path, default=Path("results/v5_core_development/config/v5_core_learned_config.json"))
    parser.add_argument("--output", type=Path, default=Path("research/frozen_config_v5_core.json"))
    args = parser.parse_args()
    if git("status", "--porcelain"):
        raise SystemExit("Freeze refused: commit all tracked V5-Core changes first")
    selection = json.loads(args.selection.read_text(encoding="utf-8"))
    selected = selection.get("selected_head")
    if not selected:
        raise SystemExit("Freeze refused: locked validation did not promote V5")
    rule = json.loads(args.rule_config.read_text(encoding="utf-8"))
    learned = json.loads(args.learned_config.read_text(encoding="utf-8"))
    source_paths = [
        ROOT / "formulaguard/v5_core.py",
        ROOT / "formulaguard/api.py",
        ROOT / "research/V5_CORE_METHOD_SPEC.md",
    ]
    payload = {
        "protocol": "v5_core_immutable_freeze_v1",
        "model_version": "v5-core-r1",
        "selected_head": selected,
        "selected_config": learned if selected == "v5_learned" else rule,
        "rule_config": rule,
        "learned_config": learned,
        "selection_receipt": str(args.selection.resolve()),
        "selection_sha256": sha256(args.selection),
        "source_sha256": {str(path.relative_to(ROOT)): sha256(path) for path in source_paths},
        "git_commit": git("rev-parse", "HEAD"),
        "historical_models_modified": False,
        "third_party_results_seen": False,
        "tag_to_create": "v5-core-lock",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
