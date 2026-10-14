from __future__ import annotations

import unittest

from scripts.audit_fspr_public_v4_baseline import compare_frozen_v4


def _frozen(workbook_hash: str, cells: list[str]) -> dict[str, object]:
    return {
        "workbook_sha256": workbook_hash,
        "ranking": [{"cell": cell} for cell in cells],
    }


def _prediction(
    workbook_hash: str,
    v4: list[str],
    fspr: list[str],
) -> dict[str, object]:
    return {
        "unit_id": f"observed-workbook:{workbook_hash}",
        "workbook_sha256": workbook_hash,
        "cohort": "enron",
        "v4_ranking": v4,
        "fspr_ranking": fspr,
    }


class FSPRPublicV4AuditTests(unittest.TestCase):
    def test_detects_full_ranking_drift_outside_prefix(self):
        frozen = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A5", "S!A6"]
        embedded = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A6", "S!A5"]
        rows, summary = compare_frozen_v4(
            [_prediction("abc", embedded, embedded)],
            {"abc": _frozen("abc", frozen)},
        )
        self.assertFalse(rows[0]["embedded_v4_full_match"])
        self.assertTrue(rows[0]["embedded_v4_prefix_match"])
        self.assertEqual(rows[0]["first_embedded_v4_difference_rank"], 5)
        self.assertEqual(summary["embedded_v4_full_mismatches"], 1)
        self.assertEqual(summary["embedded_v4_prefix_mismatches"], 0)

    def test_detects_frozen_prefix_violation_and_preserves_inventory(self):
        frozen = ["S!A1", "S!A2", "S!A3", "S!A4", "S!A5", "S!A6"]
        embedded = ["S!A2", "S!A1", "S!A3", "S!A4", "S!A5", "S!A6"]
        rows, summary = compare_frozen_v4(
            [_prediction("abc", embedded, embedded)],
            {"abc": _frozen("abc", frozen)},
        )
        self.assertTrue(rows[0]["formula_inventory_match"])
        self.assertFalse(rows[0]["embedded_v4_prefix_match"])
        self.assertFalse(rows[0]["fspr_frozen_prefix_match"])
        self.assertEqual(summary["embedded_v4_prefix_mismatches"], 1)
        self.assertEqual(summary["fspr_frozen_prefix_mismatches"], 1)


if __name__ == "__main__":
    unittest.main()
