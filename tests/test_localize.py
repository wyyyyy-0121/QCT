import unittest
from unittest.mock import patch

from formulaguard.localize import (
    _competition_ranks,
    _energy,
    _v3_component_change,
    _v4_bounded_change,
    behavior_anomaly_scores,
    constraint_residual_scores,
    generate_candidates,
    graph_review_scores,
    localize,
    v4_default_parameters,
    v4_scores,
)
from formulaguard.v5 import _v5_consensus_order, v5_default_parameters, v5_scores
from formulaguard.workbook import WorkbookModel


def repeated_formula_model():
    cells = {}
    formulas = {}
    for row in range(5, 10):
        cells[("Model", f"B{row}")] = row
        cells[("Model", f"C{row}")] = row + 1
        formulas[("Model", f"D{row}")] = f"=B{row}*C{row}"
        formulas[("Model", f"E{row}")] = f"=D{row}*(1+$B$2)"
    cells[("Model", "B2")] = 0.08
    formulas[("Model", "D7")] = "=B6*C7"
    formulas[("Model", "E11")] = "=SUM(E5:E9)"
    return WorkbookModel.from_cells(cells, formulas)


class LocalizationTests(unittest.TestCase):

    def test_v4_public_parameter_contract_matches_evidence(self):
        params = v4_default_parameters()
        results = localize(repeated_formula_model(), "formulaguard_v4", candidate_limit=15)
        evidence = results[0].evidence
        self.assertEqual(params["rrf_k"], evidence["rrf_k"])
        self.assertEqual(params["intervention_budget"], evidence["intervention_budget"])
        self.assertEqual(params["scope_depth"], evidence["scope_depth"])
        self.assertEqual(params["scope_decay"], evidence["scope_decay"])

    def test_peer_translation_generates_true_repair_without_ground_truth(self):
        model = repeated_formula_model()
        candidates = generate_candidates(model, ("Model", "D7"), limit=20)
        indexed = {candidate.formula: candidate for candidate in candidates}
        self.assertIn("=B7*C7", indexed)
        self.assertIn("peer_translation", indexed["=B7*C7"].sources)
        self.assertGreater(indexed["=B7*C7"].quality, 0.0)

    def test_horizontal_peer_evidence_is_kept_with_vertical_neighbors(self):
        cells = {
            ("Model", "A6"): 2, ("Model", "A7"): 3,
            ("Model", "B5"): 4, ("Model", "C5"): 5,
            ("Model", "D5"): 20, ("Model", "E5"): 20,
        }
        formulas = {
            ("Model", "D5"): "=B4*C5",
            ("Model", "D6"): "=A6+A7",
            ("Model", "D7"): "=A7+A6",
            ("Model", "E5"): "=C5*D5",
            ("Model", "F5"): "=D5*E5",
        }
        model = WorkbookModel.from_cells(cells, formulas)
        candidates = generate_candidates(model, ("Model", "D5"), limit=20)
        indexed = {candidate.formula: candidate for candidate in candidates}
        self.assertIn("=B5*C5", indexed)
        self.assertIn("peer_translation", indexed["=B5*C5"].sources)
        self.assertGreaterEqual(indexed["=B5*C5"].support, 2)

    def test_internal_balance_residual_responds_to_counterfactual_repair(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 10},
            {
                ("Model", "B1"): "=A1*2",
                ("Model", "C1"): "=A1*3",
                ("Model", "D1"): "=B1-C1",
            },
        )
        before = behavior_anomaly_scores(model)
        after = behavior_anomaly_scores(model, {("Model", "B1"): "=A1*3"})
        self.assertGreater(before[("Model", "D1")], 0.0)
        self.assertEqual(after[("Model", "D1")], 0.0)
        invalid = constraint_residual_scores(model, {("Model", "B1"): "=A1/0"})
        self.assertEqual(invalid[("Model", "D1")], 1.0)

    def test_behavior_and_constraint_scores_share_one_workbook_evaluation(self):
        model = repeated_formula_model()
        with patch.object(model, "evaluate", wraps=model.evaluate) as evaluate:
            behavior_anomaly_scores(model)
        self.assertEqual(evaluate.call_count, 1)

    def test_energy_does_not_double_count_constraint_as_general_behavior(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 10},
            {
                ("Model", "B1"): "=A1*2",
                ("Model", "C1"): "=A1*3",
                ("Model", "D1"): "=B1-C1",
            },
        )
        _, components = _energy(model)
        self.assertEqual(components["behavior_general"], 0.0)
        self.assertEqual(components["constraint"], 1.0)
        self.assertEqual(components["behavior"], 0.75)

    def test_all_no_oracle_methods_return_complete_rankings(self):
        model = repeated_formula_model()
        methods = [
            "random",
            "excel_like",
            "pattern",
            "graph",
            "behavior",
            "excelint_like",
            "warder_like",
            "formulaguard",
            "formulaguard_v3",
            "formulaguard_v3_real",
            "formulaguard_v4",
        ]
        for method in methods:
            results = localize(model, method, candidate_limit=5)
            self.assertEqual(len(results), len(model.formula_cells))
            self.assertEqual({result.cell for result in results}, set(model.formula_cells))
            self.assertTrue(all(results[i].score >= results[i + 1].score for i in range(len(results) - 1)))

    def test_formulaguard_exposes_auditable_evidence(self):
        result = localize(repeated_formula_model(), "formulaguard", candidate_limit=5)[0]
        self.assertIn("base_energy", result.evidence)
        self.assertIn("prior_score", result.evidence)
        self.assertIn("prior_responsibility", result.evidence)
        self.assertIn("rootness_factor", result.evidence)
        self.assertIn("block_boundary_factor", result.evidence)
        self.assertIn("localization_seconds", result.evidence)
        self.assertIn("delta_energy_normalized", result.evidence)
        self.assertIn("delta_responsibility", result.evidence)
        self.assertIn("candidate_quality", result.evidence)
        self.assertIn("candidate_quality_responsibility", result.evidence)
        self.assertGreaterEqual(result.evidence["influence"], 0.0)
        self.assertLessEqual(result.evidence["influence"], 1.0)

    def test_v3_adaptive_weights_sum_to_one_and_shift_graph_weight(self):
        results = localize(repeated_formula_model(), "formulaguard_v3", candidate_limit=5)
        for result in results:
            evidence = result.evidence
            total = (
                evidence["adaptive_weight_formula"]
                + evidence["adaptive_weight_graph"]
                + evidence["adaptive_weight_behavior"]
            )
            self.assertAlmostEqual(total, 1.0)
            self.assertGreaterEqual(evidence["structure_reliability"], 0.0)
            self.assertLessEqual(evidence["structure_reliability"], 1.0)
            self.assertLessEqual(evidence["adaptive_weight_graph"], 0.20)

    def test_v3_component_change_records_side_effects(self):
        gain, harm = _v3_component_change(0.4, 0.2)
        self.assertAlmostEqual(gain, 0.5)
        self.assertEqual(harm, 0.0)
        gain, harm = _v3_component_change(0.4, 0.6)
        self.assertEqual(gain, 0.0)
        self.assertAlmostEqual(harm, 0.5)

    def test_v3_exposes_counterfactual_and_path_evidence(self):
        results = localize(repeated_formula_model(), "formulaguard_v3", candidate_limit=5)
        self.assertEqual(len(results), len(repeated_formula_model().formula_cells))
        evidence = results[0].evidence
        required = {
            "structure_reliability",
            "adaptive_prior",
            "raw_gain",
            "side_effect",
            "net_gain",
            "gain_constraint",
            "harm_constraint",
            "path_responsibility",
            "reported_path",
            "evidence_strength",
            "candidate_evidence",
        }
        self.assertTrue(required.issubset(evidence))
        self.assertGreaterEqual(evidence["side_effect"], 0.0)
        self.assertGreaterEqual(evidence["net_gain"], 0.0)

    def test_v3_weak_candidate_cannot_receive_intervention_bonus(self):
        model = WorkbookModel.from_cells(
            {("Check", "A1"): 1},
            {("Check", "B1"): "=A1", ("Check", "C1"): "=B1"},
        )
        results = localize(model, "formulaguard_v3", candidate_limit=1)
        for result in results:
            if result.evidence["net_gain"] == 0:
                self.assertEqual(result.evidence["evidence_strength"], 0.0)
                self.assertLessEqual(result.score, 0.20)

    def test_v3_intervenes_on_all_formulas_in_typical_medium_workbook(self):
        cells = {("Model", f"A{row}"): row for row in range(1, 55)}
        formulas = {("Model", f"B{row}"): f"=A{row}*2" for row in range(1, 55)}
        model = WorkbookModel.from_cells(cells, formulas)
        results = localize(model, "formulaguard_v3", candidate_limit=1)
        indexed = {result.cell: result for result in results}
        self.assertIsNotNone(indexed[("Model", "B54")].candidate_formula)

    def test_v3_reports_all_reachable_structural_sinks(self):
        cells = {("Model", "A1"): 2}
        formulas = {("Model", "B1"): "=A1*2"}
        for row in range(2, 14):
            formulas[("Model", f"B{row}")] = "=B1+1"
        model = WorkbookModel.from_cells(cells, formulas)
        source = next(
            result for result in localize(model, "formulaguard_v3", candidate_limit=1)
            if result.cell == ("Model", "B1")
        )
        for row in range(2, 14):
            self.assertIn(f"Model!B{row}", source.evidence["reported_paths"])

    def test_v3_real_falls_back_to_v2_order_when_no_positive_evidence(self):
        model = WorkbookModel.from_cells(
            {("Plain", "A1"): 1},
            {("Plain", "B1"): "=A1", ("Plain", "C1"): "=B1"},
        )
        v2 = localize(model, "formulaguard", candidate_limit=1)
        v3_real = localize(model, "formulaguard_v3_real", candidate_limit=1)
        self.assertEqual([item.cell for item in v3_real], [item.cell for item in v2])
        self.assertTrue(all(
            item.evidence["counterfactual_evidence_strength"] == 0
            for item in v3_real
        ))

    def test_v3_real_exposes_selective_evidence_contract(self):
        results = localize(repeated_formula_model(), "formulaguard_v3_real", candidate_limit=5)
        for result in results:
            evidence = result.evidence
            self.assertIn(evidence["diagnostic_status"], {
                "counterfactual_supported", "pattern_only", "insufficient_evidence"
            })
            self.assertEqual(
                evidence["fusion_policy"],
                "v2_score_then_counterfactual_tiebreak",
            )

    def test_v3_real_never_crosses_distinct_v2_score_groups(self):
        model = repeated_formula_model()
        v2 = localize(model, "formulaguard", candidate_limit=5)
        v3_real = localize(model, "formulaguard_v3_real", candidate_limit=5)
        v3_position = {item.cell: index for index, item in enumerate(v3_real)}
        for left in v2:
            for right in v2:
                if left.score > right.score:
                    self.assertLess(v3_position[left.cell], v3_position[right.cell])

    def test_v4_bounded_change_stays_stable_near_zero(self):
        gain, harm = _v4_bounded_change(1e-12, 0.0)
        self.assertLessEqual(gain, 1.0)
        self.assertEqual(harm, 0.0)
        gain, harm = _v4_bounded_change(0.0, 1e-4)
        self.assertEqual(gain, 0.0)
        self.assertGreater(harm, 0.0)
        self.assertLessEqual(harm, 1.0)

    def test_v4_rank_fusion_preserves_equal_component_scores(self):
        ranks = _competition_ranks({
            ("Model", "A1"): 0.0,
            ("Model", "A2"): 1.0,
            ("Model", "A3"): 0.0,
        })
        self.assertEqual(ranks[("Model", "A2")], 1)
        self.assertEqual(ranks[("Model", "A1")], 2)
        self.assertEqual(ranks[("Model", "A3")], 2)

    def test_graph_review_helper_matches_public_graph_ranking(self):
        model = repeated_formula_model()
        expected = [item.cell for item in localize(model, "graph")]
        scores = graph_review_scores(model)
        actual = sorted(model.formula_cells, key=lambda cell: (-scores[cell], cell))
        self.assertEqual(actual, expected)

    def test_v4_exposes_selection_calibration_and_rank_contract(self):
        results = localize(repeated_formula_model(), "formulaguard_v4", candidate_limit=5)
        self.assertEqual(len(results), len(repeated_formula_model().formula_cells))
        required = {
            "rrf_score",
            "consensus_rrf_rank",
            "unified_rrf_rank",
            "graph_rank",
            "base_rank",
            "intervention_selected",
            "candidate_count",
            "diagnostic_status",
            "local_scope_size",
            "candidate_delta",
            "null_control_count",
            "intervention_responsibility_gain",
            "promotion_cap",
            "final_rank",
        }
        for result in results:
            self.assertTrue(required.issubset(result.evidence))
            self.assertIn(result.evidence["diagnostic_status"], {
                "not_intervened",
                "no_candidate",
                "pattern_only",
                "uncalibrated_candidate",
                "moderate_counterfactual",
                "strong_counterfactual",
            })
            self.assertLessEqual(result.evidence["promotion_cap"], 10)

    def test_v4_distinguishes_budget_exclusion_from_empty_candidates(self):
        model = repeated_formula_model()
        results = v4_scores(model, candidate_limit=3, max_intervention_cells=2)
        selected = [item for item in results if item.evidence["intervention_selected"]]
        excluded = [item for item in results if not item.evidence["intervention_selected"]]
        self.assertEqual(len(selected), 2)
        self.assertTrue(excluded)
        self.assertTrue(all(
            item.evidence["diagnostic_status"] == "not_intervened"
            and item.evidence["candidate_count"] == 0
            for item in excluded
        ))

    def test_v4_weak_or_uncalibrated_evidence_cannot_promote(self):
        model = WorkbookModel.from_cells(
            {("Plain", "A1"): 1},
            {("Plain", "B1"): "=A1", ("Plain", "C1"): "=B1"},
        )
        results = localize(model, "formulaguard_v4", candidate_limit=1)
        for result in results:
            if result.evidence["diagnostic_status"] not in {
                "strong_counterfactual", "moderate_counterfactual"
            }:
                self.assertEqual(result.evidence["promotion_cap"], 0)

    def test_v5_public_parameter_contract_is_preregistered(self):
        params = v5_default_parameters()
        self.assertEqual(params["base_model"], "v4-dev-r1")
        self.assertEqual(params["pattern_fraction"], 0.02)
        self.assertEqual(params["pattern_min_elite"], 3)
        self.assertEqual(params["pattern_max_elite"], 10)
        self.assertEqual(params["max_joint_candidates"], 5)
        self.assertEqual(params["rescue_below_v4_rank"], 5)

    @staticmethod
    def _mock_v4_result(cell, rank, pattern_rank, status="pattern_only", irg=0.0, delta=0.0):
        from formulaguard.localize import LocalizationResult
        return LocalizationResult(
            cell=("Model", cell),
            score=100.0 - rank,
            evidence={
                "formula_rank": pattern_rank,
                "diagnostic_status": status,
                "intervention_responsibility_gain": irg,
                "candidate_delta": delta,
                "final_rank": rank,
            },
        )

    def test_v5_joint_gate_promotes_consensus_and_preserves_other_relative_order(self):
        items = [
            self._mock_v4_result("A1", 1, 8),
            self._mock_v4_result("A2", 2, 6),
            self._mock_v4_result("A3", 6, 1, "strong_counterfactual", 8.0, 0.3),
            self._mock_v4_result("A4", 7, 2, "strong_counterfactual", 6.0, 0.4),
            self._mock_v4_result("A5", 5, 7),
        ]
        ordered, joint, elite_limit, active = _v5_consensus_order(items)
        self.assertTrue(active)
        self.assertEqual(elite_limit, 3)
        self.assertEqual(joint, {("Model", "A3"), ("Model", "A4")})
        self.assertEqual(
            [item.cell for item in ordered],
            [("Model", "A3"), ("Model", "A4"), ("Model", "A1"), ("Model", "A2"), ("Model", "A5")],
        )

    def test_v5_requires_both_pattern_elite_and_strong_counterfactual(self):
        items = [
            self._mock_v4_result("A1", 1, 1, "pattern_only", 10.0, 0.8),
            self._mock_v4_result("A2", 6, 8, "strong_counterfactual", 10.0, 0.8),
            self._mock_v4_result("A3", 3, 4),
            self._mock_v4_result("A4", 4, 5),
        ]
        ordered, joint, _, active = _v5_consensus_order(items)
        self.assertFalse(active)
        self.assertFalse(joint)
        self.assertEqual([item.cell for item in ordered], [item.cell for item in items])

    def test_v5_rejects_nonselective_joint_evidence(self):
        items = [
            self._mock_v4_result(
                f"A{index}", index + 5, 1, "strong_counterfactual", 10.0 - index / 10, 0.5
            )
            for index in range(1, 7)
        ]
        ordered, joint, _, active = _v5_consensus_order(items)
        self.assertFalse(active)
        self.assertEqual(len(joint), 6)
        self.assertEqual([item.cell for item in ordered], [item.cell for item in items])

    def test_v5_exposes_consensus_diagnostics_without_mutating_v4(self):
        model = repeated_formula_model()
        before = localize(model, "formulaguard_v4", candidate_limit=5)
        v5 = v5_scores(model, candidate_limit=5)
        after = localize(model, "formulaguard_v4", candidate_limit=5)
        self.assertEqual([item.cell for item in before], [item.cell for item in after])
        self.assertEqual([item.score for item in before], [item.score for item in after])
        self.assertEqual(len(v5), len(before))
        required = {
            "v4_diagnostic_status", "v4_final_rank", "pattern_elite_limit",
            "pattern_elite", "joint_eligible", "joint_candidate_count",
            "joint_gate_active", "joint_confirmed", "v5_final_rank",
            "v5_rank_change", "v5_promotion_distance", "v5_override_reason",
        }
        for result in v5:
            self.assertTrue(required.issubset(result.evidence))
            self.assertNotIn("source_cell", result.evidence)
            self.assertNotIn("correct_formula", result.evidence)

    def test_v5_does_not_override_strong_candidate_already_in_v4_top5(self):
        items = [
            self._mock_v4_result("A1", 2, 1, "strong_counterfactual", 9.0, 0.4),
            self._mock_v4_result("A2", 6, 6),
            self._mock_v4_result("A3", 7, 7),
        ]
        ordered, joint, _, active = _v5_consensus_order(items)
        self.assertFalse(active)
        self.assertEqual(joint, set())
        self.assertEqual([item.cell for item in ordered], [item.cell for item in items])


if __name__ == "__main__":
    unittest.main()
