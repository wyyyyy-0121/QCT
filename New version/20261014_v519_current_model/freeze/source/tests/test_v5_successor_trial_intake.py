from __future__ import annotations

import csv
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from scripts.audit_v5_successor_revealed_trial import (
    CASE_FIELDS_V1,
    ERROR_TYPES,
    REVIEW_FIELDS_V1,
    SECRET_COMPONENTS_V1,
    _safe_member_name,
    audit_package,
)


def csv_bytes(fields, rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def write_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in sorted(members.items()):
            archive.writestr(name, value)


def build_v1_package(root: Path) -> None:
    public_rows = []
    cases = []
    reviews = []
    public_members = {}
    secret_members = {}
    hash_rows = []
    validation_rows = []
    mapping_rows = []
    error_index = 0
    for index in range(360):
        template = index // 12
        slot = index % 12
        instance = f"psl_{index:016x}"
        workbook = f"workbooks/{instance}.xlsx"
        original = f"originals/{instance}.xlsx"
        workbook_bytes = f"workbook-{index}".encode()
        original_bytes = f"original-{index}".encode()
        is_error = slot < 8
        if is_error:
            error_type = ERROR_TYPES[error_index % len(ERROR_TYPES)]
            identifiable = error_index < 180
            if identifiable:
                challenge = ""
            else:
                challenge = (
                    "single_source_exception_like" if error_index < 210
                    else "symmetric_multi_source"
                )
            sources = "Model!A1" if challenge != "symmetric_multi_source" else "Model!A1;Model!A2"
            for reviewer in (0, 1):
                reviews.append({
                    "instance_id": instance,
                    "reviewer_id": f"reviewer_{reviewer}",
                    "source_guess": sources if identifiable else "",
                    "unique_source": "1" if identifiable else "0",
                    "confidence": "high",
                    "notes": "",
                })
            error_index += 1
        else:
            error_type = identifiable = challenge = sources = ""
        public_rows.append({"instance_id": instance, "workbook": workbook})
        hash_rows.append({
            "instance_id": instance, "workbook": workbook,
            "sha256": digest(workbook_bytes),
        })
        cases.append({
            "instance_id": instance,
            "template_id": f"template_{template:02d}",
            "creator_id": f"creator_{template % 6}",
            "workbook": workbook,
            "original_workbook": original,
            "case_kind": "error" if is_error else "control",
            "error_type": error_type,
            "source_cells": sources,
            "identifiability": "identifiable" if identifiable is True else (
                "ambiguous" if identifiable is False else ""
            ),
            "control_subtype": "" if is_error else ("regular" if slot < 10 else "legal_exception"),
            "challenge_stratum": challenge,
            "template_origin": "steward_owned",
            "license_id": f"license_{template:02d}",
        })
        public_members[workbook] = workbook_bytes
        secret_members[original] = original_bytes
        validation_rows.append({"instance_id": instance})
        mapping_rows.append({
            "custodian_instance_id": f"raw_{index:03d}",
            "public_instance_id": instance,
        })
    manifest = csv_bytes(("instance_id", "workbook"), public_rows)
    workbook_hashes = csv_bytes(("instance_id", "workbook", "sha256"), hash_rows)
    secret_members.update({
        "cases.csv": csv_bytes(CASE_FIELDS_V1, cases),
        "reviews.csv": csv_bytes(REVIEW_FIELDS_V1, reviews),
        "third_party_declaration.json": json.dumps({"custodian_id": "custodian"}).encode(),
        "design_audit.json": json.dumps({"passed": True}).encode(),
        "case_validation.csv": csv_bytes(("instance_id",), validation_rows),
        "custodian_id_mapping.csv": csv_bytes(
            ("custodian_instance_id", "public_instance_id"), mapping_rows,
        ),
    })
    secret_zip = root / "FormulaGuard_V5_PSL_SECRET_360.zip"
    write_zip(secret_zip, secret_members)
    commitments = {
        name: digest(secret_members[name]) for name in SECRET_COMPONENTS_V1
    }
    commitments["SECRET.zip"] = hashlib.sha256(secret_zip.read_bytes()).hexdigest()
    precommit = "".join(
        f"{value}  {name}\n" for name, value in sorted(commitments.items())
    ).encode()
    public_members.update({
        "manifest.csv": manifest,
        "workbook_hashes.csv": workbook_hashes,
        "secret_precommit_sha256.txt": precommit,
    })
    public_members["public_metadata.json"] = json.dumps({
        "protocol": "v5_psl_third_party_pack_v1",
        "case_count": 360,
        "manifest_sha256": digest(manifest),
        "workbook_hashes_sha256": digest(workbook_hashes),
        "secret_precommit_sha256": digest(precommit),
        "labels_in_public_manifest": [],
    }).encode()
    public_zip = root / "FormulaGuard_V5_PSL_PUBLIC_360.zip"
    write_zip(public_zip, public_members)
    receipt = {
        "protocol": "v5_psl_third_party_pack_v1",
        "public_archive": public_zip.name,
        "public_archive_sha256": hashlib.sha256(public_zip.read_bytes()).hexdigest(),
        "secret_archive": secret_zip.name,
        "secret_archive_sha256": hashlib.sha256(secret_zip.read_bytes()).hexdigest(),
        "design_audit_sha256": digest(secret_members["design_audit.json"]),
        "case_count": 360,
    }
    (root / "package_receipt.json").write_text(json.dumps(receipt), encoding="utf-8")


class V5SuccessorTrialIntakeTests(unittest.TestCase):
    def test_unsafe_archive_names_are_rejected(self):
        for value in ("../escape", "/absolute", "folder\\file", "folder/./file"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                _safe_member_name(value)

    def test_complete_v1_package_is_audited_without_model_invocation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "trial"
            root.mkdir()
            build_v1_package(root)
            with mock.patch(
                "scripts.audit_v5_successor_revealed_trial.ALLOWED_ROOT", Path(directory)
            ), mock.patch(
                "scripts.audit_v5_successor_revealed_trial.ROOT", Path(directory)
            ), mock.patch(
                "scripts.audit_v5_successor_revealed_trial._git",
                return_value="a" * 40,
            ):
                result = audit_package(root)
            self.assertTrue(result["safe_to_begin_revealed_trial_prediction"])
            self.assertEqual(result["public_audit"]["workbooks"], 360)
            self.assertEqual(result["secret_audit"]["case_kind_counts"], {
                "control": 120, "error": 240,
            })
            self.assertEqual(result["model_invocations"], [])
            self.assertFalse(result["declared_six_creator_identity_independently_verified"])

    def test_receipt_hash_mismatch_is_rejected_before_archive_use(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "trial"
            root.mkdir()
            build_v1_package(root)
            receipt_path = root / "package_receipt.json"
            receipt = json.loads(receipt_path.read_text())
            receipt["public_archive_sha256"] = "0" * 64
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with (
                mock.patch(
                    "scripts.audit_v5_successor_revealed_trial.ALLOWED_ROOT", Path(directory)
                ),
                self.assertRaisesRegex(ValueError, "public archive hash failed"),
            ):
                audit_package(root)


if __name__ == "__main__":
    unittest.main()
