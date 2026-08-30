from __future__ import annotations

import csv
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from formulaguard.v5_psl import v5_psl_default_parameters
from formulaguard.v5_psl_corpora import (
    INVENTORY_FIELDS,
    adapt_corpus,
    load_registry,
    safe_extract_zip,
)
from formulaguard.v5_psl_protocol import (
    PREDICTION_METHODS,
    canonical_json_sha256,
    combined_shards_sha256,
    deterministic_zip,
    sha256,
)
import scripts.freeze_v5_psl_candidate as freeze_candidate
from scripts.audit_v5_psl_public_pressure import (
    _audit_inventories,
    _audit_pressure_run,
    _audit_supplemental_roles,
    _verify_acquisition,
)
from scripts.audit_v5_psl_supplemental_corpora import (
    _forepbench,
    _spreadsheetbench,
    _write as write_role_audit,
)
from scripts.build_v5_psl_third_party_pack import validate_case_pair
from scripts.build_v6_dataset import write_xlsx
from scripts.run_v5_psl_predictions import (
    FORBIDDEN_SECRET_NAMES,
    REQUIRED_CANDIDATE_SOURCES,
    audit_prediction_shard,
    git_head,
    predict_workbook,
    verify_candidate_lock,
)
from scripts.run_v5_psl_public_pressure import (
    PRESSURE_EVENT_FIELDS,
    PRESSURE_FIELDS,
    PRESSURE_METHODS,
    _predict as predict_pressure_workbook,
    audit_shard as audit_pressure_shard,
    _write_development_signatures,
    _write_events,
    read_manifest as read_pressure_manifest,
)
from scripts.score_v5_psl_blind import (
    promotion_gates,
    promotion_metrics,
    summarize_all,
    summarize_method,
)
from scripts.tune_v5_psl_parameters import (
    BASELINE_ID,
    _audit_case as audit_tuning_case,
    _case_task as run_tuning_case,
    assign_group_folds,
    select_profile,
    tuning_profiles,
)
from scripts.verify_v5_psl_prediction_lock import _validate_prediction_inventory


ROOT = Path(__file__).resolve().parents[1]


def passed_literature_gate() -> dict[str, object]:
    reviewed = [
        {
            "claim_area": area,
            "citation_key": citation_key,
            "title": f"Unit primary source {index}",
            "stable_locator": f"https://example.test/source/{index}",
            "primary_source_checked": True,
            "evidence_scope": "full_text",
            "checked_on": "2026-08-30",
            "overlap_assessment": "known_component",
            "permitted_claim": "bounded combination claim",
            "forbidden_claim": "unbounded novelty claim",
            "source_sha256": f"{index:x}" * 64,
            "evidence_sha256": f"{index:x}" * 64,
        }
        for index, (citation_key, area) in enumerate(
            sorted(freeze_candidate.REQUIRED_LITERATURE_SOURCES.items()), 1
        )
    ]
    reviewed.extend(
        {
            "claim_area": area,
            "citation_key": citation_key,
            "title": f"Unit unavailable source {index}",
            "stable_locator": f"https://example.test/unavailable/{index}",
            "primary_source_checked": False,
            "evidence_scope": "full_text_unavailable_disclosed",
            "checked_on": None,
            "availability_checked_on": "2026-08-30",
            "retrieval_status": "closed_no_legal_full_text_found",
            "retrieval_attempts": sorted(
                freeze_candidate.REQUIRED_AVAILABILITY_CHECKS
            ),
            "overlap_assessment": "known_component_full_text_unavailable",
            "permitted_claim": "availability disclosure only",
            "forbidden_claim": "unavailable source supports novelty",
            "source_sha256": f"{index:x}" * 64,
            "evidence_sha256": f"{index:x}" * 64,
        }
        for index, (citation_key, area) in enumerate(
            sorted(
                freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES.items()
            ),
            len(reviewed) + 1,
        )
    )
    return {
        "protocol": freeze_candidate.LITERATURE_PROTOCOL,
        "passed": True,
        "required_claim_areas": sorted(freeze_candidate.LITERATURE_AREAS),
        "required_citation_keys": sorted(
            freeze_candidate.REQUIRED_LITERATURE_SOURCES
        ),
        "disclosed_unavailable_citation_keys": sorted(
            freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES
        ),
        "amendment": dict(freeze_candidate.LITERATURE_AMENDMENT),
        "primary_sources_verified": len(
            freeze_candidate.REQUIRED_LITERATURE_SOURCES
        ),
        "claim_matrix_sha256": sha256(ROOT / "research/V5_PSL_CLAIM_MATRIX.md"),
        "reviewed_sources": reviewed,
        "disclosed_unavailable_sources": sorted(
            freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES
        ),
        "unresolved_sources": [],
        "unresolved_claims": [],
    }


def workbook_pair(root: Path) -> tuple[Path, Path]:
    cells = {"A1": 2, "B1": 3}
    original_formulas = {"C1": "=A1+B1", "D1": "=C1*2"}
    changed_formulas = {"C1": "=A1-B1", "D1": "=C1*2"}
    original = root / "original.xlsx"
    changed = root / "changed.xlsx"
    write_xlsx(original, [("Model", cells, original_formulas)])
    write_xlsx(changed, [("Model", cells, changed_formulas)])
    return original, changed


