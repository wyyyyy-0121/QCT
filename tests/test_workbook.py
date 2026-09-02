import unittest

from formulaguard.workbook import WorkbookModel


def simple_model():
    cells = {
        ("Model", "A1"): 2,
        ("Model", "B1"): 3,
        ("Model", "A2"): 4,
        ("Model", "B2"): 5,
    }
    formulas = {
        ("Model", "C1"): "=A1+B1",
        ("Model", "C2"): "=A2+B2",
        ("Model", "D1"): "=C1*2",
        ("Model", "D2"): "=SUM(C1:C2)",
        ("Model", "E1"): "=IF(D2>10,D2,0)",
    }
    return WorkbookModel.from_cells(cells, formulas)


class WorkbookTests(unittest.TestCase):
    def test_supported_formula_evaluation(self):
        values, errors = simple_model().evaluate()
        self.assertFalse(errors)
        self.assertAlmostEqual(values[("Model", "C1")], 5)
        self.assertAlmostEqual(values[("Model", "D2")], 14)
        self.assertAlmostEqual(values[("Model", "E1")], 14)

    def test_dependency_graph_and_propagation_depth(self):
        model = simple_model()
        graph = model.dependency_graph()
        self.assertIn(("Model", "C1"), graph.dependents[("Model", "A1")])
        self.assertIn(("Model", "E1"), graph.descendants(("Model", "C1")))
        self.assertEqual(graph.shortest_path_length(("Model", "C1"), ("Model", "E1")), 2)
        self.assertEqual(graph.shortest_path(("Model", "C1"), ("Model", "E1")), [
            ("Model", "C1"),
            ("Model", "D2"),
            ("Model", "E1"),
        ])

    def test_counterfactual_override_changes_downstream_value(self):
        model = simple_model()
        base, base_errors = model.evaluate()
        changed, changed_errors = model.evaluate({("Model", "C1"): "=A1-B1"})
        self.assertFalse(base_errors)
        self.assertFalse(changed_errors)
        self.assertNotEqual(base[("Model", "E1")], changed[("Model", "E1")])

    def test_value_override_changes_inputs_without_mutating_model(self):
        model = simple_model()
        base, base_errors = model.evaluate()
        changed, changed_errors = model.evaluate(value_overrides={("Model", "A1"): 20})
        repeated, repeated_errors = model.evaluate()
        self.assertFalse(base_errors)
        self.assertFalse(changed_errors)
        self.assertFalse(repeated_errors)
        self.assertNotEqual(base[("Model", "C1")], changed[("Model", "C1")])
        self.assertEqual(base, repeated)

    def test_value_override_rejects_formula_cell(self):
        model = simple_model()
        with self.assertRaisesRegex(ValueError, "formula cells"):
            model.evaluate(value_overrides={("Model", "C1"): 99})

    def test_if_only_evaluates_the_selected_branch(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 1, ("Model", "B1"): 0},
            {
                ("Model", "C1"): "=IF(A1>0,1,1/B1)",
                ("Model", "C2"): "=IF(A1<0,1/B1,2)",
            },
        )

        values, errors = model.evaluate()

        self.assertFalse(errors)
        self.assertEqual(values[("Model", "C1")], 1)
        self.assertEqual(values[("Model", "C2")], 2)

    def test_targeted_evaluation_matches_full_result_and_skips_unrelated_formulas(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 2, ("Model", "Z2"): 0},
            {
                ("Model", "B1"): "=A1+1",
                ("Model", "C1"): "=B1*2",
                ("Model", "Z1"): "=1/Z2",
            },
        )

        full_values, full_errors = model.evaluate()
        values, errors = model.evaluate(targets=[("Model", "C1")])

        self.assertEqual(values[("Model", "C1")], full_values[("Model", "C1")])
        self.assertEqual(values[("Model", "B1")], full_values[("Model", "B1")])
        self.assertNotIn(("Model", "Z1"), values)
        self.assertNotIn(("Model", "Z1"), errors)
        self.assertIn(("Model", "Z1"), full_errors)

    def test_full_column_range_materializes_only_present_cells(self):
        model = WorkbookModel.from_cells(
            {("Model", "A1"): 10, ("Model", "A3"): 20},
            {("Model", "B1"): "=AVERAGE(A1:A1048576)"},
        )

        graph = model.dependency_graph()
        values, errors = model.evaluate()
        changed, changed_errors = model.evaluate(
            value_overrides={("Model", "A2"): 30}
        )

        self.assertEqual(
            graph.precedents[("Model", "B1")],
            {("Model", "A1"), ("Model", "A3")},
        )
        self.assertFalse(errors)
        self.assertFalse(changed_errors)
        self.assertEqual(values[("Model", "B1")], 15)
        self.assertEqual(changed[("Model", "B1")], 20)


if __name__ == "__main__":
    unittest.main()
