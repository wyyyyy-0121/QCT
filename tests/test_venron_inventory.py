import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import inventory_venron_v0


class VEnronInventoryTests(unittest.TestCase):
    def test_member_paths_fail_closed(self):
        for value in (
            "../escape.xls",
            "/absolute.xls",
            "C:/drive.xls",
            "group\\file.xls",
            "group//file.xls",
            "group/./file.xls",
            "group/line\nbreak.xls",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                inventory_venron_v0.safe_member_name(value)

    def test_inventory_counts_workbook_parents_without_opening_files(self):
        summary, rows = inventory_venron_v0.build_inventory([
            "VEnron/",
            "VEnron/group-1/",
            "VEnron/group-1/v1.xls",
            "VEnron/group-1/v2.xls",
            "VEnron/group-2/v1.xlsx",
            "VEnron/README.txt",
        ])
        self.assertEqual(summary["member_count"], 6)
        self.assertEqual(summary["workbook_member_count"], 3)
        self.assertEqual(summary["workbook_parent_candidate_count"], 2)
        self.assertEqual(summary["workbook_parent_size_distribution"], {"1": 1, "2": 1})
        self.assertEqual(sum(row["kind"] == "workbook" for row in rows), 3)

    def test_inventory_binds_archive_and_records_zero_content_reads(self):
        archive_bytes = b"public VEnron fixture"
        size = len(archive_bytes)
        md5 = hashlib.md5(archive_bytes, usedforsecurity=False).hexdigest()
        archive_sha256 = hashlib.sha256(archive_bytes).hexdigest()
        acquisition = {
            "protocol": inventory_venron_v0.ACQUISITION_PROTOCOL,
            "complete": True,
            "bytes": size,
            "md5": md5,
            "sha256": archive_sha256,
            "protected_data_inputs": [],
        }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "VEnron1.0.7z"
            archive.write_bytes(archive_bytes)
            receipt = root / "acquisition.json"
            receipt.write_text(json.dumps(acquisition), encoding="ascii")
            output = root / "output"
            with (
                mock.patch.object(
                    inventory_venron_v0,
                    "require_clean_pushed_worktree",
                    return_value="b" * 40,
                ),
                mock.patch.object(
                    inventory_venron_v0,
                    "resolve_bsdtar",
                    return_value="/fake/bsdtar",
                ),
                mock.patch.object(
                    inventory_venron_v0,
                    "list_members",
                    return_value=["VEnron/group/v1.xls", "VEnron/group/v2.xls"],
                ),
                mock.patch.object(inventory_venron_v0.subprocess, "run") as run,
            ):
                run.return_value.stdout = "bsdtar 3.8.7 - libarchive 3.8.7"
                result = inventory_venron_v0.inventory(
                    archive=archive,
                    acquisition_receipt=receipt,
                    output_dir=output,
                )

            payload = json.loads(result.read_text(encoding="ascii"))
            self.assertEqual(payload["archive_member_names_read"], 2)
            self.assertEqual(payload["archive_members_extracted"], 0)
            self.assertEqual(payload["workbook_contents_read"], 0)
            self.assertEqual(payload["protected_data_inputs"], [])
            self.assertEqual(payload["summary"]["workbook_parent_candidate_count"], 1)


if __name__ == "__main__":
    unittest.main()