def pressure_run(
    root: Path,
    *,
    case_count: int = 1,
) -> tuple[Path, Path, dict[str, str]]:
    original, changed = workbook_pair(root)
    row = {
        "instance_id": "pressure_001",
        "corpus_id": "info1",
        "workbook": changed.name,
        "original_workbook": original.name,
        "case_kind": "error",
        "source_cells": "Model!C1",
        "identifiability": "identifiable",
        "control_subtype": "",
        "include": "1",
        "exclusion_reason": "",
        "license_id": "unit-test",
    }
    rows = [
        {
            **row,
            "instance_id": f"pressure_{index:03d}",
            "workbook": f"changed_{index:03d}.xlsx",
        }
        for index in range(1, case_count + 1)
    ]
    for current in rows:
        (root / current["workbook"]).write_bytes(changed.read_bytes())
    manifest = root / "manifest.csv"
    with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PRESSURE_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    run = root / "run"
    (run / "shards").mkdir(parents=True)
    shards = []
    for current in rows:
        shard = run / "shards" / f"{current['instance_id']}.json"
        shard.write_text(
            json.dumps(predict_pressure_workbook(
                root / current["workbook"], current["instance_id"], current["workbook"],
            )),
            encoding="utf-8",
        )
        shards.append(shard)
    metadata = {
        "protocol": "v5_psl_public_pressure_run_v1",
        "manifest_sha256": sha256(manifest),
        "included_cases": len(rows),
        "excluded_cases": 0,
        "git_commit": git_head(),
        "source_sha256": {
            relative: sha256(ROOT / relative)
            for relative in REQUIRED_CANDIDATE_SOURCES
        },
        "clean_git_worktree_before_prediction": True,
        "methods": list(PRESSURE_METHODS),
        "parameters": v5_psl_default_parameters(),
        "label_inputs_to_model": [],
        "labels_used_after_prediction_for_development_scoring": [
            "case_kind", "source_cells", "identifiability", "control_subtype",
        ],
        "third_party_confirmation_files_read": [],
    }
    metadata_path = run / "public_pressure_metadata.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    events = _write_events(run, rows)
    signatures = _write_development_signatures(manifest, rows, run)
    completion = {
        "protocol": "v5_psl_public_pressure_completion_v1",
        "complete": True,
        "cases": len(rows),
        "method_events": len(events),
        "methods": list(PRESSURE_METHODS),
        "combined_shards_sha256": combined_shards_sha256(shards),
        "events_sha256": sha256(run / "public_pressure_events.csv"),
        "development_signatures": len(signatures),
        "development_signatures_sha256": sha256(
            run / "development_formula_change_signatures.txt"
        ),
        "manifest_sha256": sha256(manifest),
        "metadata_sha256": sha256(metadata_path),
        "full_ranking_audit_passed": True,
        "third_party_confirmation_files_read": [],
    }
    (run / "public_pressure_complete.json").write_text(
        json.dumps(completion), encoding="utf-8",
    )
    return manifest, run, row


