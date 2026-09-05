"""Materialize and audit preregistered public VRER revision candidates."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.vrer import (
    PROTOCOL,
    R0_PROTOCOL,
    audit_candidate,
    safe_relative_path,
    sha256_bytes,
    summarize_r0,
    workbook_profile,
)

SOURCE_PROTOCOL = "formulaguard_vrer_source_candidates_v1"


def _git(repo: Path, *args: str, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=text,
    )
    return completed.stdout


def _normalized_url(value: str) -> str:
    return value.removesuffix(".git").rstrip("/").lower()


def _write_materialized(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _audit_repository(
    source_root: Path,
    output: Path,
    source: Mapping[str, object],
) -> list[dict[str, object]]:
    repository = str(source.get("repository", ""))
    local_directory = safe_relative_path(source.get("local_directory"))
    canonical_url = str(source.get("canonical_url", ""))
    repo = (source_root / local_directory).resolve()
    if not repo.is_relative_to(source_root.resolve()) or not (repo / ".git").is_dir():
        raise ValueError(f"VRER source repository is absent: {repository}")
    origin = str(_git(repo, "remote", "get-url", "origin")).strip()
    if _normalized_url(origin) != _normalized_url(canonical_url):
        raise ValueError(f"VRER source origin differs: {repository}")

    pinned_head = str(source.get("pinned_head", ""))
    if str(_git(repo, "rev-parse", "HEAD")).strip() != pinned_head:
        raise ValueError(f"VRER source HEAD differs: {repository}")
    license_path = safe_relative_path(source.get("license_path"))
    license_bytes = _git(repo, "show", f"{pinned_head}:{license_path}", text=False)
    if not isinstance(license_bytes, bytes):
        raise TypeError("VRER license extraction did not return bytes")
    license_sha256 = sha256_bytes(license_bytes)
    declared_license_hash = str(source.get("license_sha256", ""))
    if declared_license_hash and declared_license_hash != license_sha256:
        raise ValueError(f"VRER source license hash differs: {repository}")
    license_verified = (
        bool(source.get("license_covers_workbooks"))
        and bool(source.get("license_spdx"))
        and bool(license_bytes.strip())
    )

    records: list[dict[str, object]] = []
    candidates = source.get("candidates")
    if not isinstance(candidates, list):
        raise TypeError(f"VRER source has no candidate list: {repository}")
    for raw in candidates:
        if not isinstance(raw, Mapping):
            raise TypeError("VRER candidate is malformed")
        candidate = dict(raw)
        candidate_id = str(candidate.get("candidate_id", ""))
        if not candidate_id or "/" in candidate_id or "\\" in candidate_id:
            raise ValueError("VRER candidate ID is invalid")
        commit = str(candidate.get("commit_sha", ""))
        parent = str(candidate.get("parent_sha", ""))
        path = safe_relative_path(candidate.get("workbook_path"))
        observed_parents = (
            str(_git(repo, "show", "-s", "--format=%P", commit)).strip().split()
        )
        if not observed_parents or observed_parents[0] != parent:
            raise ValueError(f"VRER candidate parent differs: {candidate_id}")
        subject = str(_git(repo, "show", "-s", "--format=%s", commit)).strip()
        if subject != str(candidate.get("evidence_quote", "")).strip():
            raise ValueError(f"VRER candidate evidence quote differs: {candidate_id}")
        commit_time = str(_git(repo, "show", "-s", "--format=%aI", commit)).strip()
        before_bytes = _git(repo, "show", f"{parent}:{path}", text=False)
        after_bytes = _git(repo, "show", f"{commit}:{path}", text=False)
        if not isinstance(before_bytes, bytes) or not isinstance(after_bytes, bytes):
            raise TypeError("VRER workbook extraction did not return bytes")
        suffix = Path(path).suffix.lower()
        before_path = output / "workbooks" / candidate_id / f"before{suffix}"
        after_path = output / "workbooks" / candidate_id / f"after{suffix}"
        _write_materialized(before_path, before_bytes)
        _write_materialized(after_path, after_bytes)
        candidate.update(
            {
                "repository": repository,
                "canonical_url": canonical_url,
                "commit_url": f"{canonical_url.rstrip('/')}/commit/{commit}",
                "committed_at": commit_time,
                "revision_group": sha256_bytes(
                    _normalized_url(canonical_url).encode("utf-8")
                ),
                "license_spdx": source.get("license_spdx"),
                "license_path": license_path,
                "license_sha256": license_sha256,
            }
        )
        before_profile = workbook_profile(before_path)
        after_profile = workbook_profile(after_path)
        record = audit_candidate(
            candidate,
            before_profile,
            after_profile,
            license_verified=license_verified,
        )
        record.update(
            {
                "canonical_url": canonical_url,
                "commit_sha": commit,
                "parent_sha": parent,
                "commit_url": candidate["commit_url"],
                "committed_at": commit_time,
                "evidence_quote": subject,
                "evidence_scope": candidate.get("evidence_scope"),
                "workbook_path": path,
                "before_sha256": before_profile["workbook_sha256"],
                "after_sha256": after_profile["workbook_sha256"],
                "license_spdx": source.get("license_spdx"),
                "license_sha256": license_sha256,
                "protected_data_inputs": [],
                "revealed_label_inputs": [],
            }
        )
        records.append(record)
    return records


def prepare(sources_path: Path, source_root: Path, output: Path) -> Path:
    if output.exists() and any(output.iterdir()):
        raise ValueError("VRER R0 output must be empty")
    sources = json.loads(sources_path.read_text(encoding="utf-8"))
    if (
        sources.get("protocol") != SOURCE_PROTOCOL
        or sources.get("vrer_protocol") != PROTOCOL
    ):
        raise ValueError("VRER source candidate protocol differs")
    rows = sources.get("sources")
    if not isinstance(rows, list) or not rows:
        raise ValueError("VRER source candidate list is empty")
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for source in rows:
        if not isinstance(source, Mapping):
            raise TypeError("VRER source record is malformed")
        records.extend(_audit_repository(source_root, output, source))
    ids = [str(row["candidate_id"]) for row in records]
    if len(ids) != len(set(ids)):
        raise ValueError("VRER candidate IDs are duplicated")
    records.sort(key=lambda row: str(row["candidate_id"]))
    summary = summarize_r0(records)
    receipt = {
        "protocol": R0_PROTOCOL,
        "vrer_protocol": PROTOCOL,
        "source_candidates_sha256": sha256_bytes(sources_path.read_bytes()),
        "summary": summary,
        "records": records,
        "protected_data_inputs": [],
        "revealed_label_inputs": [],
        "reproduction_status": "pending_independent_process",
    }
    receipt_path = output / "receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return receipt_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    path = prepare(
        args.sources.resolve(), args.source_root.resolve(), args.output.resolve()
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
