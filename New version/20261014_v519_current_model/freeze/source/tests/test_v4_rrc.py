import unittest

import numpy as np

from formulaguard.v4_rrc import (
    MODEL_FEATURES,
    candidate_feature_map,
    fit_ridge,
    guarded_candidate,
    peer_candidates,
    rerank,
    residual_utility,
    structure_fold,
)
from scripts.run_v4_residual_controller import (
    Unit,
    choose_threshold,
    training_examples,
)


def audit() -> dict[str, object]:
    cells = [f"S!A{i}" for i in range(1, 8)]
    rankings = {
        "peer": [cells[5], cells[6], *cells[:5]],
        "combined": [cells[5], *cells[:5], cells[6]],
        "role": [cells[6], *cells[:6]],
        "impact": list(cells),
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
        records.append({
            "cell": cell,
            "equivalence_class_size": 2,
            "region_size": 1,
            "precedent_count": 1,
            "dependent_count": 1,
            "peer_counts": {"row": 1, "column": 1, "local": 2, "role": 2},
            "peer_formula_count": 2,
            "formula_family_count": 2,
            "alternative_support": 2 if index == 6 else 0,
            "second_alternative_support": 0,
            "independent_support": 2 if index == 6 else 0,
            "alternative_margin": 1,
            "peer_disagreement": 0.1,
            "role_outlier_score": 0.2,
            "competition_score": 0.3,
            "defect_score": 0.4,
            "evidence_tier": 3 if index == 6 else 0,
            "status": "evidence_supported" if index == 6 else "unsupported",
            "impact_only": 0,
            "descendant_count": 1,
            "sink_count": 1,
            "max_depth": 1,
            "weighted_reach": 1.0,
            "impact_score": 0.5,
            "truncated": 0,
        })
    return {
        "formula_count": 7,
        "parseable_formula_count": 7,
        "visible_formula_count": 7,
        "unsupported_formula_count": 0,
        "region_count": 7,
        "rankings": rankings,
        "rank_records": rank_records,
        "review_cells": {"peer": [cells[5], cells[6]]},
        "records": records,
    }


def v4_ranking() -> list[dict[str, object]]:
    rows = []
    for rank in range(1, 8):
        rows.append({
            "cell": f"S!A{rank}",
            "rank": rank,
            "evidence": {
                "diagnostic_status": "strong_counterfactual" if rank == 6 else "not_intervened",
                "formula_anomaly": rank / 10,
                "graph_anomaly": 0,
                "behavior_anomaly": 0,
                "legacy_prior": 0,
                "rrf_score": 1 / rank,
                "consensus_rrf_score": 1 / rank,
                "candidate_support": 2,
                "candidate_quality": 0.8,
                "local_gain": 0.1,
                "global_harm": 0,
                "candidate_delta": 0.1,
                "intervention_responsibility_gain": 1,
            },
        })
    return rows


class V4RRCTests(unittest.TestCase):
    def test_structure_fold_is_stable_and_bounded(self):
        self.assertEqual(structure_fold("g1"), structure_fold("g1"))
        self.assertIn(structure_fold("g1"), range(5))

    def test_candidate_pool_uses_review_cells_and_excludes_v4_top5(self):
        self.assertEqual(peer_candidates(audit(), v4_ranking()), ["S!A6", "S!A7"])

    def test_feature_map_is_complete_and_contains_no_identity_text(self):
        features = candidate_feature_map("S!A6", audit(), v4_ranking())
        self.assertTrue(all(name in features or name.startswith("missing_") for name in MODEL_FEATURES))
        self.assertEqual(features["top5_combined"], 1.0)
        self.assertEqual(features["atomic_status_evidence_supported"], 1.0)
        self.assertFalse(any("sheet" in name or "workbook" == name for name in features))

    def test_revision_guard_is_exactly_the_preregistered_tightening(self):
        self.assertTrue(guarded_candidate("S!A6", audit(), revision=0))
        self.assertTrue(guarded_candidate("S!A6", audit(), revision=1))
        self.assertFalse(guarded_candidate("S!A7", audit(), revision=1))

    def test_residual_utility_and_rerank_preserve_v4_prefix(self):
        v4 = [f"S!A{i}" for i in range(1, 8)]
        self.assertEqual(residual_utility("error", ["S!A6"], v4, "S!A6"), 1.0)
        self.assertEqual(residual_utility("error", ["S!A5"], v4, "S!A6"), -4.0)
        self.assertEqual(residual_utility("control", [], v4, "S!A6"), -2.0)
        changed = rerank(v4, "S!A6")
        self.assertEqual(changed[:4], v4[:4])
        self.assertEqual(changed[4], "S!A6")
        self.assertEqual(sorted(changed), sorted(v4))

    def test_weighted_ridge_is_deterministic_and_finite(self):
        first = candidate_feature_map("S!A6", audit(), v4_ranking())
        second = candidate_feature_map("S!A7", audit(), v4_ranking())
        model_a = fit_ridge([first, second], [1.0, -2.0], [1.0, 1.0])
        model_b = fit_ridge([first, second], [1.0, -2.0], [1.0, 1.0])
        self.assertEqual(model_a.to_dict(), model_b.to_dict())
        self.assertTrue(np.isfinite(model_a.predict(first)))

    def _unit(self, index: int, *, control: bool = False) -> Unit:
        v4 = tuple(f"S!A{cell}" for cell in range(1, 8))
        event = {
            "event_id": f"e{index}",
            "case_kind": "control" if control else "error",
            "cohort": "public:modified_euses",
            "source_formula_cells": [] if control else ["S!A6"],
        }
        return Unit(
            unit_id=f"u{index}",
            structure_group=f"g{index}",
            fold=index % 5,
            events=(event,),
            audit={},
            v4_rows=(),
            v4_cells=v4,
            candidates=("S!A6",),
            features={"S!A6": {}},
        )

    def test_threshold_calibration_requires_controls_and_three_recoveries(self):
        units = [self._unit(index) for index in range(4)]
        predictions = {
            unit.unit_id: {"candidate": "S!A6", "score": 1.0}
            for unit in units
        }
        threshold, result = choose_threshold(units, predictions)
        self.assertTrue(np.isinf(threshold))
        self.assertFalse(result["finite_threshold"])

        control = self._unit(10, control=True)
        units.append(control)
        predictions[control.unit_id] = {"candidate": "S!A6", "score": -1.0}
        threshold, result = choose_threshold(units, predictions)
        self.assertTrue(np.isfinite(threshold))
        self.assertTrue(result["finite_threshold"])
        self.assertEqual(result["summary"]["residual_event_gains"], 4)
        self.assertEqual(result["summary"]["acted_control_workbooks"], 0)

    def test_training_weights_sum_to_one_within_structure_group(self):
        unit = self._unit(1)
        second_event = dict(unit.events[0], event_id="e2")
        unit = Unit(
            unit_id=unit.unit_id,
            structure_group="shared",
            fold=unit.fold,
            events=(unit.events[0], second_event),
            audit={},
            v4_rows=(),
            v4_cells=unit.v4_cells,
            candidates=("S!A6", "S!A7"),
            features={"S!A6": {}, "S!A7": {}},
        )
        _, _, weights = training_examples([unit], revision=0)
        self.assertEqual(len(weights), 4)
        self.assertAlmostEqual(sum(weights), 1.0)


if __name__ == "__main__":
    unittest.main()
