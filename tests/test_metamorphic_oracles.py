from __future__ import annotations

import json
import unittest

from formulaguard.metamorphic_oracles import (
    MetamorphicOracleConfig,
    audit_metamorphic_oracles,
    validate_metamorphic_output,
)
from formulaguard.workbook import WorkbookModel


def relation(record: dict[str, object], name: str) -> dict[str, object]:
    return next(
        item
        for item in record["relations"]  # type: ignore[union-attr]
        if item["relation"] == name
    )


def record(payload: dict[str, object], cell: str) -> dict[str, object]:
    return next(
        item
        for item in payload["records"]  # type: ignore[union-attr]
        if item["cell"] == cell
    )


class MetamorphicOracleTests(unittest.TestCase):
    def test_affine_sum_supports_characterization_and_conservation_with_witnesses(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 2,
                ("Sheet", "A2"): 3,
                ("Sheet", "A3"): 5,
            },
            {("Sheet", "D1"): "=SUM(A1:A3)+10"},
        )

        payload = audit_metamorphic_oracles(model)
        row = payload["records"][0]

        self.assertEqual(row["status"], "supported")
        self.assertEqual(row["support_count"], 2)
        self.assertEqual(row["violation_count"], 0)
        self.assertEqual(payload["summary"]["supports"], 2)
        for check in row["relations"][:2]:
            self.assertTrue(check["applicability"])
            self.assertTrue(check["support"])
            self.assertFalse(check["violation"])
            self.assertIsNone(check["rejection_reason"])
            self.assertIsInstance(check["witness"], dict)
        redundant = relation(row, "redundant_path_invariance")
        self.assertFalse(redundant["applicability"])
        self.assertEqual(redundant["rejection_reason"], "not_explicit_path_residual")

        scaling = relation(row, "affine_scaling")
        self.assertEqual(scaling["role"], "characterization")
        self.assertFalse(scaling["witness"]["can_identify_formula_error"])
        self.assertEqual(scaling["witness"]["baseline_output"], 20.0)
        self.assertEqual(scaling["witness"]["expected_output"], 30.0)
        self.assertEqual(scaling["witness"]["observed_output"], 30.0)
        self.assertEqual(validate_metamorphic_output(payload), [])
        json.dumps(payload, sort_keys=True)

    def test_single_formula_duplicate_count_is_a_conservation_violation(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 2,
                ("Sheet", "A2"): 3,
                ("Sheet", "A3"): 5,
            },
            {("Sheet", "D1"): "=SUM(A1:A3)+A2"},
        )

        payload = audit_metamorphic_oracles(model)
        row = payload["records"][0]
        conservation = relation(row, "aggregate_conservation")

        self.assertEqual(row["status"], "violation")
        self.assertEqual(payload["violation_cells"], ["Sheet!D1"])
        self.assertTrue(conservation["applicability"])
        self.assertTrue(conservation["violation"])
        self.assertFalse(conservation["support"])
        probes = conservation["witness"]["anchors"][0]["probes"]
        failing = [probe for probe in probes if not probe["passed"]]
        self.assertEqual(len(failing), 1)
        self.assertEqual(failing[0]["negative_cell"], "Sheet!A2")
        self.assertNotEqual(
            failing[0]["observed_output"], failing[0]["expected_output"]
        )
        self.assertEqual(validate_metamorphic_output(payload), [])

    def test_duplicate_inside_sum_is_visible_in_occurrence_witness(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 1,
                ("Sheet", "A2"): 2,
                ("Sheet", "A3"): 3,
            },
            {("Sheet", "D1"): "=SUM(A1:A3,A2)"},
        )

        payload = audit_metamorphic_oracles(model)
        check = relation(payload["records"][0], "aggregate_conservation")

        self.assertTrue(check["violation"])
        anchor = check["witness"]["anchors"][0]
        self.assertEqual(anchor["input_occurrences"]["Sheet!A2"], 2)

    def test_sum_domain_sign_error_is_a_conservation_violation(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 2,
                ("Sheet", "A2"): 3,
                ("Sheet", "A3"): 5,
            },
            {("Sheet", "D1"): "=SUM(A1:A3)-2*A2"},
        )

        payload = audit_metamorphic_oracles(model)
        check = relation(payload["records"][0], "aggregate_conservation")

        self.assertTrue(check["violation"])
        failing_cells = {
            probe["negative_cell"]
            for probe in check["witness"]["anchors"][0]["probes"]
            if not probe["passed"]
        }
        self.assertEqual(failing_cells, {"Sheet!A2"})

    def test_legal_nonlinear_and_if_formulas_abstain_without_violation(self):
        model = WorkbookModel.from_cells(
            {("Sheet", "A1"): 2, ("Sheet", "B1"): 3},
            {
                ("Sheet", "C1"): "=A1*B1",
                ("Sheet", "C2"): "=IF(A1>B1,A1,B1)",
                ("Sheet", "C3"): "=MIN(A1:B1)",
                ("Sheet", "C4"): "=SUM(A1:B1)*A1",
                ("Sheet", "C5"): "=IF(A1>B1,SUM(A1:B1),0)",
            },
        )

        payload = audit_metamorphic_oracles(model)
        expected_reasons = {
            "Sheet!C1": "data_dependent_multiplication",
            "Sheet!C2": "conditional_formula",
            "Sheet!C3": "nonlinear_function",
            "Sheet!C4": "data_dependent_multiplication",
            "Sheet!C5": "conditional_formula",
        }
        for cell, reason in expected_reasons.items():
            row = record(payload, cell)
            self.assertEqual(row["status"], "abstained")
            self.assertEqual(row["violation_count"], 0)
            for check in row["relations"]:
                self.assertFalse(check["applicability"])
                self.assertEqual(check["outcome"], "abstain")
                self.assertFalse(check["support"])
                self.assertFalse(check["violation"])
                self.assertEqual(check["rejection_reason"], reason)
                self.assertIsNone(check["witness"])
        self.assertEqual(payload["violation_cells"], [])
        self.assertEqual(validate_metamorphic_output(payload), [])

    def test_mixed_sign_affine_formula_is_only_characterized(self):
        model = WorkbookModel.from_cells(
            {("Sheet", "A1"): 7, ("Sheet", "B1"): 2},
            {("Sheet", "C1"): "=A1-B1"},
        )

        payload = audit_metamorphic_oracles(model)
        row = payload["records"][0]

        self.assertTrue(relation(row, "affine_scaling")["support"])
        self.assertEqual(
            relation(row, "aggregate_conservation")["rejection_reason"],
            "no_explicit_aggregate",
        )
        self.assertEqual(
            relation(row, "redundant_path_invariance")["rejection_reason"],
            "residual_operands_are_not_distinct_formula_paths",
        )
        self.assertEqual(row["violation_count"], 0)

    def test_silent_boundary_omission_breaks_independent_zero_residual(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 2,
                ("Sheet", "A2"): 3,
                ("Sheet", "A3"): 0,
            },
            {
                ("Sheet", "D1"): "=SUM(A1:A2)",
                ("Sheet", "E1"): "=SUM(A1:A3)",
                ("Sheet", "F1"): "=D1-E1",
            },
        )

        payload = audit_metamorphic_oracles(model)
        row = record(payload, "Sheet!F1")
        check = relation(row, "redundant_path_invariance")

        self.assertEqual(check["role"], "detector")
        self.assertTrue(check["violation"])
        self.assertEqual(check["witness"]["baseline_residual"], 0.0)
        self.assertEqual(check["witness"]["mismatched_sensitivity_cells"], ["Sheet!A3"])
        omitted_probe = next(
            probe
            for probe in check["witness"]["probes"]
            if probe["input_cell"] == "Sheet!A3"
        )
        self.assertFalse(omitted_probe["passed"])
        self.assertEqual(omitted_probe["observed_residual"], -1.0)

    def test_complete_independent_paths_preserve_zero_residual(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 2,
                ("Sheet", "A2"): 3,
                ("Sheet", "A3"): 5,
            },
            {
                ("Sheet", "D1"): "=SUM(A1:A3)",
                ("Sheet", "E1"): "=SUM(A1:A3)",
                ("Sheet", "F1"): "=D1-E1",
            },
        )

        payload = audit_metamorphic_oracles(model)
        check = relation(record(payload, "Sheet!F1"), "redundant_path_invariance")

        self.assertTrue(check["support"])
        self.assertEqual(check["witness"]["mismatched_sensitivity_cells"], [])
        self.assertTrue(all(probe["passed"] for probe in check["witness"]["probes"]))

    def test_legal_unequal_paths_abstain(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 1,
                ("Sheet", "A2"): 2,
                ("Sheet", "B1"): 1,
                ("Sheet", "B2"): 2,
            },
            {
                ("Sheet", "D1"): "=SUM(A1:A2)",
                ("Sheet", "E1"): "=SUM(B1:B2)",
                ("Sheet", "F1"): "=D1-E1",
            },
        )

        payload = audit_metamorphic_oracles(model)
        row = record(payload, "Sheet!F1")
        check = relation(row, "redundant_path_invariance")

        self.assertFalse(check["applicability"])
        self.assertEqual(check["outcome"], "abstain")
        self.assertEqual(
            check["rejection_reason"], "insufficient_shared_path_sensitivity"
        )
        self.assertEqual(row["violation_count"], 0)

    def test_affine_analysis_expands_formula_dependencies_to_raw_inputs(self):
        model = WorkbookModel.from_cells(
            {("Sheet", "A1"): 2, ("Sheet", "B1"): 3},
            {
                ("Sheet", "C1"): "=A1+B1",
                ("Sheet", "D1"): "=C1*2+5",
            },
        )

        payload = audit_metamorphic_oracles(model)
        scaling = relation(record(payload, "Sheet!D1"), "affine_scaling")

        self.assertTrue(scaling["support"])
        self.assertEqual(scaling["witness"]["affine_intercept"], 5.0)
        self.assertEqual(
            sorted(scaling["witness"]["input_values_before"]),
            ["Sheet!A1", "Sheet!B1"],
        )
        self.assertNotIn("Sheet!C1", scaling["witness"]["input_values_before"])

    def test_average_conservation_is_supported(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 4,
                ("Sheet", "A2"): 8,
                ("Sheet", "A3"): 12,
            },
            {("Sheet", "B1"): "=AVERAGE(A1:A3)*2"},
        )

        payload = audit_metamorphic_oracles(model)
        check = relation(payload["records"][0], "aggregate_conservation")

        self.assertTrue(check["support"])
        self.assertEqual(check["witness"]["anchors"][0]["function"], "AVERAGE")

    def test_output_and_witness_order_are_deterministic(self):
        model = WorkbookModel.from_cells(
            {
                ("Beta", "B1"): 4,
                ("Alpha", "A1"): 1,
                ("Alpha", "A2"): 2,
            },
            {
                ("Beta", "C1"): "=B1*2",
                ("Alpha", "B1"): "=SUM(A1:A2)",
            },
        )

        first = audit_metamorphic_oracles(model)
        second = audit_metamorphic_oracles(model)

        self.assertEqual(first, second)
        self.assertEqual(
            [row["cell"] for row in first["records"]], ["Alpha!B1", "Beta!C1"]
        )
        self.assertEqual(validate_metamorphic_output(first), [])

    def test_invalid_config_is_rejected(self):
        with self.assertRaises(ValueError):
            MetamorphicOracleConfig(scale_factor=1.0)
        with self.assertRaises(ValueError):
            MetamorphicOracleConfig(max_aggregate_cells=1)


if __name__ == "__main__":
    unittest.main()
