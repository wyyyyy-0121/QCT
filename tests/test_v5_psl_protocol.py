from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from formulaguard.v5_psl_protocol import (
    CASE_FIELDS,
    ERROR_TYPES,
    PUBLIC_FIELDS,
    audit_design,
    model_output_projection,
    read_sha256_commitments,
    validate_complete_ranking,
    validate_public_manifest,
)


DECLARATION = {
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
    "custodian_id": "custodian_external_01",
    "calculation_engine": "LibreOffice Calc",
    "calculation_engine_version": "unit-test",
    "permission_evidence_sha256": "a" * 64,
    "anonymization_evidence_sha256": "b" * 64,
    "case_plan_sha256": "c" * 64,
    "template_overlap_evidence_sha256": "d" * 64,
}


def complete_design() -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    error_index = 0
    for template_index in range(30):
        template_id = f"template_{template_index + 1:02d}"
        origin = "steward_owned" if template_index < 20 else "licensed_public"
        license_id = f"permission_{template_index + 1:02d}"
        for case_index in range(12):
            instance_id = f"case_{template_index + 1:02d}_{case_index + 1:02d}"
            common = {
                "instance_id": instance_id,
                "template_id": template_id,
                "steward_id": DECLARATION["custodian_id"],
                "workbook": f"workbooks/{instance_id}.xlsx",
                "original_workbook": f"originals/{instance_id}.xlsx",
                "template_origin": origin,
                "license_id": license_id,
            }
            if case_index < 8:
                identifiable = case_index < 6
                challenge = "" if identifiable else (
                    "single_source_exception_like"
                    if case_index == 6 else "symmetric_multi_source"
                )
                sources = "Model!C6" if challenge != "symmetric_multi_source" else "Model!C6;Model!C7"
                row = {
                    **common,
                    "case_kind": "error",
                    "error_type": ERROR_TYPES[error_index % len(ERROR_TYPES)],
                    "source_cells": sources,
                    "identifiability": "identifiable" if identifiable else "ambiguous",
                    "control_subtype": "",
                    "challenge_stratum": challenge,
                    "adjudication_rationale": (
                        "Objective ambiguity stratum recorded before model output."
                        if not identifiable else ""
                    ),
                }
                error_index += 1
            else:
                row = {
                    **common,
                    "case_kind": "control",
                    "error_type": "",
                    "source_cells": "",
                    "identifiability": "",
                    "control_subtype": "regular" if case_index < 10 else "legal_exception",
                    "challenge_stratum": "",
                    "adjudication_rationale": (
                        "Valid formula exception retained as a clean control."
                        if case_index >= 10 else ""
                    ),
                }
            cases.append({field: row[field] for field in CASE_FIELDS})
    return cases


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


