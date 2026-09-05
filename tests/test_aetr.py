import unittest

from formulaguard.aetr import (
    AETR_VIEWS,
    VIEW_ORDER,
    ranking_from_model,
    workbook_feature_maps,
)
from formulaguard.v4_rrc import ATOMIC_NUMERIC, fit_ridge
from scripts.run_aetr_crossfit import (
    LOCO_COHORTS,
    AETRUnit,
    _gates,
    training_examples,
)


def atomic_audit() -> dict[str, object]:
    cells = [f"S!A{index}" for index in range(1, 7)]
    rankings = {
        "peer": cells,
        "combined": [cells[1], cells[0], *cells[2:]],
        "role": [cells[2], cells[0], cells[1], *cells[3:]],
        "impact": list(reversed(cells)),
    }
    rank_records = {
        channel: [
            {"cell": cell, "rank": rank, "score": 1.0 / rank}
            for rank, cell in enumerate(ranking, start=1)
        ]
        for channel, ranking in rankings.items()
    }
    records = []
    for index, cell in enumerate(cells, start=1):
        record = {
            name: float(index)
            for name in ATOMIC_NUMERIC
            if not name.startswith("peer_count_")
        }
        record.update({
            "cell": cell,
            "peer_counts": {
                "row": 1,
                "column": 2,
                "local": 3,
                "role": 4,
            },
            "status": "evidence_supported" if index == 1 else "unsupported",
        })
        records.append(record)
    return {
        "formula_count": 6,
        "parseable_formula_count": 6,
        "visible_formula_count": 6,
        "unsupported_formula_count": 0,
        "region_count": 3,
        "rankings": rankings,
        "rank_records": rank_records,
        "records": records,
        "label_inputs": [],
    }


def unit(group: str, *, source: str = "S!A1") -> AETRUnit:
    audit = atomic_audit()
    inventory, features = workbook_feature_maps(audit)
    return AETRUnit(
        unit_id=f"unit:{group}",
        structure_group=group,
        fold=0,
        cohort="enron",
        events=({
            "event_id": f"event:{group}",
            "case_kind": "error",
            "source_formula_cells": [source],
        },),
        audit=audit,
        inventory=inventory,
        features=features,
    )


class AETRTests(unittest.TestCase):
    def test_atomic_features_are_complete_and_exclude_v4(self):
        inventory, features = workbook_feature_maps(atomic_audit())
        self.assertEqual(len(inventory), 6)
        full = AETR_VIEWS["full"]
        self.assertEqual(
            set(features[inventory[0]]),
            {*full.continuous, *full.discrete},
        )
        self.assertFalse(any(
            name.startswith("v4_") or "candidate_minus_fifth" in name
            for name in features[inventory[0]]
        ))
        self.assertEqual(tuple(AETR_VIEWS), VIEW_ORDER)

    def test_group_balanced_weights_split_each_unit_between_classes(self):
        rows, targets, weights, audit = training_examples(
            [unit("g1"), unit("g2")],
            "full",
        )
        self.assertEqual(len(rows), 12)
        self.assertAlmostEqual(sum(weights), 2.0)
        self.assertAlmostEqual(
            sum(weight for target, weight in zip(targets, weights) if target == 1.0),
            1.0,
        )
        self.assertAlmostEqual(
            sum(weight for target, weight in zip(targets, weights) if target == 0.0),
            1.0,
        )
        self.assertEqual(audit["structure_groups"], 2)

    def test_formula_micro_ablation_preserves_total_weight_scale(self):
        _, _, weights, audit = training_examples(
            [unit("g1"), unit("g2")],
            "formula_micro_weighting",
        )
        self.assertAlmostEqual(sum(weights), 2.0)
        self.assertEqual(len(set(weights)), 1)
        self.assertEqual(audit["weighting"], "formula_micro")

    def test_model_ranking_is_complete_and_deterministic(self):
        audit = atomic_audit()
        inventory, features = workbook_feature_maps(audit)
        view = AETR_VIEWS["full"]
        model = fit_ridge(
            [features[cell] for cell in inventory],
            [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            [1.0] * len(inventory),
            continuous_features=view.continuous,
            binary_features=view.discrete,
        )
        first, scores = ranking_from_model(model, audit, inventory, features)
        second, _ = ranking_from_model(model, audit, inventory, features)
        self.assertEqual(first, second)
        self.assertEqual(set(first), set(inventory))
        self.assertTrue(all(cell in scores for cell in inventory))

    def test_public_gates_match_preregistered_boundaries(self):
        cohort_summary = {
            name: {"top5_difference": 0.05, "mrr_difference": 0.0}
            for name in LOCO_COHORTS
        }
        summary = {
            "top5_difference": 0.05,
            "mrr_difference": 0.0,
            "by_cohort": cohort_summary,
        }
        folds = [
            {"test_summary": {"top5_difference": value}}
            for value in (0.01, 0.0, 0.02, 0.03, -0.01)
        ]
        loco = {
            name: {"summary": {"top5_difference": 0.05, "mrr_difference": 0.0}}
            for name in LOCO_COHORTS
        }
        gates = _gates(summary, folds, {"ci95_delta_pp": [0.01, 8.0]}, loco)
        self.assertTrue(all(gates.values()))
        loco["enron"]["summary"]["mrr_difference"] = -0.001
        gates = _gates(summary, folds, {"ci95_delta_pp": [0.01, 8.0]}, loco)
        self.assertFalse(gates["leave_enron_out_mrr_nonnegative"])


if __name__ == "__main__":
    unittest.main()
