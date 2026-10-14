import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

import formulaguard.v5_core_r2 as r2_module
from formulaguard.api import localize
from formulaguard.v5_core_r2 import (
    MODEL_VERSION,
    ObservationalEvidence,
    PlaceboEvidence,
    observational_probe_set,
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
    @staticmethod
    def observation(cell, *, formula=0.0, regime=0.0, behavior=0.0, graph=0.0, propagation=0.0):
        return ObservationalEvidence(
            cell=cell, raw_score=max(formula, regime, behavior, graph, propagation),
            empirical_tail=0.5, formula_residual=formula,
            regime_conditioned_residual=regime, behavior_residual=behavior,
            graph_residual=graph, propagation_potential=propagation,
            descendant_anomaly_coverage=0.0, branch_spread=0.0, ancestor_penalty=0.0,
            indegree=0, outdegree=0, descendant_count=0, complexity=("ref", 1, 1),
        )

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

    def test_protection_profile_is_configurable_and_traceable(self):
        results = v5_core_r2_scores(
            propagation_family(),
            config={"boundary_protection": False, "role_replication": False},
        )
        self.assertTrue(all(not row.evidence["boundary_protection"] for row in results))
        self.assertTrue(all(not row.evidence["role_replication"] for row in results))
        ablation = v5_core_r2_scores(propagation_family(), ablation="no_boundary_no_role")
        self.assertTrue(all(not row.evidence["boundary_protection"] for row in ablation))
        self.assertTrue(all(not row.evidence["role_replication"] for row in ablation))

    def test_adaptive_exception_release_is_candidate_independent_and_traceable(self):
        model = propagation_family()
        with mock.patch.object(
            r2_module,
            "build_candidate_portfolio",
            side_effect=AssertionError("candidate generation entered source stage"),
        ):
            results = v5_core_r2_scores(
                model,
                stage="source",
                config={"adaptive_exception_release": True, "exception_release_tail": 0.25},
            )
        self.assertTrue(all(
            row.evidence["adaptive_exception_release"]
            and 0.0 <= row.evidence["propagation_empirical_tail"] <= 1.0
            for row in results
        ))

    def test_conservative_wcn_can_use_protected_global_residual(self):
        model = propagation_family()
        results = v5_core_r2_scores(
            model,
            config={
                "adaptive_exception_release": True,
                "wcn_variant": "rcr",
                "wcn_protected_global_max": True,
            },
        )
        self.assertTrue(all(row.evidence["wcn_protected_global_max"] for row in results))
        self.assertEqual(
            results[0].evidence["workbook_null_statistic"],
            max(row.evidence["alarm_regime_conditioned_residual"] for row in results),
        )

    def test_safe_counterfactual_reorder_rejects_non_significant_treatment(self):
        model = propagation_family()
        source = [row.cell for row in v5_core_r2_scores(model, stage="source")]
        with mock.patch.object(
            r2_module,
            "matched_placebo_evidence",
            return_value={},
        ):
            results = v5_core_r2_scores(
                model,
                config={"safe_counterfactual_reorder": True, "uncertainty_rank_cap": 12},
            )
        self.assertEqual([row.cell for row in results], source)
        self.assertTrue(all(row.evidence["safe_counterfactual_reorder"] for row in results))

    def test_top1_release_requires_independent_candidate_support(self):
        cells = [("S", "A1"), ("S", "A2"), ("S", "A3")]
        observations = {
            cell: ObservationalEvidence(
                **{**self.observation(cell, formula=0.8).__dict__, "empirical_tail": 1 / 9}
            )
            for cell in cells
        }
        candidate = SimpleNamespace(sources=("boundary_consensus", "peer_up"))
        placebo = {
            cells[0]: PlaceboEvidence(cell=cells[0]),
            cells[1]: PlaceboEvidence(
                cell=cells[1], treatment=0.8, empirical_tail=1 / 9,
                best=SimpleNamespace(
                    local_harm=0.0, global_harm=0.0, candidate=candidate,
                ),
                candidate_coverage=True,
            ),
        }
        ranked = r2_module._rerank_uncertainty(
            cells, cells[:2], placebo, observations,
            safe_counterfactual_reorder=True,
            counterfactual_tail=0.125,
            minimum_treatment=0.05,
            protect_observational_top1=True,
            independent_support_tiebreak=True,
            release_tied_top1_with_dcf=True,
            minimum_independent_support=2,
        )
        self.assertEqual(ranked[0], cells[1])

        correlated = SimpleNamespace(sources=("peer_up", "peer_down"))
        placebo[cells[1]] = PlaceboEvidence(
            cell=cells[1], treatment=0.8, empirical_tail=1 / 9,
            best=SimpleNamespace(
                local_harm=0.0, global_harm=0.0, candidate=correlated,
            ),
            candidate_coverage=True,
        )
        protected = r2_module._rerank_uncertainty(
            cells, cells[:2], placebo, observations,
            safe_counterfactual_reorder=True,
            counterfactual_tail=0.125,
            minimum_treatment=0.05,
            protect_observational_top1=True,
            independent_support_tiebreak=True,
            release_tied_top1_with_dcf=True,
            minimum_independent_support=2,
        )
        self.assertEqual(protected[0], cells[0])

    def test_relative_ancestor_penalty_requires_strict_upstream_dominance(self):
        graph = SimpleNamespace(ancestors=lambda _cell: {("S", "A1")})
        signals = {("S", "A1"): 1.0, ("S", "B1"): 1.0}
        self.assertEqual(
            r2_module._ancestor_penalty(
                graph, ("S", "B1"), signals, relative=True, dominance_margin=0.10,
            ),
            0.0,
        )
        signals[("S", "B1")] = 0.45
        self.assertGreater(
            r2_module._ancestor_penalty(
                graph, ("S", "B1"), signals, relative=True, dominance_margin=0.10,
            ),
            0.0,
        )

    def test_r2_r2_context_controls_are_traceable(self):
        results = v5_core_r2_scores(
            propagation_family(),
            config={
                "relative_ancestor_penalty": True,
                "ancestor_dominance_margin": 0.10,
                "protect_observational_top1": True,
                "observational_primary_weight": 0.60,
                "observational_secondary_weight": 0.30,
                "observational_propagation_weight": 0.10,
            },
        )
        self.assertTrue(all(row.evidence["relative_ancestor_penalty"] for row in results))
        self.assertTrue(all(row.evidence["protect_observational_top1"] for row in results))
        self.assertTrue(all(
            row.evidence["ancestor_dominance_margin"] == 0.10 for row in results
        ))
        self.assertTrue(all(row.evidence["observational_primary_weight"] == 0.60 for row in results))
        with self.assertRaises(ValueError):
            v5_core_r2_scores(
                propagation_family(),
                stage="source",
                config={
                    "observational_primary_weight": 0.60,
                    "observational_secondary_weight": 0.30,
                    "observational_propagation_weight": 0.20,
                },
            )

    def test_evidence_probe_refuses_address_based_cutoff_ties(self):
        cells = [("S", f"A{index}") for index in range(1, 5)]
        evidence = {
            cells[0]: self.observation(cells[0], formula=1.0),
            cells[1]: self.observation(cells[1], formula=0.5),
            cells[2]: self.observation(cells[2], formula=0.5),
            cells[3]: self.observation(cells[3], formula=0.0),
        }
        self.assertEqual(
            observational_probe_set(cells, evidence, per_signal=2),
            [cells[0]],
        )
        self.assertEqual(
            observational_probe_set(cells, evidence, per_signal=2, small_workbook_limit=4),
            cells,
        )

    def test_uncertainty_includes_bounded_empirical_tail_equivalence_class(self):
        cells = [("S", f"A{index}") for index in range(1, 8)]
        evidence = {}
        for index, cell in enumerate(cells):
            row = self.observation(cell, formula=max(0.0, 1.0 - index / 5))
            evidence[cell] = ObservationalEvidence(
                **{
                    **row.__dict__,
                    "raw_score": 1.0 if index == 0 else 0.1,
                    "empirical_tail": 1 / 9 if index < 5 else 2 / 9,
                }
            )
        ordinary = r2_module.observational_uncertainty_set(cells, evidence, limit=12)
        tied = r2_module.observational_uncertainty_set(
            cells, evidence, limit=12, empirical_tie_rank_cap=5,
        )
        self.assertEqual(ordinary, [cells[0]])
        self.assertEqual(tied, cells[:5])

    def test_probe_promotion_is_bounded_and_preserves_source_top1(self):
        cells = [("S", f"A{index}") for index in range(1, 8)]
        observations = {
            cell: self.observation(cell, formula=1.0 - index / 10)
            for index, cell in enumerate(cells)
        }
        probe = cells[-1]
        placebo = {
            probe: PlaceboEvidence(
                cell=probe, treatment=0.8, empirical_tail=1 / 9,
                best=SimpleNamespace(local_harm=0.0, global_harm=0.0),
                candidate_coverage=True,
            ),
        }
        promoted, selected = r2_module._promote_probe_candidate(
            cells, [probe], placebo, observations,
        )
        self.assertEqual(promoted[0], cells[0])
        self.assertEqual(promoted[4], probe)
        self.assertEqual(selected, (probe,))

    def test_rank_fusion_can_preserve_the_pre_fusion_leader(self):
        cells = [("S", "A1"), ("S", "A2"), ("S", "A3")]
        evidence = {
            cells[0]: ObservationalEvidence(
                **{**self.observation(cells[0], formula=0.0).__dict__, "empirical_tail": 0.1}
            ),
            cells[1]: ObservationalEvidence(
                **{**self.observation(cells[1], formula=1.0).__dict__, "empirical_tail": 0.2}
            ),
            cells[2]: ObservationalEvidence(
                **{**self.observation(cells[2], formula=0.5).__dict__, "empirical_tail": 0.3}
            ),
        }
        unprotected = observational_ranking(
            evidence, formula_rank_fusion_weight=1.0,
            formula_rank_fusion_method="reciprocal_rank",
        )
        protected = observational_ranking(
            evidence, formula_rank_fusion_weight=1.0,
            formula_rank_fusion_method="reciprocal_rank",
            protect_pre_fusion_top1=True,
        )
        self.assertEqual(unprotected[0], cells[1])
        self.assertEqual(protected[0], cells[0])

    def test_bounded_formula_probe_only_changes_two_slots(self):
        cells = [("S", f"A{index}") for index in range(1, 7)]
        evidence = {}
        for index, cell in enumerate(cells):
            row = self.observation(
                cell,
                formula=(0.9 if index == 4 else 0.8 if index == 5 else 0.1),
                graph=(0.5 if index in {4, 5} else 0.0),
            )
            evidence[cell] = ObservationalEvidence(
                **{**row.__dict__, "empirical_tail": 0.1 + index * 0.1}
            )
        ranked = observational_ranking(
            evidence,
            formula_rank_fusion_weight=0.7,
            formula_rank_fusion_method="reciprocal_rank",
            formula_rank_fusion_scope="bounded_probe",
            formula_probe_limit=2,
            formula_probe_start_rank=2,
        )
        self.assertEqual(ranked[:3], [cells[0], cells[4], cells[5]])
        self.assertEqual([cell for cell in ranked if cell in cells[1:4]], cells[1:4])
        unique_top = observational_ranking(
            evidence,
            formula_rank_fusion_weight=0.7,
            formula_rank_fusion_method="reciprocal_rank",
            formula_rank_fusion_scope="bounded_probe",
            formula_probe_limit=2,
            formula_probe_start_rank=2,
            formula_probe_allow_unique_top1=True,
            formula_probe_top1_margin=0.04,
        )
        self.assertEqual(unique_top[:3], [cells[4], cells[5], cells[0]])

    def test_r2_r2_probe_configuration_is_traceable(self):
        results = v5_core_r2_scores(
            propagation_family(),
            config={
                "evidence_probe_per_signal": 2,
                "evidence_probe_small_workbook_limit": 64,
            },
        )
        self.assertTrue(all(row.evidence["in_evidence_probe_set"] for row in results))
        self.assertTrue(all(row.evidence["evidence_probe_per_signal"] == 2 for row in results))

    def test_structural_priority_prevents_placebo_from_overruling_regime_source(self):
        cells = [("S", "A1"), ("S", "A2"), ("S", "A3")]
        observations = {
            cells[0]: self.observation(cells[0], regime=0.8),
            cells[1]: self.observation(cells[1], regime=0.0),
            cells[2]: self.observation(cells[2], regime=0.2),
        }
        placebo = {
            cells[0]: PlaceboEvidence(
                cell=cells[0], treatment=0.4, empirical_tail=1.0,
                candidate_coverage=True,
            ),
            cells[1]: PlaceboEvidence(
                cell=cells[1], treatment=1.0, empirical_tail=1 / 9,
                candidate_coverage=True,
            ),
            cells[2]: PlaceboEvidence(
                cell=cells[2], treatment=0.7, empirical_tail=1 / 9,
                candidate_coverage=True,
            ),
        }
        ordinary = r2_module._rerank_uncertainty(
            cells, cells, placebo, observations,
            safe_counterfactual_reorder=True,
        )
        guarded = r2_module._rerank_uncertainty(
            cells, cells, placebo, observations,
            safe_counterfactual_reorder=True,
            structural_priority_in_uncertainty=True,
        )
        self.assertEqual(ordinary[0], cells[1])
        self.assertEqual(guarded, [cells[0], cells[2], cells[1]])

    def test_structural_priority_still_uses_dcf_when_regime_evidence_ties(self):
        cells = [("S", "A1"), ("S", "A2")]
        observations = {
            cell: self.observation(cell, regime=1.0) for cell in cells
        }
        placebo = {
            cells[0]: PlaceboEvidence(
                cell=cells[0], treatment=0.4, empirical_tail=1 / 5,
                candidate_coverage=True,
            ),
            cells[1]: PlaceboEvidence(
                cell=cells[1], treatment=0.8, empirical_tail=1 / 9,
                candidate_coverage=True,
            ),
        }
        guarded = r2_module._rerank_uncertainty(
            cells, cells, placebo, observations,
            safe_counterfactual_reorder=True,
            counterfactual_tail=0.25,
            structural_priority_in_uncertainty=True,
        )
        self.assertEqual(guarded, [cells[1], cells[0]])

    def test_structural_priority_setting_is_traceable(self):
        results = v5_core_r2_scores(
            propagation_family(),
            config={"structural_priority_in_uncertainty": True},
        )
        self.assertTrue(all(
            row.evidence["structural_priority_in_uncertainty"] for row in results
        ))


if __name__ == "__main__":
    unittest.main()
