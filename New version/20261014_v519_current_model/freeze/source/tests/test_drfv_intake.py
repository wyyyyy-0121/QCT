import hashlib
import io
import json
import tarfile
import tempfile
import unittest
from pathlib import Path

from scripts.intake_drfv_spreadsheetbench_v1 import intake


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


class DRFVIntakeTests(unittest.TestCase):
    def build_archive(self, path: Path, *, unsafe_member: str | None = None) -> None:
        with tarfile.open(path, "w:gz") as archive:
            add_bytes(
                archive,
                "all_data_912_v0.1/dataset.json",
                json.dumps([{
                    "id": "task-1",
                    "spreadsheet_path": "spreadsheet/task-1",
                    "instruction": "DO_NOT_EXPORT_SECRET_INSTRUCTION",
                    "answer_position": "SECRET_CELL",
                }]).encode(),
            )
            add_bytes(
                archive,
                "all_data_912_v0.1/spreadsheet/task-1/1_task-1_input.xlsx",
                b"INPUT_WORKBOOK",
            )
            add_bytes(
                archive,
                "all_data_912_v0.1/spreadsheet/task-1/1_task-1_answer.xlsx",
                b"SECRET_ANSWER_WORKBOOK",
            )
            if unsafe_member is not None:
                add_bytes(archive, unsafe_member, b"unsafe")

    def test_intake_extracts_only_inputs_without_reading_task_metadata_values(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            self.build_archive(source)
            receipt_path = intake(
                archive_path=source,
                destination=root / "inputs",
                output_dir=root / "receipt",
                expected_archive_sha256=digest(source),
                expected_archive_size=source.stat().st_size,
                expected_tasks=1,
                expected_inputs=1,
            )
            receipt = json.loads(receipt_path.read_text(encoding="ascii"))
            self.assertEqual(receipt["extracted_inputs"], 1)
            self.assertEqual(receipt["answer_members_seen_not_read"], 1)
            self.assertEqual(receipt["task_metadata_values_read"], [])
            self.assertEqual(receipt["answer_workbook_inputs"], [])
            self.assertEqual(receipt["protected_data_inputs"], [])
            self.assertEqual(
                (root / "inputs/task-1/1_task-1_input.xlsx").read_bytes(),
                b"INPUT_WORKBOOK",
            )
            self.assertFalse((root / "inputs/task-1/1_task-1_answer.xlsx").exists())
            exported = "\n".join(
                path.read_text(encoding="ascii") for path in (root / "receipt").glob("*.json")
            )
            self.assertNotIn("DO_NOT_EXPORT_SECRET_INSTRUCTION", exported)
            self.assertNotIn("SECRET_CELL", exported)
            self.assertNotIn("SECRET_ANSWER_WORKBOOK", exported)

    def test_intake_rejects_path_traversal_even_when_member_is_not_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            self.build_archive(source, unsafe_member="all_data_912_v0.1/../escape.txt")
            with self.assertRaisesRegex(ValueError, "unsafe tar member"):
                intake(
                    archive_path=source,
                    destination=root / "inputs",
                    output_dir=root / "receipt",
                    expected_archive_sha256=digest(source),
                    expected_archive_size=source.stat().st_size,
                    expected_tasks=1,
                    expected_inputs=1,
                )
            self.assertFalse((root / "inputs").exists())
            self.assertFalse((root / "receipt").exists())

    def test_completed_intake_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.tar.gz"
            self.build_archive(source)
            kwargs = {
                "archive_path": source,
                "destination": root / "inputs",
                "output_dir": root / "receipt",
                "expected_archive_sha256": digest(source),
                "expected_archive_size": source.stat().st_size,
                "expected_tasks": 1,
                "expected_inputs": 1,
            }
            intake(**kwargs)
            with self.assertRaisesRegex(ValueError, "already exists"):
                intake(**kwargs)


if __name__ == "__main__":
    unittest.main()
