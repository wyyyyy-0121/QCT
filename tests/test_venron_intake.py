import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import acquire_venron


def metadata(payload: bytes = b"VEnron test archive") -> dict[str, object]:
    return {
        "id": acquire_venron.ARTICLE_ID,
        "title": acquire_venron.ARTICLE_TITLE,
        "doi": acquire_venron.ARTICLE_DOI,
        "license": {"name": acquire_venron.LICENSE_NAME},
        "files": [{
            "id": acquire_venron.FILE_ID,
            "name": acquire_venron.FILE_NAME,
            "size": len(payload),
            "computed_md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
            "download_url": acquire_venron.DOWNLOAD_URL,
        }],
    }


class VEnronIntakeTests(unittest.TestCase):
    def test_exact_structured_metadata_is_accepted(self):
        with (
            mock.patch.object(acquire_venron, "FILE_SIZE", 20),
            mock.patch.object(
                acquire_venron,
                "FILE_MD5",
                "15a3430526b01a3ace679225a450cc1e",
            ),
        ):
            payload = metadata(b"x" * 20)
            payload["files"][0]["computed_md5"] = acquire_venron.FILE_MD5
            observed = acquire_venron.validate_metadata(payload)
        self.assertEqual(observed["article"]["id"], acquire_venron.ARTICLE_ID)
        self.assertEqual(observed["license"], "CC0")
        self.assertEqual(observed["file"]["id"], acquire_venron.FILE_ID)

    def test_changed_license_or_file_identity_is_rejected(self):
        payload = metadata()
        payload["license"] = {"name": "restricted"}
        with self.assertRaisesRegex(ValueError, "license changed"):
            acquire_venron.validate_metadata(payload)

        payload = metadata()
        payload["files"][0]["download_url"] = "https://example.invalid/replacement"
        with self.assertRaisesRegex(ValueError, "file identity changed"):
            acquire_venron.validate_metadata(payload)

    def test_acquisition_hashes_download_and_records_zero_protected_inputs(self):
        archive = b"VEnron test archive"
        expected_md5 = hashlib.md5(archive, usedforsecurity=False).hexdigest()
        expected_sha256 = hashlib.sha256(archive).hexdigest()

        def fake_download(url: str, destination: Path) -> tuple[int, str, str]:
            self.assertEqual(url, acquire_venron.DOWNLOAD_URL)
            destination.write_bytes(archive)
            return len(archive), expected_md5, expected_sha256

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "raw" / acquire_venron.FILE_NAME
            output = root / "results"
            with (
                mock.patch.object(acquire_venron, "FILE_SIZE", len(archive)),
                mock.patch.object(acquire_venron, "FILE_MD5", expected_md5),
                mock.patch.object(acquire_venron, "fetch_metadata", return_value=metadata()),
                mock.patch.object(acquire_venron, "download_to", side_effect=fake_download),
                mock.patch.object(
                    acquire_venron,
                    "require_clean_tracked_worktree",
                    return_value="a" * 40,
                ),
            ):
                receipt_path = acquire_venron.acquire(
                    destination=destination,
                    output_dir=output,
                )

            receipt = json.loads(receipt_path.read_text(encoding="ascii"))
            self.assertEqual(destination.read_bytes(), archive)
            self.assertEqual(receipt["sha256"], expected_sha256)
            self.assertEqual(receipt["archive_members_read"], 0)
            self.assertEqual(receipt["workbook_contents_read"], 0)
            self.assertEqual(receipt["protected_data_inputs"], [])

    def test_existing_output_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "archive.7z"
            destination.write_bytes(b"existing")
            with self.assertRaisesRegex(ValueError, "already exists"):
                acquire_venron.acquire(destination=destination, output_dir=root / "result")


if __name__ == "__main__":
    unittest.main()
