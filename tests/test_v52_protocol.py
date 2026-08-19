from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from formulaguard.workbook import WorkbookModel
from scripts.build_v52_stress_workbooks import build_redteam_workbooks
from scripts.run_external_evaluation import sha256_file
from scripts.v52_blind_protocol import validate_public_manifest, verify_joint_lock
from scripts.run_v4_v52_blind_100_lock import verify_precommit


class V52BlindProtocolTests(unittest.TestCase):
    def _public_set(
        self, root: Path, *, columns=("instance_id", "workbook"), count=15
    ) -> Path:
        workbook_dir = root / "workbooks"
        workbook_dir.mkdir()
        manifest = root / "manifest.csv"
        with manifest.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(columns))
            writer.writeheader()
            for index in range(1, count + 1):
                name = f"case_{index:03d}.xlsx"
                (workbook_dir / name).write_bytes(b"xlsx-test-fixture")
                row = {"instance_id": f"case_{index:03d}", "workbook": f"workbooks/{name}"}
                if "source_cell" in columns:
                    row["source_cell"] = "S!A1"
                writer.writerow(row)
        return manifest

    def test_public_manifest_requires_exactly_15_label_free_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._public_set(Path(directory))
            rows, hashes = validate_public_manifest(manifest)
            self.assertEqual(len(rows), 15)
            self.assertEqual(len(hashes), 15)

    def test_public_manifest_supports_preregistered_100_event_cohort(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._public_set(Path(directory), count=100)
            rows, hashes = validate_public_manifest(manifest, expected_events=100)
            self.assertEqual(len(rows), 100)
            self.assertEqual(len(hashes), 100)

    def test_100_case_precommit_requires_matching_public_hashes_and_partition(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            commitment = root / "commitment.json"
            public = root / "secret_precommit_sha256.txt"
            digest_a = "a" * 64
            digest_b = "b" * 64
            digest_c = "c" * 64
            commitment.write_text(json.dumps({
                "expected_total_events": 2,
                "previously_revealed_ids": ["case_001"],
                "new_blind_ids": ["case_002"],
                "labels_sha256": digest_a,
                "exceptions_sha256": digest_b,
                "private_batch2_archive_sha256": digest_c,
            }), encoding="utf-8")
            public.write_text("\n".join((digest_a, digest_b, digest_c)), encoding="utf-8")
            checked = verify_precommit(
                commitment, public, {"case_001", "case_002"}, 2
            )
            self.assertEqual(checked["labels_sha256"], digest_a)

    def test_public_manifest_rejects_even_one_label_column(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._public_set(
                Path(directory), columns=("instance_id", "workbook", "source_cell")
            )
            with self.assertRaisesRegex(ValueError, "forbidden fields"):
                validate_public_manifest(manifest)

    def test_public_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._public_set(root)
            rows = manifest.read_text(encoding="utf-8").splitlines()
            rows[1] = "case_001,../outside.xlsx"
            (root.parent / "outside.xlsx").write_bytes(b"outside")
            manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")
            try:
                with self.assertRaisesRegex(ValueError, "escapes"):
                    validate_public_manifest(manifest)
            finally:
                (root.parent / "outside.xlsx").unlink(missing_ok=True)

    def test_joint_lock_detects_changed_decisions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {}
            for key, name in {
                "v4_rankings": "v4.csv",
                "v52_decisions": "v52.csv",
                "metadata": "metadata.json",
            }.items():
                path = root / name
                path.write_text(key, encoding="utf-8")
                paths[key] = path
            lock = root / "prediction_lock.json"
            lock.write_text(json.dumps({
                "files": {
                    key: {"file": path.name, "sha256": sha256_file(path)}
                    for key, path in paths.items()
                }
            }), encoding="utf-8")
            verify_joint_lock(lock)
            paths["v52_decisions"].write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "v52_decisions"):
                verify_joint_lock(lock)

    def test_redteam_generator_builds_six_types_three_depths_two_strata(self):
        with tempfile.TemporaryDirectory() as directory:
            records = build_redteam_workbooks(Path(directory))
            self.assertEqual(len(records), 36)
            combinations = {
                (row["error_type"], row["depth_bin"], row["intended_v4_stratum"])
                for row in records
            }
            self.assertEqual(len(combinations), 36)
            ordinary = next(row for row in records if row["intended_v4_stratum"] == "top5")
            stress = next(row for row in records if row["intended_v4_stratum"] == "below5")
            ordinary_model = WorkbookModel.from_xlsx(ordinary["path"])
            stress_model = WorkbookModel.from_xlsx(stress["path"])
            self.assertNotEqual(ordinary_model.formulas[("Model", "V6")], ordinary["correct_formula"])
            self.assertGreater(len(stress_model.formulas), len(ordinary_model.formulas) + 100)


if __name__ == "__main__":
    unittest.main()
