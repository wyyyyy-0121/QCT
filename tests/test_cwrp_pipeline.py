import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.acquire_cwrp_sheetjs import acquire, collect_workbooks, parse_tree_snapshot
from scripts.build_v6_dataset import write_xlsx
from scripts.convert_cwrp_sheetjs import convert, install_converted


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CWRPAcquisitionTests(unittest.TestCase):
    def test_tree_snapshot_requires_complete_nuix_blob_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            path.write_text(json.dumps({
                "truncated": False,
                "tree": [
                    {"path": "nuix/a.xls", "type": "blob", "size": 3},
                    {"path": "nuix/readme.txt", "type": "blob", "size": 9},
                    {"path": "edrm/b.xls", "type": "blob", "size": 99},
                ],
            }), encoding="utf-8")
            self.assertEqual(
                parse_tree_snapshot(path),
                {"workbook_count": 1, "workbook_bytes": 3},
            )
            path.write_text(json.dumps({"truncated": True, "tree": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "truncated"):
                parse_tree_snapshot(path)

    def test_collect_workbooks_hashes_only_xls_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nuix").mkdir()
            workbook = root / "nuix/example.xls"
            workbook.write_bytes(b"xls")
            (root / "nuix/ignored.txt").write_text("ignored", encoding="utf-8")
            rows = collect_workbooks(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["relative_path"], "nuix/example.xls")
            self.assertEqual(rows[0]["sha256"], digest(workbook))

    def test_acquisition_pins_commit_license_tree_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"
            upstream.mkdir()
            subprocess.run(("git", "init", "-q"), cwd=upstream, check=True)
            subprocess.run(("git", "config", "user.email", "test@example.invalid"), cwd=upstream, check=True)
            subprocess.run(("git", "config", "user.name", "CWRP Test"), cwd=upstream, check=True)
            (upstream / "nuix").mkdir()
            (upstream / "edrm").mkdir()
            (upstream / "nuix/one.xls").write_bytes(b"one")
            (upstream / "edrm/excluded.xls").write_bytes(b"excluded")
            (upstream / "LICENSE").write_text("CC0 1.0 Universal", encoding="utf-8")
            (upstream / "README.md").write_text("fixture", encoding="utf-8")
            subprocess.run(("git", "add", "nuix", "edrm", "LICENSE", "README.md"), cwd=upstream, check=True)
            subprocess.run(("git", "commit", "-qm", "fixture"), cwd=upstream, check=True)
            commit = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=upstream, check=True,
                capture_output=True, text=True,
            ).stdout.strip()

            tree = root / "tree.json"
            tree.write_text(json.dumps({
                "truncated": False,
                "tree": [
                    {"path": "nuix/one.xls", "type": "blob", "size": 3},
                    {"path": "edrm/excluded.xls", "type": "blob", "size": 8},
                ],
            }), encoding="utf-8")
            receipt_path = acquire(
                destination=root / "checkout",
                output_dir=root / "receipt",
                tree_snapshot=tree,
                repository=str(upstream),
                commit=commit,
                expected_tree_sha256=digest(tree),
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            manifest = json.loads((root / "receipt/source_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(receipt["complete"])
            self.assertEqual(receipt["checkout_head"], commit)
            self.assertEqual(receipt["local_workbook_count"], 1)
            self.assertEqual(receipt["cell_contents_read"], 0)
            self.assertEqual(manifest["workbooks"][0]["relative_path"], "nuix/one.xls")
            self.assertFalse((root / "checkout/edrm").exists())

            with self.assertRaisesRegex(ValueError, "already exists"):
                acquire(
                    destination=root / "other-checkout",
                    output_dir=root / "receipt",
                    tree_snapshot=tree,
                    repository=str(upstream),
                    commit=commit,
                    expected_tree_sha256=digest(tree),
                )


class CWRPConversionTests(unittest.TestCase):
    def test_install_uses_target_filesystem_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            source = source_dir / "converted.xlsx"
            target = target_dir / "final.xlsx"
            source.write_bytes(b"converted")
            actual_replace = __import__("os").replace
            calls = []

            def inspect_replace(left, right):
                calls.append((Path(left), Path(right)))
                return actual_replace(left, right)

            with patch("scripts.convert_cwrp_sheetjs.os.replace", side_effect=inspect_replace):
                install_converted(source, target)
            self.assertEqual(target.read_bytes(), b"converted")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0].parent, target.parent)
            self.assertEqual(calls[0][1], target)

    def test_conversion_verifies_source_and_emits_formula_counts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            acquisition = root / "acquisition"
            source_workbook = source / "nuix/one.xls"
            source_workbook.parent.mkdir(parents=True)
            temporary_xlsx = root / "fixture.xlsx"
            write_xlsx(
                temporary_xlsx,
                [("Sheet", {"A1": 1, "B1": 2}, {"C1": "=A1+B1"})],
            )
            source_workbook.write_bytes(temporary_xlsx.read_bytes())
            source_hash = digest(source_workbook)
            acquisition.mkdir()
            manifest = {
                "protocol": "formulaguard_cwrp_sheetjs_acquisition_v1",
                "repository": "fixture",
                "commit": "5b73fc395cbe4727a986ab02a5028c1c1585617f",
                "workbooks": [{
                    "source_id": "sheetjs:" + source_hash,
                    "relative_path": "nuix/one.xls",
                    "bytes": source_workbook.stat().st_size,
                    "sha256": source_hash,
                }],
            }
            manifest_path = acquisition / "source_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt = {
                "protocol": "formulaguard_cwrp_sheetjs_acquisition_v1",
                "commit": "5b73fc395cbe4727a986ab02a5028c1c1585617f",
                "source_manifest_sha256": digest(manifest_path),
                "local_workbook_count": 1,
                "complete": True,
            }
            (acquisition / "acquisition_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8",
            )

            converter = root / "fake_libreoffice.py"
            converter.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, shutil, sys\n"
                "if '--version' in sys.argv:\n"
                "    print('Fake LibreOffice 1.0')\n"
                "    raise SystemExit(0)\n"
                "out = pathlib.Path(sys.argv[sys.argv.index('--outdir') + 1])\n"
                "source = pathlib.Path(sys.argv[-1])\n"
                "shutil.copyfile(source, out / (source.stem + '.xlsx'))\n",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            result_path = convert(
                source_root=source,
                acquisition_dir=acquisition,
                destination=root / "converted",
                output_dir=root / "result",
                workers=1,
                libreoffice=str(converter),
                timeout_seconds=10,
            )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            converted_manifest = json.loads(
                (root / "result/conversion_manifest.json").read_text(encoding="utf-8")
            )
            row = converted_manifest["results"][0]
            self.assertTrue(result["complete"])
            self.assertEqual(result["eligible_workbooks"], 1)
            self.assertEqual(row["formula_count"], 1)
            self.assertEqual(row["parseable_formula_count"], 1)
            self.assertNotIn("formula", row)
            self.assertNotIn("cell", row)
            with self.assertRaisesRegex(ValueError, "already complete"):
                convert(
                    source_root=source,
                    acquisition_dir=acquisition,
                    destination=root / "converted",
                    output_dir=root / "result",
                    workers=1,
                    libreoffice=str(converter),
                    timeout_seconds=10,
                )


if __name__ == "__main__":
    unittest.main()
