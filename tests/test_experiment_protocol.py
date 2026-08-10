import unittest

from scripts.prepare_enron_manifest import property_coordinate
from scripts.run_clean_evaluation import select_threshold


class ExperimentProtocolTests(unittest.TestCase):
    def test_threshold_maximizes_recall_under_clean_alarm_constraint(self):
        recall, threshold, alarm = select_threshold(
            mutant_scores=[0.9, 0.8, 0.7, 0.2],
            clean_scores=[0.6, 0.1, 0.05, 0.01],
            max_clean_alarm=0.25,
        )
        self.assertEqual(recall, 1.0)
        self.assertEqual(threshold, 0.2)
        self.assertEqual(alarm, 0.25)

    def test_enron_property_coordinate_uses_zero_based_sheet_index(self):
        self.assertEqual(property_coordinate("0!D!2", ["Inputs", "Summary"]), "Inputs!D2")
        self.assertEqual(property_coordinate("1!AA!19", ["Inputs", "Summary"]), "Summary!AA19")


if __name__ == "__main__":
    unittest.main()
