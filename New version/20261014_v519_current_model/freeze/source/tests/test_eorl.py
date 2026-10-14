import json
import tempfile
import unittest
from pathlib import Path

from formulaguard.eorl import (
    residual,
    select_output_task,
    source_formula_descendants,
    source_repair_recoverability,
)
from formulaguard.workbook import WorkbookModel
from scripts.audit_eorl_d0 import _validate_prediction_task
from scripts.run_model_discovery_signals import stable_hash
from scripts.verify_eorl_d0_reproduction import verify


def pair():
    cells = {
        ("Model", "A1"): 2,
        ("Model", "B1"): 3,
        ("Model", "A2"): 4,
        ("Model", "B2"): 5,
        ("Model", "A3"): 6,
        ("Model", "B3"): 7,
    }
    observed = WorkbookModel.from_cells(cells, {
        ("Model", "C1"): "=A1+B1",
        ("Model", "C2"): "=A2-B2",
        ("Model", "C3"): "=A3+B3",
        ("Model", "D1"): "=SUM(C1:C3)",
        ("Model", "E1"): "=D1*2",
    })
    reference = WorkbookModel.from_cells(cells, {
        ("Model", "C1"): "=A1+B1",
        ("Model", "C2"): "=A2+B2",
        ("Model", "C3"): "=A3+B3",
        ("Model", "D1"): "=SUM(C1:C3)",
        ("Model", "E1"): "=D1*2",
    })
    return observed, reference


class EorlTests(unittest.TestCase):
    def test_error_output_is_affected_sink_with_largest_cone(self):
        observed, reference = pair()
        task = select_output_task(
            observed,
            reference,
            case_kind="error",
            source_formula_cells=[("Model", "C2")],
        )
        self.assertTrue(task["eligible"])
        self.assertEqual(task["output_cell"], "Model!E1")
        self.assertEqual(task["cone_formula_count"], 5)
        self.assertGreater(task["base_residual"], 0.0)

    def test_control_requires_matching_reference_output(self):
        _, reference = pair()
        task = select_output_task(
            reference,
            reference,
            case_kind="control",
            source_formula_cells=[],
        )
        self.assertTrue(task["eligible"])
        self.assertEqual(task["output_cell"], "Model!E1")
        self.assertEqual(task["base_residual"], 0.0)

    def test_source_peer_repair_reduces_expected_output_residual(self):
        observed, reference = pair()
        expected, errors = reference.evaluate()
        self.assertFalse(errors)
        result = source_repair_recoverability(
            observed,
            output_cell=("Model", "E1"),
            expected_value=expected[("Model", "E1")],
            source_formula_cells=[("Model", "C2")],
            records_by_cell={
                "Model!C2": {
                    "repair_hypotheses": [
                        {"formula": "=A2+B2", "support_count": 2},
                        {"formula": "=A2*B2", "support_count": 1},
                    ],
                },
            },
        )
        self.assertTrue(result["residually_recoverable"])
        self.assertEqual(result["best"]["formula"], "=A2+B2")
        self.assertEqual(result["best"]["residual"], 0.0)

    def test_residual_is_scale_normalized(self):
        self.assertEqual(residual(8, 10), 0.2)
        self.assertEqual(residual(0.25, 0.5), 0.25)

    def test_source_formula_descendants_excludes_nonformula_dependents(self):
        observed, _ = pair()
        result = source_formula_descendants(observed, [("Model", "C2")])
        self.assertEqual(result["source_formula_count"], 1)
        self.assertEqual(result["sources_with_formula_descendants"], 1)
        self.assertEqual(result["formula_descendants"], ["Model!D1", "Model!E1"])

    def test_source_formula_descendants_rejects_nonformula_source(self):
        observed, _ = pair()
        with self.assertRaisesRegex(ValueError, "not formulas"):
            source_formula_descendants(observed, [("Model", "A1")])

    def test_prediction_task_rejects_scoring_label(self):
        task = {
            "inference_fields": ["workbook_path", "output_cell", "expected_value"],
            "label_inputs_to_prediction": [],
            "source_formula_cells": ["Model!C2"],
        }
        with self.assertRaisesRegex(ValueError, "scoring fields"):
            _validate_prediction_task(task)

    def test_reproduction_requires_byte_identical_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directories = [root / "a", root / "b"]
            receipt = {
                "protocol": "formulaguard_eorl_d0_v1",
                "eorl_protocol": "formulaguard_eorl_v1",
                "pre_reproduction_gates": {
                    "mechanism": True,
                    "protected_and_forbidden_inputs_absent": True,
                },
                "summary": {"eligible_error_events": 40},
                "protected_data_inputs": [],
                "label_inputs_to_prediction": [],
            }
            receipt["receipt_sha256"] = stable_hash(receipt)
            for directory in directories:
                directory.mkdir()
                for name in ("tasks.jsonl", "scoring.jsonl", "cross_engine.jsonl"):
                    (directory / name).write_text("{}\n", encoding="utf-8")
                (directory / "receipt.json").write_text(
                    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            result_path = verify(directories[0], directories[1], root / "reproduction.json")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertTrue(result["d0_passed"])
            self.assertTrue(result["gates"]["independent_process_byte_identical"])


if __name__ == "__main__":
    unittest.main()