class V5PSLProtocolTests(unittest.TestCase):
    def test_model_projection_ignores_only_runtime_measurements(self):
        recorded = {
            "state": "localized",
            "elapsed_seconds": 0.1,
            "runtime_seconds": 0.2,
            "ranking": [{
                "rank": 1,
                "cell": "Model!A1",
                "evidence": {
                    "localization_seconds": 0.3,
                    "role_consistency": 0.75,
                },
            }],
        }
        independently_recomputed = {
            **recorded,
            "elapsed_seconds": 1.1,
            "runtime_seconds": 1.2,
            "ranking": [{
                **recorded["ranking"][0],
                "evidence": {
                    "localization_seconds": 1.3,
                    "role_consistency": 0.75,
                },
            }],
        }
        projection = model_output_projection(recorded)
        self.assertEqual(projection, model_output_projection(independently_recomputed))

        for semantic_change in (
            {**independently_recomputed, "state": "review"},
            {
                **independently_recomputed,
                "ranking": [{
                    **independently_recomputed["ranking"][0],
                    "cell": "Model!A2",
                }],
            },
            {
                **independently_recomputed,
                "ranking": [{
                    **independently_recomputed["ranking"][0],
                    "evidence": {
                        "localization_seconds": 1.3,
                        "role_consistency": 0.5,
                    },
                }],
            },
        ):
            self.assertNotEqual(projection, model_output_projection(semantic_change))

    def test_exact_240_error_120_control_design_passes(self):
        cases = complete_design()
        result = audit_design(cases, DECLARATION)
        self.assertTrue(result["passed"])
        self.assertEqual(result["counts"]["total"], 360)
        self.assertEqual(result["counts"]["errors"], 240)
        self.assertEqual(result["counts"]["controls"], 120)
        self.assertEqual(result["counts"]["stewards"], 1)
        self.assertEqual(result["counts"]["manual_adjudication_rationales"], 120)
        self.assertEqual(result["error_types"], {name: 40 for name in ERROR_TYPES})

    def test_project_generated_profile_preserves_non_external_claim(self):
        cases = complete_design()
        declaration = {
            "independent_custodian": False,
            "model_was_run": False,
            "dataset_origin": "project_generated",
            "creator_id": "project_generator_v1",
            "custodian_id": DECLARATION["custodian_id"],
            "custodian_is_creator": False,
        }
        result = audit_design(
            cases, declaration, declaration_profile="project_generated",
        )
        self.assertEqual(
            result["protocol"], "formulaguard_project_generated_design_audit_v1",
        )

    def test_project_generated_profile_rejects_external_claim(self):
        cases = complete_design()
        declaration = {
            "independent_custodian": True,
            "model_was_run": False,
            "dataset_origin": "project_generated",
            "creator_id": "project_generator_v1",
            "custodian_id": DECLARATION["custodian_id"],
            "custodian_is_creator": False,
        }
        with self.assertRaisesRegex(ValueError, "independent_custodian=False"):
            audit_design(
                cases, declaration, declaration_profile="project_generated",
            )

    def test_design_rejects_multiple_stewards(self):
        cases = complete_design()
        cases[0]["steward_id"] = "second_steward"
        with self.assertRaisesRegex(ValueError, "one independent steward"):
            audit_design(cases, DECLARATION)

    def test_design_requires_documented_matching_custodian(self):
        cases = complete_design()
        declaration = {**DECLARATION, "custodian_id": "different_custodian"}
        with self.assertRaisesRegex(ValueError, "steward_id"):
            audit_design(cases, declaration)

        declaration = {**DECLARATION, "calculation_engine_version": ""}
        with self.assertRaisesRegex(ValueError, "calculation engine"):
            audit_design(cases, declaration)

        declaration = {**DECLARATION, "case_plan_sha256": "not-a-hash"}
        with self.assertRaisesRegex(ValueError, "case_plan_sha256"):
            audit_design(cases, declaration)

        declaration = dict(DECLARATION)
        declaration.pop("single_custodian_design_acknowledged")
        declaration["reviewers_worked_independently"] = True
        with self.assertRaisesRegex(ValueError, "single_custodian_design_acknowledged"):
            audit_design(cases, declaration)

    def test_design_rejects_ambiguous_source_count_mismatch(self):
        cases = complete_design()
        row = next(item for item in cases if item["challenge_stratum"] == "symmetric_multi_source")
        row["source_cells"] = "Model!C6"
        with self.assertRaisesRegex(ValueError, "2 to 5 sources"):
            audit_design(cases, DECLARATION)

    def test_design_requires_rationale_for_subjective_strata(self):
        cases = complete_design()
        row = next(item for item in cases if item["identifiability"] == "ambiguous")
        row["adjudication_rationale"] = ""
        with self.assertRaisesRegex(ValueError, "adjudication rationale"):
            audit_design(cases, DECLARATION)

    def test_public_manifest_accepts_only_exact_label_free_fields_and_safe_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "workbooks").mkdir()
            (root / "workbooks/a.xlsx").write_bytes(b"fixture")
            manifest = root / "manifest.csv"
            write_csv(
                manifest,
                PUBLIC_FIELDS,
                [{"instance_id": "opaque_001", "workbook": "workbooks/a.xlsx"}],
            )
            rows = validate_public_manifest(manifest, root, expected_count=1)
            self.assertEqual(rows[0]["instance_id"], "opaque_001")

            write_csv(
                manifest,
                (*PUBLIC_FIELDS, "source_cells"),
                [{
                    "instance_id": "opaque_001",
                    "workbook": "workbooks/a.xlsx",
                    "source_cells": "Model!A1",
                }],
            )
            with self.assertRaisesRegex(ValueError, "exactly"):
                validate_public_manifest(manifest, root, expected_count=1)

    def test_public_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root.parent / "outside.xlsx"
            outside.write_bytes(b"fixture")
            try:
                manifest = root / "manifest.csv"
                write_csv(
                    manifest,
                    PUBLIC_FIELDS,
                    [{"instance_id": "opaque_001", "workbook": "../outside.xlsx"}],
                )
                with self.assertRaisesRegex(ValueError, "escapes root"):
                    validate_public_manifest(manifest, root, expected_count=1)
            finally:
                outside.unlink(missing_ok=True)

    def test_complete_ranking_rejects_duplicate_or_missing_cells(self):
        formula_cells = {"Model!A1", "Model!A2"}
        validate_complete_ranking(
            [{"rank": 1, "cell": "Model!A1"}, {"rank": 2, "cell": "Model!A2"}],
            formula_cells,
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_complete_ranking(
                [{"rank": 1, "cell": "Model!A1"}, {"rank": 2, "cell": "Model!A1"}],
                formula_cells,
            )

    def test_commitment_parser_rejects_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hashes.txt"
            digest = "a" * 64
            path.write_text(f"{digest}  SECRET.zip\n{digest}  SECRET.zip\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                read_sha256_commitments(path)


if __name__ == "__main__":
    unittest.main()
