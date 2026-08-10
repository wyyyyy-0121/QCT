import unittest
from unittest.mock import patch

from formulaguard.localize import (
    _energy,
    _v3_component_change,
    behavior_anomaly_scores,
    constraint_residual_scores,
    generate_candidates,
    localize,
)
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


if __name__ == "__main__":
    unittest.main()
