import unittest

import torch

from formulaguard.formula_compatibility_pilot import candidate_rows, token_mutations
from formulaguard.formula_compatibility_pilot_torch import FormulaCompatibilityPilot


class FormulaCompatibilityPilotTests(unittest.TestCase):
    def test_mutations_are_deterministic_and_distinct(self):
        tokens = (
            "BINARY", "OP_+", "REF", "SELF", "ROW_REL", "OFFSET_ZERO", "DIGIT_0",
            "COL_REL", "OFFSET_NEG", "DIGIT_1", "NUM_ONE", "BINARY_END",
        )
        first = token_mutations(tokens)
        second = token_mutations(tokens)
        self.assertEqual(first, second)
        self.assertEqual(len({candidate for _, candidate in first}), len(first))
        self.assertIn("operator", {kind for kind, _ in first})
        self.assertIn("reference_offset", {kind for kind, _ in first})

    def test_candidate_rows_put_observed_first_and_deduplicate(self):
        example = {
            "observed_tokens": ["BINARY", "OP_+", "NUM_ONE"],
            "repair_candidates": [
                {"tokens": ["BINARY", "OP_-", "NUM_ONE"]},
                {"tokens": ["BINARY", "OP_-", "NUM_ONE"]},
            ],
        }
        rows = candidate_rows(example)
        self.assertEqual(rows[0]["kind"], "observed")
        self.assertEqual(len({row["tokens"] for row in rows}), len(rows))

    def test_dual_encoder_candidate_shape_and_mask(self):
        model = FormulaCompatibilityPilot(32)
        context = torch.tensor([[1, 2, 3], [1, 4, 0]])
        context_lengths = torch.tensor([3, 2])
        formulas = torch.tensor([
            [[1, 5, 2], [1, 6, 2]],
            [[1, 7, 2], [0, 0, 0]],
        ])
        formula_lengths = torch.tensor([[3, 3], [3, 1]])
        mask = torch.tensor([[True, True], [True, False]])
        logits = model.candidate_logits(
            context, context_lengths, formulas, formula_lengths, mask
        )
        self.assertEqual(tuple(logits.shape), (2, 2))
        self.assertTrue(torch.isneginf(logits[1, 1]))


if __name__ == "__main__":
    unittest.main()
