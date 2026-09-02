import unittest

from formulaguard.behavioral_consistency import (
    audit_behavioral_consistency,
    canonical_response,
    rank_behavioral_candidates,
    response_distance,
)
from formulaguard.counterfactual_candidates import generate_counterfactual_candidates
from formulaguard.counterfactual_response import build_response_signature
from formulaguard.workbook import WorkbookModel


class BehavioralConsistencyTests(unittest.TestCase):
    def test_algebraically_different_formulas_share_a_response_role(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row + 1 for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2+A2",
                ("S", "B3"): "=SUM(A3,A3)",
                ("S", "B4"): "=A4*3",
            },
        )

        signatures = {
            key: canonical_response(build_response_signature(model, key))
            for key in model.formula_cells
        }
        self.assertAlmostEqual(
            response_distance(signatures[("S", "B1")], signatures[("S", "B2")]), 0.0
        )
        self.assertAlmostEqual(
            response_distance(signatures[("S", "B1")], signatures[("S", "B3")]), 0.0
        )
        self.assertGreater(
            response_distance(signatures[("S", "B1")], signatures[("S", "B4")]), 0.0
        )

        audit = audit_behavioral_consistency(model)
        records = {row["cell"]: row for row in audit["records"]}
        self.assertEqual(records["S!B1"]["status"], "consistent")
        self.assertEqual(records["S!B2"]["status"], "consistent")
        self.assertEqual(records["S!B3"]["status"], "consistent")
        self.assertEqual(records["S!B4"]["status"], "behavioral_outlier")
        self.assertGreater(records["S!B4"]["score"], 0.0)

    def test_wrong_reference_is_exposed_by_relative_input_support(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A2*2",
                ("S", "B4"): "=A4*2",
            },
        )
        audit = audit_behavioral_consistency(model, targets=[("S", "B3")])
        record = audit["records"][0]

        self.assertEqual(record["status"], "behavioral_outlier")
        self.assertGreater(record["score"], 0.4)
        self.assertEqual(record["witness"]["axis"], "column")
        self.assertEqual(record["witness"]["peer_coherence"], 0.0)

    def test_alternating_legal_roles_do_not_create_an_outlier(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*3",
                ("S", "B3"): "=A3*2",
                ("S", "B4"): "=A4*3",
            },
        )
        audit = audit_behavioral_consistency(model)

        self.assertFalse(audit["summary"]["behavioral_outliers"])
        self.assertTrue(all(row["status"] == "consistent" for row in audit["records"]))

    def test_sparse_region_abstains(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2, ("S", "A2"): 4},
            {("S", "B1"): "=A1*2", ("S", "B2"): "=A2*2"},
        )
        audit = audit_behavioral_consistency(model, targets=[("S", "B1")])

        self.assertEqual(audit["records"][0]["status"], "abstained")
        self.assertEqual(audit["records"][0]["reason"], "no_coherent_peer_axis")

    def test_correct_ast_candidate_closes_behavioral_outlier(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A2*2",
                ("S", "B4"): "=A4*2",
            },
        )
        candidates = generate_counterfactual_candidates(model, ("S", "B3"), budget=32)
        ranking = rank_behavioral_candidates(model, ("S", "B3"), candidates)

        self.assertGreater(ranking["observed_score"], 0.0)
        self.assertTrue(ranking["candidates"])
        self.assertEqual(ranking["candidates"][0]["formula"], "=(A3*2)")
        self.assertAlmostEqual(ranking["candidates"][0]["candidate_score"], 0.0)
        self.assertGreater(ranking["candidates"][0]["improvement"], 0.4)


if __name__ == "__main__":
    unittest.main()
