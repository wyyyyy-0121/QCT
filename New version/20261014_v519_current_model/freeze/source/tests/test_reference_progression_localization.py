import unittest

from formulaguard.workbook import WorkbookModel
from scripts.run_reference_progression_localization import progression_rankings


class ReferenceProgressionLocalizationTests(unittest.TestCase):
    def test_strict_residual_promotes_only_the_corrupted_progression_cell(self):
        model = WorkbookModel.from_cells({}, {
            ("S", "B2"): "=A2",
            ("S", "C2"): "=A2",
            ("S", "D2"): "=B2",
            ("S", "E2"): "=A2",
            ("S", "F2"): "=A2",
        })
        v4 = [
            {"rank": rank, "cell": f"S!{address}"}
            for rank, address in enumerate(("B2", "C2", "E2", "F2", "D2"), 1)
        ]
        result = progression_rankings(model, v4)
        self.assertEqual(result["action_cells"], ["S!D2"])
        self.assertEqual(result["standalone_ranking"][0]["cell"], "S!D2")
        self.assertEqual(result["v4_fusion_ranking"][0]["cell"], "S!D2")

    def test_clean_progression_abstains(self):
        model = WorkbookModel.from_cells({}, {
            ("S", "B2"): "=A2",
            ("S", "C2"): "=A2",
            ("S", "D2"): "=A2",
            ("S", "E2"): "=A2",
            ("S", "F2"): "=A2",
        })
        v4 = [
            {"rank": rank, "cell": f"S!{address}"}
            for rank, address in enumerate(("B2", "C2", "D2", "E2", "F2"), 1)
        ]
        result = progression_rankings(model, v4)
        self.assertEqual(result["action_cells"], [])
        self.assertEqual(result["v4_fusion_ranking"], v4)


if __name__ == "__main__":
    unittest.main()
