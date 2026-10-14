import csv
import importlib.util
import json
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from zipfile import ZipFile

from openpyxl import Workbook

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_sfri_predictions.py"
SPEC = importlib.util.spec_from_file_location("run_sfri_predictions", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

GROUP_FIELDS = (
    "cohort",
    "workbook",
    "workbook_sha256",
    "structure_cluster_id",
)
WORKSHEET_NAMESPACE = (
    "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
)


def write_sfri_workbook(path: Path, target_formula: str = "=A5-B5") -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Model"
    for row in range(2, 7):
        sheet[f"A{row}"] = row
        sheet[f"B{row}"] = row * 2
        sheet[f"C{row}"] = target_formula if row == 5 else f"=A{row}+B{row}"
    path.parent.mkdir(parents=True)
    workbook.save(path)

    with ZipFile(path, "r") as source:
        members = [(item, source.read(item.filename)) for item in source.infolist()]
    worksheet_name = "xl/worksheets/sheet1.xml"
    worksheet = ET.fromstring(
        next(data for item, data in members if item.filename == worksheet_name)
    )
    for address in ("C2", "C3", "C4", "C6"):
        cell = worksheet.find(
            f".//{{{WORKSHEET_NAMESPACE}}}c[@r='{address}']"
        )
        if cell is None:
            raise AssertionError(f"missing test cell {address}")
        formula = cell.find(f"{{{WORKSHEET_NAMESPACE}}}f")
        if formula is None:
            raise AssertionError(f"missing test formula {address}")
        formula.attrib.update({"t": "shared", "si": "7"})
        if address == "C2":
            formula.attrib["ref"] = "C2:C6"
        else:
            formula.text = None

    rewritten = ET.tostring(worksheet, encoding="utf-8", xml_declaration=True)
    temporary = path.with_suffix(".rewritten.xlsx")
    with ZipFile(temporary, "w") as destination:
        for item, data in members:
            destination.writestr(
                item,
                rewritten if item.filename == worksheet_name else data,
            )
    temporary.replace(path)


def write_groups(
    path: Path,
    rows: list[dict[str, str]],
    extra_field: str | None = None,
) -> None:
    fields = [*GROUP_FIELDS]
    if extra_field:
        fields.append(extra_field)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class SfriPredictionTests(unittest.TestCase):
    def test_run_is_label_free_sharded_and_byte_stable(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "data/public/model.xlsx"
            write_sfri_workbook(workbook)
            digest = runner.sha256(workbook)
            groups = root / "groups.csv"
            row = {
                "cohort": "public:test",
                "workbook": "data/public/model.xlsx",
                "workbook_sha256": digest,
                "structure_cluster_id": "structure:test",
            }
            write_groups(groups, [row, row])

            first = root / "first"
            second = root / "second"
            with mock.patch.object(runner, "_git_source_status", return_value=()):
                runner.run(
                    groups=groups,
                    output=first,
                    cohorts=("public:test",),
                    workers=1,
                    root=root,
                    allowed_roots=(root / "data",),
                    allowed_group_roots=(root,),
                    allow_dirty=True,
                )
                runner.run(
                    groups=groups,
                    output=second,
                    cohorts=("public:test",),
                    workers=1,
                    root=root,
                    allowed_roots=(root / "data",),
                    allowed_group_roots=(root,),
                    allow_dirty=True,
                )

            relative_files = sorted(
                path.relative_to(first)
                for path in first.rglob("*")
                if path.is_file()
            )
            self.assertEqual(
                relative_files,
                sorted(
                    path.relative_to(second)
                    for path in second.rglob("*")
                    if path.is_file()
                ),
            )
            for relative in relative_files:
                self.assertEqual(
                    (first / relative).read_bytes(),
                    (second / relative).read_bytes(),
                )

            record = json.loads((first / "predictions.jsonl").read_text())
            self.assertEqual(record["workbook_sha256"], digest)
            self.assertEqual(record["declared_region_count"], 1)
            self.assertEqual(record["certificate_count"], 1)
            self.assertEqual(record["disagreement_count"], 1)
            self.assertTrue(record["has_deterministic_candidate"])
            self.assertEqual(record["label_inputs"], [])
            candidate = record["result"]["deterministic_candidate"]
            self.assertEqual(candidate["candidate_formula"], "=A5+B5")
            self.assertEqual(candidate["observed_formula"], "=A5-B5")
            self.assertTrue(
                candidate["certificate"][
                    "candidate_derived_without_observed_target"
                ]
            )

            summary = json.loads((first / "scan_summary.json").read_text())
            self.assertEqual(summary["selected_identity_rows"], 2)
            self.assertEqual(summary["unique_observed_workbooks"], 1)
            self.assertEqual(summary["global"]["candidate_workbooks"], 1)
            self.assertEqual(summary["global"]["action_workbooks"], 0)
            self.assertEqual(summary["actions"], [])
            self.assertEqual(summary["label_inputs"], [])
            self.assertEqual(summary["protected_data_inputs"], [])
            self.assertTrue(summary["formal_evidence"])

            receipt = json.loads(
                (first / "completion_receipt.json").read_text()
            )
            shard_name = f"shards/{digest}.json"
            self.assertEqual(
                receipt["prediction_shard_sha256"][shard_name],
                runner.sha256(first / shard_name),
            )
            self.assertEqual(
                receipt["source_sha256"],
                {
                    relative: runner.sha256(ROOT / relative)
                    for relative in runner.SOURCE_PATHS
                },
            )

    def test_label_columns_and_protected_paths_are_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "data/public/model.xlsx"
            write_sfri_workbook(workbook)
            row = {
                "cohort": "public:test",
                "workbook": "data/public/model.xlsx",
                "workbook_sha256": runner.sha256(workbook),
                "structure_cluster_id": "structure:test",
                "source_cells": "Model!C5",
            }
            groups = root / "groups.csv"
            write_groups(groups, [row], extra_field="source_cells")
            with self.assertRaisesRegex(ValueError, "possible labels"):
                runner.load_units(
                    groups,
                    cohorts=("public:test",),
                    root=root,
                    allowed_roots=(root / "data",),
                    allowed_group_roots=(root,),
                )

            row.pop("source_cells")
            row["workbook"] = "data/external/v5_psl/final_blind/model.xlsx"
            protected = root / "data/external/v5_psl/final_blind/model.xlsx"
            protected.parent.mkdir(parents=True)
            protected.write_bytes(workbook.read_bytes())
            groups = root / "protected.csv"
            write_groups(groups, [row])
            with self.assertRaisesRegex(ValueError, "protected"):
                runner.load_units(
                    groups,
                    cohorts=("public:test",),
                    root=root,
                    allowed_roots=(root / "data",),
                    allowed_group_roots=(root,),
                )

    def test_dirty_sources_require_explicit_nonformal_mode(self):
        with mock.patch.object(
            runner,
            "_git_source_status",
            return_value=(" M formulaguard/workbook.py",),
        ):
            with self.assertRaisesRegex(ValueError, "clean tracked source"):
                runner.capture_source_state(ROOT)
            state = runner.capture_source_state(ROOT, allow_dirty=True)
        self.assertTrue(state["source_tree_dirty"])
        self.assertFalse(state["formal_evidence"])

    def test_output_cannot_overlap_prediction_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "data/public/model.xlsx"
            write_sfri_workbook(workbook)
            groups = root / "groups.csv"
            write_groups(
                groups,
                [
                    {
                        "cohort": "public:test",
                        "workbook": "data/public/model.xlsx",
                        "workbook_sha256": runner.sha256(workbook),
                        "structure_cluster_id": "structure:test",
                    }
                ],
            )
            with (
                mock.patch.object(runner, "_git_source_status", return_value=()),
                self.assertRaisesRegex(ValueError, "overlaps"),
            ):
                runner.run(
                    groups=groups,
                    output=root / "data",
                    cohorts=("public:test",),
                    workers=1,
                    root=root,
                    allowed_roots=(root / "data",),
                    allowed_group_roots=(root,),
                    allow_dirty=True,
                )


if __name__ == "__main__":
    unittest.main()
