from __future__ import annotations

import unittest

from scripts.run_fspr_public_predictions import (
    PROTOCOL,
    SCHEMA_VERSION,
    stable_hash,
    validate_record,
)
from scripts.score_fspr_public_predictions import _event_metrics, _structure_macro


class FSPRPublicPredictionTests(unittest.TestCase):
    def test_prediction_record_preserves_prefix_and_inventory(self):
        v4 = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A5", "S!A6"]
        fspr = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A6", "S!A5"]
        record = {
            "protocol": PROTOCOL,
            "schema_version": SCHEMA_VERSION,
            "model_sha256": "model",
            "formula_count": len(v4),
            "formula_inventory_sha256": stable_hash(sorted(v4)),
            "v4_ranking": v4,
            "fspr_ranking": fspr,
            "v4_top5": v4[:5],
            "fspr_top5": fspr[:5],
            "fspr_candidate": "S!A6",
            "ranking_changed": True,
            "label_inputs": [],
            "revealed_localization_inputs": [],
            "answer_workbook_inputs": [],
            "task_text_inputs": [],
            "protected_data_inputs": [],
        }
        validate_record(record, "model")

    def test_event_and_structure_metrics_preserve_group_weighting(self):
        rows = [
            {
                "structure_group": "g1",
                "v4_top5": 0,
                "fspr_top5": 1,
                "v4_mrr": 0.1,
                "fspr_mrr": 0.2,
                "rescue": 1,
                "loss": 0,
            },
            {
                "structure_group": "g1",
                "v4_top5": 1,
                "fspr_top5": 1,
                "v4_mrr": 0.5,
                "fspr_mrr": 0.5,
                "rescue": 0,
                "loss": 0,
            },
            {
                "structure_group": "g2",
                "v4_top5": 1,
                "fspr_top5": 0,
                "v4_mrr": 1.0,
                "fspr_mrr": 0.1,
                "rescue": 0,
                "loss": 1,
            },
        ]
        micro = _event_metrics(rows)
        macro = _structure_macro(rows)
        self.assertEqual(micro["net_rescues"], 0)
        self.assertAlmostEqual(micro["top5_delta"], 0.0)
        self.assertAlmostEqual(macro["top5_delta"], -0.25)


if __name__ == "__main__":
    unittest.main()
