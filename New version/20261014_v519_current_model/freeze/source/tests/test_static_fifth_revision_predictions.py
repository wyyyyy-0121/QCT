import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from zipfile import ZipFile

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_static_fifth_revision_predictions.py"
SPEC = importlib.util.spec_from_file_location(
    "run_static_fifth_revision_predictions", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def workbook_bytes(path: Path) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Model"
    for row in range(1, 9):
        sheet[f"A{row}"] = row
        sheet[f"B{row}"] = row * 2
        sheet[f"C{row}"] = f"=A{row}+B{row}"
    workbook.save(path)
    return path.read_bytes()


def write_archive(path: Path) -> None:
    payload = workbook_bytes(path.with_suffix(".xlsx"))
    with ZipFile(path, "w") as archive:
        for index in range(1, 5):
            archive.writestr(
                f"public_revisions/workbooks/PWR{index:03d}/before.xlsx",
                payload,
            )
            archive.writestr(
                f"public_revisions/workbooks/PWR{index:03d}/after.xlsx",
                b"label payload must not be read by prediction",
            )
        archive.writestr(
            "public_revisions/cases.csv",
            b"label payload must not be read by prediction",
        )


class StaticFifthRevisionPredictionTests(unittest.TestCase):
    def test_double_run_is_before_only_complete_and_byte_stable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "public_revisions.zip"
            write_archive(archive)
            expected_hash = runner.sha256(archive)
            first = root / "first"
            second = root / "second"
            with mock.patch.object(runner, "_git_source_status", return_value=()):
                runner.run(
                    archive=archive,
                    output=first,
                    expected_archive_sha256=expected_hash,
                    allow_dirty=True,
                )
                runner.run(
                    archive=archive,
                    output=second,
                    expected_archive_sha256=expected_hash,
                    allow_dirty=True,
                )

            files = sorted(
                path.relative_to(first)
                for path in first.rglob("*")
                if path.is_file()
            )
            self.assertEqual(
                files,
                sorted(
                    path.relative_to(second)
                    for path in second.rglob("*")
                    if path.is_file()
                ),
            )
            for relative in files:
                self.assertEqual(
                    (first / relative).read_bytes(),
                    (second / relative).read_bytes(),
                )

            metadata = json.loads(
                (first / "prediction_metadata.json").read_text()
            )
            self.assertEqual(metadata["prediction_records"], 4)
            self.assertEqual(len(metadata["prediction_shard_sha256"]), 4)
            self.assertEqual(metadata["label_members_read"], [])
            self.assertEqual(metadata["label_inputs"], [])
            self.assertEqual(metadata["protected_data_inputs"], [])
            self.assertEqual(
                metadata["archive_payload_members_read"],
                [
                    f"public_revisions/workbooks/PWR{index:03d}/before.xlsx"
                    for index in range(1, 5)
                ],
            )
            self.assertFalse(
                any(
                    "after.xlsx" in member or member.endswith("cases.csv")
                    for member in metadata["archive_payload_members_read"]
                )
            )
            record = json.loads(
                (first / "shards/PWR001.json").read_text()
            )
            self.assertEqual(set(record["rankings"]), {"v4_r1", "v4_static_fifth"})
            self.assertEqual(
                len(record["rankings"]["v4_r1"]),
                record["formula_count"],
            )
            self.assertEqual(
                record["rankings"]["v4_r1"][:4],
                record["rankings"]["v4_static_fifth"][:4],
            )

    def test_archive_hash_and_before_count_are_enforced(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "public_revisions.zip"
            write_archive(archive)
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                runner.load_before_workbooks(
                    archive,
                    expected_archive_sha256="0" * 64,
                )

            incomplete = root / "incomplete.zip"
            payload = workbook_bytes(root / "incomplete.xlsx")
            with ZipFile(incomplete, "w") as output:
                output.writestr(
                    "public_revisions/workbooks/PWR001/before.xlsx",
                    payload,
                )
            with self.assertRaisesRegex(ValueError, "expected 4"):
                runner.load_before_workbooks(
                    incomplete,
                    expected_archive_sha256=runner.sha256(incomplete),
                )


if __name__ == "__main__":
    unittest.main()
