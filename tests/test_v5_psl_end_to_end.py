from __future__ import annotations

import csv
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scripts.build_v5_psl_third_party_pack as packer
import scripts.run_v5_psl_predictions as predictor
import scripts.score_v5_psl_blind as scorer
import scripts.verify_v5_psl_prediction_lock as locker
from formulaguard.v5_psl_protocol import CASE_FIELDS, ERROR_TYPES
from scripts.build_v6_dataset import write_xlsx

RUN_SYNTHETIC_E2E = os.environ.get("FORMULAGUARD_RUN_V5_PSL_E2E") == "1"


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _formula_pair(error_type: str) -> tuple[str, str]:
    pairs = {
        "absolute_reference": ("=$A$1+$B$1", "=$A$2+$B$1"),
        "copy_offset": ("=A1+B1", "=A2+B1"),
        "function_replacement": ("=SUM(A1:B1)", "=MAX(A1:B1)"),
        "operator_replacement": ("=A1+B1", "=A1-B1"),
        "range_boundary": ("=SUM(A1:B1)", "=SUM(A1:A2)"),
        "reference_shift": ("=A1*B1", "=A1*B2"),
    }
    return pairs[error_type]


def _build_synthetic_raw(root: Path) -> None:
    cases: list[dict[str, str]] = []
    error_index = 0
    for template_index in range(30):
        template_id = f"template_{template_index + 1:02d}"
        origin = "steward_owned" if template_index < 20 else "licensed_public"
        for case_index in range(12):
            instance_id = f"synthetic_{template_index + 1:02d}_{case_index + 1:02d}"
            workbook_name = f"workbooks/{instance_id}.xlsx"
            original_name = f"originals/{instance_id}.xlsx"
            common = {
                "instance_id": instance_id,
                "template_id": template_id,
                "steward_id": "synthetic_custodian",
                "workbook": workbook_name,
                "original_workbook": original_name,
                "template_origin": origin,
                "license_id": f"synthetic-engineering-{template_index + 1:02d}",
            }
            values = {
                "A1": 11 + template_index * 12 + case_index,
                "A2": 3 + case_index,
                "B1": 5 + template_index,
                "B2": 2 + case_index,
            }
            if case_index < 8:
                error_type = ERROR_TYPES[error_index % len(ERROR_TYPES)]
                original_formula, changed_formula = _formula_pair(error_type)
                challenge = ""
                identity = "identifiable"
                sources = "Model!C6"
                if case_index == 6:
                    identity = "ambiguous"
                    challenge = "single_source_exception_like"
                elif case_index == 7:
                    identity = "ambiguous"
                    challenge = "symmetric_multi_source"
                    sources = "Model!C6;Model!C7"
                original_formulas = {"C6": original_formula, "C7": "=C6*2"}
                changed_formulas = {"C6": changed_formula, "C7": "=C6*2"}
                if challenge == "symmetric_multi_source":
                    changed_formulas["C7"] = "=C6*3"
                row = {
                    **common,
                    "case_kind": "error",
                    "error_type": error_type,
                    "source_cells": sources,
                    "identifiability": identity,
                    "control_subtype": "",
                    "challenge_stratum": challenge,
                    "adjudication_rationale": (
                        "Synthetic objective ambiguity fixture."
                        if identity == "ambiguous" else ""
                    ),
                }
                error_index += 1
            else:
                original_formulas = {"C6": "=A1+B1", "C7": "=C6*2"}
                changed_formulas = dict(original_formulas)
                row = {
                    **common,
                    "case_kind": "control",
                    "error_type": "",
                    "source_cells": "",
                    "identifiability": "",
                    "control_subtype": "regular" if case_index < 10 else "legal_exception",
                    "challenge_stratum": "",
                    "adjudication_rationale": (
                        "Synthetic valid-formula exception fixture."
                        if case_index >= 10 else ""
                    ),
                }
            write_xlsx(root / original_name, [("Model", values, original_formulas)])
            write_xlsx(root / workbook_name, [("Model", values, changed_formulas)])
            cases.append({field: row[field] for field in CASE_FIELDS})

    _write_csv(root / "cases.csv", CASE_FIELDS, cases)
    declaration = {
        "independent_custodian": True,
        "custodian_not_in_model_development": True,
        "custodian_prepared_or_supervised_all_cases": True,
        "model_was_run": False,
        "labels_withheld_until_prediction_lock": True,
        "permissions_and_anonymization_checked": True,
        "all_cases_recalculated_without_runtime_errors": True,
        "case_plan_fixed_before_third_party_predictions": True,
        "templates_withheld_until_candidate_lock": True,
        "no_development_template_overlap": True,
        "custodian_received_no_model_outputs": True,
        "single_custodian_design_acknowledged": True,
        "custodian_id": "synthetic_custodian",
        "calculation_engine": "FormulaGuard synthetic fixture writer",
        "calculation_engine_version": "engineering-test-v1",
        "permission_evidence_sha256": "a" * 64,
        "anonymization_evidence_sha256": "b" * 64,
        "case_plan_sha256": "c" * 64,
        "template_overlap_evidence_sha256": "d" * 64,
        "fixture_scope": "synthetic_engineering_test_only",
    }
    (root / "third_party_declaration.json").write_text(
        json.dumps(declaration, indent=2) + "\n", encoding="utf-8",
    )


