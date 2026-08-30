"""Acquire the preregistered SheetJS nuix corpus with an auditable receipt.

The command materializes only the pinned sparse paths. Workbook contents and
the detailed file manifest remain under ignored local paths; no cell content is
opened by this acquisition stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = "formulaguard_cwrp_sheetjs_acquisition_v1"
REPOSITORY = "https://github.com/SheetJS/enron_xls"
COMMIT = "5b73fc395cbe4727a986ab02a5028c1c1585617f"
TREE_SNAPSHOT_SHA256 = "22ac8694943eb5d2a552fc304ed4576fc2e55f5a5954656528cc2ec073998876"
DEFAULT_TREE_SNAPSHOT = Path("/tmp/sheetjs_enron_tree.json")
DEFAULT_DESTINATION = ROOT / "data/external/model_discovery/raw/sheetjs_enron"
DEFAULT_OUTPUT = ROOT / "results/cwrp_sheetjs_acquisition_v1"
SPARSE_PATHS = ("nuix", "LICENSE", "README.md")
MAX_WORKBOOK_BYTES = 256 * 1024 * 1024


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _run(command: Sequence[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def parse_tree_snapshot(path: Path) -> dict[str, int]:
    """Return the pinned remote nuix inventory without reading workbook blobs."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("truncated") is True:
        raise ValueError("GitHub tree snapshot is missing or truncated")
    tree = payload.get("tree")
    if not isinstance(tree, list):
        raise ValueError("GitHub tree snapshot has no tree list")
    count = 0
    total_bytes = 0
    for item in tree:
        if not isinstance(item, dict):
            continue
        relative = str(item.get("path", ""))
        if (
            item.get("type") == "blob"
            and relative.startswith("nuix/")
            and relative.lower().endswith(".xls")
        ):
            size = item.get("size")
            if not isinstance(size, int) or size < 0:
                raise ValueError(f"invalid remote size for {relative!r}")
            count += 1
            total_bytes += size
    if count == 0:
        raise ValueError("GitHub tree snapshot contains no nuix .xls files")
    return {"workbook_count": count, "workbook_bytes": total_bytes}


