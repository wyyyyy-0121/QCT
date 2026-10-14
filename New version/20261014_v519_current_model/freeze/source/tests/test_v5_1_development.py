import unittest

from formulaguard.api import localize
from formulaguard.v5_1_development import (
    MODEL_VERSION,
    v5_1_development_default_parameters,
    v5_1_development_scores,
)
from formulaguard.workbook import WorkbookModel


def sales_model(wrong_rows=()):
    cells = {
        ("Ops", "A1"): "Period",
        ("Ops", "B1"): "Units",
        ("Ops", "C1"): "Price",
        ("Ops", "D1"): "Revenue",
        ("Ops", "E1"): "Cost",
        ("Ops", "F1"): "Margin",
    }
    formulas = {}
    for row in range(2, 14):
        cells[("Ops", f"A{row}")] = f"P{row}"
        cells[("Ops", f"B{row}")] = 10 + row
        cells[("Ops", f"C{row}")] = 5
        formulas[("Ops", f"D{row}")] = (
            f"=B{row}+C{row}" if row in wrong_rows else f"=B{row}*C{row}"
        )
        formulas[("Ops", f"E{row}")] = f"=B{row}*2"
        formulas[("Ops", f"F{row}")] = f"=D{row}-E{row}"
    return WorkbookModel.from_cells(cells, formulas)


class V51DevelopmentTests(unittest.TestCase):
    def test_public_parameter_contract(self):
        self.assertEqual(
            v5_1_development_default_parameters()["model_version"], MODEL_VERSION
        )
        self.assertTrue(v5_1_development_default_parameters()["frozen_v5_r2_untouched"])

    def test_api_dispatch_exposes_development_model(self):
        results = localize(sales_model(), "v5.1-development")
        self.assertTrue(results)
        self.assertEqual(results[0].evidence["model_version"], MODEL_VERSION)

    def test_clean_workbook_gate_has_no_candidates(self):
        model = sales_model()
        original = dict(model.formulas)
        results = v5_1_development_scores(model)
        self.assertTrue(all(result.candidate_formula is None for result in results))
        self.assertEqual(model.formulas, original)

    def test_singleton_semantic_error_gets_repair_candidate(self):
        model = sales_model((6,))
        result = next(
            item
            for item in v5_1_development_scores(model)
            if item.cell == ("Ops", "D6")
        )
        self.assertEqual(result.candidate_formula, "=B6*C6")
        self.assertEqual(
            result.evidence["candidate_origin"], "semantic_revenue_product"
        )

    def test_contiguous_block_is_propagated_as_one_template(self):
        model = sales_model(tuple(range(5, 10)))
        results = v5_1_development_scores(model)
        repaired = [item for item in results if item.candidate_formula is not None]
        self.assertEqual(
            {item.cell for item in repaired},
            {("Ops", f"D{row}") for row in range(5, 10)},
        )
        self.assertTrue(
            all(item.evidence["group_propagated"] == 1 for item in repaired)
        )

    def test_systematic_column_is_not_lost_when_observed_majority_is_wrong(self):
        model = sales_model(tuple(range(2, 14)))
        results = v5_1_development_scores(model)
        repaired = [
            item
            for item in results
            if item.candidate_formula is not None
            and item.cell[0] == "Ops"
            and item.cell[1].startswith("D")
        ]
        self.assertEqual(len(repaired), 12)
        self.assertTrue(
            all(
                item.candidate_formula == f"=B{item.cell[1][1:]}*C{item.cell[1][1:]}"
                for item in repaired
            )
        )
