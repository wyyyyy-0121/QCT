import inspect
import unittest

import formulaguard.v5_psl as psl
from formulaguard.api import diagnose, localize
from formulaguard.v5_psl import (
    ABLATIONS,
    DiagnosticState,
    PSLConfig,
    build_perturbation_scenarios,
    diagnose_v5_psl,
    v5_psl_default_parameters,
)
from formulaguard.workbook import WorkbookModel


def repeated_model(*, corrupt: bool = False, source: str = "first.xlsx") -> WorkbookModel:
    cells = {}
    formulas = {}
    for row in range(1, 13):
        cells[("Model", f"A{row}")] = row + 1
        cells[("Model", f"B{row}")] = row + 2
        formula = f"=A{row}+B{row}"
        if corrupt and row == 6:
            formula = "=A6-B6"
        formulas[("Model", f"C{row}")] = formula
        formulas[("Model", f"D{row}")] = f"=C{row}*2"
    return WorkbookModel(cells, formulas, source=source)


class V5PSLTests(unittest.TestCase):
    def test_downstream_probe_counts_only_directed_recovery(self):
        target = ("Model", "D1")
        peers = (("Model", "D2"), ("Model", "D3"))
        before = {
            target: (2.0, 2.0, 2.0),
            peers[0]: (1.0, 1.0, 1.0),
            peers[1]: (1.0, 1.0, 1.0),
        }
        references = {target: peers}

        toward = {**before, target: (1.5, 1.5, 1.5)}
        effect, stability, cells = psl._directed_response_recovery(
            before, toward, (target,), references,
        )
        self.assertAlmostEqual(effect, 0.5)
        self.assertEqual(stability, 1.0)
        self.assertEqual(cells, (target,))

        for changed in ((0.0, 0.0, 0.0), (3.0, 3.0, 3.0)):
            with self.subTest(changed=changed):
                effect, stability, cells = psl._directed_response_recovery(
                    before, {**before, target: changed}, (target,), references,
                )
                self.assertEqual(effect, 0.0)
                self.assertEqual(stability, 0.0)
                self.assertEqual(cells, (target,))

    def test_public_interface_has_no_truth_inputs(self):
        parameters = inspect.signature(diagnose_v5_psl).parameters
        forbidden = {"source", "label", "correct_formula", "failed_sinks", "expected_output"}
        self.assertFalse(forbidden & set(parameters))

    def test_scenarios_are_paired_deterministic_and_path_independent(self):
        left = repeated_model(source="left.xlsx")
        right = repeated_model(source="renamed.xlsx")
        left_rows, left_roles = build_perturbation_scenarios(left)
        right_rows, right_roles = build_perturbation_scenarios(right)
        self.assertEqual(len(left_rows), 12)
        self.assertEqual(left_roles, right_roles)
        self.assertEqual(left_rows, right_rows)
        for first, second in zip(left_rows[::2], left_rows[1::2]):
            for key in first.value_overrides:
                original = float(left.cells[key])
                self.assertAlmostEqual(
                    float(first.value_overrides[key]) + float(second.value_overrides[key]),
                    2 * original,
                    delta=2.0,
                )

    def test_complete_ranking_and_dispatch(self):
        model = repeated_model(corrupt=True)
        report = diagnose(model, "v5_psl")
        ranking = localize(model, "v5_psl")
        self.assertEqual(len(report.ranking), len(model.formulas))
        self.assertEqual([row.cell for row in report.ranking], [row.cell for row in ranking])
        self.assertEqual(len({row.cell for row in report.ranking}), len(model.formulas))
        self.assertTrue(all(
            report.ranking[index].score >= report.ranking[index + 1].score
            for index in range(len(report.ranking) - 1)
        ))

    def test_response_error_is_localized_without_v4_ranking(self):
        report = diagnose_v5_psl(repeated_model(corrupt=True))
        self.assertEqual(report.state, DiagnosticState.LOCALIZED)
        self.assertEqual(report.ranking[0].cell, ("Model", "C6"))
        self.assertGreaterEqual(
            report.ranking[0].evidence["strong_evidence_families"], 2,
        )
        self.assertEqual(report.review_cells, (("Model", "C6"),))
        cell_sets = [set(family.cells) for family in report.evidence_families]
        for index, cells in enumerate(cell_sets):
            for other in cell_sets[index + 1:]:
                self.assertFalse(cells & other)

    def test_uniform_workbook_does_not_force_a_localization(self):
        report = diagnose_v5_psl(repeated_model())
        self.assertIn(report.state, {
            DiagnosticState.ABSTAIN_UNIDENTIFIABLE,
            DiagnosticState.REVIEW,
        })
        self.assertNotEqual(report.state, DiagnosticState.LOCALIZED)

    def test_unsupported_formulas_stay_in_ranking_and_state(self):
        cells = {("Model", "A1"): 1, ("Model", "B1"): 2}
        formulas = {
            ("Model", f"C{row}"): "=VLOOKUP(A1,A1:B1,2)"
            for row in range(1, 7)
        }
        model = WorkbookModel.from_cells(cells, formulas)
        report = diagnose_v5_psl(model)
        self.assertEqual(report.state, DiagnosticState.UNSUPPORTED)
        self.assertEqual(len(report.ranking), len(formulas))
        self.assertEqual(set(report.support.unsupported_formula_cells), set(formulas))

    def test_hidden_text_is_not_part_of_scenarios_or_provenance(self):
        base = repeated_model()
        cells = dict(base.cells)
        cells[("Model", "Z1")] = "secret-label-one"
        left = WorkbookModel(
            cells, base.formulas,
            cell_visibility={("Model", "Z1"): False},
        )
        cells[("Model", "Z1")] = "secret-label-two"
        right = WorkbookModel(
            cells, base.formulas,
            cell_visibility={("Model", "Z1"): False},
        )
        self.assertEqual(
            diagnose_v5_psl(left).provenance["structure_sha256"],
            diagnose_v5_psl(right).provenance["structure_sha256"],
        )

    def test_invalid_scenario_contract_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly 12"):
            PSLConfig.from_mapping({"scenario_count": 10})

    def test_frozen_default_parameters_round_trip_through_config(self):
        self.assertEqual(
            PSLConfig.from_mapping(v5_psl_default_parameters()),
            PSLConfig(),
        )
        changed = v5_psl_default_parameters()
        changed["model_version"] = "v5-r1"
        with self.assertRaisesRegex(ValueError, "metadata changed"):
            PSLConfig.from_mapping(changed)

    def test_four_preregistered_ablations_keep_complete_rankings(self):
        model = repeated_model(corrupt=True)
        for ablation in ABLATIONS:
            with self.subTest(ablation=ablation):
                report = diagnose_v5_psl(model, ablation=ablation)
                self.assertEqual(len(report.ranking), len(model.formulas))
                self.assertEqual(len({row.cell for row in report.ranking}), len(model.formulas))
                self.assertEqual(report.provenance["ablation"], ablation)

    def test_no_identifiability_gate_forces_bounded_review(self):
        model = repeated_model()
        report = diagnose(model, "v5_psl", ablation="no_identifiability_gate")
        self.assertEqual(report.state, DiagnosticState.REVIEW)
        self.assertEqual(len(report.review_cells), 5)

    def test_unknown_ablation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            diagnose_v5_psl(repeated_model(), ablation="label_aware_oracle")


if __name__ == "__main__":
    unittest.main()
