from __future__ import annotations

import copy
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
    def test_affine_sum_characterizes_scaling_and_conservation_with_witnesses(self):
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

        self.assertEqual(row["status"], "characterized")
        self.assertEqual(row["relation_holds_count"], 2)
        self.assertEqual(row["ambiguity_count"], 0)
        self.assertEqual(row["violation_count"], 0)
        self.assertEqual(payload["summary"]["relations_holding"], 2)
        self.assertEqual(payload["summary"]["violations"], 0)
        self.assertFalse(payload["can_identify_formula_error"])
        self.assertIsNone(payload["external_assertion_source"])
        for check in row["relations"][:2]:
            self.assertTrue(check["applicability"])
            self.assertEqual(check["role"], "characterization")
            self.assertEqual(check["outcome"], "relation_holds")
            self.assertTrue(check["relation_holds"])
            self.assertFalse(check["ambiguous"])
            self.assertFalse(check["violation"])
            self.assertIsNone(check["ambiguity_reason"])
            self.assertIsNone(check["rejection_reason"])
            self.assertIsInstance(check["witness"], dict)
            self.assertFalse(check["witness"]["can_identify_formula_error"])
            self.assertIsNone(check["witness"]["external_assertion_source"])
        redundant = relation(row, "redundant_path_invariance")
        self.assertFalse(redundant["applicability"])
        self.assertEqual(redundant["rejection_reason"], "not_explicit_path_residual")

        scaling = relation(row, "affine_scaling")
        self.assertEqual(scaling["role"], "characterization")
        self.assertFalse(scaling["witness"]["can_identify_formula_error"])
        self.assertEqual(scaling["witness"]["baseline_output"], 20.0)
        self.assertEqual(scaling["witness"]["target_ast_predicted_output"], 30.0)
        self.assertEqual(scaling["witness"]["observed_output"], 30.0)
        self.assertEqual(validate_metamorphic_output(payload), [])
        json.dumps(payload, sort_keys=True)

    def test_legal_reward_formula_is_ambiguous_not_a_violation(self):
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

        self.assertEqual(row["status"], "ambiguous")
        self.assertEqual(row["violation_count"], 0)
        self.assertEqual(row["ambiguity_count"], 1)
        self.assertEqual(payload["ambiguous_cells"], ["Sheet!D1"])
        self.assertEqual(payload["violation_cells"], [])
        self.assertTrue(conservation["applicability"])
        self.assertEqual(conservation["role"], "characterization")
        self.assertEqual(conservation["outcome"], "ambiguous")
        self.assertFalse(conservation["relation_holds"])
        self.assertTrue(conservation["ambiguous"])
        self.assertFalse(conservation["violation"])
        self.assertEqual(
            conservation["ambiguity_reason"],
            "relation_break_without_external_assertion",
        )
        self.assertEqual(
            conservation["witness"]["evidence_basis"], "target_formula_ast_only"
        )
        self.assertIsNone(conservation["witness"]["external_assertion_source"])
        self.assertFalse(conservation["witness"]["can_identify_formula_error"])
        probes = conservation["witness"]["anchors"][0]["probes"]
        failing = [probe for probe in probes if not probe["relation_held"]]
        self.assertEqual(len(failing), 1)
        self.assertEqual(failing[0]["negative_cell"], "Sheet!A2")
        self.assertNotEqual(
            failing[0]["observed_output"],
            failing[0]["baseline_output_reference"],
        )
        self.assertEqual(validate_metamorphic_output(payload), [])

    def test_repeated_reference_uses_occurrence_weighted_transfer(self):
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

        self.assertEqual(check["outcome"], "relation_holds")
        self.assertTrue(check["relation_holds"])
        self.assertFalse(check["ambiguous"])
        self.assertFalse(check["violation"])
        anchor = check["witness"]["anchors"][0]
        self.assertEqual(anchor["input_occurrences"]["Sheet!A2"], 2)
        repeated_probe = next(
            probe
            for probe in anchor["probes"]
            if probe["negative_cell"] == "Sheet!A2"
        )
        self.assertEqual(repeated_probe["aggregate_numerator_transfer"], 1.0)
        self.assertEqual(repeated_probe["positive_delta"], 1.0)
        self.assertEqual(repeated_probe["negative_delta"], -0.5)
        self.assertTrue(repeated_probe["relation_held"])
        self.assertEqual(repeated_probe["observed_output"], 8.0)
        self.assertEqual(validate_metamorphic_output(payload), [])

    def test_sum_domain_sign_change_is_ambiguous_without_external_schema(self):
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

        self.assertEqual(check["outcome"], "ambiguous")
        self.assertTrue(check["ambiguous"])
        self.assertFalse(check["violation"])
        failing_cells = {
            probe["negative_cell"]
            for probe in check["witness"]["anchors"][0]["probes"]
            if not probe["relation_held"]
        }
        self.assertEqual(failing_cells, {"Sheet!A2"})
        self.assertEqual(payload["violation_cells"], [])

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
                self.assertFalse(check["relation_holds"])
                self.assertFalse(check["ambiguous"])
                self.assertFalse(check["violation"])
                self.assertIsNone(check["ambiguity_reason"])
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

        self.assertTrue(relation(row, "affine_scaling")["relation_holds"])
        self.assertEqual(
            relation(row, "aggregate_conservation")["rejection_reason"],
            "no_explicit_aggregate",
        )
        self.assertEqual(
            relation(row, "redundant_path_invariance")["rejection_reason"],
            "residual_operands_are_not_distinct_formula_paths",
        )
        self.assertEqual(row["violation_count"], 0)

    def test_optional_boundary_difference_is_ambiguous_between_paths(self):
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

        self.assertEqual(row["status"], "ambiguous")
        self.assertEqual(row["violation_count"], 0)
        self.assertEqual(check["role"], "characterization")
        self.assertEqual(check["outcome"], "ambiguous")
        self.assertTrue(check["ambiguous"])
        self.assertFalse(check["violation"])
        self.assertEqual(check["witness"]["baseline_residual_reference"], 0.0)
        self.assertEqual(check["witness"]["localization"], "ambiguous_between_paths")
        self.assertEqual(
            check["witness"]["evidence_basis"],
            "target_formula_and_baseline_only",
        )
        self.assertIsNone(check["witness"]["external_assertion_source"])
        self.assertFalse(check["witness"]["can_identify_formula_error"])
        self.assertEqual(check["witness"]["mismatched_sensitivity_cells"], ["Sheet!A3"])
        omitted_probe = next(
            probe
            for probe in check["witness"]["probes"]
            if probe["input_cell"] == "Sheet!A3"
        )
        self.assertFalse(omitted_probe["relation_held"])
        self.assertEqual(omitted_probe["observed_residual"], -1.0)
        self.assertEqual(payload["violation_cells"], [])
        self.assertEqual(validate_metamorphic_output(payload), [])

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

        self.assertEqual(check["outcome"], "relation_holds")
        self.assertTrue(check["relation_holds"])
        self.assertFalse(check["ambiguous"])
        self.assertFalse(check["violation"])
        self.assertEqual(check["witness"]["mismatched_sensitivity_cells"], [])
        self.assertTrue(
            all(probe["relation_held"] for probe in check["witness"]["probes"])
        )

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

        self.assertTrue(scaling["relation_holds"])
        self.assertEqual(scaling["witness"]["affine_intercept"], 5.0)
        self.assertEqual(
            sorted(scaling["witness"]["input_values_before"]),
            ["Sheet!A1", "Sheet!B1"],
        )
        self.assertNotIn("Sheet!C1", scaling["witness"]["input_values_before"])

    def test_average_conservation_relation_holds(self):
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

        self.assertTrue(check["relation_holds"])
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

    def test_validator_rejects_violation_claims_and_inconsistent_ambiguity(self):
        model = WorkbookModel.from_cells(
            {
                ("Sheet", "A1"): 2,
                ("Sheet", "A2"): 3,
                ("Sheet", "A3"): 5,
            },
            {("Sheet", "D1"): "=SUM(A1:A3)+A2"},
        )
        payload = audit_metamorphic_oracles(model)

        violation_claim = copy.deepcopy(payload)
        conservation = relation(
            violation_claim["records"][0],  # type: ignore[index]
            "aggregate_conservation",
        )
        conservation["violation"] = True
        self.assertIn(
            "record 0 characterization claims a violation",
            validate_metamorphic_output(violation_claim),
        )

        inconsistent_outcome = copy.deepcopy(payload)
        conservation = relation(
            inconsistent_outcome["records"][0],  # type: ignore[index]
            "aggregate_conservation",
        )
        conservation["outcome"] = "relation_holds"
        self.assertIn(
            "record 0 relation has inconsistent outcome state",
            validate_metamorphic_output(inconsistent_outcome),
        )

        missing_reason = copy.deepcopy(payload)
        conservation = relation(
            missing_reason["records"][0],  # type: ignore[index]
            "aggregate_conservation",
        )
        conservation["ambiguity_reason"] = None
        self.assertIn(
            "record 0 ambiguity lacks a reason",
            validate_metamorphic_output(missing_reason),
        )

        nonempty_violations = copy.deepcopy(payload)
        nonempty_violations["violation_cells"] = ["Sheet!D1"]
        self.assertIn(
            "violation_cells must be empty for characterization output",
            validate_metamorphic_output(nonempty_violations),
        )

    def test_invalid_config_is_rejected(self):
        with self.assertRaises(ValueError):
            MetamorphicOracleConfig(scale_factor=1.0)
        with self.assertRaises(ValueError):
            MetamorphicOracleConfig(max_aggregate_cells=1)


if __name__ == "__main__":
    unittest.main()
