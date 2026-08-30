import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.acquire_cwrp_sheetjs import acquire, collect_workbooks, parse_tree_snapshot
from scripts.build_v6_dataset import write_xlsx
from scripts.convert_cwrp_sheetjs import convert, install_converted
from scripts.build_cwrp_corpus import cluster_profiles, read_targets
from scripts.run_cwrp_self_supervised import (
    _validate_example,
    HierarchicalRolePrior,
    permute_training_targets,
    select_support_threshold,
)
from formulaguard.cwrp import (
    formula_count_ratio_eligible,
    formula_role_fingerprint,
    masked_formula_examples,
    weighted_jaccard,
    workbook_profile,
)
from formulaguard.workbook import WorkbookModel


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CWRPAcquisitionTests(unittest.TestCase):
    def test_tree_snapshot_requires_complete_nuix_blob_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tree.json"
            path.write_text(json.dumps({
                "truncated": False,
                "tree": [
                    {"path": "nuix/a.xls", "type": "blob", "size": 3},
                    {"path": "nuix/readme.txt", "type": "blob", "size": 9},
                    {"path": "edrm/b.xls", "type": "blob", "size": 99},
                ],
            }), encoding="utf-8")
            self.assertEqual(
                parse_tree_snapshot(path),
                {"workbook_count": 1, "workbook_bytes": 3},
            )
            path.write_text(json.dumps({"truncated": True, "tree": []}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "truncated"):
                parse_tree_snapshot(path)

    def test_collect_workbooks_hashes_only_xls_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "nuix").mkdir()
            workbook = root / "nuix/example.xls"
            workbook.write_bytes(b"xls")
            (root / "nuix/ignored.txt").write_text("ignored", encoding="utf-8")
            rows = collect_workbooks(root)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["relative_path"], "nuix/example.xls")
            self.assertEqual(rows[0]["sha256"], digest(workbook))

    def test_acquisition_pins_commit_license_tree_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upstream = root / "upstream"
            upstream.mkdir()
            subprocess.run(("git", "init", "-q"), cwd=upstream, check=True)
            subprocess.run(("git", "config", "user.email", "test@example.invalid"), cwd=upstream, check=True)
            subprocess.run(("git", "config", "user.name", "CWRP Test"), cwd=upstream, check=True)
            (upstream / "nuix").mkdir()
            (upstream / "edrm").mkdir()
            (upstream / "nuix/one.xls").write_bytes(b"one")
            (upstream / "edrm/excluded.xls").write_bytes(b"excluded")
            (upstream / "LICENSE").write_text("CC0 1.0 Universal", encoding="utf-8")
            (upstream / "README.md").write_text("fixture", encoding="utf-8")
            subprocess.run(("git", "add", "nuix", "edrm", "LICENSE", "README.md"), cwd=upstream, check=True)
            subprocess.run(("git", "commit", "-qm", "fixture"), cwd=upstream, check=True)
            commit = subprocess.run(
                ("git", "rev-parse", "HEAD"), cwd=upstream, check=True,
                capture_output=True, text=True,
            ).stdout.strip()

            tree = root / "tree.json"
            tree.write_text(json.dumps({
                "truncated": False,
                "tree": [
                    {"path": "nuix/one.xls", "type": "blob", "size": 3},
                    {"path": "edrm/excluded.xls", "type": "blob", "size": 8},
                ],
            }), encoding="utf-8")
            receipt_path = acquire(
                destination=root / "checkout",
                output_dir=root / "receipt",
                tree_snapshot=tree,
                repository=str(upstream),
                commit=commit,
                expected_tree_sha256=digest(tree),
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            manifest = json.loads((root / "receipt/source_manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(receipt["complete"])
            self.assertEqual(receipt["checkout_head"], commit)
            self.assertEqual(receipt["local_workbook_count"], 1)
            self.assertEqual(receipt["cell_contents_read"], 0)
            self.assertEqual(manifest["workbooks"][0]["relative_path"], "nuix/one.xls")
            self.assertFalse((root / "checkout/edrm").exists())

            with self.assertRaisesRegex(ValueError, "already exists"):
                acquire(
                    destination=root / "other-checkout",
                    output_dir=root / "receipt",
                    tree_snapshot=tree,
                    repository=str(upstream),
                    commit=commit,
                    expected_tree_sha256=digest(tree),
                )


class CWRPConversionTests(unittest.TestCase):
    def test_install_uses_target_filesystem_before_atomic_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_dir = root / "source"
            target_dir = root / "target"
            source_dir.mkdir()
            target_dir.mkdir()
            source = source_dir / "converted.xlsx"
            target = target_dir / "final.xlsx"
            source.write_bytes(b"converted")
            actual_replace = __import__("os").replace
            calls = []

            def inspect_replace(left, right):
                calls.append((Path(left), Path(right)))
                return actual_replace(left, right)

            with patch("scripts.convert_cwrp_sheetjs.os.replace", side_effect=inspect_replace):
                install_converted(source, target)
            self.assertEqual(target.read_bytes(), b"converted")
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0].parent, target.parent)
            self.assertEqual(calls[0][1], target)

    def test_conversion_verifies_source_and_emits_formula_counts_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            acquisition = root / "acquisition"
            source_workbook = source / "nuix/one.xls"
            source_workbook.parent.mkdir(parents=True)
            temporary_xlsx = root / "fixture.xlsx"
            write_xlsx(
                temporary_xlsx,
                [("Sheet", {"A1": 1, "B1": 2}, {"C1": "=A1+B1"})],
            )
            source_workbook.write_bytes(temporary_xlsx.read_bytes())
            source_hash = digest(source_workbook)
            acquisition.mkdir()
            manifest = {
                "protocol": "formulaguard_cwrp_sheetjs_acquisition_v1",
                "repository": "fixture",
                "commit": "5b73fc395cbe4727a986ab02a5028c1c1585617f",
                "workbooks": [{
                    "source_id": "sheetjs:" + source_hash,
                    "relative_path": "nuix/one.xls",
                    "bytes": source_workbook.stat().st_size,
                    "sha256": source_hash,
                }],
            }
            manifest_path = acquisition / "source_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            receipt = {
                "protocol": "formulaguard_cwrp_sheetjs_acquisition_v1",
                "commit": "5b73fc395cbe4727a986ab02a5028c1c1585617f",
                "source_manifest_sha256": digest(manifest_path),
                "local_workbook_count": 1,
                "complete": True,
            }
            (acquisition / "acquisition_receipt.json").write_text(
                json.dumps(receipt), encoding="utf-8",
            )

            converter = root / "fake_libreoffice.py"
            converter.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib, shutil, sys\n"
                "if '--version' in sys.argv:\n"
                "    print('Fake LibreOffice 1.0')\n"
                "    raise SystemExit(0)\n"
                "out = pathlib.Path(sys.argv[sys.argv.index('--outdir') + 1])\n"
                "source = pathlib.Path(sys.argv[-1])\n"
                "shutil.copyfile(source, out / (source.stem + '.xlsx'))\n",
                encoding="utf-8",
            )
            converter.chmod(0o755)
            result_path = convert(
                source_root=source,
                acquisition_dir=acquisition,
                destination=root / "converted",
                output_dir=root / "result",
                workers=1,
                libreoffice=str(converter),
                timeout_seconds=10,
            )
            result = json.loads(result_path.read_text(encoding="utf-8"))
            converted_manifest = json.loads(
                (root / "result/conversion_manifest.json").read_text(encoding="utf-8")
            )
            row = converted_manifest["results"][0]
            self.assertTrue(result["complete"])
            self.assertEqual(result["eligible_workbooks"], 1)
            self.assertEqual(row["formula_count"], 1)
            self.assertEqual(row["parseable_formula_count"], 1)
            self.assertNotIn("formula", row)
            self.assertNotIn("cell", row)
            with self.assertRaisesRegex(ValueError, "already complete"):
                convert(
                    source_root=source,
                    acquisition_dir=acquisition,
                    destination=root / "converted",
                    output_dir=root / "result",
                    workers=1,
                    libreoffice=str(converter),
                    timeout_seconds=10,
                )


