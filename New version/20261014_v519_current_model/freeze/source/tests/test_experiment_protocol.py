import unittest

from scripts.prepare_enron_manifest import property_coordinate
from scripts.run_clean_evaluation import select_threshold
from scripts.run_experiments import resolve_worker_count


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

    def test_auto_worker_count_uses_three_quarters_of_logical_cpus(self):
        self.assertEqual(resolve_worker_count(0, 48, logical_cpus=32), 24)
        self.assertEqual(resolve_worker_count(0, 12, logical_cpus=32), 12)

    def test_explicit_worker_count_is_bounded_by_tasks(self):
        self.assertEqual(resolve_worker_count(8, 3, logical_cpus=32), 3)


if __name__ == "__main__":
    unittest.main()
