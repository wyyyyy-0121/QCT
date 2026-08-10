import unittest

from formulaguard.localize import generate_candidates, localize
from formulaguard.workbook import WorkbookModel


def repeated_formula_model():
    cells = {}
    formulas = {}
    for row in range(5, 10):
        cells[("Model", f"B{row}")] = row
        cells[("Model", f"C{row}")] = row + 1
        formulas[("Model", f"D{row}")] = f"=B{row}*C{row}"
        formulas[("Model", f"E{row}")] = f"=D{row}*(1+$B$2)"
    cells[("Model", "B2")] = 0.08
    formulas[("Model", "D7")] = "=B6*C7"
    formulas[("Model", "E11")] = "=SUM(E5:E9)"
    return WorkbookModel.from_cells(cells, formulas)


class LocalizationTests(unittest.TestCase):
    def test_peer_translation_generates_true_repair_without_ground_truth(self):
        model = repeated_formula_model()
        candidates = generate_candidates(model, ("Model", "D7"), limit=20)
        indexed = {candidate.formula: candidate for candidate in candidates}
        self.assertIn("=B7*C7", indexed)
        self.assertIn("peer_translation", indexed["=B7*C7"].sources)
        self.assertGreater(indexed["=B7*C7"].quality, 0.0)

    def test_all_no_oracle_methods_return_complete_rankings(self):
        model = repeated_formula_model()
        methods = [
            "random",
            "excel_like",
            "pattern",
            "graph",
            "behavior",
            "excelint_like",
            "warder_like",
            "formulaguard",
        ]
        for method in methods:
            results = localize(model, method, candidate_limit=5)
            self.assertEqual(len(results), len(model.formula_cells))
            self.assertEqual({result.cell for result in results}, set(model.formula_cells))
            self.assertTrue(all(results[i].score >= results[i + 1].score for i in range(len(results) - 1)))

    def test_formulaguard_exposes_auditable_evidence(self):
        result = localize(repeated_formula_model(), "formulaguard", candidate_limit=5)[0]
        self.assertIn("base_energy", result.evidence)
        self.assertIn("prior_score", result.evidence)
        self.assertIn("localization_seconds", result.evidence)
        self.assertIn("delta_energy_normalized", result.evidence)
        self.assertIn("candidate_quality", result.evidence)
        self.assertGreaterEqual(result.evidence["influence"], 0.0)
        self.assertLessEqual(result.evidence["influence"], 1.0)


if __name__ == "__main__":
    unittest.main()