class CWRPStructuralProfileTests(unittest.TestCase):
    def test_target_profile_reader_rejects_fault_label_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "targets.csv"
            path.write_text(
                "unit_id,cohort,structure_cluster_id,path,workbook_sha256,source_cell\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "forbidden=.*source_cell"):
                read_targets(path)

    def test_role_fingerprint_removes_numbers_and_sheet_names(self):
        left = formula_role_fingerprint("=SUM('Inputs'!A1:A3)+10", "C5", "Model")
        right = formula_role_fingerprint("=SUM('Private Data'!A1:A3)+999", "C5", "Output")
        self.assertEqual(left, right)
        self.assertNotIn("INPUTS", left.upper())
        self.assertNotIn("999", right)
        local = formula_role_fingerprint("=A1", "C5", "Model")
        external = formula_role_fingerprint("=Other!A1", "C5", "Model")
        self.assertNotEqual(local, external)

    def test_workbook_profile_is_translation_and_sheet_rename_invariant(self):
        first = WorkbookModel.from_cells(
            {("Private", "A1"): "Alice", ("Private", "B1"): 10},
            {("Private", "C1"): "=B1*2", ("Private", "C2"): "=B1+5"},
        )
        translated = WorkbookModel.from_cells(
            {("Renamed", "D7"): "Bob", ("Renamed", "E7"): 999},
            {("Renamed", "F7"): "=E7*8", ("Renamed", "F8"): "=E7+42"},
        )
        left = workbook_profile(first)
        right = workbook_profile(translated)
        self.assertEqual(left["structural_signature"], right["structural_signature"])
        self.assertEqual(left["role_fingerprint_counts"], right["role_fingerprint_counts"])
        serialized = json.dumps(left)
        self.assertNotIn("Alice", serialized)
        self.assertNotIn("Private", serialized)
        self.assertNotIn("10", json.dumps(left["role_fingerprint_counts"]))
        self.assertEqual(left["sensitive_text_features"], 0)

    def test_weighted_jaccard_and_formula_count_ratio_are_fixed(self):
        self.assertAlmostEqual(weighted_jaccard({"a": 2, "b": 1}, {"a": 1, "c": 1}), 0.25)
        self.assertTrue(formula_count_ratio_eligible(10, 20))
        self.assertTrue(formula_count_ratio_eligible(20, 10))
        self.assertFalse(formula_count_ratio_eligible(4, 10))

    def test_target_overlap_excludes_entire_internal_template_component(self):
        def row(workbook_id, fingerprint_counts, signature):
            counts = [
                {"fingerprint": key, "count": value}
                for key, value in sorted(fingerprint_counts.items())
            ]
            return {
                "workbook_id": workbook_id,
                "workbook_sha256": workbook_id * 64,
                "relative_path": f"nuix/{workbook_id}.xlsx",
                "profile": {
                    "formula_count": sum(fingerprint_counts.values()),
                    "parseable_formula_count": sum(fingerprint_counts.values()),
                    "role_fingerprint_counts": counts,
                    "formula_multiset_sha256": hashlib.sha256(workbook_id.encode()).hexdigest(),
                    "structural_signature": signature,
                },
            }

        corpus = [
            row("a", {"SUM": 10}, "structure-a"),
            row("b", {"SUM": 9, "MAX": 1}, "structure-b"),
            row("c", {"OTHER": 10}, "structure-c"),
        ]
        targets = [row("t", {"SUM": 10}, "target-structure")]
        manifest, audit = cluster_profiles(corpus, targets)
        by_id = {item["workbook_id"]: item for item in manifest}
        self.assertTrue(by_id["a"]["excluded_target_overlap_component"])
        self.assertTrue(by_id["b"]["excluded_target_overlap_component"])
        self.assertFalse(by_id["c"]["excluded_target_overlap_component"])
        self.assertEqual(by_id["a"]["template_group_id"], by_id["b"]["template_group_id"])
        self.assertEqual(audit["excluded_component_workbooks"], 2)

    def test_masked_context_does_not_change_when_only_target_formula_changes(self):
        cells = {("S", "A1"): 1, ("S", "B1"): 2}
        shared = {("S", "D1"): "=C1*2", ("S", "C2"): "=A2+B2"}
        left = WorkbookModel.from_cells(cells, {**shared, ("S", "C1"): "=A1+B1"})
        right = WorkbookModel.from_cells(cells, {**shared, ("S", "C1"): "=A1-B1"})
        left_rows = masked_formula_examples(
            left, workbook_id="w", template_group_id="g", outer_fold=0,
        )
        right_rows = masked_formula_examples(
            right, workbook_id="w", template_group_id="g", outer_fold=0,
        )
        left_by_id = {row["example_id"]: row for row in left_rows}
        right_by_id = {row["example_id"]: row for row in right_rows}
        changed_id = next(
            example_id for example_id in left_by_id
            if left_by_id[example_id]["target_fingerprint"]
            != right_by_id[example_id]["target_fingerprint"]
        )
        self.assertEqual(
            left_by_id[changed_id]["context_keys"],
            right_by_id[changed_id]["context_keys"],
        )
        self.assertEqual(
            left_by_id[changed_id]["local_peer_candidates"],
            right_by_id[changed_id]["local_peer_candidates"],
        )
        self.assertEqual(left_by_id[changed_id]["target_formula_features"], 0)

    def test_sparse_mask_requires_no_same_role_axis_peer(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 1, ("S", "B1"): 2, ("S", "A2"): 3, ("S", "B2"): 4},
            {
                ("S", "C1"): "=A1+B1",
                ("S", "C2"): "=A2+B2",
                ("S", "D5"): "=A1*B1",
            },
        )
        rows = masked_formula_examples(
            model, workbook_id="w", template_group_id="g", outer_fold=0,
        )
        self.assertEqual(sum(not row["locally_unsupported"] for row in rows), 2)
        self.assertEqual(sum(row["locally_unsupported"] for row in rows), 1)

    def test_context_excludes_raw_values_and_identity_text(self):
        left = WorkbookModel.from_cells(
            {
                ("Private 2025", "A1"): "customer alpha",
                ("Private 2025", "B1"): 17,
                ("Private 2025", "A2"): "internal note",
                ("Private 2025", "B2"): 31,
            },
            {
                ("Private 2025", "C1"): "=B1*2",
                ("Private 2025", "C2"): "=B2+2",
            },
        )
        right = WorkbookModel.from_cells(
            {
                ("Renamed", "A1"): "different confidential text",
                ("Renamed", "B1"): 999999,
                ("Renamed", "A2"): "another value",
                ("Renamed", "B2"): -42,
            },
            {
                ("Renamed", "C1"): "=B1*2",
                ("Renamed", "C2"): "=B2+2",
            },
        )
        left_rows = masked_formula_examples(
            left, workbook_id="private-filename", template_group_id="g", outer_fold=0,
        )
        right_rows = masked_formula_examples(
            right, workbook_id="different-filename", template_group_id="g", outer_fold=0,
        )
        left_contexts = {
            row["target_fingerprint"]: (row["context_keys"], row["local_peer_candidates"])
            for row in left_rows
        }
        right_contexts = {
            row["target_fingerprint"]: (row["context_keys"], row["local_peer_candidates"])
            for row in right_rows
        }
        self.assertEqual(left_contexts, right_contexts)

    def test_masked_example_validator_rejects_unregistered_fields(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 1}, {("S", "B1"): "=A1+1"},
        )
        example = masked_formula_examples(
            model, workbook_id="w", template_group_id="g", outer_fold=0,
        )[0]
        expected = {"workbook_id": "w", "template_group_id": "g", "outer_fold": 0}
        _validate_example(example, expected)
        with self.assertRaisesRegex(ValueError, "schema mismatch"):
            _validate_example({**example, "raw_formula": "=A1+1"}, expected)


