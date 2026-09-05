import unittest

from formulaguard.peer_repair_learnability import (
    CLOSURE_CANDIDATE_FLAGS,
    CLOSURE_CANDIDATE_NUMERIC,
    CLOSURE_GLOBAL_NUMERIC,
    FEATURE_VIEWS,
    RESPONSIBILITY_FLAGS,
    RESPONSIBILITY_NUMERIC,
    VIEW_ORDER,
    build_feature_views,
)
from formulaguard.v4_rrc import (
    BINARY_FEATURES,
    CONTINUOUS_FEATURES,
    fit_ridge,
)
from scripts.audit_peer_repair_learnability import (
    _public_gates,
    select_passing_view,
)


def closure_probe() -> dict[str, object]:
    candidate: dict[str, object] = {
        name: 1.0 for name in CLOSURE_CANDIDATE_NUMERIC
    }
    candidate.update({name: True for name in CLOSURE_CANDIDATE_FLAGS})
    candidate["status_before"] = "unsupported"
    candidate["status_after"] = "evidence_supported"
    global_metrics: dict[str, object] = {
        name: 1.0 for name in CLOSURE_GLOBAL_NUMERIC
    }
    global_metrics["no_new_actionable_anomaly"] = True
    return {
        "candidate_v4_rank": 6,
        "repair_hypothesis_available": True,
        "repair_executed": True,
        "closure": {
            "candidate": candidate,
            "global": global_metrics,
            "round_trip_reversible": True,
            "repair_closes_without_new_anomaly": True,
        },
    }


def responsibility_probe() -> dict[str, object]:
    responsibility: dict[str, object] = {
        name: 1.0 for name in RESPONSIBILITY_NUMERIC
    }
    responsibility.update({name: True for name in RESPONSIBILITY_FLAGS})
    return {
        "candidate_v4_rank": 6,
        "repair_hypothesis_available": True,
        "responsibility_evaluated": True,
        "responsibility": responsibility,
    }


class PeerRepairLearnabilityTests(unittest.TestCase):
    def test_feature_views_are_complete_disjoint_and_identity_free(self):
        base = {
            name: 0.0 for name in (*CONTINUOUS_FEATURES, *BINARY_FEATURES)
        }
        views = build_feature_views(
            base,
            closure_probe(),
            responsibility_probe(),
        )
        self.assertEqual(tuple(views), VIEW_ORDER)
        for name, values in views.items():
            contract = FEATURE_VIEWS[name]
            self.assertEqual(
                tuple(values),
                (*contract.continuous, *contract.binary),
            )
            self.assertFalse(set(contract.continuous) & set(contract.binary))
            self.assertFalse(any(
                forbidden in field
                for field in values
                for forbidden in ("unit_id", "cell_address", "formula_text", "cohort")
            ))
        expected_combined = sum(
            len(FEATURE_VIEWS[name].continuous) + len(FEATURE_VIEWS[name].binary)
            for name in VIEW_ORDER[:-1]
        )
        self.assertEqual(len(views["combined"]), expected_combined)

    def test_feature_view_rejects_non_boolean_probe_flag(self):
        base = {
            name: 0.0 for name in (*CONTINUOUS_FEATURES, *BINARY_FEATURES)
        }
        probe = closure_probe()
        probe["repair_executed"] = 1
        with self.assertRaisesRegex(TypeError, "boolean feature"):
            build_feature_views(base, probe, responsibility_probe())

    def test_named_ridge_uses_only_declared_features(self):
        rows = [
            {"signal": 0.0, "available": 0.0, "ignored": 100.0},
            {"signal": 1.0, "available": 1.0, "ignored": -100.0},
        ]
        model = fit_ridge(
            rows,
            [0.0, 1.0],
            [1.0, 1.0],
            continuous_features=("signal",),
            binary_features=("available",),
        )
        serialized = model.to_dict()["preprocessor"]
        self.assertEqual(serialized["continuous_features"], ["signal"])
        self.assertEqual(serialized["binary_features"], ["available"])
        self.assertEqual(
            serialized["model_features"],
            ["signal", "available", "missing_signal"],
        )

    def test_public_gates_use_preregistered_boundaries(self):
        summary = {
            "top5_difference": 0.05,
            "mrr_difference": 0.0,
            "positive_residual_action_precision": 0.75,
            "v4_hit_loss_rate": 0.02,
            "control_workbook_action_rate": 0.15,
            "by_cohort": {"enron": {"top5_difference": 0.05}},
        }
        gates = _public_gates(summary, {"ci95_delta_pp": [0.01, 10.0]})
        self.assertTrue(all(gates.values()))
        gates = _public_gates(summary, {"ci95_delta_pp": [0.0, 10.0]})
        self.assertFalse(gates["structure_bootstrap_lower_bound_positive"])

    def test_passing_view_selection_uses_fixed_lexicographic_rule(self):
        results: dict[str, dict[str, object]] = {}
        for index, name in enumerate(VIEW_ORDER):
            results[name] = {
                "all_public_gates_passed": name in {"v4", "combined"},
                "outer_summary": {
                    "top5_difference": 0.06,
                    "mrr_difference": 0.01,
                    "positive_residual_action_precision": 0.8,
                    "by_cohort": {"enron": {"top5_difference": 0.06}},
                },
                "feature_contract": {
                    "model_feature_count_with_missing_indicators": 10 + index,
                },
            }
        self.assertEqual(select_passing_view(results), "v4")
        results["combined"]["outer_summary"]["top5_difference"] = 0.07
        self.assertEqual(select_passing_view(results), "combined")


if __name__ == "__main__":
    unittest.main()