def collect_workbooks(destination: Path) -> list[dict[str, object]]:
    nuix = destination / "nuix"
    if not nuix.is_dir():
        raise ValueError("sparse checkout is missing nuix/")
    rows: list[dict[str, object]] = []
    for path in sorted(nuix.rglob("*"), key=lambda item: item.as_posix()):
        if path.is_symlink():
            raise ValueError(f"symlink is not allowed in nuix corpus: {path}")
        if not path.is_file() or path.suffix.lower() != ".xls":
            continue
        size = path.stat().st_size
        if size <= 0 or size > MAX_WORKBOOK_BYTES:
            raise ValueError(f"unsafe workbook size for {path}: {size}")
        relative = path.relative_to(destination).as_posix()
        digest = sha256(path)
        rows.append({
            "source_id": "sheetjs:" + digest,
            "relative_path": relative,
            "bytes": size,
            "sha256": digest,
        })
    if not rows:
        raise ValueError("sparse checkout contains no nuix .xls files")
    if len({str(row["relative_path"]) for row in rows}) != len(rows):
        raise ValueError("duplicate relative workbook path")
    return rows


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _checkout_sparse(destination: Path, repository: str, commit: str) -> None:
    if destination.exists():
        raise ValueError(f"destination already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(("git", "init", str(destination)))
    _run(("git", "remote", "add", "origin", repository), cwd=destination)
    _run(("git", "sparse-checkout", "init", "--no-cone"), cwd=destination)
    _run(("git", "sparse-checkout", "set", *SPARSE_PATHS), cwd=destination)
    _run(
        ("git", "fetch", "--depth=1", "--filter=blob:none", "--no-tags", "origin", commit),
        cwd=destination,
    )
    _run(("git", "checkout", "--detach", "FETCH_HEAD"), cwd=destination)


def acquire(
    *,
    destination: Path,
    output_dir: Path,
    tree_snapshot: Path,
    repository: str = REPOSITORY,
    commit: str = COMMIT,
    expected_tree_sha256: str = TREE_SNAPSHOT_SHA256,
) -> Path:
    destination = destination.resolve()
    output_dir = output_dir.resolve()
    tree_snapshot = tree_snapshot.resolve()
    if output_dir.exists():
        raise ValueError(f"acquisition output already exists: {output_dir}")
    if not tree_snapshot.is_file():
        raise FileNotFoundError(tree_snapshot)
    observed_tree_hash = sha256(tree_snapshot)
    if observed_tree_hash != expected_tree_sha256:
        raise ValueError(
            "GitHub tree snapshot hash mismatch: "
            f"expected {expected_tree_sha256}, observed {observed_tree_hash}"
        )
    remote_inventory = parse_tree_snapshot(tree_snapshot)
    _checkout_sparse(destination, repository, commit)
    observed_commit = _run(("git", "rev-parse", "HEAD"), cwd=destination)
    if observed_commit != commit:
        raise ValueError(f"checked out {observed_commit}, expected {commit}")
    if _run(("git", "status", "--porcelain"), cwd=destination):
        raise ValueError("sparse checkout is unexpectedly dirty")

    license_path = destination / "LICENSE"
    if not license_path.is_file():
        raise ValueError("sparse checkout is missing LICENSE")
    license_text = license_path.read_text(encoding="utf-8", errors="replace").upper()
    if "CC0" not in license_text and "CREATIVE COMMONS ZERO" not in license_text:
        raise ValueError("upstream LICENSE does not identify CC0")

    rows = collect_workbooks(destination)
    local_bytes = sum(int(row["bytes"]) for row in rows)
    if len(rows) != remote_inventory["workbook_count"]:
        raise ValueError(
            f"local/remote workbook count mismatch: {len(rows)} vs "
            f"{remote_inventory['workbook_count']}"
        )
    if local_bytes != remote_inventory["workbook_bytes"]:
        raise ValueError(
            f"local/remote workbook byte mismatch: {local_bytes} vs "
            f"{remote_inventory['workbook_bytes']}"
        )

    manifest = {
        "protocol": PROTOCOL,
        "repository": repository,
        "commit": commit,
        "sparse_paths": list(SPARSE_PATHS),
        "workbooks": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=False)
    manifest_path = output_dir / "source_manifest.json"
    _write_json_atomic(manifest_path, manifest)
    source_path = Path(__file__).resolve()
    receipt = {
        "protocol": PROTOCOL,
        "repository": repository,
        "commit": commit,
        "checkout_head": observed_commit,
        "sparse_paths": list(SPARSE_PATHS),
        "excluded_paths": ["edrm"],
        "license": "CC0-1.0",
        "license_sha256": sha256(license_path),
        "tree_snapshot_sha256": observed_tree_hash,
        "remote_workbook_count": remote_inventory["workbook_count"],
        "remote_workbook_bytes": remote_inventory["workbook_bytes"],
        "local_workbook_count": len(rows),
        "local_workbook_bytes": local_bytes,
        "source_manifest_sha256": sha256(manifest_path),
        "source_inventory_sha256": stable_hash(rows),
        "tool_sha256": sha256(source_path),
        "cell_contents_read": 0,
        "fault_label_inputs": [],
        "protected_data_inputs": [],
        "complete": True,
    }
    receipt_path = output_dir / "acquisition_receipt.json"
    _write_json_atomic(receipt_path, receipt)
    return receipt_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=DEFAULT_DESTINATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--tree-snapshot", type=Path, default=DEFAULT_TREE_SNAPSHOT)
    args = parser.parse_args()
    try:
        receipt = acquire(
            destination=args.destination,
            output_dir=args.output,
            tree_snapshot=args.tree_snapshot,
        )
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"CWRP acquisition refused: {exc}") from exc
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
