from __future__ import annotations

import unittest

from formulaguard.vepr import (
    PROTOCOL,
    build_control,
    classify_ranking_transition,
    evaluate_u0_gates,
    fold_for_group,
    layout_sha256,
    snapshot_sha256,
    transition_is_control_candidate,
    transition_is_ranking_candidate,
    validate_private_manifest,
)


def profile(formulas: dict[tuple[str, str], str]) -> dict[str, object]:
    return {
        "formulas": [
            {"sheet": sheet, "address": address, "formula": formula}
            for (sheet, address), formula in sorted(formulas.items())
        ]
    }


def transition(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "eligible": True,
        "previous_formula_count": 10,
        "current_formula_count": 10,
        "direct_formula_text_changes": 1,
        "formula_additions": 0,
        "formula_removals": 0,
        "unchanged_formula_keys": 9,
        "bulk_direct_rewrite": False,
        "bulk_add_remove": False,
        "no_formula_text_change": False,
    }
    row.update(overrides)
    return row


class VEPRPrimitiveTests(unittest.TestCase):
    def test_fold_is_stable_and_in_range(self):
        self.assertEqual(fold_for_group(17), fold_for_group(17))
        self.assertIn(fold_for_group(17), range(5))

    def test_ranking_eligibility_applies_every_bound(self):
        self.assertTrue(transition_is_ranking_candidate(transition()))
        rejected = (
            {"previous_formula_count": 9},
            {"previous_formula_count": 5001},
            {"direct_formula_text_changes": 0},
            {"direct_formula_text_changes": 20},
            {"formula_additions": 13},
            {"unchanged_formula_keys": 4},
            {"bulk_direct_rewrite": True},
            {"bulk_add_remove": True},
            {"eligible": False},
        )
        for values in rejected:
            with self.subTest(values=values):
                self.assertFalse(transition_is_ranking_candidate(transition(**values)))

    def test_control_requires_a_strictly_unchanged_pair(self):
        unchanged = transition(
            direct_formula_text_changes=0,
            unchanged_formula_keys=10,
            no_formula_text_change=True,
        )
        self.assertTrue(transition_is_control_candidate(unchanged))
        self.assertFalse(
            transition_is_control_candidate(
                {**unchanged, "formula_additions": 1, "no_formula_text_change": False}
            )
        )

    def test_snapshot_and_layout_hashes_have_distinct_contracts(self):
        first = profile({("S", "A1"): "=1", ("S", "A2"): "=A1"})
        changed = profile({("S", "A1"): "=2", ("S", "A2"): "=A1"})
        self.assertNotEqual(snapshot_sha256(first), snapshot_sha256(changed))
        self.assertEqual(layout_sha256(first), layout_sha256(changed))

    def test_classification_exports_only_opaque_candidate_labels(self):
        current_formulas = {
            ("Secret Sheet", f"A{index}"): f"={index}"
            for index in range(1, 11)
        }
        future_formulas = dict(current_formulas)
        future_formulas[("Secret Sheet", "A3")] = "=300"
        row = classify_ranking_transition(
            group_id=7,
            current_order=4,
            transition=transition(),
            current=profile(current_formulas),
            future=profile(future_formulas),
        )
        self.assertEqual(row["positive_count"], 1)
        self.assertEqual(row["stable_count"], 9)
        self.assertEqual(row["candidate_count"], 10)
        self.assertEqual(
            sum(label["next_direct_edit"] for label in row["candidate_labels"]),
            1,
        )
        serialized = repr(row)
        self.assertNotIn("Secret Sheet", serialized)
        self.assertNotIn("A3", serialized)
        self.assertNotIn("=300", serialized)

    def test_classification_rejects_manifest_profile_disagreement(self):
        formulas = {("S", f"A{index}"): f"={index}" for index in range(1, 11)}
        with self.assertRaisesRegex(ValueError, "differs from the frozen transition"):
            classify_ranking_transition(
                group_id=1,
                current_order=1,
                transition=transition(direct_formula_text_changes=2),
                current=profile(formulas),
                future=profile(formulas),
            )

    def test_control_is_opaque_and_records_layout(self):
        formulas = {("S", f"A{index}"): f"={index}" for index in range(1, 11)}
        unchanged = transition(
            direct_formula_text_changes=0,
            unchanged_formula_keys=10,
            no_formula_text_change=True,
        )
        row = build_control(
            group_id=2,
            current_order=3,
            transition=unchanged,
            current=profile(formulas),
        )
        self.assertEqual(row["current_formula_count"], 10)
        self.assertEqual(len(row["layout_sha256"]), 64)
        self.assertNotIn("S", row.values())


class VEPRGateTests(unittest.TestCase):
    def passing_summary(self) -> dict[str, object]:
        return {
            "ranking_transitions": 300,
            "ranking_groups": 50,
            "positive_rows": 600,
            "stable_rows": 30_000,
            "controls": 200,
            "control_groups": 80,
            "overlap_exclusion_complete": True,
            "overlap_excluded_rows": 0,
            "profile_text_validation_complete": True,
            "invalid_profile_rows": 0,
            "input_hashes_verified": True,
            "group_order_verified": True,
            "candidate_accounting_verified": True,
            "snapshot_before_label_verified": True,
            "fold_isolation_verified": True,
            "folds": {
                str(fold): {
                    "ranking_transitions": 60,
                    "ranking_groups": 10,
                    "positive_rows": 120,
                    "stable_rows": 6_000,
                    "controls": 40,
                    "control_groups": 16,
                }
                for fold in range(5)
            },
            "cached_value_inputs": [],
            "constant_inputs": [],
            "cell_text_inputs": [],
            "email_inputs": [],
            "fault_label_inputs": [],
            "expected_output_inputs": [],
            "correct_workbook_inputs": [],
            "public_source_cell_inputs": [],
            "v4_inputs": [],
            "protected_data_inputs": [],
        }

    def test_all_u0_gates_pass_at_the_frozen_boundaries(self):
        self.assertTrue(all(evaluate_u0_gates(self.passing_summary()).values()))

    def test_each_fold_requires_both_ranking_and_control_coverage(self):
        summary = self.passing_summary()
        summary["folds"]["4"]["control_groups"] = 9
        gates = evaluate_u0_gates(summary)
        self.assertFalse(gates["five_fold_control_coverage"])
        self.assertTrue(gates["five_fold_ranking_coverage"])

    def test_manifest_validates_accounting_and_control_deduplication(self):
        formulas = {("S", f"A{index}"): f"={index}" for index in range(1, 11)}
        future = dict(formulas)
        future[("S", "A1")] = "=11"
        ranking = classify_ranking_transition(
            group_id=9,
            current_order=1,
            transition=transition(),
            current=profile(formulas),
            future=profile(future),
        )
        unchanged = transition(
            direct_formula_text_changes=0,
            unchanged_formula_keys=10,
            no_formula_text_change=True,
        )
        control = build_control(
            group_id=10,
            current_order=1,
            transition=unchanged,
            current=profile(formulas),
        )
        payload = {
            "protocol": PROTOCOL,
            "ranking_transitions": [ranking],
            "unchanged_controls": [control],
        }
        validate_private_manifest(payload)
        with self.assertRaisesRegex(ValueError, "control identity or layout"):
            validate_private_manifest(
                {**payload, "unchanged_controls": [control, {**control, "control_id": "a" * 64}]}
            )


if __name__ == "__main__":
    unittest.main()
