from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from formulaguard.v6 import _effective_rows, _prepare_v6, semantic_candidates, v6_scores
from formulaguard.workbook import WorkbookModel
from scripts.build_v6_dataset import Case, build_case, enumerate_cases, write_xlsx
from scripts.build_v6_third_party_pack import validate_external_case
from scripts.run_v6_blind_lock import audit_locked_shard
from scripts.run_v6_enron import DEFAULT_ENRON_MANIFEST, EXPECTED_RETROSPECTIVE_EVENTS, included_events
from scripts.run_v6_predictions import audit_complete_shard


ROOT = Path(__file__).resolve().parents[1]


def sha256(path: Path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class V6ProtocolTests(unittest.TestCase):
    @staticmethod
    def _minimal_v6_evidence():
        return {
            "model_version": "v6-semantic-r1", "v4_rank": 1, "v6_rank": 1,
            "semantic_tier": "none", "candidate_portfolio": [],
            "candidate_formulas": [], "semantic_energy_gain": 0.0,
            "counterfactual_delta": 0.0, "counterfactual_irg": 0.0,
            "global_harm": 0.0, "promotion_reason": "not_promoted",
            "propagation_path": [],
        }
    def test_frozen_v4_and_v52_sources_are_unchanged(self):
        v4 = json.loads((ROOT / "research/frozen_config_v4.json").read_text(encoding="utf-8"))
        v52 = json.loads((ROOT / "research/frozen_config_v52.json").read_text(encoding="utf-8"))
        self.assertEqual(sha256(ROOT / "formulaguard/localize.py"), v4["model_source_sha256"]["formulaguard/localize.py"])
        self.assertEqual(sha256(ROOT / "formulaguard/localize.py"), v52["model_source_sha256"]["formulaguard/localize.py"])
        self.assertEqual(sha256(ROOT / "formulaguard/v52.py"), v52["model_source_sha256"]["formulaguard/v52.py"])

    def test_v6_enron_default_uses_all_30_evaluation_ready_events(self):
        events = included_events(DEFAULT_ENRON_MANIFEST)
        self.assertEqual(len(events), EXPECTED_RETROSPECTIVE_EVENTS)
        self.assertEqual(len({row["instance_id"] for row in events}), EXPECTED_RETROSPECTIVE_EVENTS)
        self.assertTrue(all(row.get("include") == "1" for row in events))

    def test_v6_public_signature_is_exact_and_label_free(self):
        self.assertEqual(
            list(inspect.signature(v6_scores).parameters),
            ["model", "variant", "base_candidate_limit", "semantic_candidate_limit"],
        )

    def test_locked_selection_does_not_add_a_development_gate(self):
        source = (ROOT / "scripts/select_v6_variant.py").read_text(encoding="utf-8")
        self.assertNotIn('"development_round_passed":', source)
        self.assertIn('"development_round_passed_diagnostic":', source)
        self.assertIn("one-shot 360-event locked validation", source)

    def test_cross_sheet_range_candidate(self):
        cells = {}
        formulas = {}
        for row in range(2, 9):
            for col, value in zip("BCD", (row, row + 1, row + 2)):
                cells[("Inputs", f"{col}{row}")] = value
            formulas[("Model", f"E{row}")] = f"=SUM('Inputs'!B{row}:'Inputs'!D{row})"
        formulas[("Model", "E5")] = "=SUM('Inputs'!B5:'Inputs'!C5)"
        model = WorkbookModel.from_cells(cells, formulas)
        candidates = semantic_candidates(model, ("Model", "E5"))
        self.assertTrue(any(item.candidate.formula == "=SUM('Inputs'!B5:'Inputs'!D5)" for item in candidates))

    def test_generated_xlsx_is_silent_and_propagates(self):
        case = Case("unit", "smoke", "function_replacement", "cross_sheet", "small", "deep", "unit_template", 12345)
        mutant_sheets, source, correct, mutant, sink = build_case(case)
        clean_sheets, *_ = build_case(case, clean_only=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_xlsx(root / "mutant.xlsx", mutant_sheets)
            write_xlsx(root / "clean.xlsx", clean_sheets)
            clean = WorkbookModel.from_xlsx(root / "clean.xlsx")
            changed = WorkbookModel.from_xlsx(root / "mutant.xlsx")
            self.assertFalse(clean.evaluate()[1])
            self.assertFalse(changed.evaluate()[1])
            source_key = tuple(source.rsplit("!", 1)); sink_key = tuple(sink.rsplit("!", 1))
            self.assertIsNotNone(changed.dependency_graph().shortest_path_length(source_key, sink_key))
            self.assertNotEqual(clean.evaluate()[0][sink_key], changed.evaluate()[0][sink_key])
            self.assertNotEqual(correct, mutant)

    def test_all_adjacent_shift_cases_change_the_preregistered_sink(self):
        """Guard every development/red-team reference and copy-offset case.

        These are the only two mutation families whose numerical effect can
        disappear when adjacent input values happen to be equal.  Checking the
        complete preregistered case inventory prevents a small smoke sample
        from hiding that generator failure again.
        """

        def model_from_sheets(sheets):
            cells = {
                (sheet, address): value
                for sheet, sheet_cells, _ in sheets
                for address, value in sheet_cells.items()
            }
            formulas = {
                (sheet, address): formula
                for sheet, _, sheet_formulas in sheets
                for address, formula in sheet_formulas.items()
            }
            return WorkbookModel.from_cells(cells, formulas)

        checked = 0
        for profile in ("development", "redteam"):
            for case in enumerate_cases(profile):
                if case.error_type not in {"reference_shift", "copy_offset"}:
                    continue
                mutant_sheets, source, correct, mutant, sink = build_case(case)
                clean_sheets, *_ = build_case(case, clean_only=True)
                clean = model_from_sheets(clean_sheets)
                changed = model_from_sheets(mutant_sheets)
                clean_values, clean_errors = clean.evaluate()
                changed_values, changed_errors = changed.evaluate()
                source_key = tuple(source.rsplit("!", 1))
                sink_key = tuple(sink.rsplit("!", 1))
                self.assertFalse(clean_errors, case.instance_id)
                self.assertFalse(changed_errors, case.instance_id)
                self.assertNotEqual(correct, mutant, case.instance_id)
                self.assertIsNotNone(
                    changed.dependency_graph().shortest_path_length(source_key, sink_key),
                    case.instance_id,
                )
                self.assertNotEqual(
                    clean_values[sink_key], changed_values[sink_key], case.instance_id
                )
                checked += 1
        self.assertEqual(checked, 520)

    def test_external_case_validator_requires_a_real_single_formula_pair(self):
        case = Case("external_unit", "smoke", "operator", "chain", "small", "shallow", "outside_01", 99173)
        mutant_sheets, source, correct, mutant, sink = build_case(case)
        clean_sheets, *_ = build_case(case, clean_only=True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mutant_path, original_path = root / "mutant.xlsx", root / "original.xlsx"
            write_xlsx(mutant_path, mutant_sheets)
            write_xlsx(original_path, clean_sheets)
            row = {
                "instance_id": "external_unit", "template_id": "outside_01",
                "error_type": "operator", "topology": "chain", "complexity": "small",
                "depth": "shallow", "construction_mode": "programmatic",
                "non_simple_neighbor_shift": "true", "mutant_workbook": str(mutant_path),
                "original_workbook": str(original_path), "source_cell": source,
                "correct_formula": correct, "mutated_formula": mutant, "sink_cell": sink,
                "source_origin": "third_party_unit", "notes": "test",
            }
            evidence = validate_external_case(row, {"outside_01"})
            self.assertGreaterEqual(evidence["actual_depth"], 1)
            self.assertGreater(evidence["formula_count"], 0)

    def test_final_pack_refuses_to_generate_its_own_independent_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pack"
            completed = subprocess.run(
                [
                    sys.executable, str(ROOT / "scripts/build_v6_third_party_pack.py"),
                    "--output", str(output), "--secret-seed", "123",
                    "--template-config", str(ROOT / "research/V6_THIRD_PARTY_TEMPLATE_EXAMPLE.json"),
                    "--final",
                ],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertNotEqual(completed.returncode, 0)
            self.assertIn("--case-manifest", completed.stdout + completed.stderr)
            self.assertFalse((output / "stage").exists())

    def test_completion_audits_reject_duplicate_or_missing_formula_ranks(self):
        case = Case("audit_unit", "smoke", "operator", "chain", "small", "shallow", "audit", 7731)
        mutant_sheets, *_ = build_case(case)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workbook = root / "case.xlsx"
            write_xlsx(workbook, mutant_sheets)
            model = WorkbookModel.from_xlsx(workbook)
            cells = [f"{sheet}!{address}" for sheet, address in model.formula_cells]
            v4 = [{"rank": rank, "cell": cell, "evidence": {}} for rank, cell in enumerate(cells, 1)]
            v6 = [
                {"rank": rank, "cell": cell, "evidence": self._minimal_v6_evidence()}
                for rank, cell in enumerate(cells, 1)
            ]
            digest = sha256(workbook)
            general = {
                "instance_id": "audit_unit", "workbook": "case.xlsx",
                "workbook_sha256": digest, "formula_count": len(cells),
                "rankings": {"v4": v4, "v6_a": v6},
            }
            shard = root / "audit_unit.json"
            shard.write_text(json.dumps(general), encoding="utf-8")
            audit_complete_shard(
                shard, {"instance_id": "audit_unit", "mutant_workbook": "case.xlsx"},
                root, {"v4", "v6_a"},
            )
            blind = dict(general)
            blind["rankings"] = {"v4": v4, "v6": v6}
            shard.write_text(json.dumps(blind), encoding="utf-8")
            audit_locked_shard(shard, {"instance_id": "audit_unit", "workbook": "case.xlsx"}, root)
            blind["rankings"]["v6"][-1]["cell"] = blind["rankings"]["v6"][0]["cell"]
            shard.write_text(json.dumps(blind), encoding="utf-8")
            with self.assertRaises(SystemExit):
                audit_locked_shard(shard, {"instance_id": "audit_unit", "workbook": "case.xlsx"}, root)

    def test_boundary_semantics_preserve_function_and_enable_safe_promotion(self):
        case = Case(
            "unit_boundary", "smoke", "range_boundary", "fanout", "medium",
            "medium", "smoke_01", 600001,
        )
        mutant_sheets, source, correct, *_ = build_case(case)
        with tempfile.TemporaryDirectory() as directory:
            workbook = Path(directory) / "boundary.xlsx"
            write_xlsx(workbook, mutant_sheets)
            model = WorkbookModel.from_xlsx(workbook)
            prepared = _prepare_v6(model, 15, 25)
            source_key = tuple(source.rsplit("!", 1))
            raw = prepared["effects_by_cell"][source_key]
            effective_a = _effective_rows(raw, "a", None)
            effective_b = _effective_rows(raw, "b", None)
            effective_b_without_bss = _effective_rows(raw, "b", "no_bss")
            rankings = {variant: v6_scores(model, variant=variant) for variant in "abc"}

        def correct_row(rows):
            return next(row for row in rows if row["candidate"].formula == correct)

        self.assertEqual(correct_row(effective_a)["effective_boundary_support"], 0.0)
        self.assertEqual(correct_row(effective_b_without_bss)["effective_boundary_support"], 0.0)
        self.assertEqual(correct_row(effective_a)["semantic_energy_gain"], 0.0)
        self.assertGreaterEqual(correct_row(effective_b)["effective_boundary_support"], 0.60)
        self.assertGreaterEqual(correct_row(effective_b)["semantic_energy_gain"], 0.05)

        source_rows = {
            variant: next(row for row in rows if row.cell_label == source)
            for variant, rows in rankings.items()
        }
        source_ranks = {
            variant: next(rank for rank, row in enumerate(rows, 1) if row.cell_label == source)
            for variant, rows in rankings.items()
        }
        # The exact V4 rank may move when label-independent input values change;
        # the protocol invariant is that A retains that V4 rank while B/C alone
        # can use boundary evidence to promote the cell.
        self.assertEqual(source_ranks["a"], source_rows["a"].evidence["v4_rank"])
        self.assertGreater(source_ranks["a"], 3)
        self.assertEqual(source_ranks["b"], 3)
        self.assertEqual(source_ranks["c"], 3)
        self.assertEqual(source_rows["a"].evidence["semantic_tier"], "none")
        for variant in "bc":
            self.assertEqual(source_rows[variant].candidate_formula, correct)
            self.assertEqual(source_rows[variant].evidence["semantic_tier"], "strong")
            self.assertGreaterEqual(source_rows[variant].evidence["semantic_energy_gain"], 0.05)

    def test_smoke_public_manifest_excludes_truth_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "dataset"
            completed = subprocess.run(
                [sys.executable, str(ROOT / "scripts/build_v6_dataset.py"), "--profile", "smoke", "--output", str(output), "--limit", "2"],
                cwd=ROOT, text=True, capture_output=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            public = json.loads((output / "instances.jsonl").read_text(encoding="utf-8").splitlines()[0])
            forbidden = {"source_cell", "correct_formula", "mutated_formula", "sink_cell", "mutation_type", "expected_depth"}
            self.assertFalse(forbidden & set(public))
            labels = json.loads((output / "evaluation_labels.jsonl").read_text(encoding="utf-8").splitlines()[0])
            self.assertTrue({"source_cell", "correct_formula", "mutation_type"} <= set(labels))


if __name__ == "__main__":
    unittest.main()
