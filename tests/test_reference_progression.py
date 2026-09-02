import unittest

from formulaguard.pcrc import formula_tokens
from formulaguard.reference_progression import (
    directional_progression_peers,
    formula_offsets,
    progression_decision,
)
from formulaguard.workbook import WorkbookModel


class ReferenceProgressionTests(unittest.TestCase):
    def test_formula_offsets_separate_shape_from_reference_coordinates(self):
        left = formula_offsets(formula_tokens("=A2+1", "D2", "S"))
        right = formula_offsets(formula_tokens("=B2+1", "D2", "S"))
        self.assertEqual(left.skeleton, right.skeleton)
        self.assertNotEqual(left.values, right.values)

    def test_exact_linear_progression_selects_the_target_coordinate(self):
        formulas = {
            ("S", "B2"): "=A2",
            ("S", "C2"): "=A2",
            ("S", "D2"): "=A2",
            ("S", "E2"): "=A2",
            ("S", "F2"): "=A2",
        }
        model = WorkbookModel.from_cells({}, formulas)
        peers = directional_progression_peers(model, ("S", "D2"))
        candidates = (
            formula_tokens("=A2", "D2", "S"),
            formula_tokens("=B2", "D2", "S"),
        )
        decision = progression_decision(candidates, peers)
        self.assertEqual(decision.candidate_index, 0)
        self.assertEqual(decision.axes, ("column",))
        self.assertEqual(decision.reason, "unique_exact_nonconstant_progression")

    def test_context_and_decision_do_not_read_the_target_formula(self):
        peer_formulas = {
            ("S", "B2"): "=A2",
            ("S", "C2"): "=A2",
            ("S", "E2"): "=A2",
            ("S", "F2"): "=A2",
        }
        first = WorkbookModel.from_cells({}, {**peer_formulas, ("S", "D2"): "=A2"})
        second = WorkbookModel.from_cells({}, {**peer_formulas, ("S", "D2"): "=Z99"})
        self.assertEqual(
            directional_progression_peers(first, ("S", "D2")),
            directional_progression_peers(second, ("S", "D2")),
        )

    def test_constant_or_undersupported_peers_abstain(self):
        candidates = (("REF", "SELF", "ROW_REL", "OFFSET_ZERO", "DIGIT_0",
                       "COL_REL", "OFFSET_NEG", "DIGIT_1"),)
        model = WorkbookModel.from_cells({}, {
            ("S", "B2"): "=A2", ("S", "C2"): "=B2", ("S", "D2"): "=C2",
        })
        peers = directional_progression_peers(model, ("S", "D2"))
        self.assertIsNone(progression_decision(candidates, peers).candidate_index)


if __name__ == "__main__":
    unittest.main()
