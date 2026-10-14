import unittest

from hybridguard.hybrid import build_parallel_group_evidence


class HybridTests(unittest.TestCase):
    def test_cross_sheet_majority_creates_group(self):
        formulas = {
            "A!I2": "=B2*C2", "B!I2": "=B2*C2", "C!I2": "=B2*C2",
            "D!I2": "=B2+C2", "E!I2": "=B2*C2",
            "A!I3": "=B3*C3", "B!I3": "=B3*C3", "C!I3": "=B3*C3",
            "D!I3": "=B3+C3", "E!I3": "=B3*C3",
        }
        by_cell, groups = build_parallel_group_evidence(
            formulas, ["A", "B", "C", "D", "E"]
        )
        self.assertEqual(set(by_cell), {"D!I2", "D!I3"})
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0].size, 2)


if __name__ == "__main__":
    unittest.main()
