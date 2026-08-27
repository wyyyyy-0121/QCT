import ast
import inspect
import unittest
from unittest import mock

import formulaguard.v5_core as v5_core_module
from formulaguard.api import localize
from formulaguard.formula import normalized_formula
from formulaguard.v5_core import (
    FEATURE_NAMES,
    NEGATIVE_FEATURES,
    POSITIVE_FEATURES,
    _category,
    _intervention_portfolio,
    build_candidate_portfolio,
    discover_formula_regimes,
    fit_pairwise_linear_ranker,
    v5_core_scores,
)
from formulaguard.workbook import WorkbookModel


def family_model(error_formula="=MIN(B5:D5)"):
    cells = {}
    formulas = {}
    for row in range(2, 9):
        for col, value in zip("BCD", (row, row + 2, row + 4)):
            cells[("Data", f"{col}{row}")] = value
        formulas[("Data", f"E{row}")] = f"=SUM(B{row}:D{row})"
        formulas[("Data", f"F{row}")] = f"=E{row}*2"
    formulas[("Data", "E5")] = error_formula
    formulas[("Data", "G9")] = "=SUM(F2:F8)"
    return WorkbookModel.from_cells(cells, formulas)


class V5CoreTests(unittest.TestCase):
    def test_public_interface_has_no_label_fields(self):
        parameters = set(inspect.signature(v5_core_scores).parameters)
        self.assertFalse(parameters & {"source_cell", "error_type", "correct_formula", "labels"})

    def test_core_function_does_not_call_v4_scores(self):
        tree = ast.parse(inspect.getsource(v5_core_scores))
        calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertNotIn("v4_scores", calls)

    def test_function_and_range_repairs_exist_before_ranking(self):
        function_rows = build_candidate_portfolio(family_model(), ("Data", "E5"))
        wanted = normalized_formula("=SUM(B5:D5)")
        self.assertIn(wanted, {normalized_formula(row.candidate.formula) for row in function_rows})
        range_rows = build_candidate_portfolio(family_model("=SUM(B5:C5)"), ("Data", "E5"))
        self.assertIn(wanted, {normalized_formula(row.candidate.formula) for row in range_rows})
        self.assertTrue(all(row.candidate.reference_quality >= 0.80 for row in function_rows + range_rows))

    def test_intervention_budget_is_quality_first_and_category_diverse(self):
        portfolio = build_candidate_portfolio(family_model("=SUM(B5:C5)"), ("Data", "E5"))
        self.assertGreaterEqual(len(portfolio), 2)
        base = _intervention_portfolio(portfolio, 2, deep=False)
        self.assertEqual(base, portfolio[:2])
        deep = _intervention_portfolio(portfolio, min(8, len(portfolio)), deep=True)
        self.assertEqual(deep[:2], portfolio[:2])
        available_categories = {_category(item.candidate) for item in portfolio}
        deep_categories = {_category(item.candidate) for item in deep}
        if len(deep) >= len(available_categories):
            self.assertTrue(available_categories.issubset(deep_categories))

    def test_complete_candidate_centric_ranking(self):
        model = family_model()
        results = v5_core_scores(model)
        self.assertEqual(len(results), len(model.formula_cells))
        self.assertEqual({row.cell for row in results}, set(model.formula_cells))
        self.assertEqual(results[0].cell, ("Data", "E5"))
        self.assertTrue(all(results[index].score >= results[index + 1].score for index in range(len(results) - 1)))
        self.assertTrue(all("candidate_portfolio" in row.evidence for row in results))
        self.assertTrue(all("evaluated_candidate_features" in row.evidence for row in results))

    def test_clean_family_is_treated_as_a_legitimate_regime(self):
        model = family_model("=SUM(B5:D5)")
        regimes = discover_formula_regimes(model)
        self.assertGreaterEqual(regimes[("Data", "E5")].exception_likelihood, 0.5)
        results = v5_core_scores(model)
        self.assertEqual(results[0].evidence["alarm_status"], "no_alarm")

    def test_periodic_family_is_identified(self):
        cells = {("S", f"A{row}"): row for row in range(2, 10)}
        formulas = {
            ("S", f"B{row}"): (f"=A{row}*2" if row % 2 == 0 else f"=A{row}+1")
            for row in range(2, 10)
        }
        regimes = discover_formula_regimes(WorkbookModel.from_cells(cells, formulas))
        self.assertEqual(regimes[("S", "B5")].regime_type, "periodic")
        self.assertTrue(regimes[("S", "B5")].periodic_position.startswith("period_2"))

    def test_api_dispatches_both_new_heads(self):
        rule = localize(family_model(), "formulaguard_v5_core_rule")
        learned = localize(family_model(), "formulaguard_v5_core_learned")
        self.assertEqual(rule[0].evidence["model_version"], "v5-core-dev-r1")
        self.assertEqual(learned[0].evidence["head"], "learned")

    def test_pairwise_ranker_enforces_weight_signs(self):
        positive = {name: 0.9 if name in POSITIVE_FEATURES else 0.1 for name in FEATURE_NAMES}
        negative = {name: 0.1 if name in POSITIVE_FEATURES else 0.9 for name in FEATURE_NAMES}
        config = fit_pairwise_linear_ranker([(positive, negative)] * 8, max_epochs=50)
        weights = config["feature_weights"]
        self.assertTrue(all(weights[name] >= 0 for name in POSITIVE_FEATURES))
        self.assertTrue(all(weights[name] <= 0 for name in NEGATIVE_FEATURES))

    def test_rule_and_learned_heads_share_counterfactual_preparation(self):
        model = family_model()
        original = v5_core_module._evaluate_candidates
        with mock.patch.object(v5_core_module, "_evaluate_candidates", wraps=original) as evaluated:
            v5_core_scores(model, head="rule")
            first_count = evaluated.call_count
            v5_core_scores(model, head="learned", config={})
        self.assertGreater(first_count, 0)
        self.assertEqual(evaluated.call_count, first_count)


if __name__ == "__main__":
    unittest.main()
