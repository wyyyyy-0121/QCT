from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from scripts.audit_core_reset_b_data import (
    InputLedger,
    build_audit,
    profile_similarity,
    read_csv,
    workbook_profile,
)
from scripts.build_v6_dataset import write_xlsx
from formulaguard.workbook import WorkbookModel


def make_workbook(
    path: Path,
    *,
    sheet: str = "Model",
    row_offset: int = 0,
    operator: str = "+",
) -> Path:
    values = {
        f"A{1 + row_offset}": 2,
        f"B{1 + row_offset}": 3,
        f"A{2 + row_offset}": 4,
        f"B{2 + row_offset}": 5,
    }
    formulas = {
        f"C{1 + row_offset}": f"=A{1 + row_offset}{operator}B{1 + row_offset}",
        f"C{2 + row_offset}": f"=A{2 + row_offset}{operator}B{2 + row_offset}",
    }
    write_xlsx(path, [(sheet, values, formulas)])
    return path


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class CoreResetBDataAuditTests(unittest.TestCase):
    def test_profile_is_translation_and_sheet_name_invariant(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = make_workbook(root / "left.xlsx", sheet="Model", row_offset=0)
            right = make_workbook(root / "right.xlsx", sheet="Renamed", row_offset=20)
            left_model = WorkbookModel.from_xlsx(left)
            right_model = WorkbookModel.from_xlsx(right)
            left_profile = workbook_profile(left_model, "a" * 64)
            right_profile = workbook_profile(right_model, "b" * 64)
            similarity = profile_similarity(left_profile, right_profile)
            self.assertTrue(similarity["near_duplicate"])
            self.assertEqual(left_profile.template_signature, right_profile.template_signature)

    def test_profile_separates_different_formula_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            left = make_workbook(root / "left.xlsx", operator="+")
            right = make_workbook(root / "right.xlsx", operator="*")
            left_profile = workbook_profile(
                WorkbookModel.from_xlsx(left), "a" * 64,
            )
            right_profile = workbook_profile(
                WorkbookModel.from_xlsx(right), "b" * 64,
            )
            similarity = profile_similarity(left_profile, right_profile)
            self.assertFalse(similarity["near_duplicate"])
            self.assertNotEqual(left_profile.template_signature, right_profile.template_signature)

    def test_input_ledger_rejects_forbidden_dataset_prefix(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            allowed = root / "data"
            forbidden = allowed / "trial"
            forbidden.mkdir(parents=True)
            workbook = make_workbook(forbidden / "case.xlsx")
            ledger = InputLedger((allowed,), (forbidden,))
            with self.assertRaisesRegex(ValueError, "forbidden dataset input"):
                ledger.record(workbook)

    def test_small_audit_groups_by_provenance_and_excludes_labels_from_export(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public"
            historical = root / "historical"
            enron = root / "enron"
            output = root / "output"
            for value in (public, historical, enron):
                value.mkdir()

            public_original = make_workbook(public / "original.xlsx")
            make_workbook(public / "error_a.xlsx", operator="*")
            make_workbook(public / "error_b.xlsx", operator="-")
            historical_book = make_workbook(historical / "historical.xlsx", row_offset=10)
            enron_book = make_workbook(enron / "enron.xlsx", operator="/")
            write_csv(
                public / "manifest.csv",
                (
                    "instance_id", "corpus_id", "workbook", "original_workbook",
                    "case_kind", "include", "source_cells", "error_type",
                ),
                [
                    {
                        "instance_id": "p1", "corpus_id": "p", "workbook": "error_a.xlsx",
                        "original_workbook": public_original.name, "case_kind": "error",
                        "include": "1", "source_cells": "Model!C1", "error_type": "operator",
                    },
                    {
                        "instance_id": "p2", "corpus_id": "p", "workbook": "error_b.xlsx",
                        "original_workbook": public_original.name, "case_kind": "error",
                        "include": "1", "source_cells": "Model!C2", "error_type": "operator",
                    },
                    {
                        "instance_id": "p3", "corpus_id": "p", "workbook": public_original.name,
                        "original_workbook": public_original.name, "case_kind": "control",
                        "include": "1", "source_cells": "", "error_type": "",
                    },
                ],
            )
            write_csv(
                historical / "manifest.csv", ("instance_id", "workbook"),
                [{"instance_id": "h1", "workbook": historical_book.name}],
            )
            write_csv(
                enron / "manifest.csv", ("instance_id", "workbook", "include", "source_cells"),
                [
                    {"instance_id": "e1", "workbook": enron_book.name, "include": "1", "source_cells": "Model!C1"},
                    {"instance_id": "e2", "workbook": enron_book.name, "include": "1", "source_cells": "Model!C2"},
                ],
            )
            audit = build_audit(
                public_root=public,
                public_manifest=public / "manifest.csv",
                historical_root=historical,
                historical_manifest=historical / "manifest.csv",
                enron_root=enron,
                enron_manifest=enron / "manifest.csv",
                output_dir=output,
                expected={
                    "public_events": 3,
                    "public_errors": 2,
                    "public_controls": 1,
                    "public_error_provenance_groups": 1,
                    "public_control_provenance_groups": 1,
                    "public_shared_error_control_groups": 1,
                    "historical_events": 1,
                    "enron_events": 2,
                    "enron_workbook_groups": 1,
                },
                forbidden_prefixes=(root / "never-read",),
            )
            self.assertTrue(audit["gate_0_passed"])
            rows = read_csv(output / "scoring_groups.csv")
            public_rows = [row for row in rows if row["cohort"].startswith("public:")]
            self.assertEqual(len({row["provenance_group_id"] for row in public_rows}), 1)
            enron_rows = [row for row in rows if row["cohort"] == "enron"]
            self.assertEqual(len({row["provenance_group_id"] for row in enron_rows}), 1)
            self.assertFalse(
                {"source_cells", "case_kind", "error_type"} & set(rows[0])
            )


if __name__ == "__main__":
    unittest.main()
