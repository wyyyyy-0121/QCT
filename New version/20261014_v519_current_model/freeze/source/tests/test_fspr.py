from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

from formulaguard.fspr import (
    DIMENSIONS,
    PROTOCOL,
    TOKENIZER_VERSION,
    forepbench_value_lookup,
    formula_feature_tokens,
    fspr_decision,
    hashed_features,
    load_model,
)


class FSPRTests(unittest.TestCase):
    def test_formula_tokens_remove_addresses_and_nontrivial_literals(self):
        data = {
            "sheetNames": ["Sheet1"],
            "sheets": {
                "Sheet1": {
                    "cells": {
                        "A1": {"v": "4", "t": "n"},
                        "B2": {"v": "text", "t": "s"},
                    }
                }
            },
        }
        syntax, context = formula_feature_tokens(
            "=SUM($A$1:B2)+12345",
            value_lookup=forepbench_value_lookup(data),
        )
        joined = " ".join((*syntax, *context))
        self.assertNotIn("A1", joined)
        self.assertNotIn("B2", joined)
        self.assertNotIn("12345", joined)
        self.assertIn("FUNC_SUM", syntax)
        self.assertTrue(any("NUMERIC" in token for token in context))
        self.assertTrue(any("TEXT" in token for token in context))

    def test_unsupported_formula_retains_bounded_lexical_shape(self):
        syntax, context = formula_feature_tokens('=A1+"abc"')
        self.assertEqual(context, ("CTX_REFERENCE_TYPES_0",))
        self.assertIn("SYN_UNSUPPORTED_AST", syntax)
        self.assertIn("LEX_REF", syntax)
        self.assertIn("LEX_STR", syntax)
        self.assertFalse(any("A1" in token or "ABC" in token for token in syntax))

    def test_unsupported_formula_does_not_leak_identity_tokens(self):
        syntax, _ = formula_feature_tokens("=[Secret.xlsx]Sheet1!A1+MY_NAME+FROB(B2)")
        joined = " ".join(syntax)
        self.assertIn("LEX_IDENT", syntax)
        self.assertIn("LEX_FUNC_FROB", syntax)
        self.assertNotIn("SECRET", joined)
        self.assertNotIn("MY_NAME", joined)
        self.assertNotIn("SHEET1", joined)

    def test_hashing_is_deterministic_l2_normalized_and_view_separated(self):
        syntax = ("SYN_A", "SYN_B")
        context = ("CTX_X",)
        full = hashed_features(syntax, context)
        self.assertEqual(full, hashed_features(syntax, context))
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in full.values())), 1.0)
        self.assertNotEqual(full, hashed_features(syntax, context, view="syntax_only"))
        self.assertNotEqual(full, hashed_features(syntax, context, view="context_only"))

    def test_fifth_slot_decision_preserves_prefix_inventory_and_tail(self):
        ranking = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A5", "S!A6", "S!A7"]
        decision = fspr_decision(
            ranking,
            {"S!A5": 0.2, "S!A6": 0.9, "S!A7": 0.1},
            0.8,
        )
        self.assertTrue(decision.changed)
        self.assertEqual(decision.ranking[:5], (*ranking[:4], "S!A6"))
        self.assertEqual(decision.ranking[5:], ("S!A5", "S!A7"))
        self.assertEqual(set(decision.ranking), set(ranking))

    def test_fifth_slot_abstains_below_threshold(self):
        ranking = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A5", "S!A6"]
        decision = fspr_decision(ranking, {"S!A6": 0.79}, 0.8)
        self.assertFalse(decision.changed)
        self.assertEqual(decision.ranking, tuple(ranking))

    def test_model_loader_and_sparse_decision_value(self):
        payload = {
            "protocol": PROTOCOL,
            "tokenizer_version": TOKENIZER_VERSION,
            "dimensions": DIMENSIONS,
            "weights": [0.0] * DIMENSIONS,
            "intercept": 0.75,
            "threshold": 1.25,
            "selected_c": 1.0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            model = load_model(path)
        self.assertEqual(model.decision_value(("A",), ("B",)), 0.75)
        self.assertEqual(model.threshold, 1.25)


if __name__ == "__main__":
    unittest.main()