class CWRPSelfSupervisedTests(unittest.TestCase):
    @staticmethod
    def example(example_id, group, target, *, exact="e", role="r", coarse="c"):
        return {
            "example_id": example_id,
            "template_group_id": group,
            "target_fingerprint": target,
            "context_keys": {"exact": exact, "role": role, "coarse": coarse},
        }

    def test_hierarchical_prior_requires_independent_group_support(self):
        rows = [
            self.example("1", "g1", "SUM", exact="shared"),
            self.example("2", "g2", "SUM", exact="shared"),
            self.example("3", "g3", "SUM", exact="shared"),
            self.example("4", "g1", "SUM", exact="shared"),
            self.example("5", "g2", "MAX", exact="shared"),
        ]
        model = HierarchicalRolePrior(rows)
        prediction = model.predict(self.example("x", "held", "SUM", exact="shared"))
        self.assertEqual(prediction["level"], "exact")
        self.assertEqual(prediction["support_groups"], 3)
        self.assertEqual(prediction["top5"][0], "SUM")
        fallback = model.predict(self.example("y", "held", "SUM", exact="unseen", role="unseen", coarse="unseen"))
        self.assertEqual(fallback["level"], "global_fallback")
        self.assertEqual(fallback["support_groups"], 0)

    def test_support_threshold_maximizes_coverage_at_target_accuracy(self):
        rows = [
            {"candidate": {"support_groups": 3}, "candidate_hit": 0},
            {"candidate": {"support_groups": 4}, "candidate_hit": 1},
            {"candidate": {"support_groups": 5}, "candidate_hit": 1},
        ]
        selected = select_support_threshold(rows, target_accuracy=0.60)
        self.assertTrue(selected["feasible"])
        self.assertEqual(selected["threshold"], 3)
        self.assertEqual(selected["calibration_selected"], 3)

    def test_target_permutation_is_deterministic_and_preserves_distribution(self):
        rows = [
            self.example(str(index), f"g{index}", f"target-{index}")
            for index in range(8)
        ]
        first = permute_training_targets(rows, seed="fixed")
        second = permute_training_targets(rows, seed="fixed")
        self.assertEqual(first, second)
        self.assertCountEqual(
            [row["target_fingerprint"] for row in first],
            [row["target_fingerprint"] for row in rows],
        )
        self.assertTrue(any(
            left["target_fingerprint"] != right["target_fingerprint"]
            for left, right in zip(sorted(rows, key=lambda row: row["example_id"]), first)
        ))


if __name__ == "__main__":
    unittest.main()
