import unittest

from scripts.run_excelint_native_baseline import (
    OutputSchemaError,
    column_name,
    parse_native_output,
    score,
)


class ExceLintNativeBaselineTests(unittest.TestCase):
    def test_native_coordinates_are_one_based_and_deduplicated(self):
        payload = [{"sheets": {
            "Input": {
                "sheet": {"formulas": [["=SECRET()"]], "values": [["private"]]},
                "foundBugs": [
                    {"x": 1, "y": 2, "c": 0},
                    {"x": 27, "y": 3, "c": 0},
                    {"x": 1, "y": 2, "c": 0},
                ],
            },
            "Empty": {"foundBugs": []},
        }}]
        self.assertEqual(column_name(26), "Z")
        self.assertEqual(column_name(27), "AA")
        result = parse_native_output(payload)
        self.assertEqual(result, ["Input!A2", "Input!AA3"])
        self.assertNotIn("SECRET", " ".join(result))

    def test_native_parser_rejects_reference_vectors(self):
        payload = [{"sheets": {"S": {"foundBugs": [{"x": 1, "y": 2, "c": 1}]}}}]
        with self.assertRaises(OutputSchemaError):
            parse_native_output(payload)

    def test_scoring_reports_native_region_cost_and_control_action(self):
        events = [
            {
                "event_id": "error-1", "unit_id": "u1", "structure_group": "g1",
                "cohort": "c1", "case_kind": "error", "source_formula_cells": ["S!A2"],
            },
            {
                "event_id": "control-1", "unit_id": "u2", "structure_group": "g2",
                "cohort": "c2", "case_kind": "control", "source_formula_cells": [],
            },
            {
                "event_id": "error-unsupported", "unit_id": "u3", "structure_group": "g3",
                "cohort": "c1", "case_kind": "error", "source_formula_cells": ["S!B2"],
            },
        ]
        predictions = {
            "u1": {"status": "ok", "review_cells": ["S!A2", "S!A3"], "review_cost": 2, "acted": 1},
            "u2": {"status": "ok", "review_cells": [], "review_cost": 0, "acted": 0},
            "u3": {"status": "nonzero_exit", "review_cells": [], "review_cost": None, "acted": None},
        }
        summary, rows = score(events, predictions)
        self.assertEqual(summary["compatibility"]["supported_units"], 2)
        self.assertEqual(summary["native_region"]["source_region_hit_structure_macro_supported"], 1.0)
        self.assertEqual(
            summary["native_region"]["source_region_hit_structure_macro_all_inputs_conservative"],
            0.5,
        )
        self.assertEqual(summary["native_region"]["mean_review_cells_per_supported_unit"], 1.0)
        self.assertEqual(summary["control_safety"]["control_workbook_action_rate_supported"], 0.0)
        self.assertIsNone(rows[2]["source_region_hit"])


if __name__ == "__main__":
    unittest.main()
