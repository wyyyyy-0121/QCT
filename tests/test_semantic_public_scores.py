import copy
import math
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import torch

from formulaguard.semantic_compatibility import FormulaVocabulary
from scripts import extract_semantic_public_scores as public_scores
from scripts.extract_semantic_public_scores import (
    PROTOCOL,
    _candidate_tensors,
    _process_profile,
    _split_cell_key,
    _validate_score_shard,
)


class SemanticPublicScoreTests(unittest.TestCase):
    def valid_shard(self):
        profile = {"unit_id": "u", "workbook_sha256": "a" * 64}
        row = {
            "cell": "S!A1",
            "v4_rank": 1,
            "candidate_count": 2,
            "semantic_anomaly_margin": 0.5,
            "semantic_anomaly_confidence": 0.5,
            "semantic_decision_margin": 0.5,
            "semantic_observed_score": 0.1,
            "semantic_best_alternative_score": 0.6,
            "semantic_prefers_alternative": True,
            "fallback_role": False,
        }
        payload = {
            "protocol": PROTOCOL,
            **profile,
            "v4_scope_cells": 1,
            "scored_cells": 1,
            "skipped_invisible": 0,
            "skipped_without_alternatives": 0,
            "scores": [row],
            "label_inputs": [],
            "raw_formula_strings_persisted": False,
            "formula_roles_persisted": False,
        }
        return profile, payload

    def test_cell_parser_uses_last_sheet_separator(self):
        self.assertEqual(_split_cell_key("SEPT 01 !AA35"), ("SEPT 01 ", "AA35"))

    def test_candidate_tensor_batch_masks_ragged_roles(self):
        vocabulary = FormulaVocabulary(("<PAD>", "<UNK>", "<START>", "<END>", "A", "B"))
        records = [
            {"candidate_roles": ("A", "B")},
            {"candidate_roles": ("A",)},
        ]
        tokens, lengths, mask = _candidate_tensors(records, vocabulary, torch.device("cpu"))
        self.assertEqual(tuple(tokens.shape[:2]), (2, 2))
        self.assertEqual(tuple(lengths.shape), (2, 2))
        self.assertEqual(mask.tolist(), [[True, True], [True, False]])

    def test_score_shard_rejects_formula_roles(self):
        profile, payload = self.valid_shard()
        _validate_score_shard(payload, profile, ("S!A1",))
        payload["scores"][0]["observed_role"] = "forbidden"
        with self.assertRaisesRegex(ValueError, "row is invalid"):
            _validate_score_shard(payload, profile, ("S!A1",))

    def test_score_shard_rejects_non_finite_and_inconsistent_scores(self):
        profile, payload = self.valid_shard()
        for field, value in (
            ("semantic_anomaly_margin", math.inf),
            ("semantic_anomaly_confidence", math.nan),
            ("semantic_decision_margin", -math.inf),
            ("semantic_observed_score", math.nan),
            ("semantic_best_alternative_score", -math.inf),
            ("semantic_anomaly_margin", 0.4),
            ("semantic_anomaly_confidence", 0.4),
            ("semantic_decision_margin", 0.4),
            ("semantic_prefers_alternative", False),
        ):
            invalid = copy.deepcopy(payload)
            invalid["scores"][0][field] = value
            with self.subTest(field=field, value=value), self.assertRaisesRegex(
                ValueError, "row is invalid"
            ):
                    _validate_score_shard(invalid, profile, ("S!A1",))

    def test_multi_candidate_decision_margin_can_be_smaller_than_raw_margin(self):
        profile, payload = self.valid_shard()
        payload["scores"][0].update({
            "candidate_count": 3,
            "semantic_anomaly_confidence": 0.2,
            "semantic_decision_margin": 0.2,
        })
        _validate_score_shard(payload, profile, ("S!A1",))

    def test_score_shard_binds_cell_to_frozen_v4_rank(self):
        profile, payload = self.valid_shard()
        payload["scores"][0]["cell"] = "S!B1"
        with self.assertRaisesRegex(ValueError, "row is invalid"):
            _validate_score_shard(payload, profile, ("S!A1",))

    def test_score_shard_requires_complete_scope_accounting(self):
        profile, payload = self.valid_shard()
        payload["skipped_without_alternatives"] = 1
        with self.assertRaisesRegex(ValueError, "shard is invalid"):
            _validate_score_shard(payload, profile, ("S!A1",))

    def test_invisible_v4_formula_is_counted_without_context_encoding(self):
        model = SimpleNamespace(
            formulas={("S", "A1"): "=1"},
            is_visible=lambda _key: False,
        )
        profile = {"unit_id": "u", "workbook_sha256": "a" * 64, "path": "unused"}
        with (
            mock.patch.object(public_scores, "_TOKENIZER_RUNTIME", object()),
            mock.patch.object(public_scores.WorkbookModel, "from_xlsx", return_value=model),
        ):
            result = _process_profile(profile, ("S!A1",))
        self.assertEqual(result["skipped_invisible"], 1)
        self.assertEqual(result["skipped_without_alternatives"], 0)
        self.assertEqual(result["batches"], [])

    def test_script_runs_directly_outside_repository(self):
        script = Path(__file__).resolve().parents[1] / "scripts/extract_semantic_public_scores.py"
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
