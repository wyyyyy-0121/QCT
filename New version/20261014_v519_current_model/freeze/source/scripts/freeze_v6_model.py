"""Freeze the selected V6 implementation, commit the receipt, tag, and push."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GIT_BUNDLED = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"


def git(*args, capture=True):
    executable = shutil.which("git") or str(GIT_BUNDLED)
    completed = subprocess.run(
        [executable, *args], cwd=ROOT, text=True, capture_output=capture, check=False
    )
    if completed.returncode:
        raise SystemExit((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    receipt_path = ROOT / "results/v6_validation_locked/v6_selection_receipt.json"
    if not receipt_path.exists():
        raise SystemExit("V6 freeze refused: selection receipt is missing")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not receipt.get("freeze_allowed") or receipt.get("selected_variant") not in {"a", "b", "c"}:
        raise SystemExit("V6 freeze refused: no variant passed all preregistered gates")
    if git("tag", "--list", "v6-lock"):
        raise SystemExit("V6 freeze tag already exists; refusing to rewrite it")
    dirty = git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SystemExit("V6 freeze refused: commit all tracked source changes first\n" + dirty)
    implementation_commit = git("rev-parse", "HEAD")
    v4_config = json.loads((ROOT / "research/frozen_config_v4.json").read_text(encoding="utf-8"))
    expected_v4 = v4_config["model_source_sha256"]["formulaguard/localize.py"]
    actual_v4 = sha256(ROOT / "formulaguard/localize.py")
    if actual_v4 != expected_v4:
        raise SystemExit("V6 freeze refused: frozen V4 source hash changed")
    source_files = tuple(dict.fromkeys([
        "formulaguard/v6.py", "formulaguard/api.py", "formulaguard/__init__.py",
        "formulaguard/cli.py", "research/V6_METHOD_SPEC.md",
        "research/V6_THIRD_PARTY_PROTOCOL.md", "research/V6_THIRD_PARTY_REVIEW_TEMPLATE.csv",
        "research/V6_THIRD_PARTY_CASE_MANIFEST_TEMPLATE.csv",
        "research/V6_THIRD_PARTY_TEMPLATE_EXAMPLE.json",
        "research/V6_FAILURE_HYPOTHESIS_AUDIT.json",
        *[path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "scripts").glob("*v6*.py"))],
        *[path.relative_to(ROOT).as_posix() for path in sorted(ROOT.glob("run_v6*.cmd"))],
        *[path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "tests").glob("test_v6*.py"))],
    ]))
    datasets = {}
    for name in ("development", "validation", "redteam", "clean"):
        root = ROOT / f"data/v6_{name}"
        datasets[name] = {
            file: sha256(root / file)
            for file in (
                "dataset_manifest.json", "dataset_build_complete.json", "instances.jsonl",
                "evaluation_labels.jsonl", "clean_manifest.json", "dataset_summary.csv",
            )
        }
        datasets[name]["dataset_quality.json"] = sha256(root / "validation/dataset_quality.json")
        datasets[name]["leakage_audit.json"] = sha256(root / "validation/leakage_audit.json")
    round_paths = {letter: ROOT / f"results/v6_development_{letter}/v6_round_audit.json" for letter in "abc"}
    round_payloads = {letter: json.loads(path.read_text(encoding="utf-8")) for letter, path in round_paths.items()}
    if any(payload.get("round") != letter or payload.get("workers") != 24 for letter, payload in round_payloads.items()):
        raise SystemExit("V6 freeze refused: A/B/C round audit identity or 24-worker policy failed")
    prediction_metadata_path = ROOT / "results/v6_validation_locked/predictions/prediction_metadata.json"
    prediction_completion_path = ROOT / "results/v6_validation_locked/predictions/prediction_complete.json"
    prediction_metadata = json.loads(prediction_metadata_path.read_text(encoding="utf-8"))
    prediction_completion = json.loads(prediction_completion_path.read_text(encoding="utf-8"))
    if prediction_metadata.get("git_commit") != implementation_commit:
        raise SystemExit("V6 freeze refused: validation predictions were not produced from current HEAD")
    if prediction_metadata.get("variants") != ["a", "b", "c"]:
        raise SystemExit("V6 freeze refused: validation did not predict A/B/C together")
    if not prediction_completion.get("complete") or not prediction_completion.get("full_ranking_audit_passed"):
        raise SystemExit("V6 freeze refused: complete-ranking audit is missing")
    clean = json.loads((ROOT / "results/v6_validation_locked/clean/v6_clean_summary.json").read_text(encoding="utf-8"))
    selected_method = f"v6_{receipt['selected_variant']}"
    selected_clean_rate = clean["variants"][selected_method]["false_alarm_rate"]
    selected_metrics = receipt["assessments"][receipt["selected_variant"]]["metrics"]

    tracked_receipt = ROOT / "research/V6_SELECTION_RECEIPT.json"
    tracked_receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tracked_rounds = {}
    for letter, payload in round_payloads.items():
        path = ROOT / f"research/V6_ROUND_{letter.upper()}_AUDIT.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tracked_rounds[letter] = path
    config = {
        "model_version": "v6-semantic-r1",
        "selected_variant": receipt["selected_variant"],
        "base_model": "frozen_v4_r1",
        "freeze_policy": "three_rounds_then_one_shot_internal_validation_then_third_party_600",
        "implementation_commit": implementation_commit,
        "parameters": __import__("formulaguard.v6", fromlist=["v6_default_parameters"]).v6_default_parameters(),
        "v4_source_sha256": actual_v4,
        "source_sha256": {file: sha256(ROOT / file) for file in source_files},
        "dataset_sha256": datasets,
        "round_audit_sha256": {letter: sha256(path) for letter, path in tracked_rounds.items()},
        "selection_receipt_sha256": sha256(tracked_receipt),
        "prediction_metadata_sha256": sha256(prediction_metadata_path),
        "prediction_completion_sha256": sha256(prediction_completion_path),
        "selected_validation_metrics": selected_metrics,
        "selected_clean_false_alarm_rate": selected_clean_rate,
        "environment": {"python": sys.version, "platform": platform.platform()},
        "final_600_labels_seen": False,
        "post_freeze_tuning_forbidden": True,
    }
    research_path = ROOT / "research/frozen_config_v6.json"
    results_path = ROOT / "results/v6_validation_locked/frozen_config_v6.json"
    text = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    research_path.write_text(text, encoding="utf-8")
    results_path.write_text(text, encoding="utf-8")
    git("add", "research/frozen_config_v6.json", "research/V6_SELECTION_RECEIPT.json",
        "research/V6_ROUND_A_AUDIT.json", "research/V6_ROUND_B_AUDIT.json",
        "research/V6_ROUND_C_AUDIT.json")
    git("commit", "-m", "Freeze FormulaGuard V6 semantic ranker")
    freeze_commit = git("rev-parse", "HEAD")
    # The committed file intentionally records the implementation parent; the
    # tag identifies the immutable config commit without a self-referential hash.
    git("tag", "-a", "v6-lock", "-m", "FormulaGuard V6 frozen before third-party 600-case release")
    git("push", "origin", "main", capture=False)
    git("push", "origin", "v6-lock", capture=False)
    print(research_path)
    print(f"V6 frozen and pushed at {freeze_commit}")


if __name__ == "__main__":
    main()
