import tempfile
import unittest
from pathlib import Path

import openpyxl

from scripts.intake_venron_order_file import ORDER_MEMBER, inspect_order_workbook, validate_layout


def workbook_row(path: str) -> dict[str, object]:
    return {"kind": "workbook", "member_path": path}


class VEnronOrderIntakeTests(unittest.TestCase):
    def test_layout_separates_order_file_and_validates_declared_group_counts(self):
        members = [
            workbook_row(ORDER_MEMBER),
            workbook_row("VEnron1.0/1_2_alpha/v1.xls"),
            workbook_row("VEnron1.0/1_2_alpha/v2.xls"),
            workbook_row("VEnron1.0/2_1_beta/v1.xls"),
        ]
        result = validate_layout(
            members,
            expected_groups=2,
            expected_group_workbooks=3,
        )
        self.assertEqual(result["evolution_groups"], 2)
        self.assertEqual(result["group_workbooks"], 3)

    def test_layout_rejects_directory_declared_count_mismatch(self):
        members = [
            workbook_row(ORDER_MEMBER),
            workbook_row("VEnron1.0/1_3_alpha/v1.xls"),
            workbook_row("VEnron1.0/1_3_alpha/v2.xls"),
        ]
        with self.assertRaisesRegex(ValueError, "directory count"):
            validate_layout(
                members,
                expected_groups=1,
                expected_group_workbooks=2,
            )

    def test_order_schema_records_types_and_samples(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "order.xlsx"
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet.title = "Order"
            sheet.append(["group", "version", "file"])
            sheet.append([1, 1, "v1.xls"])
            sheet.append([1, 2, "v2.xls"])
            workbook.save(path)
            workbook.close()

            schema = inspect_order_workbook(path, sample_rows=2)
            observed = schema["sheets"][0]
            self.assertEqual(schema["sheet_count"], 1)
            self.assertEqual(observed["nonempty_cells"], 9)
            self.assertEqual(len(observed["sample_nonempty_rows"]), 2)
            self.assertEqual(observed["sample_nonempty_rows"][1][2]["value"], "v1.xls")


if __name__ == "__main__":
    unittest.main()