def _run_main(module: object, *arguments: str) -> None:
    script = str(Path(module.__file__).name)
    with mock.patch.object(sys, "argv", [script, *arguments]):
        module.main()


@unittest.skipUnless(
    RUN_SYNTHETIC_E2E,
    "set FORMULAGUARD_RUN_V5_PSL_E2E=1 for the synthetic 360-case protocol smoke",
)
class V5PSLSyntheticEndToEndTests(unittest.TestCase):
    def test_pack_predict_lock_and_score_command_paths(self):
        """Exercise protocol plumbing only; this is not independent research evidence."""
        with tempfile.TemporaryDirectory(prefix="v5_psl_e2e_") as directory:
            root = Path(directory)
            raw = root / "raw"
            package = root / "package"
            predictions = root / "predictions"
            scored = root / "scored"
            raw.mkdir()
            _build_synthetic_raw(raw)

            key = root / "pseudonym.key"
            key.write_bytes(b"synthetic-engineering-key-only-0001")
            signatures = root / "development_signatures.txt"
            signatures.write_text("0" * 64 + "\n", encoding="utf-8")
            _run_main(
                packer,
                "--raw", str(raw),
                "--output", str(package),
                "--pseudonym-key-file", str(key),
                "--development-signatures", str(signatures),
            )

            package_receipt = json.loads(
                (package / "package_receipt.json").read_text(encoding="utf-8")
            )
            candidate = {
                "candidate_id": "synthetic-engineering-smoke",
                "development_formula_change_signatures": ["0" * 64],
                "third_party_commitments_received_before_lock": {
                    "public_archive_sha256": package_receipt["public_archive_sha256"],
                    "secret_archive_sha256": package_receipt["secret_archive_sha256"],
                },
            }
            candidate_path = root / "synthetic_candidate_lock.json"
            candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            public = package / "stage/PUBLIC"

            with mock.patch.object(predictor, "verify_candidate_lock", return_value=candidate):
                _run_main(
                    predictor,
                    "--public", str(public),
                    "--candidate-lock", str(candidate_path),
                    "--output", str(predictions),
                    "--workers", "8",
                )
            with mock.patch.object(locker, "verify_candidate_lock", return_value=candidate):
                _run_main(
                    locker,
                    "--public", str(public),
                    "--candidate-lock", str(candidate_path),
                    "--predictions", str(predictions),
                )
            with (
                mock.patch.object(scorer, "verify_candidate_lock", return_value=candidate),
                mock.patch.object(locker, "verify_candidate_lock", return_value=candidate),
            ):
                _run_main(
                    scorer,
                    "--public", str(public),
                    "--candidate-lock", str(candidate_path),
                    "--predictions", str(predictions),
                    "--secret-zip",
                    str(package / "FormulaGuard_V5_PSL_SECRET_360.zip"),
                    "--output", str(scored),
                )

            summary = json.loads(
                (scored / "independent_360_summary.json").read_text(encoding="utf-8")
            )
            receipt = json.loads((scored / "score_receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["events"], 360)
            self.assertEqual(summary["method_events"], 1440)
            self.assertEqual(summary["current_model_name"], "V5-PSL-dev1")
            self.assertTrue(summary["all_360_cases_retained"])
            self.assertTrue(summary["labels_opened_only_after_prediction_lock"])
            self.assertTrue(receipt["formal_version_not_created_by_scorer"])


if __name__ == "__main__":
    unittest.main()
