import unittest

from scripts.audit_v4_peer_allocator_crossfit import MODELS, choose_model


def rows(model: str, gains: dict[int, int], losses: dict[int, int]):
    output = []
    for fold in range(5):
        for index in range(20):
            gain = index < gains.get(fold, 0)
            loss = not gain and index < gains.get(fold, 0) + losses.get(fold, 0)
            output.append({
                "event_id": f"{model}_{fold}_{index}",
                "structure_group": f"g_{fold}_{index}",
                "fold": fold,
                "cohort": "enron",
                "v4_top5": int(not gain),
                "candidate_top5": int(not loss),
                "v4_mrr": 0.5,
                "candidate_mrr": 0.5,
            })
    return output


class V4PeerAllocatorCrossfitTests(unittest.TestCase):
    def test_outer_fold_is_excluded_from_architecture_selection(self):
        model_rows = {model: rows(model, {}, {}) for model in MODELS}
        model_rows["guarded_fifth"] = rows("guarded_fifth", {0: 20}, {})
        model_rows["evidence_allocator"] = rows(
            "evidence_allocator", {1: 3, 2: 3, 3: 3, 4: 3}, {},
        )
        selected, _metrics = choose_model(model_rows, outer_fold=0)
        self.assertEqual(selected, "evidence_allocator")

    def test_training_loss_constraint_rejects_higher_gain_model(self):
        model_rows = {model: rows(model, {}, {}) for model in MODELS}
        model_rows["guarded_fifth"] = rows(
            "guarded_fifth", {1: 2, 2: 2, 3: 2, 4: 2}, {},
        )
        model_rows["evidence_allocator"] = rows(
            "evidence_allocator", {1: 5, 2: 5, 3: 5, 4: 5}, {1: 2},
        )
        selected, _metrics = choose_model(model_rows, outer_fold=0)
        self.assertEqual(selected, "guarded_fifth")


if __name__ == "__main__":
    unittest.main()
