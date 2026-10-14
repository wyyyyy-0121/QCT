import tempfile
import unittest
from pathlib import Path

import openpyxl

from formulaguard.venron_proxy import (
    direct_formula_edits,
    exact_reversions,
    explicit_formula_errors,
)


def profile(rows: list[tuple[str, str, str]]) -> dict[str, object]:
    return {
        "formulas": [
            {"sheet": sheet, "address": address, "formula": formula}
            for sheet, address, formula in rows
        ]
    }


class VEnronProxyTests(unittest.TestCase):
    def test_explicit_error_profile_does_not_export_non_error_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cached.xlsx"
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            sheet["A1"] = "#REF!"
            sheet["A1"].data_type = "e"
            sheet["A2"] = 123456
            sheet["A3"] = "private text"
            sheet["Z100"] = "#N/A"
            sheet["Z100"].data_type = "e"
            workbook.save(path)
            workbook.close()
            result = explicit_formula_errors(
                path,
                profile([
                    ("Sheet", "A1", "=BAD()"),
                    ("Sheet", "A2", "=1"),
                    ("Sheet", "Z100", "=NA()"),
                ]),
            )
            self.assertEqual(result, [
                {"sheet": "Sheet", "address": "A1", "error": "#REF!"},
                {"sheet": "Sheet", "address": "Z100", "error": "#N/A"},
            ])
            self.assertNotIn("123456", str(result))
            self.assertNotIn("private text", str(result))

    def test_exact_reversion_requires_same_key_and_first_change_back_to_previous(self):
        previous = profile([("S", "A1", "=OLD"), ("S", "A2", "=X")])
        current = profile([("S", "A1", "=NEW"), ("S", "A2", "=Y")])
        future_1 = profile([("S", "A1", "=NEW"), ("S", "A2", "=THIRD")])
        future_2 = profile([("S", "A1", "=OLD"), ("S", "A2", "=X")])
        result = exact_reversions(previous, current, [future_1, future_2])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["address"], "A1")
        self.assertEqual(result[0]["horizon"], 2)

    def test_direct_edit_ignores_additions_and_removals(self):
        previous = profile([("S", "A1", "=1"), ("S", "A2", "=2")])
        current = profile([("S", "A1", "=3"), ("S", "A3", "=4")])
        result = direct_formula_edits(previous, current)
        self.assertEqual(result, [{
            "sheet": "S",
            "address": "A1",
            "previous_formula": "=1",
            "current_formula": "=3",
        }])


if __name__ == "__main__":
    unittest.main()
