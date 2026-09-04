import json
import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook

from scripts.run_v5_structural_guard_public_predictions import (
    PUBLIC_FIELDS,
    combined_shards_sha256,
    prediction_record,
    prediction_scope,
    validate_public_manifest_fields,
)


class V5StructuralGuardPublicPredictionTests(unittest.TestCase):
    def test_public_manifest_schema_is_exact_and_label_free(self):
        validate_public_manifest_fields(PUBLIC_FIELDS)
        with self.assertRaisesRegex(ValueError, "fields differ"):
            validate_public_manifest_fields((*PUBLIC_FIELDS, "source_cell"))

    def test_prediction_is_complete_and_does_not_need_labels(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "anonymous.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Ops"
            sheet.append(["Opening", "Shipped", "Closing", "Balance Check"])
            for row in range(2, 9):
                sheet.append(
                    [100 + row, 10, f"=A{row}-B{row}", f"=C{row}-(A{row}-B{row})"]
                )
            workbook.save(path)
            record, elapsed = prediction_record(
                (
                    str(path),
                    {
                        "case_id": "k_0123456789abcdef0123",
                        "cluster_id": "c_0123456789abcd",
                        "workbook_path": "workbooks/anonymous.xlsx",
                        "workbook_sha256": "0" * 64,
                        "file_format": "xlsx",
                        "integrity_status": "package-valid",
                    },
                )
            )
        self.assertEqual(record["formula_count"], 14)
        self.assertEqual(len(record["ranking"]), 14)
        self.assertEqual([row["rank"] for row in record["ranking"]], list(range(1, 15)))
        self.assertGreaterEqual(elapsed, 0.0)
        self.assertNotIn("labels", record)

    def test_combined_shard_hash_is_order_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "a.json"
            second = root / "b.json"
            first.write_text(json.dumps({"value": 1}) + "\n", encoding="utf-8")
            second.write_text(json.dumps({"value": 2}) + "\n", encoding="utf-8")
            forward = combined_shards_sha256([first, second])
            reverse = combined_shards_sha256([second, first])
        self.assertEqual(forward, reverse)

    def test_prediction_scope_distinguishes_recalculation_stage(self):
        pending = [{"integrity_status": "package-valid;external-recalc-pending"}]
        complete = [{"integrity_status": "package-valid;external-recalc-complete"}]
        self.assertEqual(
            prediction_scope(pending)[0],
            "label_free_public_pre_recalc_engineering_prediction",
        )
        self.assertEqual(
            prediction_scope(complete)[0],
            "label_free_public_recalc_prediction",
        )
        with self.assertRaisesRegex(ValueError, "uniform recalculation stage"):
            prediction_scope(pending + complete)


if __name__ == "__main__":
    unittest.main()
