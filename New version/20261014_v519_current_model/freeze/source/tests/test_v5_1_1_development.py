import unittest

from formulaguard.api import localize
from formulaguard.v5_1_1_development import (
    MODEL_VERSION,
    v5_1_1_development_default_parameters,
    v5_1_1_development_scores,
)
from formulaguard.workbook import WorkbookModel


def revenue_percent_model(wrong_rows=()):
    cells = {
        ("Ops", "A1"): "Period",
        ("Ops", "B1"): "Units",
        ("Ops", "C1"): "Price",
        ("Ops", "D1"): "Revenue",
        ("Ops", "E1"): "Cost",
        ("Ops", "F1"): "Margin",
        ("Ops", "G1"): "Margin %",
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
        formulas[("Ops", f"G{row}")] = f"=F{row}/D{row}"
    return WorkbookModel.from_cells(cells, formulas)


def unsupported_function_model():
    model = revenue_percent_model()
    model.formulas[("Ops", "D6")] = "=IF(B6>0,B6,0)"
    return model


def average_model(wrong_rows=()):
    cells = {
        ("Grades", "A1"): "Student",
        ("Grades", "B1"): "Quiz",
        ("Grades", "C1"): "Project",
        ("Grades", "D1"): "Exam",
        ("Grades", "E1"): "Average",
    }
    formulas = {}
    for row in range(2, 14):
        cells[("Grades", f"A{row}")] = f"S{row}"
        for column in "BCD":
            cells[("Grades", f"{column}{row}")] = 70
        formulas[("Grades", f"E{row}")] = (
            f"=B{row}+C{row}" if row in wrong_rows else f"=AVERAGE(B{row}:D{row})"
        )
    return WorkbookModel.from_cells(cells, formulas)


class V511DevelopmentTests(unittest.TestCase):
    def test_public_parameter_contract_and_api_alias(self):
        self.assertEqual(
            v5_1_1_development_default_parameters()["model_version"], MODEL_VERSION
        )
        results = localize(revenue_percent_model(), "v5.1.1-development")
        self.assertTrue(results)
        self.assertEqual(results[0].evidence["model_version"], MODEL_VERSION)

    def test_percent_column_is_not_misclassified_as_margin_difference(self):
        results = v5_1_1_development_scores(revenue_percent_model())
        self.assertTrue(all(result.candidate_formula is None for result in results))

    def test_unknown_function_mismatch_abstains(self):
        results = v5_1_1_development_scores(unsupported_function_model())
        target = next(result for result in results if result.cell == ("Ops", "D6"))
        self.assertIsNone(target.candidate_formula)
        self.assertEqual(target.evidence["function_compatibility"], "failed")

    def test_legal_neutral_suffix_is_not_flagged(self):
        model = revenue_percent_model()
        model.formulas[("Ops", "D6")] = "=B6*C6+0"
        results = v5_1_1_development_scores(model)
        self.assertTrue(all(result.candidate_formula is None for result in results))

    def test_average_role_is_reconstructed(self):
        result = next(
            item
            for item in v5_1_1_development_scores(average_model((6,)))
            if item.cell == ("Grades", "E6")
        )
        self.assertEqual(result.candidate_formula, "=AVERAGE(B6:D6)")
        self.assertEqual(result.evidence["candidate_origin"], "semantic_average_inputs")

    def test_tied_noncontiguous_templates_abstain(self):
        results = v5_1_1_development_scores(revenue_percent_model((3, 5, 7, 9, 11, 13)))
        self.assertTrue(all(result.candidate_formula is None for result in results))
