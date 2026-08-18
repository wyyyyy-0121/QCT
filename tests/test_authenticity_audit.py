import unittest

from scripts.audit_benchmark_independence import classify_coupling
from scripts.audit_external_manifest import manifest_sources
from scripts.analyze_external_results import random_event_expectation
from scripts.audit_v4_development import build_audit
from scripts.prepare_enron_manifest import expand_fault_spec
from scripts.run_external_evaluation import METHODS, parse_methods


class AuthenticityAuditTests(unittest.TestCase):
    def test_mirrored_mutation_operator_classification(self):
        self.assertTrue(classify_coupling("M3_operator", {"operator"}))
        self.assertTrue(classify_coupling("M2_range_boundary", {"range_boundary_end_row"}))
        self.assertFalse(classify_coupling("M3_operator", {"reference_shift"}))
        self.assertFalse(classify_coupling("unknown", {"operator"}))

    def test_external_evaluation_includes_frozen_v3_and_keeps_v2_reference(self):
        self.assertIn("formulaguard_v3", METHODS)
        self.assertIn("formulaguard_v4", METHODS)
        self.assertIn("formulaguard", METHODS)
        self.assertNotIn("sfl_oracle", METHODS)

    def test_external_method_subset_is_ordered_validated_and_deduplicated(self):
        self.assertEqual(
            parse_methods("graph,formulaguard_v4,graph"),
            ["graph", "formulaguard_v4"],
        )
        with self.assertRaises(ValueError):
            parse_methods("graph,not_a_method")

    def test_v4_development_audit_rejects_weak_promotion(self):
        rows = []
        for method in ("graph", "pattern", "formulaguard", "formulaguard_v3", "formulaguard_v4"):
            row = {
                "instance_id": "event-1", "method": method, "rank": "1",
                "diagnostic_status": "", "promotion_cap": "0",
                "null_control_count": "0", "candidate_delta": "0",
                "intervention_responsibility_gain": "0", "intervention_selected": "1",
                "candidate_count": "1",
            }
            rows.append(row)
        v4 = next(row for row in rows if row["method"] == "formulaguard_v4")
        v4.update({
            "diagnostic_status": "pattern_only", "promotion_cap": "10",
            "candidate_delta": "0.00001", "intervention_responsibility_gain": "9",
        })
        audit = build_audit(rows, expected_events=1)
        self.assertFalse(audit["gates"]["promotion_rules_respected"])
        self.assertFalse(audit["development_decision_ready"])

    def test_enron_overview_range_expansion_is_event_level(self):
        self.assertEqual(expand_fault_spec("F28:G28"), {"F28", "G28"})
        self.assertEqual(expand_fault_spec("G33; I34"), {"G33", "I34"})
        self.assertIsNone(expand_fault_spec("C10:E14; etc."))

    def test_external_manifest_preserves_multi_cell_event(self):
        sources = manifest_sources({
            "source_cells": "Sheet1!F28;Sheet1!G28",
            "source_cell": "",
        })
        self.assertEqual(sources, {("Sheet1", "F28"), ("Sheet1", "G28")})

    def test_exact_random_expectation_handles_multi_cell_events(self):
        single = random_event_expectation(10, 1)
        multiple = random_event_expectation(10, 2)
        self.assertAlmostEqual(single["top1"], 0.1)
        self.assertAlmostEqual(single["exam"], 0.55)
        self.assertGreater(multiple["top5"], single["top5"])
        self.assertGreater(multiple["mrr"], single["mrr"])


if __name__ == "__main__":
    unittest.main()
