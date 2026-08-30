#!/usr/bin/env python3
"""Acquire the pinned public VEnron artifact with a fail-closed receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import urllib.request
from pathlib import Path
from typing import BinaryIO, Mapping


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_vhrl_venron_acquisition_v1"
ARTICLE_API = "https://api.figshare.com/v2/articles/4797943"
ARTICLE_ID = 4_797_943
ARTICLE_TITLE = "VEnron1.0"
ARTICLE_DOI = "10.6084/m9.figshare.4797943.v1"
LICENSE_NAME = "CC0"
FILE_ID = 7_889_947
FILE_NAME = "VEnron1.0.7z"
FILE_SIZE = 64_878_068
FILE_MD5 = "15a3430526b01a3ace679225a450cc1e"
DOWNLOAD_URL = "https://ndownloader.figshare.com/files/7889947"
DEFAULT_DESTINATION = (
    ROOT / "data/external/model_discovery/raw/venron/VEnron1.0.7z"
)
DEFAULT_OUTPUT = ROOT / "results/venron_intake_v1"
USER_AGENT = "FormulaGuard-VHRL-intake/1.0"


def hash_stream(handle: BinaryIO) -> tuple[int, str, str]:
    size = 0
    md5 = hashlib.md5(usedforsecurity=False)
    sha256 = hashlib.sha256()
    for block in iter(lambda: handle.read(1024 * 1024), b""):
        size += len(block)
        md5.update(block)
        sha256.update(block)
    return size, md5.hexdigest(), sha256.hexdigest()


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hash_stream(handle)[2]


def stable_hash(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )
    os.replace(temporary, path)


def require_clean_tracked_worktree() -> str:
    status = subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=no"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        raise ValueError("tracked worktree must be clean before VEnron acquisition")
    commit = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return commit.stdout.strip()


def fetch_metadata(url: str = ARTICLE_API) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Figshare metadata is not a JSON object")
    return payload


def validate_metadata(payload: Mapping[str, object]) -> dict[str, object]:
    expected_article = {
        "id": ARTICLE_ID,
        "title": ARTICLE_TITLE,
        "doi": ARTICLE_DOI,
    }
    observed_article = {key: payload.get(key) for key in expected_article}
    if observed_article != expected_article:
        raise ValueError(
            f"Figshare article identity changed: {observed_article!r}"
        )
    license_payload = payload.get("license")
    if not isinstance(license_payload, Mapping) or license_payload.get("name") != LICENSE_NAME:
        raise ValueError("Figshare license changed or is missing")
    files = payload.get("files")
    if not isinstance(files, list):
        raise ValueError("Figshare metadata has no file list")
    selected = [item for item in files if isinstance(item, Mapping) and item.get("id") == FILE_ID]
    if len(selected) != 1:
        raise ValueError("pinned VEnron file ID is missing or duplicated")
    expected_file = {
        "id": FILE_ID,
        "name": FILE_NAME,
        "size": FILE_SIZE,
        "computed_md5": FILE_MD5,
        "download_url": DOWNLOAD_URL,
    }
    observed_file = {key: selected[0].get(key) for key in expected_file}
    if observed_file != expected_file:
        raise ValueError(f"pinned VEnron file identity changed: {observed_file!r}")
    return {
        "article": expected_article,
        "license": LICENSE_NAME,
        "file": expected_file,
    }


def download_to(url: str, destination: Path) -> tuple[int, str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response, destination.open("xb") as output:
        size = 0
        md5 = hashlib.md5(usedforsecurity=False)
        sha256_digest = hashlib.sha256()
        for block in iter(lambda: response.read(1024 * 1024), b""):
            size += len(block)
            if size > FILE_SIZE:
                raise ValueError("VEnron download exceeds the pinned file size")
            output.write(block)
            md5.update(block)
            sha256_digest.update(block)
    return size, md5.hexdigest(), sha256_digest.hexdigest()


def acquire(*, destination: Path, output_dir: Path) -> Path:
    destination = destination.resolve()
    output_dir = output_dir.resolve()
    if destination.exists() or output_dir.exists():
        raise ValueError("completed or partial VEnron acquisition output already exists")
    commit = require_clean_tracked_worktree()
    metadata = validate_metadata(fetch_metadata())

    destination.parent.mkdir(parents=True, exist_ok=True)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary_archive = destination.with_suffix(destination.suffix + ".partial")
    temporary_output = output_dir.with_name(f".{output_dir.name}.{os.getpid()}.tmp")
    if temporary_archive.exists() or temporary_output.exists():
        raise ValueError("VEnron acquisition staging path already exists")

    installed_archive = False
    try:
        size, md5, archive_sha256 = download_to(DOWNLOAD_URL, temporary_archive)
        if size != FILE_SIZE or md5 != FILE_MD5:
            raise ValueError(
                "VEnron download identity mismatch: "
                f"bytes={size}, md5={md5}"
            )
        temporary_output.mkdir()
        source_path = Path(__file__).resolve()
        receipt = {
            "protocol": PROTOCOL,
            "implementation_commit": commit,
            "article_api": ARTICLE_API,
            "article_id": ARTICLE_ID,
            "article_title": ARTICLE_TITLE,
            "article_doi": ARTICLE_DOI,
            "license": LICENSE_NAME,
            "file_id": FILE_ID,
            "file_name": FILE_NAME,
            "download_url": DOWNLOAD_URL,
            "bytes": size,
            "md5": md5,
            "sha256": archive_sha256,
            "metadata_identity_sha256": stable_hash(metadata),
            "tool_sha256": sha256(source_path),
            "archive_members_read": 0,
            "workbook_contents_read": 0,
            "fault_label_inputs": [],
            "protected_data_inputs": [],
            "complete": True,
        }
        _write_json_atomic(temporary_output / "acquisition_receipt.json", receipt)
        os.replace(temporary_archive, destination)
        installed_archive = True
        os.replace(temporary_output, output_dir)
    except BaseException:
        temporary_archive.unlink(missing_ok=True)
        if installed_archive:
            destination.unlink(missing_ok=True)
        if temporary_output.exists():
            for path in temporary_output.iterdir():
                path.unlink()
            temporary_output.rmdir()
        raise
    return output_dir / "acquisition_receipt.json"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    try:
        receipt = acquire(destination=args.destination, output_dir=args.output)
    except (
        OSError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        raise SystemExit(f"VEnron acquisition refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
