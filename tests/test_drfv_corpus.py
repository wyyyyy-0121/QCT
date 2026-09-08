import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_drfv_corpus import PROTOCOL, assign_splits, build
from scripts.build_v6_dataset import write_xlsx
from scripts.intake_drfv_spreadsheetbench_v1 import PROTOCOL as INTAKE_PROTOCOL


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DRFVCorpusTests(unittest.TestCase):
    def make_intake(self, root: Path) -> tuple[Path, Path]:
        source = root / "inputs"
        intake = root / "intake"
        source.mkdir()
        rows = []
        for index in range(3):
            task_id = f"task-{index}"
            task_dir = source / task_id
            task_dir.mkdir()
            workbook = task_dir / f"1_{task_id}_input.xlsx"
            write_xlsx(
                workbook,
                [("PrivateSheetName", {"A1": index + 1, "B1": 2}, {"C1": "=A1+B1"})],
            )
            rows.append({
                "workbook_id": f"spreadsheetbench-v1:{task_id}:{workbook.name}",
                "task_id": task_id,
                "relative_path": f"{task_id}/{workbook.name}",
                "bytes": workbook.stat().st_size,
                "sha256": digest(workbook),
            })
        intake.mkdir()
        manifest = {"protocol": INTAKE_PROTOCOL, "archive_sha256": "fixture", "workbooks": rows}
        manifest_path = intake / "input_manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="ascii")
        receipt = {
            "protocol": INTAKE_PROTOCOL,
            "complete": True,
            "input_manifest_sha256": digest(manifest_path),
            "extracted_inputs": len(rows),
            "task_metadata_values_read": [],
            "instruction_inputs": [],
            "answer_position_inputs": [],
            "answer_workbook_inputs": [],
            "fault_label_inputs": [],
            "v4_rank_inputs": [],
            "protected_data_inputs": [],
        }
        (intake / "intake_receipt.json").write_text(json.dumps(receipt), encoding="ascii")
        return intake, source

    def test_split_assignment_is_deterministic_and_group_disjoint(self):
        groups = [f"group-{index:03d}" for index in range(100)]
        first = assign_splits(groups)
        second = assign_splits(list(reversed(groups)))
        self.assertEqual(first, second)
        self.assertEqual(sum(value == "train" for value in first.values()), 70)
        self.assertEqual(sum(value == "calibration" for value in first.values()), 15)
        self.assertEqual(sum(value == "internal_test" for value in first.values()), 15)

    def test_build_profiles_without_exporting_cell_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            intake, source = self.make_intake(root)
            receipt_path = build(
                intake_dir=intake,
                source_root=source,
                prior_profile_dir=None,
                output_dir=root / "output",
                workers=2,
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            manifest = json.loads((root / "output/corpus_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(receipt["protocol"], PROTOCOL)
            self.assertEqual(receipt["status_counts"], {"eligible": 3})
            self.assertFalse(receipt["u0_passed"])
            self.assertEqual(receipt["answer_workbook_inputs"], [])
            self.assertEqual(receipt["protected_data_inputs"], [])
            self.assertTrue(all(row["status"] == "eligible" for row in manifest["workbooks"]))
            exported = "\n".join(
                path.read_text(encoding="utf-8")
                for path in (root / "output").rglob("*.json")
            )
            self.assertNotIn("PrivateSheetName", exported)
            self.assertNotIn('"A1": 1', exported)


if __name__ == "__main__":
    unittest.main()
