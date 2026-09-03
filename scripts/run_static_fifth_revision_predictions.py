#!/usr/bin/env python3
"""Create locked V4/static-fifth predictions from public before workbooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.localize import v4_scores
from formulaguard.v4_static_fifth import (
    ARCHITECTURE,
    MODEL_VERSION,
    REVIEW_BUDGET,
    static_fifth_decision,
)
from formulaguard.v5_psl import diagnose_v5_psl
from formulaguard.workbook import WorkbookModel

PROTOCOL = "formulaguard_static_fifth_public_revision_predictions_v1"
SCHEMA_VERSION = 1
EXPECTED_ARCHIVE_SHA256 = (
    "9a8496ff1ee457473bcf34019c3af2aa369fa38c41e2c8975d86b9067f9a67e4"
)
BEFORE_PATTERN = re.compile(
    r"public_revisions/workbooks/(?P<revision_id>PWR[0-9]{3})/before\.xlsx"
)
EXPECTED_REVISIONS = 4
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_MEMBER_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
DEFAULT_ARCHIVE = Path(
    "/home/ayaka/code/FormulaGuard_public_revisions_delivery_20260831.zip"
)
DEFAULT_OUTPUT = ROOT / "results/static_fifth_revision_predictions"
SOURCE_PATHS = (
    "formulaguard/a1.py",
    "formulaguard/formula.py",
    "formulaguard/localize.py",
    "formulaguard/v4_static_fifth.py",
    "formulaguard/v5_psl.py",
    "formulaguard/workbook.py",
    "scripts/run_static_fifth_revision_predictions.py",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_hash(payload: object) -> str:
    return sha256_bytes(canonical_json(payload).encode("ascii"))


def git_commit(root: Path = ROOT) -> str:
    return subprocess.check_output(
        ("git", "rev-parse", "HEAD"), cwd=root, text=True
    ).strip()


def _git_source_status(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "status", "--porcelain", "--", *SOURCE_PATHS),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return tuple(line for line in completed.stdout.splitlines() if line)


def capture_source_state(
    source_root: Path = ROOT,
    *,
    allow_dirty: bool = False,
) -> dict[str, object]:
    source_root = source_root.resolve()
    state = {
        "git_commit": git_commit(source_root),
        "source_sha256": {
            relative: sha256(source_root / relative) for relative in SOURCE_PATHS
        },
        "source_status": list(_git_source_status(source_root)),
    }
    dirty = bool(state["source_status"])
    if dirty and not allow_dirty:
        raise ValueError("formal prediction requires clean tracked source files")
    state["source_tree_dirty"] = dirty
    state["formal_evidence"] = not dirty
    return state


def verify_source_state(
    expected: Mapping[str, object], source_root: Path = ROOT
) -> None:
    observed = capture_source_state(source_root, allow_dirty=True)
    if any(
        observed[key] != expected[key]
        for key in ("git_commit", "source_sha256", "source_status")
    ):
        raise ValueError("prediction source changed during the run")


def _assert_safe_archive_path(path: Path) -> Path:
    candidate = path.resolve()
    if "FormulaGuard_240_120" in candidate.parts:
        raise ValueError("protected 240+120 path is forbidden")
    if not candidate.is_file() or candidate.suffix.lower() != ".zip":
        raise ValueError("public revision input must be an existing ZIP file")
    current = path.absolute()
    while True:
        if current.is_symlink():
            raise ValueError("symlinked archive paths are forbidden")
        if current == current.parent:
            break
        current = current.parent
    return candidate


def _validate_member(info: ZipInfo) -> None:
    name = info.filename
    pure = PurePosixPath(name)
    if (
        not name
        or "\\" in name
        or pure.is_absolute()
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise ValueError(f"unsafe ZIP member name: {name!r}")
    if info.flag_bits & 0x1:
        raise ValueError(f"encrypted ZIP member is forbidden: {name}")
    unix_mode = info.external_attr >> 16
    if unix_mode and stat.S_ISLNK(unix_mode):
        raise ValueError(f"symlink ZIP member is forbidden: {name}")
    if info.file_size > MAX_MEMBER_UNCOMPRESSED_BYTES:
        raise ValueError(f"ZIP member is too large: {name}")


def load_before_workbooks(
    archive: Path,
    *,
    expected_archive_sha256: str = EXPECTED_ARCHIVE_SHA256,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Read only preregistered before.xlsx payloads from the verified archive."""

    archive = _assert_safe_archive_path(archive)
    archive_hash = sha256(archive)
    if archive_hash != expected_archive_sha256:
        raise ValueError("public revision archive hash mismatch")
    try:
        with ZipFile(archive) as source:
            infos = source.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError("public revision archive has duplicate member names")
            for info in infos:
                _validate_member(info)
            if sum(info.file_size for info in infos) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise ValueError("public revision archive is too large")
            selected = []
            for info in infos:
                match = BEFORE_PATTERN.fullmatch(info.filename)
                if match:
                    selected.append((match.group("revision_id"), info))
            if len(selected) != EXPECTED_REVISIONS:
                raise ValueError(
                    f"expected {EXPECTED_REVISIONS} before workbooks, "
                    f"observed {len(selected)}"
                )
            identifiers = [revision_id for revision_id, _ in selected]
            if len(identifiers) != len(set(identifiers)):
                raise ValueError("duplicate public revision identifiers")
            workbooks = [
                {
                    "revision_id": revision_id,
                    "archive_member": info.filename,
                    "workbook_bytes": source.read(info),
                }
                for revision_id, info in sorted(selected)
            ]
    except BadZipFile as exc:
        raise ValueError("public revision archive is not a valid ZIP") from exc
    inventory = [
        {
            "revision_id": str(item["revision_id"]),
            "archive_member": str(item["archive_member"]),
            "workbook_sha256": sha256_bytes(item["workbook_bytes"]),
            "workbook_size": len(item["workbook_bytes"]),
        }
        for item in workbooks
    ]
    return workbooks, {
        "archive": archive.as_posix(),
        "archive_sha256": archive_hash,
        "archive_payload_members_read": [
            str(item["archive_member"]) for item in workbooks
        ],
        "before_workbook_inventory": inventory,
        "before_workbook_inventory_sha256": stable_hash(inventory),
        "label_members_read": [],
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def _ranking(
    cells: Sequence[str],
    candidate_formulas: Mapping[str, str | None],
) -> list[dict[str, object]]:
    return [
        {
            "rank": rank,
            "cell": cell,
            "candidate_formula": candidate_formulas.get(cell),
        }
        for rank, cell in enumerate(cells, 1)
    ]


def predict_workbook(
    workbook: Path,
    *,
    revision_id: str,
    archive_member: str,
    workbook_sha256: str,
    archive_sha256: str,
) -> dict[str, object]:
    if sha256(workbook) != workbook_sha256:
        raise ValueError("staged before workbook hash mismatch before parsing")
    model = WorkbookModel.from_xlsx(workbook)
    if sha256(workbook) != workbook_sha256:
        raise ValueError("staged before workbook changed while parsing")
    v4 = v4_scores(model, candidate_limit=15)
    static = diagnose_v5_psl(model, ablation="no_perturbation").ranking
    v4_cells = tuple(item.cell_label for item in v4)
    static_cells = tuple(item.cell_label for item in static)
    formula_cells = {f"{sheet}!{address}" for sheet, address in model.formula_cells}
    if set(v4_cells) != formula_cells:
        raise ValueError("V4 ranking does not contain the complete formula inventory")
    decision = static_fifth_decision(v4_cells, static_cells)
    candidate_formulas = {
        item.cell_label: item.candidate_formula for item in v4
    }
    return {
        "protocol": PROTOCOL,
        "schema_version": SCHEMA_VERSION,
        "revision_id": revision_id,
        "archive_sha256": archive_sha256,
        "archive_member": archive_member,
        "workbook_sha256": workbook_sha256,
        "formula_count": len(model.formulas),
        "review_budget": REVIEW_BUDGET,
        "model_version": MODEL_VERSION,
        "architecture": ARCHITECTURE,
        "static_candidate": decision.static_candidate,
        "displaced_v4_fifth": decision.displaced_v4_fifth,
        "ranking_changed": decision.changed,
        "rankings": {
            "v4_r1": _ranking(v4_cells, candidate_formulas),
            "v4_static_fifth": _ranking(decision.ranking, candidate_formulas),
        },
        "label_members_read": [],
        "label_inputs": [],
        "protected_data_inputs": [],
    }


def validate_record(record: Mapping[str, object]) -> None:
    if record.get("protocol") != PROTOCOL or record.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("prediction record protocol or schema mismatch")
    if record.get("label_members_read") != [] or record.get("label_inputs") != []:
        raise ValueError("prediction record declares label inputs")
    if record.get("protected_data_inputs") != []:
        raise ValueError("prediction record declares protected inputs")
    rankings = record.get("rankings")
    if not isinstance(rankings, Mapping) or set(rankings) != {
        "v4_r1",
        "v4_static_fifth",
    }:
        raise ValueError("prediction record ranking methods are malformed")
    formula_count = int(record["formula_count"])
    expected_cells: set[str] | None = None
    for method, raw_ranking in rankings.items():
        if not isinstance(raw_ranking, list) or len(raw_ranking) != formula_count:
            raise ValueError(f"{method} ranking is incomplete")
        cells = [str(item["cell"]) for item in raw_ranking]
        ranks = [int(item["rank"]) for item in raw_ranking]
        if ranks != list(range(1, formula_count + 1)) or len(cells) != len(set(cells)):
            raise ValueError(f"{method} ranking is malformed")
        if expected_cells is None:
            expected_cells = set(cells)
        elif set(cells) != expected_cells:
            raise ValueError("prediction methods rank different formula inventories")
    v4_cells = [str(item["cell"]) for item in rankings["v4_r1"]]
    candidate_cells = [
        str(item["cell"]) for item in rankings["v4_static_fifth"]
    ]
    if candidate_cells[:4] != v4_cells[:4]:
        raise ValueError("static-fifth prediction changed the frozen V4 Top-4")


def write_predictions(
    output: Path,
    records: Sequence[Mapping[str, object]],
    *,
    input_audit: Mapping[str, object],
    source_state: Mapping[str, object],
) -> Path:
    for record in records:
        validate_record(record)
    output = output.resolve()
    partial = output.with_name(output.name + ".partial")
    if output.exists() or partial.exists():
        raise ValueError("prediction output or partial output already exists")
    partial.mkdir(parents=True)
    try:
        shards = partial / "shards"
        shards.mkdir()
        shard_hashes: dict[str, str] = {}
        for record in records:
            name = f"{record['revision_id']}.json"
            path = shards / name
            path.write_text(canonical_json(record) + "\n", encoding="ascii")
            shard_hashes[f"shards/{name}"] = sha256(path)
        predictions_path = partial / "predictions.jsonl"
        with predictions_path.open("w", encoding="ascii", newline="\n") as handle:
            for record in records:
                handle.write(canonical_json(record) + "\n")
        metadata = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            **dict(input_audit),
            **dict(source_state),
            "candidate": {
                "model_version": MODEL_VERSION,
                "architecture": ARCHITECTURE,
                "review_budget": REVIEW_BUDGET,
                "formal_version": None,
            },
            "prediction_records": len(records),
            "changed_workbooks": sum(
                record["ranking_changed"] is True for record in records
            ),
            "predictions_sha256": sha256(predictions_path),
            "prediction_shard_sha256": shard_hashes,
            "shard_inventory_sha256": stable_hash(shard_hashes),
            "record_set_sha256": stable_hash(records),
            "labels_may_be_read_by_separate_scorer": True,
            "label_members_read": [],
            "label_inputs": [],
            "protected_data_inputs": [],
        }
        metadata_path = partial / "prediction_metadata.json"
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        receipt = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "complete": True,
            "formal_evidence": source_state["formal_evidence"],
            "git_commit": source_state["git_commit"],
            "archive_sha256": input_audit["archive_sha256"],
            "prediction_metadata_sha256": sha256(metadata_path),
            "predictions_sha256": sha256(predictions_path),
            "prediction_shard_sha256": shard_hashes,
            "shard_inventory_sha256": stable_hash(shard_hashes),
            "record_set_sha256": stable_hash(records),
            "prediction_records": len(records),
            "label_members_read": [],
            "label_inputs": [],
            "protected_data_inputs": [],
        }
        (partial / "completion_receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
            encoding="ascii",
        )
        os.replace(partial, output)
    except BaseException:
        shutil.rmtree(partial, ignore_errors=True)
        raise
    return output / "completion_receipt.json"


