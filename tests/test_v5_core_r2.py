import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from formulaguard.api import localize
import formulaguard.v5_core_r2 as r2_module
from formulaguard.v5_core_r2 import (
    MODEL_VERSION,
    observational_ranking,
    observational_source_evidence,
    observational_uncertainty_set,
    regime_conditioned_residuals,
    v5_core_r2_scores,
)
from formulaguard.workbook import WorkbookModel


def propagation_family(error_formula="=MIN(B5:D5)"):
    cells = {}
    formulas = {}
    for row in range(2, 9):
        for col, value in zip("BCD", (row, row + 2, row + 4)):
            cells[("Data", f"{col}{row}")] = value
        formulas[("Data", f"E{row}")] = f"=SUM(B{row}:D{row})"
        formulas[("Data", f"F{row}")] = f"=E{row}*2"
        formulas[("Data", f"G{row}")] = f"=F{row}+1"
    formulas[("Data", "E5")] = error_formula
    formulas[("Data", "H9")] = "=SUM(G2:G8)"
    return WorkbookModel.from_cells(cells, formulas)


class V5CoreR2Tests(unittest.TestCase):
    def test_public_interface_has_no_label_or_identity_fields(self):
        parameters = set(inspect.signature(v5_core_r2_scores).parameters)
        forbidden = {
            "source_cell", "error_type", "correct_formula", "labels",
            "template_id", "instance_id", "workbook_filename",
        }
        self.assertFalse(parameters & forbidden)

    def test_source_ranking_does_not_generate_candidates(self):
        model = propagation_family()
        with mock.patch.object(
            r2_module,
            "build_candidate_portfolio",
            side_effect=AssertionError("candidate generation entered source stage"),
        ):
            results = v5_core_r2_scores(model, stage="source")
        self.assertEqual(results[0].cell, ("Data", "E5"))
        self.assertTrue(all(row.candidate_formula is None for row in results))

    def test_candidate_absence_does_not_change_observational_order(self):
        model = propagation_family()
        source = [row.cell for row in v5_core_r2_scores(model, stage="source")]
        with mock.patch.object(r2_module, "build_candidate_portfolio", return_value=[]):
            full = v5_core_r2_scores(model, stage="full")
        self.assertEqual([row.cell for row in full], source)
        self.assertEqual(full[0].evidence["diagnostic_status"], "unsupported_coverage")

    def test_full_ranking_only_reorders_uncertainty_slots(self):
        model = propagation_family()
        observations, _ = observational_source_evidence(model)
        source = observational_ranking(observations)
        uncertainty = set(observational_uncertainty_set(source, observations))
        full = [row.cell for row in v5_core_r2_scores(model, stage="full")]
        outside_source = [cell for cell in source if cell not in uncertainty]
        outside_full = [cell for cell in full if cell not in uncertainty]
        self.assertEqual(outside_full, outside_source)
        self.assertEqual(
            [index for index, cell in enumerate(full) if cell in uncertainty],
            [index for index, cell in enumerate(source) if cell in uncertainty],
        )

    def test_empirical_tails_are_traceable(self):
        evidence, _ = observational_source_evidence(propagation_family(), matched_controls=6)
        self.assertTrue(evidence)
        for row in evidence.values():
            self.assertGreater(row.empirical_tail, 0.0)
            self.assertLessEqual(row.empirical_tail, 1.0)
            self.assertLessEqual(len(row.matched_controls), 6)
            expected = (
                1 + sum(evidence[cell].raw_score >= row.raw_score for cell in row.matched_controls)
            ) / (1 + len(row.matched_controls))
            self.assertAlmostEqual(row.empirical_tail, expected)

    def test_formula_error_is_source_ranked_and_repair_is_explanatory(self):
        results = v5_core_r2_scores(propagation_family(), stage="full")
        self.assertEqual(results[0].cell, ("Data", "E5"))
        self.assertEqual(results[0].candidate_formula, "=SUM(B5:D5)")
        self.assertEqual(results[0].evidence["model_version"], MODEL_VERSION)
        self.assertTrue(results[0].evidence["candidate_independent_source_ranking"])
        self.assertIn(
            results[0].evidence["diagnostic_status"],
            {"localized", "review", "abstain_ambiguous", "unsupported_coverage"},
        )

    def test_api_exposes_three_pre_registered_stages(self):
        model = propagation_family()
        source = localize(model, "v5_core_r2_source")
        placebo = localize(model, "v5_core_r2_placebo")
        full = localize(model, "formulaguard_v5_core_r2")
        self.assertEqual(source[0].evidence["stage"], "source")
        self.assertEqual(placebo[0].evidence["stage"], "placebo")
        self.assertEqual(full[0].evidence["stage"], "full")

    def test_complete_ranking_has_unique_cells_and_monotone_rank_scores(self):
        model = propagation_family()
        results = v5_core_r2_scores(model)
        self.assertEqual(len(results), len(model.formula_cells))
        self.assertEqual({row.cell for row in results}, set(model.formula_cells))
        self.assertEqual(len({row.cell for row in results}), len(results))
        self.assertTrue(all(
            results[index].score > results[index + 1].score
            for index in range(len(results) - 1)
        ))

    def test_regime_residual_understands_periodic_slots(self):
        cells = {}
        formulas = {}
        for row in range(2, 13):
            for col, value in zip("BCD", (row, row + 2, row + 4)):
                cells[("S", f"{col}{row}")] = value
            function = "SUM" if row % 2 == 0 else "AVERAGE"
            formulas[("S", f"E{row}")] = f"={function}(B{row}:D{row})"
        formulas[("S", "E7")] = "=MIN(B7:D7)"
        residuals = regime_conditioned_residuals(WorkbookModel.from_cells(cells, formulas))
        self.assertGreaterEqual(residuals[("S", "E7")], 0.75)
        self.assertEqual(residuals[("S", "E9")], 0.0)

    def test_distant_repeated_aggregate_role_protects_a_legal_exception(self):
        cells = {}
        formulas = {}
        for row in range(2, 13):
            for col, value in zip("BCD", (row, row + 1, row + 2)):
                cells[("S", f"{col}{row}")] = value
            formulas[("S", f"E{row}")] = f"=SUM(B{row}:D{row})"
        formulas[("S", "E4")] = "=MAX(B4:D4)"
        single = regime_conditioned_residuals(WorkbookModel.from_cells(cells, formulas))
        formulas[("S", "E10")] = "=MAX(B10:D10)"
        repeated = regime_conditioned_residuals(WorkbookModel.from_cells(cells, formulas))
        self.assertGreater(single[("S", "E4")], repeated[("S", "E4")])
        self.assertLessEqual(repeated[("S", "E4")], 0.25)

    def test_directional_footprint_requires_local_and_downstream_evidence(self):
        both = SimpleNamespace(
            counterfactual_delta=0.10,
            graph_recovery_evidence=0.10,
            local_harm=0.0,
            global_harm=0.0,
        )
        no_local = SimpleNamespace(**{**both.__dict__, "counterfactual_delta": 0.0})
        no_downstream = SimpleNamespace(**{**both.__dict__, "graph_recovery_evidence": 0.0})
        self.assertAlmostEqual(r2_module._treatment(both), 1.0)
        self.assertEqual(r2_module._treatment(no_local), 0.0)
        self.assertEqual(r2_module._treatment(no_downstream), 0.0)

    def test_cross_workbook_null_can_force_abstention(self):
        results = v5_core_r2_scores(
            propagation_family(),
            config={"clean_null_scores": [1.0] * 20, "clean_null_tail": 0.10},
        )
        self.assertTrue(results[0].evidence["clean_null_calibrated"])
        self.assertEqual(results[0].evidence["diagnostic_status"], "abstain_ambiguous")

    def test_all_registered_ablations_keep_a_complete_ranking(self):
        model = propagation_family()
        for ablation in (
            "no_rcr", "no_boundary", "no_role_replication", "no_ancestor",
            "additive_dcf", "no_placebo", "unrestricted_rerank",
        ):
            with self.subTest(ablation=ablation):
                results = v5_core_r2_scores(model, ablation=ablation)
                self.assertEqual(len(results), len(model.formula_cells))
                self.assertEqual({row.cell for row in results}, set(model.formula_cells))
                self.assertEqual(results[0].evidence["ablation"], ablation)

    def test_removing_all_candidates_preserves_source_order(self):
        model = propagation_family()
        source = [row.cell for row in v5_core_r2_scores(model, stage="source")]
        removed = v5_core_r2_scores(model, stage="full", candidate_keep_fraction=0.0)
        self.assertEqual([row.cell for row in removed], source)
        self.assertTrue(all(not row.evidence["candidate_coverage"] for row in removed))

    def test_candidate_dropout_values_are_bounded(self):
        model = propagation_family()
        for fraction in (0.0, 0.5, 0.75, 1.0):
            with self.subTest(fraction=fraction):
                results = v5_core_r2_scores(model, candidate_keep_fraction=fraction)
                self.assertTrue(all(
                    row.evidence["candidate_keep_fraction"] == fraction for row in results
                ))
        with self.assertRaises(ValueError):
            v5_core_r2_scores(model, candidate_keep_fraction=1.01)


if __name__ == "__main__":
    unittest.main()
