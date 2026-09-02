import json
import unittest

from formulaguard.counterfactual_response import (
    CounterfactualResponseConfig,
    build_counterfactual_response_signature,
    build_response_signature,
)
from formulaguard.workbook import WorkbookModel

Cell = tuple[str, str]


def _probe(signature, cell: Cell):
    return next(probe for probe in signature.probes if probe.input_cell == cell)


class CounterfactualResponseTests(unittest.TestCase):
    def test_plus_and_minus_operators_have_opposite_input_directions(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 4, ("Model", "B1"): 2},
            {
                ("Model", "C1"): "=A1+B1",
                ("Model", "C2"): "=A1-B1",
                ("Model", "D1"): "=C1*3",
                ("Model", "D2"): "=C2*3",
            },
        )
        original_cells = dict(model.cells)
        original_formulas = dict(model.formulas)

        addition = build_counterfactual_response_signature(model, ("Model", "C1"))
        subtraction = build_counterfactual_response_signature(model, ("Model", "C2"))
        addition_b = _probe(addition, ("Model", "B1"))
        subtraction_b = _probe(subtraction, ("Model", "B1"))

        self.assertTrue(addition.eligible)
        self.assertTrue(subtraction.eligible)
        self.assertEqual(addition_b.target_response.positive_direction, 1)
        self.assertEqual(addition_b.target_response.negative_direction, 1)
        self.assertEqual(addition_b.target_response.direction, 1)
        self.assertEqual(subtraction_b.target_response.positive_direction, -1)
        self.assertEqual(subtraction_b.target_response.negative_direction, -1)
        self.assertEqual(subtraction_b.target_response.direction, -1)
        self.assertAlmostEqual(addition_b.target_response.symmetry_residual, 0.0)
        self.assertAlmostEqual(addition_b.target_response.nonlinearity_residual, 0.0)
        self.assertAlmostEqual(addition_b.propagation_coverage, 1.0)
        self.assertEqual(addition_b.witness.path[0], ("Model", "B1"))
        self.assertIn(("Model", "C1"), addition_b.witness.path)
        self.assertEqual(model.cells, original_cells)
        self.assertEqual(model.formulas, original_formulas)

    def test_wrong_reference_changes_selected_input_and_path_witness(self):
        cells = {
            ("Model", "A2"): 10,
            ("Model", "B1"): 1,
            ("Model", "B2"): 2,
        }
        clean = WorkbookModel.from_cells(
            cells,
            {
                ("Model", "C2"): "=A2+B2",
                ("Model", "D2"): "=C2*2",
            },
        )
        wrong = WorkbookModel.from_cells(
            cells,
            {
                ("Model", "C2"): "=A2+B1",
                ("Model", "D2"): "=C2*2",
            },
        )

        clean_signature = build_response_signature(clean, ("Model", "C2"))
        wrong_signature = build_response_signature(wrong, ("Model", "C2"))

        self.assertEqual(
            set(clean_signature.selected_inputs),
            {("Model", "A2"), ("Model", "B2")},
        )
        self.assertEqual(
            set(wrong_signature.selected_inputs),
            {("Model", "A2"), ("Model", "B1")},
        )
        wrong_probe = _probe(wrong_signature, ("Model", "B1"))
        self.assertEqual(
            wrong_probe.path_to_target,
            (("Model", "B1"), ("Model", "C2")),
        )
        self.assertEqual(wrong_probe.target_response.path, wrong_probe.path_to_target)
        self.assertEqual(
            wrong_signature.as_dict(),
            build_response_signature(wrong, ("Model", "C2")).as_dict(),
        )
        json.dumps(wrong_signature.as_dict(), sort_keys=True)

    def test_range_omission_removes_input_but_keeps_auditable_propagation(self):
        cells = {
            ("Model", "A1"): 1,
            ("Model", "A2"): 2,
            ("Model", "A3"): 3,
        }
        clean = WorkbookModel.from_cells(
            cells,
            {
                ("Model", "C1"): "=SUM(A1:A3)",
                ("Model", "D1"): "=C1*2",
                ("Model", "E1"): "=D1+1",
            },
        )
        omitted = WorkbookModel.from_cells(
            cells,
            {
                ("Model", "C1"): "=SUM(A1:A2)",
                ("Model", "D1"): "=C1*2",
                ("Model", "E1"): "=D1+1",
            },
        )

        clean_signature = build_response_signature(clean, ("Model", "C1"))
        omitted_signature = build_response_signature(omitted, ("Model", "C1"))

        self.assertIn(("Model", "A3"), clean_signature.selected_inputs)
        self.assertNotIn(("Model", "A3"), omitted_signature.selected_inputs)
        self.assertEqual(
            clean_signature.downstream_cells,
            (("Model", "D1"), ("Model", "E1")),
        )
        a3_probe = _probe(clean_signature, ("Model", "A3"))
        self.assertTrue(a3_probe.target_response.active)
        self.assertEqual(a3_probe.responsive_downstream_count, 2)
        self.assertAlmostEqual(a3_probe.propagation_coverage, 1.0)
        self.assertAlmostEqual(clean_signature.propagation_coverage, 1.0)
        self.assertAlmostEqual(omitted_signature.propagation_coverage, 1.0)

    def test_additive_constant_error_changes_normalized_response_magnitude(self):
        cells = {("Model", "A1"): 3, ("Model", "B1"): 2}
        clean = WorkbookModel.from_cells(
            cells,
            {
                ("Model", "C1"): "=A1+B1+10",
            },
        )
        wrong_constant = WorkbookModel.from_cells(
            cells,
            {
                ("Model", "C1"): "=A1+B1+100",
            },
        )

        clean_response = _probe(
            build_response_signature(clean, ("Model", "C1")),
            ("Model", "A1"),
        ).target_response
        wrong_response = _probe(
            build_response_signature(wrong_constant, ("Model", "C1")),
            ("Model", "A1"),
        ).target_response

        self.assertEqual(clean_response.direction, wrong_response.direction)
        self.assertAlmostEqual(clean_response.symmetry_residual, 0.0)
        self.assertAlmostEqual(wrong_response.symmetry_residual, 0.0)
        self.assertGreater(
            clean_response.normalized_magnitude,
            wrong_response.normalized_magnitude * 5,
        )

    def test_inactive_if_inputs_are_valid_local_exception_witnesses(self):
        model = WorkbookModel.from_cells(
            {
                ("Model", "A1"): 1,
                ("Model", "B1"): 10,
                ("Model", "C1"): 20,
            },
            {
                ("Model", "D1"): "=IF(A1>0,B1,C1)",
                ("Model", "E1"): "=D1*2",
            },
        )

        signature = build_response_signature(model, ("Model", "D1"))
        active = _probe(signature, ("Model", "B1"))
        inactive_condition = _probe(signature, ("Model", "A1"))
        inactive_branch = _probe(signature, ("Model", "C1"))

        self.assertTrue(signature.eligible)
        self.assertEqual(active.status, "ok")
        self.assertTrue(active.target_response.active)
        self.assertAlmostEqual(active.propagation_coverage, 1.0)
        for probe in (inactive_condition, inactive_branch):
            self.assertEqual(probe.status, "ok")
            self.assertIsNone(probe.rejection_reason)
            self.assertFalse(probe.target_response.active)
            self.assertEqual(probe.witness.kind, "locally_inactive")
            self.assertAlmostEqual(probe.propagation_coverage, 0.0)
            self.assertFalse(probe.issues)

    def test_symmetric_and_nonlinear_residuals_are_separate(self):
        square = WorkbookModel.from_cells(
            {("Model", "A1"): 0},
            {("Model", "B1"): "=A1^2"},
        )
        cube = WorkbookModel.from_cells(
            {("Model", "A1"): 0},
            {("Model", "B1"): "=A1^3"},
        )

        square_response = _probe(
            build_response_signature(square, ("Model", "B1")),
            ("Model", "A1"),
        ).target_response
        cube_response = _probe(
            build_response_signature(cube, ("Model", "B1")),
            ("Model", "A1"),
        ).target_response

        self.assertEqual(square_response.direction, 0)
        self.assertAlmostEqual(square_response.symmetry_residual, 1.0)
        self.assertAlmostEqual(square_response.nonlinearity_residual, 0.0)
        self.assertEqual(cube_response.direction, 1)
        self.assertAlmostEqual(cube_response.symmetry_residual, 0.0)
        self.assertGreater(cube_response.nonlinearity_residual, 0.5)

    def test_errors_and_abstention_reasons_are_explicit(self):
        constant = WorkbookModel.from_cells({}, {("Model", "A1"): "=7"})
        constant_signature = build_response_signature(constant, ("Model", "A1"))
        self.assertFalse(constant_signature.eligible)
        self.assertEqual(
            constant_signature.rejection_reason,
            "no_numeric_upstream_inputs",
        )

        nonformula = build_response_signature(constant, ("Model", "B1"))
        self.assertFalse(nonformula.eligible)
        self.assertEqual(nonformula.rejection_reason, "target_not_formula")

        singular = WorkbookModel.from_cells(
            {("Model", "A1"): 0.05},
            {("Model", "B1"): "=1/A1"},
        )
        singular_signature = build_response_signature(singular, ("Model", "B1"))
        singular_probe = _probe(singular_signature, ("Model", "A1"))
        self.assertFalse(singular_signature.eligible)
        self.assertEqual(
            singular_signature.rejection_reason,
            "all_input_probes_rejected",
        )
        self.assertEqual(singular_probe.status, "rejected")
        self.assertEqual(singular_probe.witness.kind, "probe_rejected")
        self.assertTrue(
            any(
                issue.stage == "negative"
                and issue.reason == "evaluation_error"
                and "division by zero" in issue.detail
                for issue in singular_signature.errors
            )
        )

    def test_invalid_configuration_is_rejected_before_evaluation(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 1},
            {("Model", "B1"): "=A1+1"},
        )
        with self.assertRaisesRegex(ValueError, "relative_step"):
            build_response_signature(
                model,
                ("Model", "B1"),
                config=CounterfactualResponseConfig(relative_step=1.0),
            )

    def test_input_and_downstream_budgets_have_auditable_rejections(self):
        model = WorkbookModel.from_cells(
            {
                ("Model", "A1"): 1,
                ("Model", "A2"): 2,
                ("Model", "A3"): 3,
            },
            {
                ("Model", "B1"): "=SUM(A1:A3)",
                ("Model", "C1"): "=B1+1",
                ("Model", "D1"): "=C1+1",
            },
        )

        signature = build_response_signature(
            model,
            ("Model", "B1"),
            config=CounterfactualResponseConfig(max_inputs=1, max_downstream=1),
        )

        self.assertEqual(signature.selected_inputs, (("Model", "A1"),))
        self.assertEqual(signature.downstream_cells, (("Model", "C1"),))
        reasons = [rejection.reason for rejection in signature.rejections]
        self.assertEqual(reasons.count("input_budget_exceeded"), 2)
        self.assertEqual(reasons.count("downstream_budget_exceeded"), 1)


if __name__ == "__main__":
    unittest.main()
