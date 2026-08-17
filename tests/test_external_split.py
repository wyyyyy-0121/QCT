import tempfile
import unittest
from pathlib import Path

from scripts.split_enron_external import sha256


class ExternalSplitTests(unittest.TestCase):
    def test_sha256_changes_when_manifest_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "manifest.csv"
            path.write_text("instance_id\na\n", encoding="utf-8")
            first = sha256(path)
            path.write_text("instance_id\nb\n", encoding="utf-8")
            self.assertNotEqual(first, sha256(path))


if __name__ == "__main__":
    unittest.main()
