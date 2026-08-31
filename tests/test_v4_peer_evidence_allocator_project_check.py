import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_v4_peer_evidence_allocator_project_check import (
    METHODS,
    score_rows,
    verify_candidate_lock,
)


ROOT = Path(__file__).resolve().parents[1]


class V4PeerEvidenceAllocatorProjectCheckTests(unittest.TestCase):
    def test_frozen_candidate_lock_matches_implementation(self):
        payload = verify_candidate_lock(
            ROOT / "research/V4_PEER_EVIDENCE_ALLOCATOR_PROJECT_CHECK_LOCK.json"
        )
        self.assertTrue(payload["candidate_locked"])
        self.assertIsNone(payload["formal_version"])

    def test_saturated_score_is_safety_evidence_not_comparative_improvement(self):
        with _Predictions() as predictions:
            cases = []
            for template in range(30):
                for index in range(8):
                    instance = f"e_{template}_{index}"
                    cases.append({
                        "instance_id": instance,
                        "template_id": f"t{template}",
                        "case_kind": "error",
                        "error_type": "copy_offset",
                        "source_cells": "S!A4",
                    })
                    predictions.add(instance, v4_rank=4, candidate_rank=4)
                for index in range(4):
                    instance = f"c_{template}_{index}"
                    cases.append({
                        "instance_id": instance,
                        "template_id": f"t{template}",
                        "case_kind": "control",
                        "error_type": "",
                        "source_cells": "",
                    })
                    predictions.add(instance, v4_rank=4, candidate_rank=4)
            summary, rows = score_rows(cases, predictions.path)
        self.assertEqual(len(rows), 240)
        self.assertEqual(summary["v4_top5"], 1.0)
        self.assertEqual(summary["candidate_top5"], 1.0)
        self.assertEqual(summary["lost_events"], 0)
        self.assertTrue(summary["safety_check_passed"])
        self.assertFalse(summary["comparative_improvement_established"])

    def test_method_inventory_is_fixed(self):
        self.assertEqual(METHODS, ("v4_r1", "evidence_allocator"))


class _Predictions:
    def __init__(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.path = Path(self._temporary.name)
        (self.path / "shards").mkdir()

    @staticmethod
    def _ranking(source_rank: int):
        cells = [f"S!A{i}" for i in range(1, 8)]
        cells.remove("S!A4")
        cells.insert(source_rank - 1, "S!A4")
        return [{"rank": rank, "cell": cell} for rank, cell in enumerate(cells, 1)]

    def add(self, instance: str, *, v4_rank: int, candidate_rank: int):
        payload = {
            "changed": False,
            "methods": {
                "v4_r1": {"ranking": self._ranking(v4_rank)},
                "evidence_allocator": {"ranking": self._ranking(candidate_rank)},
            },
        }
        (self.path / "shards" / f"{instance}.json").write_text(json.dumps(payload))

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self._temporary.cleanup()


if __name__ == "__main__":
    unittest.main()
