"""Create a pre-PUBLIC candidate lock without promoting V5-PSL to V5-R1."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from formulaguard.v5_psl import v5_psl_default_parameters
from formulaguard.v5_psl_protocol import PREDICTION_METHODS, canonical_json_sha256, sha256


HISTORICAL_SOURCE_HASHES = {
    "formulaguard/localize.py": "760fbf8519dce5a4604bcc6ba158e9ca44d9434e7e898c85e9f7bc51c6c99c40",
    "formulaguard/v5.py": "4e7d2b5cb5e850b823dc6e3e8e5901667fdae1ebf510a143fade5971af9b2a64",
    "formulaguard/v52.py": "3454998f904d277d7c9a05ba1c0512afdba7bd216d36369ef14a446d4e7af91d",
    "formulaguard/v6.py": "75296073a37c31c422364361d7fde7d6da0a313b816b5e7d7f5cc71b95d2a3c3",
}
REQUIRED_CORPORA = {
    "modified_euses", "info1", "integer_corpus", "enron_error",
    "forepbench", "spreadsheetbench",
}
CLAIM_MATRIX = ROOT / "research/V5_PSL_CLAIM_MATRIX.md"
BASELINE_POLICY = {
    "v4_r1": "fixed_top5_review",
    "v4_2_review_b": "frozen_v4_top5_plus_optional_sixth_review_slot",
    "v4_3_semantic_c": "fixed_top5_review",
    "v5_psl_dev1": "one_cell_localized_five_cell_review_otherwise_no_action",
}
LITERATURE_AREAS = {
    "spreadsheet ambiguity",
    "metamorphic spreadsheet testing",
    "invariant-based spreadsheet debugging",
    "spreadsheet formula-role outlier detection",
    "interventional debugging",
    "selective prediction",
}


def _git(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, text=True, capture_output=True, check=False,
    )
    if completed.returncode:
        raise ValueError((completed.stderr or completed.stdout).strip())
    return completed.stdout.strip()


def _read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _read_signatures(path: Path) -> list[str]:
    result = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        value = line.strip().lower()
        if not value or value.startswith("#"):
            continue
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise ValueError(f"Invalid formula-change signature at line {line_number}")
        result.append(value)
    if not result or len(result) != len(set(result)):
        raise ValueError("Development formula-change signatures must be non-empty and unique")
    return sorted(result)


def _validate_literature_gate(payload: dict[str, object]) -> list[dict[str, object]]:
    if payload.get("protocol") != "v5_psl_literature_gate_v1" or payload.get("passed") is not True:
        raise ValueError("The literature and novelty-claim gate has not passed")
    reviewed = payload.get("reviewed_sources")
    if not isinstance(reviewed, list) or not all(isinstance(row, dict) for row in reviewed):
        raise ValueError("Literature gate reviewed_sources must contain structured records")
    areas = [str(row.get("claim_area", "")) for row in reviewed]
    if len(reviewed) != len(LITERATURE_AREAS) or set(areas) != LITERATURE_AREAS:
        raise ValueError("Literature gate must cover each preregistered claim area exactly once")
    if payload.get("primary_sources_verified") != len(reviewed):
        raise ValueError("Literature gate primary-source count does not match its records")
    if payload.get("unresolved_claims") != []:
        raise ValueError("Literature gate still contains unresolved claims")
    required_text = (
        "citation_key", "title", "stable_locator", "checked_on",
        "overlap_assessment", "permitted_claim", "evidence_sha256",
    )
    for row in reviewed:
        area = str(row["claim_area"])
        if row.get("primary_source_checked") is not True:
            raise ValueError(f"Literature primary source was not checked: {area}")
        if any(not str(row.get(field, "")).strip() for field in required_text):
            raise ValueError(f"Literature review record is incomplete: {area}")
        if not str(row["stable_locator"]).startswith(("https://", "doi:")):
            raise ValueError(f"Literature review locator is not stable: {area}")
        if not re.fullmatch(r"20[0-9]{2}-[01][0-9]-[0-3][0-9]", str(row["checked_on"])):
            raise ValueError(f"Literature review date is invalid: {area}")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row["evidence_sha256"])):
            raise ValueError(f"Literature review evidence hash is invalid: {area}")
        if row["overlap_assessment"] == "same_method_found":
            raise ValueError(f"Literature review found the same method in prior work: {area}")
    return reviewed


def candidate_source_files() -> list[str]:
    fixed = {
        "pyproject.toml",
        "run_tests.sh",
        "scripts/libreoffice_psl_worker.py",
        "tests/test_version_lineage.py",
        "tests/test_workbook.py",
        "research/V5_PSL_METHOD_SPEC.md",
        "research/V5_PSL_CLAIM_MATRIX.md",
        "research/V5_PSL_PUBLIC_PRESSURE_PROTOCOL.md",
        "research/V5_PSL_THIRD_PARTY_PROTOCOL.md",
        "research/V5_PSL_MECHANISM_REVISION_LOG.json",
        "data/external/v5_psl/corpus_registry.json",
        "research/VERSION_LINEAGE_AND_NAMING_POLICY.md",
        "PROJECT_STATUS.md",
    }
    fixed.update(HISTORICAL_SOURCE_HASHES)
    fixed.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "formulaguard").glob("*.py")
    )
    fixed.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "scripts").glob("*v5_psl*.py")
    )
    fixed.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("test_v5_psl*.py")
    )
    fixed.update(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "research").glob("V5_PSL*")
        if path.is_file()
    )
    missing = sorted(relative for relative in fixed if not (ROOT / relative).is_file())
    if missing:
        raise ValueError(f"Candidate source inventory is incomplete: {missing}")
    return sorted(fixed)


def _libreoffice_version() -> str | None:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if not executable:
        return None
    completed = subprocess.run(
        [executable, "--version"], text=True, capture_output=True, check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def build_candidate_lock(
    literature_gate_path: Path,
    pressure_audit_path: Path,
    signatures_path: Path,
    *,
    public_archive_sha256: str,
    secret_archive_sha256: str,
) -> dict[str, object]:
    dirty = _git("status", "--porcelain", "--untracked-files=all")
    if dirty:
        raise ValueError("Candidate freeze requires a clean Git worktree")
    head = _git("rev-parse", "HEAD")
    literature = _read_json_object(literature_gate_path)
    reviewed_sources = _validate_literature_gate(literature)
    claim_matrix_sha256 = sha256(CLAIM_MATRIX)
    if literature.get("claim_matrix_sha256") != claim_matrix_sha256:
        raise ValueError("Literature gate does not bind the current V5-PSL claim matrix")
    pressure = _read_json_object(pressure_audit_path)
    if pressure.get("protocol") != "v5_psl_public_pressure_audit_v1":
        raise ValueError("Public pressure audit protocol is invalid")
    if pressure.get("hard_gate_passed") is not True or pressure.get("ablations_complete") is not True:
        raise ValueError("Public pressure and four-ablation gates have not passed")
    if int(pressure.get("mechanism_revision_count", -1)) not in {0, 1}:
        raise ValueError("Public development permits at most one recorded mechanism revision")
    observed_corpora = set(pressure.get("corpora_audited", []))
    if not REQUIRED_CORPORA <= observed_corpora:
        raise ValueError(f"Public corpus audit is incomplete: {sorted(REQUIRED_CORPORA - observed_corpora)}")
    if pressure.get("third_party_confirmation_files_read") != []:
        raise ValueError("Public pressure audit touched third-party confirmation files")
    sources = candidate_source_files()
    if pressure.get("git_commit") != head:
        raise ValueError("Public pressure audit was produced by a different Git commit")
    pressure_sources = pressure.get("source_sha256")
    if not isinstance(pressure_sources, dict) or set(pressure_sources) != set(sources):
        raise ValueError("Public pressure audit source inventory is incomplete")
    for relative in sources:
        if pressure_sources.get(relative) != sha256(ROOT / relative):
            raise ValueError(f"Public pressure source differs from the freeze candidate: {relative}")
    signatures = _read_signatures(signatures_path)
    signatures_file_sha256 = sha256(signatures_path)
    if pressure.get("development_signatures_sha256") != signatures_file_sha256:
        raise ValueError("Public pressure audit does not bind the development signatures file")
    archive_commitments = {
        "public_archive_sha256": public_archive_sha256.lower(),
        "secret_archive_sha256": secret_archive_sha256.lower(),
    }
    if any(
        not re.fullmatch(r"[0-9a-f]{64}", value)
        for value in archive_commitments.values()
    ):
        raise ValueError("Third-party archive commitments must be SHA-256 values")
    if len(set(archive_commitments.values())) != 2:
        raise ValueError("PUBLIC and SECRET archive commitments must differ")

    libreoffice_version = _libreoffice_version()
    if not libreoffice_version:
        raise ValueError("Candidate freeze requires an available LibreOffice installation")

    for relative, expected in HISTORICAL_SOURCE_HASHES.items():
        if sha256(ROOT / relative) != expected:
            raise ValueError(f"Historical frozen source changed: {relative}")
    return {
        "protocol": "v5_psl_candidate_lock_v1",
        "candidate_id": f"v5-psl-dev1-{head[:12]}",
        "candidate_locked": True,
        "formal_version": None,
        "formal_promotion_requires_third_party_240_120_pass": True,
        "git_commit": head,
        "parameters": v5_psl_default_parameters(),
        "prediction_methods": list(PREDICTION_METHODS),
        "baseline_policy": BASELINE_POLICY,
        "development_formula_change_signatures": signatures,
        "development_formula_change_signatures_sha256": canonical_json_sha256(signatures),
        "development_formula_change_signatures_file_sha256": signatures_file_sha256,
        "claim_matrix_sha256": claim_matrix_sha256,
        "literature_reviewed_sources_sha256": canonical_json_sha256(reviewed_sources),
        "literature_gate_sha256": sha256(literature_gate_path),
        "pressure_audit_sha256": sha256(pressure_audit_path),
        "source_sha256": {relative: sha256(ROOT / relative) for relative in sources},
        "historical_source_hashes_verified": True,
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
            "libreoffice": libreoffice_version,
        },
        "third_party_public_seen": False,
        "third_party_labels_seen": False,
        "third_party_files_read": [],
        "third_party_commitments_received_before_lock": archive_commitments,
        "candidate_tag_suggestion": "v5-psl-candidate-lock",
        "tag_created_by_this_script": False,
        "post_lock_tuning_forbidden": True,
        "clean_git_worktree_required_for_prediction": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze the V5-PSL development candidate")
    parser.add_argument("--literature-gate", type=Path, required=True)
    parser.add_argument("--pressure-audit", type=Path, required=True)
    parser.add_argument("--development-signatures", type=Path, required=True)
    parser.add_argument("--public-archive-sha256", required=True)
    parser.add_argument("--secret-archive-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Candidate lock already exists; refusing to rewrite it: {output}")
    try:
        payload = build_candidate_lock(
            args.literature_gate.resolve(), args.pressure_audit.resolve(),
            args.development_signatures.resolve(),
            public_archive_sha256=args.public_archive_sha256,
            secret_archive_sha256=args.secret_archive_sha256,
        )
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        raise SystemExit(f"V5-PSL candidate freeze refused: {exc}") from exc
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
    print(f"candidate_lock_sha256={sha256(output)}")
    print("This locks V5-PSL-dev1 only; it does not authorize the V5-R1 name.")


if __name__ == "__main__":
    main()
