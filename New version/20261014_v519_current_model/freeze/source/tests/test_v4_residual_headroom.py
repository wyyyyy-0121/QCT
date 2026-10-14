import json
import tempfile
import unittest
from pathlib import Path

from scripts.analyze_v4_residual_headroom import (
    CHANNELS,
    build_receipt,
    forced_channel_top1_hit,
    load_events,
    retained_or_replaced_hit,
    source_hit,
    structure_macro,
    v4_cells,
)


def event(
    event_id: str,
    group: str,
    source: str,
    v4: list[str],
    peer: list[str],
) -> dict[str, object]:
    reviews = {channel: [] for channel in CHANNELS}
    reviews["peer"] = peer
    return {
        "event_id": event_id,
        "case_kind": "error",
        "cohort": "enron",
        "structure_group": group,
        "source_formula_cells": [source],
        "v4_rank": v4,
        "review_cells": reviews,
    }


class V4ResidualHeadroomTests(unittest.TestCase):
    def test_optional_replacement_recovers_miss_and_retains_fifth_place_hit(self):
        recovered = event(
            "e1", "g1", "S!P1",
            ["S!A1", "S!B1", "S!C1", "S!D1", "S!E1"],
            ["S!P1"],
        )
        retained = event(
            "e2", "g2", "S!E1",
            ["S!A1", "S!B1", "S!C1", "S!D1", "S!E1"],
            ["S!P1"],
        )
        self.assertEqual(retained_or_replaced_hit(recovered, ("peer",)), 1)
        self.assertEqual(retained_or_replaced_hit(retained, ("peer",)), 1)
        self.assertEqual(forced_channel_top1_hit(retained, "peer"), 0)

    def test_fixed_budget_oracle_equals_union_for_binary_top5_hit(self):
        row = event(
            "e1", "g1", "S!P1",
            ["S!A1", "S!B1", "S!C1", "S!D1", "S!E1"],
            ["S!P1", "S!Q1"],
        )
        union_hit = source_hit(row, v4_cells(row) + ["S!P1", "S!Q1"])
        self.assertEqual(retained_or_replaced_hit(row, ("peer",)), union_hit)

    def test_structure_macro_weights_groups_equally(self):
        rows = [
            event("e1", "g1", "S!A1", ["S!A1"], []),
            event("e2", "g1", "S!Z1", ["S!A1"], []),
            event("e3", "g2", "S!Z1", ["S!A1"], []),
        ]
        score = structure_macro(rows, lambda row: source_hit(row, v4_cells(row)))
        self.assertAlmostEqual(score, 0.25)

    def test_receipt_marks_revealed_result_and_zero_protected_inputs(self):
        rows = [
            event(
                "e1", "g1", "S!P1",
                ["S!A1", "S!B1", "S!C1", "S!D1", "S!E1"],
                ["S!P1"],
            )
        ]
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            receipt = build_receipt(load_events(path), path)
        self.assertTrue(receipt["evidence_role"]["revealed_development_labels_used"])
        self.assertFalse(receipt["evidence_role"]["deployable_model_result"])
        self.assertEqual(receipt["evidence_role"]["protected_data_inputs"], [])

    def test_duplicate_event_ids_fail_closed(self):
        row = event("e1", "g1", "S!A1", ["S!A1"], [])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
            with self.assertRaisesRegex(ValueError, "duplicate event_id"):
                load_events(path)


if __name__ == "__main__":
    unittest.main()
