import unittest

from scripts.run_reference_progression_pilot import baseline_candidate, summarize


def row(observed, candidates, progression=None, group="g1"):
    return {
        "observed_candidate_key": observed,
        "progression_candidate_key": progression,
        "structure_group": group,
        "candidates": [
            {"candidate_key": key, "kind": kind, "exact_peer_support": support}
            for key, kind, support in candidates
        ],
    }


class ReferenceProgressionPilotTests(unittest.TestCase):
    def test_baseline_ties_use_content_not_candidate_position(self):
        candidates = (("a", "observed", 0), ("b", "peer", 0))
        forward = row("a", candidates)
        reverse = row("a", tuple(reversed(candidates)))
        self.assertEqual(baseline_candidate(forward, {}), "b")
        self.assertEqual(baseline_candidate(reverse, {}), "b")

    def test_summary_counts_rescues_and_harms(self):
        rows = [
            row("a", (("a", "observed", 0), ("b", "peer", 1)), progression="a"),
            row("c", (("c", "observed", 1), ("d", "peer", 0)), progression="d"),
            row("e", (("e", "observed", 2), ("f", "peer", 0))),
        ]
        metrics = summarize(rows, {})
        self.assertEqual(metrics["rescues"], 1)
        self.assertEqual(metrics["harms"], 1)
        self.assertEqual(metrics["net_rescues"], 0)
        self.assertEqual(metrics["changed_decisions"], 2)


if __name__ == "__main__":
    unittest.main()
