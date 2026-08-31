import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import torch

from formulaguard.semantic_compatibility import (
    FormulaVocabulary,
    canonical_formula_role,
    pad_token_ids,
    role_tokens,
    semantic_candidate_roles,
)
from formulaguard.semantic_compatibility_torch import SemanticCompatibilityHead
from formulaguard.workbook import WorkbookModel
from scripts.build_semantic_compatibility_corpus import PROTOCOL, _validate_shard


class SemanticFormulaRoleTests(unittest.TestCase):
    def test_supported_roles_are_relative_and_literal_free(self):
        first = canonical_formula_role("=SUM(A1:A3)+2", "B4", "Sheet")
        second = canonical_formula_role("=SUM(C7:C9)+99", "D10", "Sheet")
        self.assertEqual(first, second)
        self.assertNotIn("99", second)

    def test_fallback_handles_unsupported_functions_and_strings(self):
        role = canonical_formula_role('=MEDIAN(A1:A3)+IF(B1="ok",7,9)', "B4", "Sheet")
        self.assertIn("MEDIAN", role)
        self.assertIn("STR", role)
        self.assertIn("SELF!R[-3]C[-1]", role)
        self.assertNotIn('"ok"', role)
        self.assertNotIn("7", role)

    def test_vocabulary_is_deterministic_and_bounds_unknowns(self):
        roles = ["FSUM(SELF!R[-1]C[+0])", "FMAX(SELF!R[-1]C[+0])"]
        first = FormulaVocabulary.build(roles, minimum_count=1)
        second = FormulaVocabulary.build(reversed(roles), minimum_count=1)
        self.assertEqual(first, second)
        encoded = first.encode("FUNSEEN(OTHER!R1C1)")
        self.assertEqual(encoded[0], first.token_to_id["<START>"])
        self.assertIn(first.token_to_id["<UNK>"], encoded)

    def test_role_tokenizer_preserves_relative_reference(self):
        self.assertIn("SELF!R[-1]C[+0]", role_tokens("FSUM(SELF!R[-1]C[+0])"))

    def test_candidate_roles_translate_axis_peers_to_target(self):
        cells = {
            ("Sheet", f"{column}{row}"): row
            for column in ("A", "B", "C")
            for row in range(1, 6)
        }
        workbook = WorkbookModel.from_cells(cells, {
            ("Sheet", "C2"): "=A2+B2",
            ("Sheet", "C3"): "=A3-B3",
            ("Sheet", "C4"): "=A4+B4",
        })
        roles = semantic_candidate_roles(workbook, ("Sheet", "C3"))
        expected = canonical_formula_role("=A3+B3", "C3", "Sheet")
        self.assertEqual(roles[0], expected)
        self.assertNotIn(
            canonical_formula_role("=A3-B3", "C3", "Sheet"),
            roles,
        )


class SemanticCompatibilityHeadTests(unittest.TestCase):
    def test_contrastive_head_has_finite_gradients(self):
        head = SemanticCompatibilityHead(32, context_size=12, output_size=8)
        context = torch.randn(4, 12)
        token_ids = torch.tensor([
            [2, 4, 3, 0],
            [2, 5, 3, 0],
            [2, 4, 6, 3],
            [2, 7, 3, 0],
        ])
        lengths = torch.tensor([3, 3, 4, 3])
        role_ids = torch.tensor([0, 1, 0, 2])
        loss = head.contrastive_loss(context, token_ids, lengths, role_ids)
        self.assertTrue(torch.isfinite(loss))
        loss.backward()
        self.assertTrue(all(
            parameter.grad is not None and torch.isfinite(parameter.grad).all()
            for parameter in head.parameters()
        ))

    def test_padding_helper_returns_lengths(self):
        rows, lengths = pad_token_ids(((1, 2), (3,)))
        self.assertEqual(rows, [[1, 2], [3, 0]])
        self.assertEqual(lengths, [2, 1])


class SemanticCorpusEntrypointTests(unittest.TestCase):
    def test_shard_without_visible_formulas_is_valid(self):
        source = {
            "workbook_id": "fcrl-wb:empty",
            "source_sha256": hashlib.sha256(b"empty").hexdigest(),
            "structure_group": "template-group:empty",
            "split": "calibration",
        }
        payload = {
            "protocol": PROTOCOL,
            **source,
            "selected_targets": 0,
            "targets": [],
            "raw_cell_text_persisted": False,
            "raw_numeric_values_persisted": False,
            "raw_formula_strings_persisted": False,
            "fault_labels_read": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty.json"
            path.write_text(json.dumps(payload), encoding="ascii")
            self.assertEqual(_validate_shard(path, source), payload)

    def test_corpus_builder_runs_directly_outside_repository(self):
        script = Path(__file__).resolve().parents[1] / "scripts/build_semantic_compatibility_corpus.py"
        completed = subprocess.run(
            (sys.executable, str(script), "--help"),
            cwd="/tmp",
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("--workers", completed.stdout)


if __name__ == "__main__":
    unittest.main()
