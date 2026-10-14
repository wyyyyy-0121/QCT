import unittest

from scripts.run_v4_peer_fifth_public_revisions import summarize_rows


class V4PeerFifthPublicRevisionTests(unittest.TestCase):
    def test_summary_is_workbook_macro_and_requires_a_recovery(self):
        rows = [
            {
                "workbook_id": "a",
                "v4_top5": 0,
                "candidate_top5": 1,
                "v4_mrr": 0.1,
                "candidate_mrr": 0.2,
            },
            {
                "workbook_id": "a",
                "v4_top5": 1,
                "candidate_top5": 1,
                "v4_mrr": 0.5,
                "candidate_mrr": 0.5,
            },
            {
                "workbook_id": "b",
                "v4_top5": 1,
                "candidate_top5": 1,
                "v4_mrr": 1.0,
                "candidate_mrr": 1.0,
            },
        ]
        summary = summarize_rows(rows)
        self.assertAlmostEqual(summary["v4_top5"], 0.75)
        self.assertEqual(summary["candidate_top5"], 1.0)
        self.assertEqual(summary["recovered_events"], 1)
        self.assertTrue(summary["confirmation_passed"])

    def test_no_change_does_not_count_as_confirmation(self):
        rows = [{
            "workbook_id": "a",
            "v4_top5": 1,
            "candidate_top5": 1,
            "v4_mrr": 1.0,
            "candidate_mrr": 1.0,
        }]
        summary = summarize_rows(rows)
        self.assertFalse(summary["gates"]["at_least_one_v4_miss_recovered"])
        self.assertFalse(summary["confirmation_passed"])


if __name__ == "__main__":
    unittest.main()