def run(
    *,
    archive: Path,
    output: Path,
    expected_archive_sha256: str = EXPECTED_ARCHIVE_SHA256,
    source_root: Path = ROOT,
    allow_dirty: bool = False,
) -> Path:
    source_state = capture_source_state(source_root, allow_dirty=allow_dirty)
    workbooks, input_audit = load_before_workbooks(
        archive,
        expected_archive_sha256=expected_archive_sha256,
    )
    records: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="static-fifth-revisions-") as directory:
        snapshot_root = Path(directory)
        for item in workbooks:
            revision_id = str(item["revision_id"])
            payload = item["workbook_bytes"]
            if not isinstance(payload, bytes):
                raise TypeError("before workbook payload is not bytes")
            workbook_hash = sha256_bytes(payload)
            snapshot = snapshot_root / f"{revision_id}.xlsx"
            snapshot.write_bytes(payload)
            records.append(
                predict_workbook(
                    snapshot,
                    revision_id=revision_id,
                    archive_member=str(item["archive_member"]),
                    workbook_sha256=workbook_hash,
                    archive_sha256=str(input_audit["archive_sha256"]),
                )
            )
            print(f"Predicted public revision {revision_id}", flush=True)
    records.sort(key=lambda item: str(item["revision_id"]))
    verify_source_state(source_state, source_root)
    return write_predictions(
        output,
        records,
        input_audit=input_audit,
        source_state=source_state,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=DEFAULT_ARCHIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-dirty", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = run(
            archive=args.archive,
            output=args.output,
            allow_dirty=args.allow_dirty,
        )
    except (OSError, TypeError, ValueError, KeyError, BadZipFile) as exc:
        raise SystemExit(f"public revision prediction refused: {exc}") from exc
    print(f"Public revision prediction receipt: {receipt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
