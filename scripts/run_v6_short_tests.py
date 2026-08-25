"""Run all Codex-owned V6 short tests and record a reproducible receipt."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_stream(command: list[str]) -> tuple[int, str]:
    process = subprocess.Popen(
        command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors="replace", bufsize=1,
    )
    lines = []
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    return process.wait(), "".join(lines)


def git_commit() -> str:
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe"
    for executable in ("git", str(bundled)):
        try:
            return subprocess.check_output([executable, "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        except Exception:
            continue
    return "unavailable"


def main():
    tests_code, tests_output = run_stream(["cmd.exe", "/d", "/c", "run_tests.cmd"])
    match = re.search(r"Ran\s+(\d+)\s+tests?", tests_output)
    tests_count = int(match.group(1)) if match else 0
    smoke_code = -1
    if tests_code == 0 and tests_count:
        smoke_code, _ = run_stream([sys.executable, "scripts/run_v6_smoke.py"])
    smoke_path = ROOT / "results/v6_smoke_semantic_r4/completion_audit.json"
    smoke = json.loads(smoke_path.read_text(encoding="utf-8")) if smoke_path.exists() else {}
    receipt = {
        "protocol": "v6_codex_owned_short_test_receipt_v1",
        "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "git_commit": git_commit(),
        "unit_tests": tests_count,
        "unit_tests_exit_code": tests_code,
        "smoke_exit_code": smoke_code,
        "smoke_audit_sha256": sha256(smoke_path) if smoke_path.exists() else None,
        "v6_source_sha256": sha256(ROOT / "formulaguard/v6.py"),
        "method_spec_sha256": sha256(ROOT / "research/V6_METHOD_SPEC.md"),
        "passed": tests_code == 0 and tests_count > 0 and smoke_code == 0 and smoke.get("passed") is True,
        "scope": "short engineering tests only; not paper performance evidence",
    }
    output = ROOT / "results/v6_short_test_receipt.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(output)
    if not receipt["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
