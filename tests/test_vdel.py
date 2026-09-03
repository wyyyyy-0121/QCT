import csv
import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from formulaguard.vdel import (
    PROTOCOL,
    classify_window,
    evaluate_u0_gates,
    fold_for_group,
    formula_signature,
    near_duplicate,
    transition_is_candidate,
    validate_private_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_vdel_u0.py"
SPEC = importlib.util.spec_from_file_location("run_vdel_u0", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def profile(rows: list[tuple[str, str, str]], titles: list[str] | None = None):
    return {
        "sheet_titles": titles or sorted({sheet for sheet, _, _ in rows}),
        "formulas": [
            {"sheet": sheet, "address": address, "formula": formula}
            for sheet, address, formula in rows
        ],
    }


def transition(direct: int = 3, additions: int = 0, removals: int = 0):
    return {
        "eligible": True,
        "direct_formula_text_changes": direct,
        "formula_additions": additions,
        "formula_removals": removals,
        "bulk_direct_rewrite": False,
        "bulk_add_remove": False,
    }


class VDELPrimitiveTests(unittest.TestCase):
    def test_near_duplicate_exact_and_coordinate_paths(self):
        first_rows = [("S", f"A{index}", f"={index}") for index in range(1, 21)]
        exact_rows = [
            ("S", f"A{index}", f"={index}" if index <= 16 else f"={index + 100}")
            for index in range(1, 21)
        ]
        self.assertTrue(
            near_duplicate(
                formula_signature(profile(first_rows)),
                formula_signature(profile(exact_rows)),
            )
        )

        coordinate_rows = [
            ("S", f"A{index}", f"={index}" if index <= 15 else f"={index + 100}")
            for index in range(1, 19)
        ] + [("T", "A1", "=1"), ("T", "A2", "=2")]
        self.assertTrue(
            near_duplicate(
                formula_signature(profile(first_rows)),
                formula_signature(profile(coordinate_rows)),
            )
        )

        low_agreement = [
            ("S", f"A{index}", f"={index}" if index <= 14 else f"={index + 100}")
            for index in range(1, 19)
        ] + [("T", "A1", "=1"), ("T", "A2", "=2")]
        self.assertFalse(
            near_duplicate(
                formula_signature(profile(first_rows)),
                formula_signature(profile(low_agreement)),
            )
        )
        self.assertFalse(
            near_duplicate(
                formula_signature(profile(first_rows[:19])),
                formula_signature(profile(exact_rows[:19])),
            )
        )

    def test_candidate_transition_uses_frozen_bounds(self):
        self.assertTrue(transition_is_candidate(transition(2, 5, 7)))
        self.assertFalse(transition_is_candidate(transition(1)))
        self.assertFalse(transition_is_candidate(transition(13)))
        self.assertFalse(transition_is_candidate(transition(2, 6, 7)))
        self.assertFalse(
            transition_is_candidate({**transition(2), "bulk_direct_rewrite": True})
        )

    def test_window_classification_masks_future_missing_keys(self):
        previous = profile([
            ("S", "A1", "=1"),
            ("S", "A2", "=2"),
            ("S", "A3", "=3"),
        ])
        current = profile([
            ("S", "A1", "=11"),
            ("S", "A2", "=22"),
            ("S", "A3", "=33"),
        ])
        future = profile([
            ("S", "A1", "=111"),
            ("S", "A2", "=22"),
        ])
        kind, row = classify_window(
            group_id=8,
            current_order=2,
            transition=transition(3),
            previous=previous,
            current=current,
            future=future,
        )
        self.assertEqual(kind, "ranking_window")
        self.assertEqual(row["positive_count"], 1)
        self.assertEqual(row["negative_count"], 1)
        self.assertEqual(row["unavailable_candidate_count"], 1)
        self.assertEqual(row["fold"], fold_for_group(8))
        self.assertNotIn("A1", str(row))
        self.assertNotIn("=111", str(row))

        control_kind, control = classify_window(
            group_id=9,
            current_order=2,
            transition=transition(3),
            previous=previous,
            current=current,
            future=current,
        )
        self.assertEqual(control_kind, "no_reedit_control")
        self.assertEqual(control["positive_count"], 0)

    def test_window_requires_unchanged_sheet_titles(self):
        previous = profile([("S", "A1", "=1"), ("S", "A2", "=2")])
        current = profile(
            [("S", "A1", "=3"), ("S", "A2", "=4")],
            titles=["S", "Added"],
        )
        kind, row = classify_window(
            group_id=1,
            current_order=2,
            transition=transition(2),
            previous=previous,
            current=current,
            future=current,
        )
        self.assertEqual(kind, "sheet_title_change")
        self.assertEqual(row, {})

    def test_manifest_and_gates_enforce_classes_folds_and_forbidden_inputs(self):
        labels = [
            {"candidate_id": "a" * 64, "re_edited": True},
            {"candidate_id": "b" * 64, "re_edited": False},
        ]
        row = {
            "window_id": "c" * 64,
            "group_id_hash": "d" * 64,
            "fold": 2,
            "candidate_labels": labels,
        }
        validate_private_manifest({
            "protocol": PROTOCOL,
            "ranking_windows": [row],
            "no_reedit_controls": [],
        })
        with self.assertRaisesRegex(ValueError, "both classes"):
            validate_private_manifest({
                "protocol": PROTOCOL,
                "ranking_windows": [
                    {**row, "candidate_labels": [
                        {"candidate_id": "a" * 64, "re_edited": True},
                        {"candidate_id": "b" * 64, "re_edited": True},
                    ]}
                ],
                "no_reedit_controls": [],
            })

        summary = {
            "ranking_windows": 120,
            "ranking_window_groups": 40,
            "ranking_candidates": 240,
            "re_edited_candidates": 120,
            "stable_candidates": 120,
            "no_reedit_controls": 30,
            "no_reedit_control_groups": 15,
            "overlap_exclusion_complete": True,
            "excluded_group_rows": 0,
            "input_hashes_verified": True,
            "group_order_verified": True,
            "candidate_accounting_verified": True,
            "fold_isolation_verified": True,
            "folds": {
                str(fold): {"ranking_windows": 24, "groups": 8}
                for fold in range(5)
            },
            "cached_value_inputs": [],
            "constant_inputs": [],
            "email_inputs": [],
            "fault_label_inputs": [],
            "public_label_inputs": [],
            "answer_workbook_inputs": [],
            "v4_inputs": [],
            "protected_data_inputs": [],
        }
        self.assertTrue(all(evaluate_u0_gates(summary).values()))
        summary["folds"]["4"]["groups"] = 7
        self.assertFalse(evaluate_u0_gates(summary)["five_fold_coverage"])


class VDELPublicInputTests(unittest.TestCase):
    def _write_workbook(self, path: Path) -> str:
        path.parent.mkdir(parents=True)
        workbook = Workbook()
        sheet = workbook.active
        sheet["A1"] = "private constant"
        sheet["A2"] = "=1"
        workbook.save(path)
        workbook.close()
        return runner.sha256(path)

    def _write_groups(self, path: Path, row: dict[str, str], fields=None) -> None:
        selected_fields = fields or list(runner.FIELDS_READ)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=selected_fields)
            writer.writeheader()
            writer.writerow(row)

    def test_public_loader_is_hash_bound_deduplicated_and_label_free(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "data/public/book.xlsx"
            digest = self._write_workbook(workbook)
            row = {
                "cohort": "public:test",
                "workbook": "data/public/book.xlsx",
                "workbook_sha256": digest,
                "structure_cluster_id": "structure:test",
            }
            groups = root / "results/core_reset_b_phase0/scoring_groups.csv"
            self._write_groups(groups, row)
            units = runner.load_public_units(
                groups,
                root=root,
                cohorts=("public:test",),
                allowed_roots=(root / "data",),
                expected_groups_sha256=runner.sha256(groups),
                expected_workbooks=1,
            )
            self.assertEqual(len(units), 1)
            self.assertNotIn("source_cells", units[0])

            labeled = root / "results/core_reset_b_phase0/labeled.csv"
            labeled_row = {**row, "source_cells": "Sheet!A2"}
            self._write_groups(labeled, labeled_row, [*runner.FIELDS_READ, "source_cells"])
            with self.assertRaisesRegex(ValueError, "label-free field allowlist"):
                runner.load_public_units(
                    labeled,
                    root=root,
                    cohorts=("public:test",),
                    allowed_roots=(root / "data",),
                    expected_groups_sha256=runner.sha256(labeled),
                    expected_workbooks=1,
                )

    def test_public_loader_rejects_protected_workbook_path(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "data/external/v5_psl/final_blind/book.xlsx"
            digest = self._write_workbook(workbook)
            groups = root / "results/core_reset_b_phase0/scoring_groups.csv"
            self._write_groups(groups, {
                "cohort": "public:test",
                "workbook": "data/external/v5_psl/final_blind/book.xlsx",
                "workbook_sha256": digest,
                "structure_cluster_id": "structure:test",
            })
            with self.assertRaisesRegex(ValueError, "protected"):
                runner.load_public_units(
                    groups,
                    root=root,
                    cohorts=("public:test",),
                    allowed_roots=(root / "data",),
                    expected_groups_sha256=runner.sha256(groups),
                    expected_workbooks=1,
                )


if __name__ == "__main__":
    unittest.main()
