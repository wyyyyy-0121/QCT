"""Build a label-free profile list for the workbooks actually seen at inference.

Phase 0 groups public error/control cases by their original workbook so that
the statistical unit is correct.  The signal audit, however, must inspect the
observed workbook (the modified error version or the clean control version),
not silently substitute its original.  This command bridges those two views:
it reads only the label-free ``scoring_groups.csv`` export, verifies every
observed file hash, and emits one deterministic profile row per unique observed
workbook content.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GROUPS = ROOT / "results/core_reset_b_phase0/scoring_groups.csv"
DEFAULT_OUTPUT = ROOT / "results/core_reset_b_phase0/observation_profiles.csv"
FORBIDDEN_FIELDS = {
    "source_cell",
    "source_cells",
    "correct_formula",
    "error_type",
    "case_kind",
    "corpus_id",
    "template_id",
    "secret_labels",
}
REQUIRED_FIELDS = {
    "cohort_instance_id",
    "cohort",
    "workbook",
    "workbook_sha256",
    "provenance_group_id",
    "structure_cluster_id",
    "outer_group_id",
}
ALLOWED_ROOTS = (
    ROOT / "data",
    ROOT / "results/v5_psl_pressure_inputs",
)
FORBIDDEN_PREFIXES = (
    "data/external/v5_psl/revealed_trial",
    "data/external/v5_psl/custodian",
    "data/external/v5_psl/final_blind",
)
OUTPUT_FIELDS = (
    "unit_id",
    "cohort",
    "structure_cluster_id",
    "path",
    "workbook_sha256",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_path(relative: str) -> Path:
    if not relative or "\\" in relative:
        raise ValueError(f"invalid workbook path: {relative!r}")
    candidate = (ROOT / relative).resolve()
    allowed = tuple(path.resolve() for path in ALLOWED_ROOTS)
    if not any(candidate == root or root in candidate.parents for root in allowed):
        raise ValueError(f"workbook path is outside the observation allowlist: {relative!r}")
    normalized = candidate.relative_to(ROOT).as_posix()
    if any(normalized == prefix or normalized.startswith(prefix + "/") for prefix in FORBIDDEN_PREFIXES):
        raise ValueError(f"workbook path is protected: {relative!r}")
    if not candidate.is_file():
        raise FileNotFoundError(candidate)
    return candidate


def _read_groups(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or ())
        missing = REQUIRED_FIELDS - fields
        forbidden = FORBIDDEN_FIELDS & fields
        if missing:
            raise ValueError(f"scoring groups missing fields: {sorted(missing)}")
        if forbidden:
            raise ValueError(f"scoring groups unexpectedly contain labels: {sorted(forbidden)}")
        rows = list(reader)
    if not rows:
        raise ValueError("scoring groups are empty")
    return rows


def build_profiles(groups_path: Path = DEFAULT_GROUPS) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Return deterministic observed-workbook profiles and an audit payload."""

    rows = _read_groups(groups_path)
    by_hash: dict[str, dict[str, str]] = {}
    paths_seen: set[Path] = set()
    for row in rows:
        path = _safe_path(row["workbook"])
        if path in paths_seen:
            # Repeated events in one Enron workbook are expected; they must
            # resolve to exactly the same hash and group metadata.
            pass
        paths_seen.add(path)
        actual_hash = sha256(path)
        declared_hash = row["workbook_sha256"].lower()
        if actual_hash != declared_hash:
            raise ValueError(
                f"workbook hash mismatch for {row['workbook']!r}: "
                f"declared {declared_hash}, observed {actual_hash}"
            )
        if len(actual_hash) != 64:
            raise ValueError(f"invalid workbook hash for {row['workbook']!r}")
        existing = by_hash.get(actual_hash)
        candidate = {
            "unit_id": "observed-workbook:" + actual_hash,
            "cohort": row["cohort"],
            "structure_cluster_id": row["structure_cluster_id"],
            "path": path.relative_to(ROOT).as_posix(),
            "workbook_sha256": actual_hash,
        }
        if existing is None:
            by_hash[actual_hash] = candidate
            continue
        for key in ("cohort", "structure_cluster_id"):
            if existing[key] != candidate[key]:
                raise ValueError(
                    f"observed hash {actual_hash} has conflicting {key}: "
                    f"{existing[key]!r} vs {candidate[key]!r}"
                )
        # Keep a stable representative path if byte-identical copies occur.
        if candidate["path"] < existing["path"]:
            existing["path"] = candidate["path"]

    profiles = sorted(by_hash.values(), key=lambda item: item["unit_id"])
    audit = {
        "protocol": "formulaguard_model_discovery_observation_profiles_v1",
        "groups_path": groups_path.relative_to(ROOT).as_posix()
        if groups_path.resolve().is_relative_to(ROOT)
        else str(groups_path.resolve()),
        "groups_sha256": sha256(groups_path),
        "group_rows": len(rows),
        "unique_observed_workbooks": len(profiles),
        "unique_observed_hashes": len({item["workbook_sha256"] for item in profiles}),
        "label_fields_read": [],
        "forbidden_fields_rejected": sorted(FORBIDDEN_FIELDS),
        "forbidden_input_prefixes": list(FORBIDDEN_PREFIXES),
        "profile_sha256": _stable_hash(profiles),
    }
    return profiles, audit


def _write_csv(path: Path, rows: Iterable[Mapping[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--groups", type=Path, default=DEFAULT_GROUPS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    groups = args.groups.resolve()
    if not groups.is_file():
        raise SystemExit(f"missing scoring groups: {groups}")
    try:
        profiles, audit = build_profiles(groups)
        output = args.output.resolve()
        _write_csv(output, profiles)
        audit["output"] = output.relative_to(ROOT).as_posix() if output.is_relative_to(ROOT) else str(output)
        audit["output_sha256"] = sha256(output)
        audit_path = output.with_name(output.stem + ".audit.json")
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"observation profile build refused: {exc}") from exc
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
