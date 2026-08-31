import unittest
from pathlib import Path

from scripts.run_v4_static_fifth_blind import (
    METHODS,
    _validate_method_inventory,
    score_rows,
    verify_candidate_lock,
)


ROOT = Path(__file__).resolve().parents[1]


class V4StaticFifthBlindTests(unittest.TestCase):
    def test_prediction_method_inventory_is_order_independent(self):
        methods = {name: {} for name in reversed(METHODS)}
        self.assertEqual(_validate_method_inventory(methods, "test.json"), methods)

    def test_frozen_candidate_lock_matches_implementation_and_public_predictions(self):
        payload = verify_candidate_lock(
            ROOT / "research" / "V4_STATIC_FIFTH_CANDIDATE_LOCK.json"
        )
        self.assertTrue(payload["candidate_locked"])
        self.assertIsNone(payload["formal_version"])

    def test_score_rows_uses_equal_budget_and_paired_recovery(self):
        cases = []
        predictions = _Predictions()
        for template in range(30):
            for index in range(8):
                instance = f"e_{template}_{index}"
                cases.append({
                    "instance_id": instance,
                    "template_id": f"t{template}",
                    "case_kind": "error",
                    "error_type": "copy_offset",
                    "identifiability": "identifiable",
                    "source_cells": "S!A6",
                })
                predictions.add(instance, v4_rank=6, static_rank=4, candidate_rank=5)
            for index in range(4):
                instance = f"c_{template}_{index}"
                cases.append({
                    "instance_id": instance,
                    "template_id": f"t{template}",
                    "case_kind": "control",
                    "error_type": "",
                    "identifiability": "",
                    "source_cells": "",
                })
                predictions.add(instance, v4_rank=6, static_rank=4, candidate_rank=5)
        with predictions:
            summary, rows = score_rows(cases, predictions.path)
        self.assertEqual(len(rows), 240)
        self.assertEqual(summary["review_budget_per_workbook"], 5)
        self.assertEqual(summary["recovered_events"], 240)
        self.assertEqual(summary["lost_events"], 0)
        self.assertEqual(summary["control_extra_review_cost_vs_v4"], 0)
        self.assertTrue(summary["promotion_allowed"])


class _Predictions:
    def __init__(self):
        import tempfile
        from pathlib import Path

        self._temporary = tempfile.TemporaryDirectory()
        self.path = Path(self._temporary.name)
        (self.path / "shards").mkdir()

    def add(self, instance, *, v4_rank, static_rank, candidate_rank):
        import json

        def ranking(source_rank):
            cells = [f"S!A{i}" for i in range(1, 8)]
            cells.remove("S!A6")
            cells.insert(source_rank - 1, "S!A6")
            return [{"rank": rank, "cell": cell} for rank, cell in enumerate(cells, 1)]

        payload = {
            "changed": True,
            "methods": {
                "v4_r1": {"ranking": ranking(v4_rank)},
                "static_anchor": {"ranking": ranking(static_rank)},
                "v4_static_fifth": {"ranking": ranking(candidate_rank)},
            },
        }
        (self.path / "shards" / f"{instance}.json").write_text(json.dumps(payload))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
