import unittest

from scripts.score_v5_structural_guard_secret import (
    average_precision,
    canonical_cell,
    formula_key,
    summarize,
)


class V5StructuralGuardSecretScoringTests(unittest.TestCase):
    def test_canonical_cell(self):
        self.assertEqual(canonical_cell("'Data Sheet'!$b$7"), ("Data Sheet", "B7"))

    def test_formula_key_removes_only_simple_sheet_quotes(self):
        self.assertEqual(formula_key("=B2 + '参数'!$B$2"), "=B2+参数!$B$2")
        self.assertEqual(formula_key("='Data'!B2"), "=DATA!B2")
        self.assertEqual(formula_key("='Data Sheet'!B2"), "='DATA SHEET'!B2")

    def test_average_precision_supports_multiple_truth_cells(self):
        ranking = [("S", "A1"), ("S", "A2"), ("S", "A3")]
        self.assertAlmostEqual(
            average_precision(ranking, {("S", "A1"), ("S", "A3")}), 5 / 6
        )
        self.assertIsNone(average_precision(ranking, set()))

    def test_summary_separates_candidates_from_group_actions(self):
        row = {
            "formula_cells": 10,
            "error_cells": 1,
            "average_precision": 1.0,
            "top_hits": {"1": 1, "3": 1, "5": 1, "10": 1, "20": 1},
            "candidate_cells": 2,
            "candidate_truth_hits": 1,
            "candidate_exact_repairs": 1,
            "group_candidate_cells": 0,
            "group_exact_repairs": 0,
            "accepted_groups": 0,
            "abstained_groups": 1,
        }
        result = summarize([row])
        self.assertEqual(result["candidate_exact_coverage"], 1.0)
        self.assertEqual(result["group_candidate_cells"], 0)
        self.assertEqual(result["accepted_groups"], 0)


if __name__ == "__main__":
    unittest.main()