class V5PSLToolTests(unittest.TestCase):
    def test_bounded_tuning_grid_and_grouped_selection_are_fixed(self):
        profiles = tuning_profiles()
        self.assertEqual(len(profiles), 12)
        for values in profiles.values():
            self.assertGreaterEqual(values["strong_effect"], 0.20)
            self.assertGreaterEqual(values["strong_stability"], 0.75)
            self.assertGreaterEqual(values["weak_effect"], 0.10)
            self.assertGreaterEqual(values["weak_stability"], 0.60)
            self.assertLessEqual(values["weak_tail"], 0.20)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _run, _row = pressure_run(root, case_count=2)
            rows = read_pressure_manifest(manifest)
            rows[1]["corpus_id"] = "modified_euses"
            groups, folds = assign_group_folds(rows, root)
            self.assertEqual(len(set(groups.values())), 1)
            self.assertEqual(len(set(folds.values())), 1)

        summary = {
            "supported_rate": 1.0,
            "error_top5": 0.60,
            "control_actionable_rate": 0.10,
            "review_efficiency_per_100_cells": 9.0,
        }
        summaries = {profile_id: dict(summary) for profile_id in profiles}
        summaries[BASELINE_ID] = {"review_efficiency_per_100_cells": 8.0}
        fold_rows = [{
            "case_kind": "error", "state": "review", "top1": 1, "top5": 1,
            "mrr": 1.0, "actionable": 1, "inspected_cells": 1, "action_hit": 1,
        }, {
            "case_kind": "control", "state": "abstain_unidentifiable",
            "top1": "", "top5": "", "mrr": "", "actionable": 0,
            "inspected_cells": 0, "action_hit": 0,
        }]
        folds = {
            profile_id: [list(fold_rows) for _ in range(5)]
            for profile_id in profiles
        }
        selected, decisions = select_profile(summaries, folds)
        self.assertEqual(selected, min(profiles))
        self.assertTrue(all(row["eligible"] for row in decisions.values()))

        summaries[next(iter(profiles))]["error_top5"] = 0.59
        for profile_id in list(profiles)[1:]:
            summaries[profile_id]["control_actionable_rate"] = 0.20
        selected, _decisions = select_profile(summaries, folds)
        self.assertIsNone(selected)

    def test_bounded_tuning_audit_binds_provenance_and_action_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _run, row = pressure_run(root)
            output = root / "tuning"
            profiles = tuning_profiles()
            for profile_id in (*profiles, BASELINE_ID):
                (output / "shards" / profile_id).mkdir(parents=True)
            run_tuning_case((
                str(root), str(output), row["instance_id"], row["workbook"],
            ))
            audit_tuning_case(output, root, row, profiles)

            shard = output / "shards" / "default_m15" / "pressure_001.json"
            record = json.loads(shard.read_text(encoding="utf-8"))
            record["result"]["state"] = "localized"
            record["result"]["review_cells"] = []
            shard.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "action budget"):
                audit_tuning_case(output, root, row, profiles)

    def test_literature_template_matches_preregistered_protocol_and_source_areas(self):
        template = json.loads(
            (ROOT / "research/V5_PSL_LITERATURE_GATE_TEMPLATE.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(template["protocol"], freeze_candidate.LITERATURE_PROTOCOL)
        self.assertEqual(
            template["required_claim_areas"],
            sorted(freeze_candidate.LITERATURE_AREAS),
        )
        self.assertEqual(
            template["required_citation_keys"],
            sorted(freeze_candidate.REQUIRED_LITERATURE_SOURCES),
        )
        self.assertEqual(
            template["disclosed_unavailable_citation_keys"],
            sorted(freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES),
        )
        self.assertEqual(template["amendment"], freeze_candidate.LITERATURE_AMENDMENT)
        self.assertEqual(
            {
                row["citation_key"]: row["claim_area"]
                for row in template["reviewed_sources"]
            },
            {
                **freeze_candidate.REQUIRED_LITERATURE_SOURCES,
                **freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES,
            },
        )

    def test_literature_progress_binds_claim_matrix_and_unavailable_disclosures(self):
        progress = json.loads(
            (ROOT / "research/V5_PSL_LITERATURE_GATE_PROGRESS.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(progress["passed"])
        self.assertEqual(progress["protocol"], freeze_candidate.LITERATURE_PROTOCOL)
        self.assertEqual(
            progress["claim_matrix_sha256"],
            sha256(ROOT / "research/V5_PSL_CLAIM_MATRIX.md"),
        )
        reviewed = {
            row["citation_key"]: row for row in progress["reviewed_sources"]
        }
        verified = {
            citation_key
            for citation_key, row in reviewed.items()
            if row["primary_source_checked"] is True
        }
        self.assertEqual(verified, set(freeze_candidate.REQUIRED_LITERATURE_SOURCES))
        self.assertEqual(progress["primary_sources_verified"], len(verified))
        self.assertEqual(progress["unresolved_sources"], [])
        self.assertEqual(progress["unresolved_claims"], [])
        self.assertEqual(
            set(progress["disclosed_unavailable_sources"]),
            set(freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES),
        )
        for citation_key, row in reviewed.items():
            if citation_key in verified:
                self.assertEqual(row["evidence_scope"], "full_text")
                self.assertEqual(len(row["source_sha256"]), 64)
                self.assertEqual(len(row["evidence_sha256"]), 64)
            else:
                self.assertIn(
                    citation_key,
                    freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES,
                )
                self.assertEqual(
                    row["evidence_scope"], "full_text_unavailable_disclosed"
                )
                self.assertEqual(len(row["source_sha256"]), 64)
                self.assertEqual(len(row["evidence_sha256"]), 64)

    def test_literature_gate_allows_multiple_sources_but_requires_preregistered_full_texts(self):
        payload = passed_literature_gate()
        extra = dict(payload["reviewed_sources"][0])
        extra["citation_key"] = "supplemental_primary_source"
        extra["title"] = "Supplemental primary source"
        extra["source_sha256"] = "e" * 64
        extra["evidence_sha256"] = "f" * 64
        payload["reviewed_sources"].append(extra)
        payload["primary_sources_verified"] += 1
        self.assertEqual(
            len(freeze_candidate._validate_literature_gate(payload)),
            len(freeze_candidate.REQUIRED_LITERATURE_SOURCES)
            + len(freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES)
            + 1,
        )

        payload = passed_literature_gate()
        payload["reviewed_sources"][0]["evidence_scope"] = "abstract"
        with self.assertRaisesRegex(ValueError, "not based on full text"):
            freeze_candidate._validate_literature_gate(payload)

        payload = passed_literature_gate()
        payload["reviewed_sources"].pop(0)
        payload["primary_sources_verified"] -= 1
        with self.assertRaisesRegex(ValueError, "missing protocol sources"):
            freeze_candidate._validate_literature_gate(payload)

        payload = passed_literature_gate()
        unavailable = next(
            row for row in payload["reviewed_sources"]
            if row["citation_key"]
            in freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES
        )
        payload["reviewed_sources"].remove(unavailable)
        with self.assertRaisesRegex(ValueError, "missing protocol sources"):
            freeze_candidate._validate_literature_gate(payload)

        payload = passed_literature_gate()
        unavailable = next(
            row for row in payload["reviewed_sources"]
            if row["citation_key"]
            in freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES
        )
        unavailable["primary_source_checked"] = True
        payload["primary_sources_verified"] += 1
        with self.assertRaisesRegex(ValueError, "represented as full text"):
            freeze_candidate._validate_literature_gate(payload)

        payload = passed_literature_gate()
        unavailable = next(
            row for row in payload["reviewed_sources"]
            if row["citation_key"]
            in freeze_candidate.DISCLOSED_UNAVAILABLE_LITERATURE_SOURCES
        )
        unavailable["retrieval_attempts"] = ["publisher_access_page"]
        with self.assertRaisesRegex(ValueError, "retrieval checks are incomplete"):
            freeze_candidate._validate_literature_gate(payload)

        payload = passed_literature_gate()
        payload["amendment"]["public_pressure_results_seen"] = True
        with self.assertRaisesRegex(ValueError, "access amendment"):
            freeze_candidate._validate_literature_gate(payload)

    def test_external_pair_validator_matches_real_formula_difference_and_blocks_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original, changed = workbook_pair(root)
            row = {
                "instance_id": "external_case",
                "workbook": changed.name,
                "original_workbook": original.name,
                "case_kind": "error",
                "source_cells": "Model!C1",
            }
            evidence = validate_case_pair(
                row, root, development_signatures={"0" * 64},
            )
            self.assertEqual(evidence["changed_formula_count"], 1)
            self.assertGreater(evidence["internally_observed_changed_formula_values"], 0)
            with self.assertRaisesRegex(ValueError, "overlaps"):
                validate_case_pair(
                    row, root,
                    development_signatures={str(evidence["formula_change_signature"])},
                )

    def test_label_free_joint_prediction_has_all_baselines_and_complete_rankings(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _original, workbook = workbook_pair(root)
            record = predict_workbook(workbook, "opaque_001", "changed.xlsx")
            shard = root / "opaque_001.json"
            shard.write_text(json.dumps(record), encoding="utf-8")
            audit_prediction_shard(
                shard,
                {"instance_id": "opaque_001", "workbook": "changed.xlsx"},
                root,
            )
            self.assertEqual(tuple(record["methods"]), PREDICTION_METHODS)
            self.assertTrue(all(
                len(payload["ranking"]) == record["formula_count"]
                for payload in record["methods"].values()
            ))
            record["methods"]["v5_psl_dev1"]["ranking"][-1]["cell"] = (
                record["methods"]["v5_psl_dev1"]["ranking"][0]["cell"]
            )
            shard.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                audit_prediction_shard(
                    shard,
                    {"instance_id": "opaque_001", "workbook": "changed.xlsx"},
                    root,
                )

    def test_prediction_recomputation_rejects_semantic_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _original, workbook = workbook_pair(root)
            record = predict_workbook(workbook, "opaque_001", "changed.xlsx")
            record["methods"]["v5_psl_dev1"]["ranking"][0]["score"] = -1.0
            shard = root / "opaque_001.json"
            shard.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not reproduce"):
                audit_prediction_shard(
                    shard,
                    {"instance_id": "opaque_001", "workbook": "changed.xlsx"},
                    root,
                    recompute=True,
                )

    def test_public_pressure_recomputation_rejects_semantic_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _original, workbook = workbook_pair(root)
            row = {
                "instance_id": "pressure_001",
                "workbook": workbook.name,
            }
            record = predict_pressure_workbook(workbook, row["instance_id"], row["workbook"])
            record["methods"]["full"]["ranking"][0]["score"] = -1.0
            shard = root / "pressure_001.json"
            shard.write_text(json.dumps(record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "does not reproduce"):
                audit_pressure_shard(shard, row, root, recompute=True)

    def test_candidate_lock_verifier_requires_current_commit_parameters_and_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "candidate.json"
            payload = {
                "protocol": "v5_psl_candidate_lock_v1",
                "candidate_id": f"v5-psl-dev1-{git_head()[:12]}",
                "candidate_locked": True,
                "formal_version": None,
                "formal_promotion_requires_third_party_240_120_pass": True,
                "third_party_public_seen": False,
                "third_party_labels_seen": False,
                "third_party_commitments_received_before_lock": {
                    "public_archive_sha256": "5" * 64,
                    "secret_archive_sha256": "6" * 64,
                },
                "parameters": v5_psl_default_parameters(),
                "prediction_methods": list(PREDICTION_METHODS),
                "baseline_policy": freeze_candidate.BASELINE_POLICY,
                "development_formula_change_signatures": ["0" * 64],
                "development_formula_change_signatures_sha256": canonical_json_sha256(
                    ["0" * 64]
                ),
                "development_formula_change_signatures_file_sha256": "1" * 64,
                "claim_matrix_sha256": sha256(ROOT / "research/V5_PSL_CLAIM_MATRIX.md"),
                "literature_reviewed_sources_sha256": "2" * 64,
                "literature_gate_sha256": "3" * 64,
                "pressure_audit_sha256": "4" * 64,
                "environment": {"libreoffice": "LibreOffice unit-test"},
                "third_party_files_read": [],
                "post_lock_tuning_forbidden": True,
                "clean_git_worktree_required_for_prediction": True,
                "historical_source_hashes_verified": True,
                "tag_created_by_this_script": False,
                "git_commit": git_head(),
                "source_sha256": {
                    relative: sha256(ROOT / relative)
                    for relative in REQUIRED_CANDIDATE_SOURCES
                },
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch(
                "scripts.run_v5_psl_predictions.git_worktree_clean", return_value=True,
            ):
                self.assertEqual(
                    verify_candidate_lock(path)["candidate_id"],
                    f"v5-psl-dev1-{git_head()[:12]}",
                )
                payload["parameters"] = {}
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "parameters"):
                    verify_candidate_lock(path)
                payload["parameters"] = v5_psl_default_parameters()
                payload["source_sha256"]["formulaguard/formula.py"] = "0" * 64
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "source changed"):
                    verify_candidate_lock(path)
            payload["source_sha256"]["formulaguard/formula.py"] = sha256(
                ROOT / "formulaguard/formula.py"
            )
            path.write_text(json.dumps(payload), encoding="utf-8")
            with mock.patch(
                "scripts.run_v5_psl_predictions.git_worktree_clean", return_value=False,
            ):
                with self.assertRaisesRegex(ValueError, "clean Git worktree"):
                    verify_candidate_lock(path)

    def test_candidate_freeze_binds_claim_matrix_signatures_and_libreoffice(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            signatures = root / "signatures.txt"
            signatures.write_text("0" * 64 + "\n", encoding="utf-8")
            literature = root / "literature.json"
            literature_payload = passed_literature_gate()
            literature.write_text(json.dumps(literature_payload), encoding="utf-8")
            pressure = root / "pressure.json"
            pressure_payload = {
                "protocol": "v5_psl_public_pressure_audit_v1",
                "hard_gate_passed": True,
                "ablations_complete": True,
                "mechanism_revision_count": 0,
                "corpora_audited": list(freeze_candidate.REQUIRED_CORPORA),
                "third_party_confirmation_files_read": [],
                "development_signatures_sha256": sha256(signatures),
                "git_commit": git_head(),
                "source_sha256": {
                    relative: sha256(ROOT / relative)
                    for relative in REQUIRED_CANDIDATE_SOURCES
                },
            }
            pressure.write_text(json.dumps(pressure_payload), encoding="utf-8")

            def fake_git(*args: str) -> str:
                return "" if args[0] == "status" else git_head()

            with (
                mock.patch.object(freeze_candidate, "_git", side_effect=fake_git),
                mock.patch.object(
                    freeze_candidate, "_libreoffice_version",
                    return_value="LibreOffice unit-test",
                ),
            ):
                lock = freeze_candidate.build_candidate_lock(
                    literature, pressure, signatures,
                    public_archive_sha256="5" * 64,
                    secret_archive_sha256="6" * 64,
                )
                self.assertEqual(
                    lock["development_formula_change_signatures_file_sha256"],
                    sha256(signatures),
                )
                literature_payload["claim_matrix_sha256"] = "f" * 64
                literature.write_text(json.dumps(literature_payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "claim matrix"):
                    freeze_candidate.build_candidate_lock(
                        literature, pressure, signatures,
                        public_archive_sha256="5" * 64,
                        secret_archive_sha256="6" * 64,
                    )

                literature_payload["claim_matrix_sha256"] = sha256(
                    ROOT / "research/V5_PSL_CLAIM_MATRIX.md"
                )
                literature.write_text(json.dumps(literature_payload), encoding="utf-8")
                pressure_payload["development_signatures_sha256"] = "e" * 64
                pressure.write_text(json.dumps(pressure_payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "signatures file"):
                    freeze_candidate.build_candidate_lock(
                        literature, pressure, signatures,
                        public_archive_sha256="5" * 64,
                        secret_archive_sha256="6" * 64,
                    )

                pressure_payload["development_signatures_sha256"] = sha256(signatures)
                pressure_payload["source_sha256"]["formulaguard/formula.py"] = "d" * 64
                pressure.write_text(json.dumps(pressure_payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "pressure source differs"):
                    freeze_candidate.build_candidate_lock(
                        literature, pressure, signatures,
                        public_archive_sha256="5" * 64,
                        secret_archive_sha256="6" * 64,
                    )

                pressure_payload["source_sha256"]["formulaguard/formula.py"] = sha256(
                    ROOT / "formulaguard/formula.py"
                )
                pressure.write_text(json.dumps(pressure_payload), encoding="utf-8")
                literature_payload["reviewed_sources"][0]["primary_source_checked"] = False
                literature.write_text(json.dumps(literature_payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "was not checked"):
                    freeze_candidate.build_candidate_lock(
                        literature, pressure, signatures,
                        public_archive_sha256="5" * 64,
                        secret_archive_sha256="6" * 64,
                    )

    def test_candidate_source_inventory_covers_runtime_and_regression_contracts(self):
        self.assertTrue({
            "pyproject.toml",
            "run_tests.sh",
            "tests/test_workbook.py",
            "tests/test_version_lineage.py",
            "research/V5_PSL_THIRD_PARTY_DECLARATION_TEMPLATE.json",
            "research/V5_PSL_LITERATURE_GATE_TEMPLATE.json",
            "research/V5_PSL_DEVELOPMENT_AMENDMENT_1.md",
            "research/V5_PSL_PARAMETER_TUNING_FAILURE_1.md",
            "research/V5_PSL_MECHANISM_REVISION_1.md",
        } <= REQUIRED_CANDIDATE_SOURCES)

    def test_public_archive_and_secret_commitments_are_bound_to_candidate(self):
        from scripts.run_v5_psl_predictions import _verify_public_commitments

        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            root = parent / "PUBLIC"
            root.mkdir()
            commitments = {
                name: str(index) * 64
                for index, name in enumerate(sorted(FORBIDDEN_SECRET_NAMES), 1)
            }
            (root / "secret_precommit_sha256.txt").write_text(
                "".join(
                    f"{digest}  {name}\n"
                    for name, digest in sorted(commitments.items())
                ),
                encoding="utf-8",
            )
            archive = parent / "public.zip"
            deterministic_zip(archive, root)
            candidate = {
                "third_party_commitments_received_before_lock": {
                    "public_archive_sha256": sha256(archive),
                    "secret_archive_sha256": commitments["SECRET.zip"],
                },
            }
            self.assertEqual(
                _verify_public_commitments(root, candidate)["SECRET.zip"],
                commitments["SECRET.zip"],
            )
            (root / "tampered.txt").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "PUBLIC archive differs"):
                _verify_public_commitments(root, candidate)

    def test_public_pressure_requires_auditable_original_for_every_included_case(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, _run, _row = pressure_run(root)
            with manifest.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["original_workbook"] = ""
            with manifest.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=PRESSURE_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ValueError, "Non-portable path"):
                read_pressure_manifest(manifest)

    def test_prediction_inventory_rejects_extra_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            predictions = Path(directory)
            (predictions / "shards").mkdir()
            for relative in (
                "prediction_metadata.json", "prediction_complete.json", "shards/case_1.json",
            ):
                (predictions / relative).write_text("{}", encoding="utf-8")
            rows = [{"instance_id": "case_1", "workbook": "workbooks/case_1.xlsx"}]
            _validate_prediction_inventory(predictions, rows, None)
            extra = predictions / "debug.log"
            extra.write_text("unexpected", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "extra"):
                _validate_prediction_inventory(predictions, rows, None)
            extra.unlink()
            (predictions / "metadata-link.json").symlink_to(
                predictions / "prediction_metadata.json"
            )
            with self.assertRaisesRegex(ValueError, "symbolic"):
                _validate_prediction_inventory(predictions, rows, None)

    def test_public_pressure_audit_recomputes_events_and_action_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, run, row = pressure_run(root, case_count=2)
            _audit_pressure_run(manifest, run, workers=2)

            events_path = run / "public_pressure_events.csv"
            with events_path.open("r", encoding="utf-8-sig", newline="") as handle:
                events = list(csv.DictReader(handle))
            events[0]["instance_id"] = "tampered"
            with events_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=PRESSURE_EVENT_FIELDS)
                writer.writeheader()
                writer.writerows(events)
            completion_path = run / "public_pressure_complete.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion["events_sha256"] = sha256(events_path)
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "do not reproduce"):
                _audit_pressure_run(manifest, run)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, run, row = pressure_run(root)
            shard = run / "shards/pressure_001.json"
            record = json.loads(shard.read_text(encoding="utf-8"))
            record["methods"]["full"]["state"] = "localized"
            record["methods"]["full"]["action_cells"] = []
            shard.write_text(json.dumps(record), encoding="utf-8")
            completion_path = run / "public_pressure_complete.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion["combined_shards_sha256"] = combined_shards_sha256([shard])
            completion_path.write_text(json.dumps(completion), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "action budget"):
                _audit_pressure_run(manifest, run)

    def test_enron_adapter_rejects_manifest_path_escape(self):
        registry = load_registry(ROOT / "data/external/v5_psl/corpus_registry.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (root / "outside.xlsx").write_bytes(b"not a workbook")
            with (source / "manifest.csv").open(
                "w", encoding="utf-8-sig", newline="",
            ) as handle:
                writer = csv.DictWriter(handle, fieldnames=(
                    "instance_id", "workbook", "source_cell", "include", "exclusion_reason",
                ))
                writer.writeheader()
                writer.writerow({
                    "instance_id": "escape",
                    "workbook": "../outside.xlsx",
                    "source_cell": "Model!C1",
                    "include": "1",
                    "exclusion_reason": "",
                })
            with self.assertRaisesRegex(ValueError, "escapes"):
                adapt_corpus("enron_error", source, registry["enron_error"])

    def test_promotion_metrics_apply_selective_review_efficiency_gate(self):
        events = []
        methods = list(PREDICTION_METHODS)
        for case_index in range(17):
            is_control = case_index >= 12
            is_ambiguous = 10 <= case_index < 12
            for method in methods:
                if method == "v5_psl_dev1":
                    localized = case_index < 4
                    state = "localized" if localized else "abstain_unidentifiable"
                    inspected = 1 if localized else 0
                    hit = int(localized)
                else:
                    state = "review"
                    inspected = 5
                    hit = int(not is_control)
                events.append({
                    "method": method,
                    "case_kind": "control" if is_control else "error",
                    "identifiability": "ambiguous" if is_ambiguous else "identifiable",
                    "control_subtype": "legal_exception" if is_control else "",
                    "state": state,
                    "inspected_cells": inspected,
                    "actionable": int(inspected > 0),
                    "action_hit": hit,
                    "top1": "" if is_control else 1,
                    "top5": "" if is_control else 1,
                    "mrr": "" if is_control else 1.0,
                })
        summary = summarize_all(events)
        metrics = promotion_metrics(summary)
        self.assertEqual(metrics["localized_coverage"], 0.4)
        self.assertGreater(metrics["review_efficiency_relative_improvement"], 0.15)
        self.assertTrue(all(promotion_gates(metrics).values()))

    def test_identifiable_ranking_metrics_use_full_denominator_and_unsupported_misses(self):
        rows = [
            {
                "case_kind": "error",
                "identifiability": "identifiable",
                "control_subtype": "",
                "state": state,
                "inspected_cells": inspected,
                "action_hit": hit,
                "top1": 1,
                "top5": 1,
                "mrr": 1.0,
                "actionable": int(inspected > 0),
            }
            for state, inspected, hit in (
                ("localized", 1, 1),
                ("review", 5, 1),
                ("unsupported", 0, 0),
            )
        ]
        summary = summarize_method(rows)
        self.assertEqual(summary["identifiable_error_denominator"], 3)
        self.assertAlmostEqual(summary["localized_coverage"], 1 / 3)
        self.assertAlmostEqual(summary["localized_top1"], 2 / 3)
        self.assertAlmostEqual(summary["localized_top5"], 2 / 3)

    def test_registry_and_info1_adapter_preserve_license_and_pending_conversion(self):
        registry = load_registry(ROOT / "data/external/v5_psl/corpus_registry.json")
        self.assertEqual(set(registry), set((
            "modified_euses", "info1", "integer_corpus", "enron_error",
            "forepbench", "spreadsheetbench",
        )))
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            _original, workbook = workbook_pair(source)
            workbook.rename(source / "exercise_1FAULTS_FAULTVERSION1.xlsx")
            (source / "exercise_1FAULTS_FAULTVERSION1.properties").write_text(
                "FAULTY_CELLS_1=1!3!1\n", encoding="utf-8",
            )
            rows, audit = adapt_corpus("info1", source, registry["info1"])
            self.assertEqual(len(rows), 2)
            faulty = next(row for row in rows if "FAULTVERSION" in row["relative_path"])
            self.assertEqual(faulty["source_cells_raw"], "1!3!1")
            self.assertIn("manual_sheet_index_mapping", faulty["exclusion_reason"])
            self.assertFalse(audit["license"]["redistribution_by_this_project"])

    def test_six_corpus_inventory_audit_recomputes_canonical_rows(self):
        registry = load_registry(ROOT / "data/external/v5_psl/corpus_registry.json")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audits = []
            for corpus_id, spec in registry.items():
                output = root / corpus_id
                output.mkdir()
                row = {
                    "corpus_id": corpus_id,
                    "item_id": f"{corpus_id}_unit",
                    "relative_path": "unit.xlsx",
                    "sha256": "0" * 64,
                    "file_type": "xlsx",
                    "task_scope": spec["task_scope"],
                    "label_sidecar": "",
                    "source_cells_raw": "",
                    "include_for_localization": "0",
                    "exclusion_reason": "unit_test_pending",
                }
                inventory = output / "inventory.csv"
                with inventory.open("w", encoding="utf-8-sig", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS)
                    writer.writeheader()
                    writer.writerow(row)
                payload = {
                    "protocol": "v5_psl_public_corpus_inventory_v1",
                    "corpus_id": corpus_id,
                    "items": 1,
                    "task_scope": spec["task_scope"],
                    "included_for_localization": 0,
                    "excluded_or_pending": 1,
                    "license": spec["license"],
                    "raw_data_redistributed": False,
                    "inventory_sha256": canonical_json_sha256([row]),
                    "inventory_file_sha256": sha256(inventory),
                }
                audit = output / "inventory_audit.json"
                audit.write_text(json.dumps(payload), encoding="utf-8")
                audits.append(audit)
            self.assertEqual(set(_audit_inventories(audits, registry)), set(registry))

            inventory = root / "info1/inventory.csv"
            with inventory.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["exclusion_reason"] = "tampered"
            with inventory.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=INVENTORY_FIELDS)
                writer.writeheader()
                writer.writerows(rows)
            audit = root / "info1/inventory_audit.json"
            payload = json.loads(audit.read_text(encoding="utf-8"))
            payload["inventory_file_sha256"] = sha256(inventory)
            audit.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "canonical hash"):
                _audit_inventories(audits, registry)

    def test_zip_adapter_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../escape.txt", "unsafe")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                safe_extract_zip(archive, root / "out")

    def test_acquisition_audit_reopens_pinned_archive_and_detects_extraction_tampering(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "info1"
            extracted = root / "extracted"
            extracted.mkdir(parents=True)
            archive = root / "source.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("fixture.txt", "pinned corpus bytes")
            (extracted / "fixture.txt").write_text("pinned corpus bytes", encoding="utf-8")
            spec = {
                "id": "info1",
                "acquisition": {
                    "kind": "http_zip",
                    "url": "https://example.test/info1.zip",
                    "sha256": sha256(archive),
                    "size_bytes": archive.stat().st_size,
                },
                "license": {
                    "status": "unit-test",
                    "redistribution_by_this_project": False,
                },
            }
            receipt = {
                "protocol": "v5_psl_public_corpus_acquisition_v1",
                "corpus_id": "info1",
                "source_url": spec["acquisition"]["url"],
                "license_status": spec["license"],
                "terms_acknowledged": True,
                "raw_redistribution_authorized_by_project": False,
                "archive_sha256": sha256(archive),
                "archive_size_bytes": archive.stat().st_size,
                "files_extracted": 1,
            }
            receipt["receipt_sha256"] = canonical_json_sha256(receipt)
            receipt_path = root / "acquisition_receipt.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            self.assertEqual(_verify_acquisition("info1", extracted, spec), sha256(receipt_path))
            (extracted / "fixture.txt").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "differ from the pinned archive"):
                _verify_acquisition("info1", extracted, spec)

    def test_supplemental_role_audits_never_create_localization_accuracy_events(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "FoRepBenchmarks.json"
            dataset.write_text(json.dumps([
                {
                    "faulty_formula": "=A1+\"bad\"",
                    "correct_formula": "=A1",
                    "runtime_errors": ["#VALUE!"],
                }
                for _ in range(618)
            ]), encoding="utf-8")
            rows, forep = _forepbench(root, sha256(dataset))
            self.assertEqual(len(rows), 618)
            self.assertTrue(forep["complete"])
            self.assertEqual(forep["localization_accuracy_events"], 0)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook_pair(root)
            rows, parser = _spreadsheetbench(root, limit=None, diagnose_limit=25)
            self.assertEqual(len(rows), 2)
            self.assertTrue(parser["complete"])
            self.assertEqual(parser["diagnosed_without_labels"], 2)
            self.assertEqual(parser["localization_accuracy_events"], 0)
            _rows, limited = _spreadsheetbench(root, limit=None, diagnose_limit=1)
            self.assertTrue(limited["limited"])
            self.assertFalse(limited["complete"])

    def test_supplemental_role_audit_recomputes_event_accounting(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            forep_source = root / "forep-source"
            forep_source.mkdir()
            dataset = forep_source / "FoRepBenchmarks.json"
            dataset.write_text(json.dumps([
                {
                    "faulty_formula": "=A1+\"bad\"",
                    "correct_formula": "=A1",
                    "runtime_errors": ["#VALUE!"],
                }
                for _ in range(618)
            ]), encoding="utf-8")
            forep_rows, forep_audit = _forepbench(forep_source, sha256(dataset))
            forep_output = root / "forep-audit"
            write_role_audit(forep_output, forep_rows, forep_audit)

            spreadsheet_source = root / "spreadsheet-source"
            spreadsheet_source.mkdir()
            workbook_pair(spreadsheet_source)
            spreadsheet_rows, spreadsheet_audit = _spreadsheetbench(
                spreadsheet_source, limit=None, diagnose_limit=25,
            )
            spreadsheet_output = root / "spreadsheet-audit"
            write_role_audit(spreadsheet_output, spreadsheet_rows, spreadsheet_audit)
            paths = [
                forep_output / "role_audit.json",
                spreadsheet_output / "role_audit.json",
            ]
            self.assertEqual(
                set(_audit_supplemental_roles(paths)),
                {"forepbench", "spreadsheetbench"},
            )

            events_path = forep_output / "events.csv"
            with events_path.open("r", encoding="utf-8-sig", newline="") as handle:
                events = list(csv.DictReader(handle))
                fields = tuple(events[0])
            events[0]["formula_pair_present"] = "0"
            with events_path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(events)
            audit_path = forep_output / "role_audit.json"
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
            payload["events_sha256"] = sha256(events_path)
            audit_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "accounting"):
                _audit_supplemental_roles(paths)


if __name__ == "__main__":
    unittest.main()
