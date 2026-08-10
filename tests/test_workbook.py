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


if __name__ == "__main__":
    unittest.main()
