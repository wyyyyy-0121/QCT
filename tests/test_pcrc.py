import unittest

from formulaguard.pcrc import (
    PCRCVocabulary,
    formula_tokens,
    masked_context_tokens,
    numeric_category,
    workbook_examples,
)
from formulaguard.workbook import WorkbookModel


def workbook(target_formula: str = "=A2+B2") -> WorkbookModel:
    cells = {
        ("Model", "A1"): 1,
        ("Model", "B1"): 2,
        ("Model", "A2"): 3,
        ("Model", "B2"): 4,
        ("Model", "A3"): 5,
        ("Model", "B3"): 6,
    }
    return WorkbookModel.from_cells(cells, {
        ("Model", "C1"): "=A1-B1",
        ("Model", "C2"): target_formula,
        ("Model", "C3"): "=A3-B3",
        ("Model", "D2"): "=C2*10",
    })


class PCRCTests(unittest.TestCase):
    def test_numeric_literals_use_bounded_categories(self):
        self.assertEqual(numeric_category(0), "NUM_ZERO")
        self.assertEqual(numeric_category(-1), "NUM_NEG_ONE")
        self.assertEqual(numeric_category(2.5), "NUM_FRACTION")
        self.assertEqual(numeric_category(120), "NUM_INTEGER_100_PLUS")

    def test_formula_tokens_keep_structure_and_bound_literals(self):
        tokens = formula_tokens("=SUM(A1:B2)+120", "C3", "Model")
        self.assertIn("FUNC_SUM", tokens)
        self.assertIn("RANGE_START", tokens)
        self.assertIn("NUM_INTEGER_100_PLUS", tokens)
        self.assertNotIn("120", tokens)

    def test_cross_sheet_range_relation_is_inherited(self):
        tokens = formula_tokens("=SUM('Other'!A1:B2)", "C3", "Model")
        start = tokens.index("RANGE_START")
        end = tokens.index("RANGE_END")
        self.assertEqual(tokens[start:end].count("OTHER"), 2)

    def test_masked_context_is_invariant_to_target_formula(self):
        left = masked_context_tokens(workbook("=A2+B2"), ("Model", "C2"))
        right = masked_context_tokens(workbook("=A2/B2"), ("Model", "C2"))
        self.assertEqual(left, right)
        self.assertIn("TOPO_2_2_MASK", left)

    def test_workbook_examples_use_peer_hypotheses_without_raw_formulas(self):
        examples = workbook_examples(
            workbook(),
            workbook_id="workbook-1",
            structure_group="group-1",
            split="train",
        )
        target = next(item for item in examples if item["observed_tokens"] == list(
            formula_tokens("=A2+B2", "C2", "Model")
        ))
        self.assertTrue(target["repair_candidates"])
        self.assertFalse(target["raw_formula_strings_persisted"])
        self.assertFalse(target["target_formula_tokens_entered_context"])
        self.assertNotIn("=A2+B2", str(target))

    def test_vocabulary_is_trainable_and_bounded(self):
        vocabulary = PCRCVocabulary.build((("CTX", "MASK"), ("REF", "SELF")))
        encoded = vocabulary.encode(("CTX", "MISSING"), maximum=4)
        self.assertEqual(encoded[0], vocabulary.ids["<START>"])
        self.assertEqual(encoded[-1], vocabulary.ids["<END>"])
        self.assertIn(vocabulary.ids["<UNK>"], encoded)


if __name__ == "__main__":
    unittest.main()
