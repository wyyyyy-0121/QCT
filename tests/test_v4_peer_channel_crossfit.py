import unittest

from scripts.audit_v4_peer_channel_crossfit import CHANNELS, choose_channel


def rows(channel: str, gains: dict[int, int], losses: dict[int, int]):
    output = []
    for fold in range(5):
        for index in range(10):
            gain = index < gains.get(fold, 0)
            loss = not gain and index < gains.get(fold, 0) + losses.get(fold, 0)
            output.append({
                "event_id": f"{channel}_{fold}_{index}",
                "structure_group": f"g_{fold}_{index}",
                "fold": fold,
                "cohort": "enron",
                "v4_top5": int(not gain),
                "candidate_top5": int(not loss),
                "v4_mrr": 0.5,
                "candidate_mrr": 0.5,
            })
    return output


class V4PeerChannelCrossfitTests(unittest.TestCase):
    def test_outer_fold_is_excluded_from_channel_selection(self):
        channel_rows = {
            channel: rows(channel, {}, {}) for channel in CHANNELS
        }
        channel_rows["peer"] = rows("peer", {0: 10}, {})
        channel_rows["role"] = rows("role", {1: 3, 2: 3, 3: 3, 4: 3}, {})
        selected, _metrics = choose_channel(channel_rows, outer_fold=0)
        self.assertEqual(selected, "role")

    def test_training_loss_constraint_rejects_unsafe_channel(self):
        channel_rows = {
            channel: rows(channel, {}, {}) for channel in CHANNELS
        }
        channel_rows["peer"] = rows("peer", {1: 4, 2: 4, 3: 4, 4: 4}, {1: 1})
        channel_rows["role"] = rows("role", {1: 2, 2: 2, 3: 2, 4: 2}, {})
        selected, _metrics = choose_channel(channel_rows, outer_fold=0)
        self.assertEqual(selected, "role")


if __name__ == "__main__":
    unittest.main()
