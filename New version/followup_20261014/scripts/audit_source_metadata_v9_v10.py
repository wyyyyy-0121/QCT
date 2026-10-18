"""Verify the new metadata checkpoint without changing older audit results."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "mapbox_like": rb"\b(?:sk|pk)\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{10,}",
    "github_token": rb"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})",
    "aws_access_key": rb"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b",
    "openai_project_key": rb"\bsk-proj-[A-Za-z0-9_-]{20,}",
    "private_key": rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    checks = []
    paths = set()
    for version in (9, 10):
        index = ROOT / f"source_discovery/expansion_index_20261018_v{version}.json"
        receipt = ROOT / f"source_discovery/expansion_20261018_v{version}/RECEIPT.json"
        data = json.loads(receipt.read_text())
        assert sha(index) == data["index_sha256"]
        paths.update((index, receipt))
        for entry in data["results"]:
            assert entry["workbook_acquired"] is False
            path = ROOT / entry["path"] if entry.get("path") else None
            if path is not None:
                assert sha(path) == entry["sha256"], entry["id"]
                assert path.stat().st_size == entry["bytes"], entry["id"]
                paths.add(path)
            checks.append({"version": version, "id": entry["id"],
                           "status": entry.get("status"),
                           "saved_response_hash_verified": path is not None})
    findings = []
    for path in sorted(paths):
        raw = path.read_bytes()
        for name, pattern in PATTERNS.items():
            count = len(re.findall(pattern, raw))
            if count:
                findings.append({"path": str(path.relative_to(ROOT)),
                                 "pattern": name, "count": count})
    assert not findings, "Potential credential patterns found; values omitted"
    result = {
        "role": "metadata integrity and credential-pattern check, not source acceptance",
        "requests_checked": checks,
        "files_pattern_scanned": len(paths),
        "credential_pattern_findings": findings,
        "workbook_bodies_acquired": False,
        "accepted_final_sources": 0,
        "accepted_final_template_families": 0,
        "audit_script_sha256": sha(Path(__file__)),
    }
    target = ROOT / "qa/SOURCE_METADATA_V9_V10_AUDIT_20261018.json"
    target.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"requests": len(checks), "files": len(paths), "findings": 0}))


if __name__ == "__main__":
    main()
