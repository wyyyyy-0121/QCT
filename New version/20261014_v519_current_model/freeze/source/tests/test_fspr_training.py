from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.train_fspr import leakage_groups, nearest_higher_quantile, select_c
from scripts.verify_fspr_reproduction import (
    EXPECTED_FILES,
    RECEIPT_HASH_FIELDS,
    ZERO_INPUT_FIELDS,
    sha256_file,
    verify,
)


class FSPRTrainingTests(unittest.TestCase):
    def test_leakage_groups_join_shared_context_and_cross_label_formula(self):
        context_a = {"sheetNames": ["S"], "sheets": {"S": {"cells": {}}}}
        context_b = {"sheetNames": ["T"], "sheets": {"T": {"cells": {}}}}
        context_c = {"sheetNames": ["U"], "sheets": {"U": {"cells": {}}}}
        rows = [
            {"data": context_a, "faulty_formula": "=A1+1", "correct_formula": "=A1"},
            {"data": context_a, "faulty_formula": "=B1+1", "correct_formula": "=B1"},
            {"data": context_b, "faulty_formula": "=C1+1", "correct_formula": "=A1+1"},
            {"data": context_c, "faulty_formula": "=D1+1", "correct_formula": "=D1"},
        ]
        groups, folds = leakage_groups(rows)
        self.assertEqual(groups[0], groups[1])
        self.assertEqual(groups[0], groups[2])
        self.assertNotEqual(groups[0], groups[3])
        self.assertEqual(folds[0], folds[1])
        self.assertEqual(folds[0], folds[2])

    def test_nearest_higher_quantile_is_fixed(self):
        self.assertEqual(nearest_higher_quantile([1, 2, 3, 4, 5], 0.9), 5)
        self.assertEqual(nearest_higher_quantile([1, 2, 3, 4], 0.5), 2)

    def test_c_selection_uses_preregistered_tie_order(self):
        rows = [
            {"c": 0.1, "pairwise_accuracy": 0.8},
            {"c": 1.0, "pairwise_accuracy": 0.8},
            {"c": 10.0, "pairwise_accuracy": 0.8},
        ]
        self.assertEqual(select_c(rows), 1.0)

    def test_reproduction_requires_byte_identical_passing_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runs = [root / "a", root / "b"]
            for run in runs:
                run.mkdir()
                for name in EXPECTED_FILES - {"label_free_receipt.json"}:
                    (run / name).write_text(
                        json.dumps({"name": name}, sort_keys=True) + "\n",
                        encoding="ascii",
                    )
                receipt = {
                    "protocol": "formulaguard_fspr_label_free_gate_v1",
                    "complete": True,
                    "gates": {"all_single_process_gates_passed": True},
                    **{
                        field: sha256_file(run / artifact)
                        for artifact, field in RECEIPT_HASH_FIELDS.items()
                    },
                    **{field: [] for field in ZERO_INPUT_FIELDS},
                }
                (run / "label_free_receipt.json").write_text(
                    json.dumps(receipt, sort_keys=True) + "\n",
                    encoding="ascii",
                )
            result = verify(runs[0], runs[1], root / "verified")
        self.assertTrue(result["all_label_free_gates_passed"])

    def test_reproduction_rejects_one_directory_as_two_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "distinct run directories"):
                verify(root, root, root / "verified")


if __name__ == "__main__":
    unittest.main()
