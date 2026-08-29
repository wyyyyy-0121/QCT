import unittest

from scripts.run_v5_core_r2_retrospective import evaluate_gates


class V5CoreR2RetrospectiveGateTests(unittest.TestCase):
    @staticmethod
    def summary(*, full_function_mrr=0.9):
        source_by_type = {
            "absolute_reference": {"mrr": 1.0},
            "copy_offset": {"mrr": 1.0},
            "function_replacement": {"mrr": 0.8},
            "operator_replacement": {"mrr": 1.0},
            "range_boundary": {"mrr": 0.7},
            "reference_replacement": {"mrr": 0.95},
        }
        full_by_type = {
            **source_by_type,
            "function_replacement": {"mrr": full_function_mrr},
            "range_boundary": {"mrr": 0.9},
            "reference_replacement": {"mrr": 1.0},
        }
        diagnostics = [
            {
                "error_type": error_type,
                "source_rank": 2 if values["mrr"] < 1.0 else 1,
                "full_rank": 1,
            }
            for error_type, values in source_by_type.items()
        ]
        return {
            "metrics": {
                "r2_source": {
                    "macro_top5": 0.99,
                    "weakest_top5": 0.95,
                    "mrr": 0.91,
                    "by_error_type": source_by_type,
                },
                "r2_full": {
                    "mrr": 0.96,
                    "by_error_type": full_by_type,
                },
                "ablate_no_rcr": {"mrr": 0.90},
            },
            "diagnostics": diagnostics,
            "counterfactual_harmed_rate": 0.0,
            "dropout_100_source_rank_identical": True,
        }

    @staticmethod
    def workbook_null():
        return {
            "selected": "wcn_rcr",
            "variants": {
                "wcn_rcr": {
                    "clean_false_alarm_rate": 0.05,
                    "error_alarm_recall": 0.9,
                }
            },
        }

    def test_net_improvement_gate_scales_to_actual_headroom(self):
        gates = evaluate_gates(self.summary(), self.workbook_null())
        self.assertTrue(gates["hard_gate_passed"])
        self.assertEqual(
            gates["values"]["headroom_error_types"],
            ["function_replacement", "range_boundary", "reference_replacement"],
        )
        self.assertEqual(gates["values"]["required_net_improved_error_types"], 3)

    def test_event_level_gain_does_not_replace_net_type_gain(self):
        gates = evaluate_gates(
            self.summary(full_function_mrr=0.7), self.workbook_null()
        )
        self.assertFalse(
            gates["gates"]["net_improvement_covers_available_headroom_types"]
        )
        self.assertIn(
            "function_replacement",
            gates["values"]["headroom_error_types"],
        )
        self.assertNotIn(
            "function_replacement",
            gates["values"]["net_improved_error_types"],
        )


if __name__ == "__main__":
    unittest.main()
