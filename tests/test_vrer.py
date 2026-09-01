import tempfile
import unittest
from pathlib import Path

import openpyxl

from formulaguard.vrer import (
    audit_candidate,
    compare_workbook_profiles,
    safe_relative_path,
    summarize_r0,
    workbook_profile,
)
from scripts.verify_vrer_r0_reproduction import compare_receipts, reproducibility_sample


def write_workbook(
    path: Path, formulas: dict[str, str], *, extra_sheet: bool = False
) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Calc"
    sheet["Z1"] = "constant values are not part of the profile"
    for address, formula in formulas.items():
        sheet[address] = formula
    if extra_sheet:
        workbook.create_sheet("Added")
    workbook.save(path)
    workbook.close()


def candidate(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "candidate_id": "case-1",
        "repository": "owner/repo",
        "revision_group": "group-1",
        "source_kind": "correction",
        "evidence_scope": "workbook",
        "evidence_quote": "Fix incorrect total formula",
    }
    base.update(overrides)
    return base


class VRERTests(unittest.TestCase):
    def test_safe_relative_path_rejects_escape_and_windows_path(self):
        self.assertEqual(safe_relative_path("books/a.xlsx"), "books/a.xlsx")
        for value in ("../a.xlsx", "/a.xlsx", "books\\a.xlsx", ""):
            with self.assertRaises(ValueError):
                safe_relative_path(value)

    def test_profile_omits_constants_and_tracks_parser_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "book.xlsx"
            write_workbook(path, {"A1": "=SUM(B1:B2)"})
            profile = workbook_profile(path)
            self.assertEqual(profile["formula_count"], 1)
            self.assertEqual(profile["parseable_formula_count"], 1)
            self.assertNotIn("constant values", str(profile))
            self.assertFalse(profile["cached_values_retained"])

    def test_workbook_level_correction_accepts_small_same_cell_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before_path = root / "before.xlsx"
            after_path = root / "after.xlsx"
            write_workbook(before_path, {"A1": "=B1+B2", "A2": "=B2"})
            write_workbook(after_path, {"A1": "=SUM(B1:B2)", "A2": "=B2"})
            result = audit_candidate(
                candidate(),
                workbook_profile(before_path),
                workbook_profile(after_path),
                license_verified=True,
            )
            self.assertTrue(result["accepted"])
            self.assertEqual(result["corrected_formula_cells"], 1)
            self.assertEqual(result["parseable_corrected_formula_cells"], 1)

    def test_missing_statement_sheet_change_and_large_diff_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before_path = root / "before.xlsx"
            after_path = root / "after.xlsx"
            before = {f"A{index}": f"={index}" for index in range(1, 14)}
            after = {f"A{index}": f"={index + 1}" for index in range(1, 14)}
            write_workbook(before_path, before)
            write_workbook(after_path, after, extra_sheet=True)
            result = audit_candidate(
                candidate(evidence_quote="Update workbook"),
                workbook_profile(before_path),
                workbook_profile(after_path),
                license_verified=True,
            )
            self.assertFalse(result["accepted"])
            self.assertIn(
                "no_explicit_correction_statement", result["rejection_reasons"]
            )
            self.assertIn("sheet_inventory_changed", result["rejection_reasons"])
            self.assertIn(
                "workbook_statement_has_more_than_12_direct_changes",
                result["rejection_reasons"],
            )

    def test_exact_cell_claim_must_equal_observed_changes(self):
        before = {
            "sheet_titles": ["S"],
            "formulas": [
                {
                    "sheet": "S",
                    "address": "A1",
                    "formula": "=1",
                    "parseable": True,
                }
            ],
        }
        after = {
            "sheet_titles": ["S"],
            "formulas": [
                {
                    "sheet": "S",
                    "address": "A1",
                    "formula": "=2",
                    "parseable": True,
                }
            ],
        }
        result = audit_candidate(
            candidate(
                evidence_scope="exact_cells",
                claimed_cells=[
                    {
                        "sheet": "S",
                        "address": "A2",
                    }
                ],
            ),
            before,
            after,
            license_verified=True,
        )
        self.assertFalse(result["accepted"])
        self.assertIn(
            "claimed_cells_do_not_equal_formula_changes", result["rejection_reasons"]
        )

    def test_profile_comparison_detects_formula_move(self):
        before = {
            "sheet_titles": ["S"],
            "formulas": [
                {
                    "sheet": "S",
                    "address": "A1",
                    "formula": "=B1",
                    "parseable": True,
                }
            ],
        }
        after = {
            "sheet_titles": ["S"],
            "formulas": [
                {
                    "sheet": "S",
                    "address": "A2",
                    "formula": "=B1",
                    "parseable": True,
                }
            ],
        }
        self.assertTrue(
            compare_workbook_profiles(before, after)["address_only_formula_move"]
        )

    def test_r0_requires_every_registered_gate(self):
        corrections = [
            {
                "accepted": True,
                "source_kind": "correction",
                "repository": f"repo-{index % 10}",
                "revision_group": f"group-{index}",
                "corrected_formula_cells": 2,
                "parseable_corrected_formula_cells": 2,
            }
            for index in range(60)
        ]
        controls = [
            {
                "accepted": True,
                "source_kind": "ordinary_edit_control",
                "repository": f"repo-{index % 5}",
                "revision_group": f"control-{index}",
                "corrected_formula_cells": 0,
                "parseable_corrected_formula_cells": 0,
            }
            for index in range(30)
        ]
        summary = summarize_r0(corrections + controls, reproducible_audit=True)
        self.assertTrue(summary["r0_passed"])
        summary = summarize_r0(corrections + controls, reproducible_audit=False)
        self.assertFalse(summary["gates"]["independent_reproduction_passed"])
        self.assertFalse(summary["r0_passed"])

    def test_reproduction_uses_stable_nonempty_twenty_percent_sample(self):
        ids = [f"case-{index}" for index in range(11)]
        sample = reproducibility_sample(ids)
        self.assertEqual(len(sample), 3)
        self.assertEqual(sample, reproducibility_sample(list(reversed(ids))))

    def test_reproduction_detects_a_sampled_diff_mismatch(self):
        candidate_id = "only-case"
        record = {
            "candidate_id": candidate_id,
            "repository": "owner/repo",
            "revision_group": "group",
            "source_kind": "correction",
            "accepted": True,
            "rejection_reasons": [],
            "corrected_formula_cells": 1,
            "parseable_corrected_formula_cells": 1,
            "diff": {"direct_formula_changes": 1},
        }
        receipt = {
            "protocol": "formulaguard_vrer_r0_audit_v1",
            "source_candidates_sha256": "a" * 64,
            "records": [record],
            "protected_data_inputs": [],
            "revealed_label_inputs": [],
        }
        matching = compare_receipts(receipt, receipt)
        self.assertTrue(matching["reproducible"])
        changed = dict(receipt)
        changed_record = dict(record)
        changed_record["diff"] = {"direct_formula_changes": 2}
        changed["records"] = [changed_record]
        mismatch = compare_receipts(receipt, changed)
        self.assertFalse(mismatch["reproducible"])
        self.assertEqual(mismatch["mismatches"][0]["field"], "diff")


if __name__ == "__main__":
    unittest.main()
