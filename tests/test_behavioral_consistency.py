import unittest
from collections import Counter
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

from formulaguard import behavioral_consistency
from formulaguard.behavioral_consistency import (
    BehavioralConsistencyConfig,
    audit_behavioral_consistency,
    canonical_response,
    rank_behavioral_candidates,
    response_distance,
)
from formulaguard.counterfactual_candidates import generate_counterfactual_candidates
from formulaguard.counterfactual_response import build_response_signature
from formulaguard.workbook import WorkbookModel


def _unshared_audit_record(model, target, config):
    """Reference implementation matching the pre-cache evaluation strategy."""
    graph = model.dependency_graph()
    neighborhoods = behavioral_consistency._frozen_peer_neighborhoods(
        model, (target,), config, graph
    )
    needed = {target}
    for axis in ("column", "row"):
        needed.update(neighborhoods[target][axis])
    signatures = {
        cell: canonical_response(
            build_response_signature(model, cell, config=config.response_config)
        )
        for cell in sorted(needed, key=behavioral_consistency._cell_sort)
    }
    return behavioral_consistency._record(
        target, signatures, config, neighborhoods[target]
    )


def _unshared_candidate_ranking(model, target, candidates, config):
    observed = _unshared_audit_record(model, target, config)
    observed_applicable = observed["status"] != "abstained"
    rows = []
    seen = set()
    for candidate in candidates:
        formula = getattr(candidate, "formula", None)
        if (
            not isinstance(formula, str)
            or not formula.startswith("=")
            or formula in seen
        ):
            continue
        seen.add(formula)
        record = _unshared_audit_record(
            behavioral_consistency._clone_with_formula(model, target, formula),
            target,
            config,
        )
        applicable = observed_applicable and record["status"] != "abstained"
        candidate_score = float(record["score"])
        improvement = float(observed["score"]) - candidate_score if applicable else None
        rows.append(
            {
                "formula": formula,
                "edit_kind": str(getattr(candidate, "edit_kind", "unknown")),
                "edit_witness": behavioral_consistency._witness_payload(
                    getattr(candidate, "witness", None)
                ),
                "applicable": applicable,
                "candidate_status": record["status"],
                "candidate_score": candidate_score,
                "improvement": improvement,
                "behavior_witness": record["witness"],
            }
        )
    rows.sort(
        key=lambda row: (
            not bool(row["applicable"]),
            -float(row["improvement"]) if row["improvement"] is not None else 0.0,
            float(row["candidate_score"]),
            str(row["formula"]),
        )
    )
    return {
        "protocol": behavioral_consistency.PROTOCOL,
        "target": behavioral_consistency._label(target),
        "observed_status": observed["status"],
        "observed_score": float(observed["score"]),
        "observed_witness": observed["witness"],
        "candidates": rows,
    }


class BehavioralConsistencyTests(unittest.TestCase):
    def test_algebraically_different_formulas_share_a_response_role(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row + 1 for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2+A2",
                ("S", "B3"): "=SUM(A3,A3)",
                ("S", "B4"): "=A4*3",
            },
        )

        signatures = {
            key: canonical_response(build_response_signature(model, key))
            for key in model.formula_cells
        }
        self.assertAlmostEqual(
            response_distance(signatures[("S", "B1")], signatures[("S", "B2")]), 0.0
        )
        self.assertAlmostEqual(
            response_distance(signatures[("S", "B1")], signatures[("S", "B3")]), 0.0
        )
        self.assertGreater(
            response_distance(signatures[("S", "B1")], signatures[("S", "B4")]), 0.0
        )

        audit = audit_behavioral_consistency(model)
        records = {row["cell"]: row for row in audit["records"]}
        self.assertEqual(records["S!B1"]["status"], "consistent")
        self.assertEqual(records["S!B2"]["status"], "consistent")
        self.assertEqual(records["S!B3"]["status"], "consistent")
        self.assertEqual(records["S!B4"]["status"], "behavioral_outlier")
        self.assertGreater(records["S!B4"]["score"], 0.0)

    def test_direct_and_one_hop_mappings_have_zero_response_distance(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2, ("S", "A2"): 2},
            {
                ("S", "C1"): "=A1*2",
                ("S", "B2"): "=A2",
                ("S", "C2"): "=B2*2",
            },
        )

        direct = canonical_response(build_response_signature(model, ("S", "C1")))
        one_hop = canonical_response(build_response_signature(model, ("S", "C2")))

        self.assertTrue(direct.eligible)
        self.assertTrue(one_hop.eligible)
        self.assertEqual(direct.influences[0].key, one_hop.influences[0].key)
        self.assertEqual(direct.influences[0].path_length, 1)
        self.assertEqual(one_hop.influences[0].path_length, 2)
        self.assertAlmostEqual(response_distance(direct, one_hop), 0.0)

    def test_path_independent_matching_key_collision_abstains(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2},
            {("S", "C1"): "=A1*2"},
        )
        signature = build_response_signature(model, ("S", "C1"))
        probe = signature.probes[0]
        self.assertIsNotNone(probe.target_response)
        indirect_response = replace(
            probe.target_response,
            path=(("S", "A1"), ("S", "B1"), ("S", "C1")),
        )
        duplicate_probe = replace(probe, target_response=indirect_response)

        response = canonical_response(
            replace(signature, probes=(probe, duplicate_probe))
        )

        self.assertFalse(response.eligible)
        self.assertEqual(response.reason, "ambiguous_relative_input_keys")
        self.assertEqual(response.influences, ())

    def test_two_peer_majority_abstains_on_legal_rate_switch_and_summary(self):
        cells = {("S", f"A{row}"): row for row in range(1, 4)}
        cases = {
            "rate_switch": {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A3*3",
            },
            "summary": {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=SUM(A1:A3)",
            },
        }

        for name, formulas in cases.items():
            with self.subTest(name=name):
                record = audit_behavioral_consistency(
                    WorkbookModel.from_cells(cells, formulas),
                    targets=[("S", "B3")],
                )["records"][0]
                self.assertEqual(record["status"], "abstained")
                self.assertEqual(record["reason"], "no_coherent_peer_axis")
                self.assertEqual(record["score"], 0.0)

    def test_wrong_reference_is_exposed_by_relative_input_support(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A2*2",
                ("S", "B4"): "=A4*2",
            },
        )
        audit = audit_behavioral_consistency(model, targets=[("S", "B3")])
        record = audit["records"][0]

        self.assertEqual(record["status"], "behavioral_outlier")
        self.assertGreater(record["score"], 0.4)
        self.assertEqual(record["witness"]["axis"], "column")
        self.assertEqual(record["witness"]["peer_coherence"], 0.0)

    def test_alternating_legal_roles_do_not_create_an_outlier(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*3",
                ("S", "B3"): "=A3*2",
                ("S", "B4"): "=A4*3",
            },
        )
        audit = audit_behavioral_consistency(model)

        self.assertFalse(audit["summary"]["behavioral_outliers"])
        self.assertTrue(all(row["status"] == "consistent" for row in audit["records"]))

    def test_sparse_region_abstains(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 2, ("S", "A2"): 4},
            {("S", "B1"): "=A1*2", ("S", "B2"): "=A2*2"},
        )
        audit = audit_behavioral_consistency(model, targets=[("S", "B1")])

        self.assertEqual(audit["records"][0]["status"], "abstained")
        self.assertEqual(audit["records"][0]["reason"], "no_coherent_peer_axis")

    def test_blank_gap_separates_unrelated_formula_blocks(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 4)},
            {
                ("S", "C4"): "=A1*2",
                ("S", "D4"): "=A2*2",
                ("S", "E4"): "=A3*2",
                ("S", "K4"): "=A1",
                ("S", "L4"): "=A2",
            },
        )

        audit = audit_behavioral_consistency(model, targets=[("S", "K4")])

        self.assertEqual(audit["records"][0]["status"], "abstained")
        self.assertEqual(audit["records"][0]["reason"], "no_coherent_peer_axis")

    def test_correct_ast_candidate_closes_behavioral_outlier(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A2*2",
                ("S", "B4"): "=A4*2",
            },
        )
        candidates = generate_counterfactual_candidates(model, ("S", "B3"), budget=32)
        ranking = rank_behavioral_candidates(model, ("S", "B3"), candidates)

        self.assertGreater(ranking["observed_score"], 0.0)
        self.assertTrue(ranking["candidates"])
        self.assertEqual(ranking["candidates"][0]["formula"], "=(A3*2)")
        self.assertAlmostEqual(ranking["candidates"][0]["candidate_score"], 0.0)
        self.assertGreater(ranking["candidates"][0]["improvement"], 0.4)

    def test_dependency_chain_cells_are_excluded_from_peer_baseline(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 6)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=B2+1",
                ("S", "B4"): "=B3+1",
                ("S", "B5"): "=A5*2",
            },
        )

        record = audit_behavioral_consistency(
            model,
            targets=[("S", "B3")],
            config=BehavioralConsistencyConfig(min_peers=2),
        )["records"][0]

        self.assertIsNotNone(record["witness"])
        self.assertEqual(record["witness"]["peers"], ["S!B1", "S!B5"])
        self.assertNotIn("S!B2", record["witness"]["peers"])
        self.assertNotIn("S!B4", record["witness"]["peers"])

    def test_shared_graph_audit_is_strictly_equivalent_and_builds_graph_once(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A2*2",
                ("S", "B4"): "=A4*2",
            },
        )
        target = ("S", "B3")
        config = BehavioralConsistencyConfig()
        original_graph = WorkbookModel.dependency_graph
        graph_calls = 0

        def counted_graph(instance, *args, **kwargs):
            nonlocal graph_calls
            graph_calls += 1
            return original_graph(instance, *args, **kwargs)

        with patch.object(WorkbookModel, "dependency_graph", new=counted_graph):
            expected = _unshared_audit_record(model, target, config)
        unshared_graph_calls = graph_calls
        graph_calls = 0
        with patch.object(WorkbookModel, "dependency_graph", new=counted_graph):
            actual = audit_behavioral_consistency(
                model, targets=[target], config=config
            )["records"][0]

        self.assertEqual(actual, expected)
        self.assertEqual(graph_calls, 1)
        self.assertLess(graph_calls, unshared_graph_calls)

    def test_candidate_ranking_freezes_peers_and_reduces_graph_and_evaluation_calls(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 5)},
            {
                ("S", "B1"): "=A1*2",
                ("S", "B2"): "=A2*2",
                ("S", "B3"): "=A2*2",
                ("S", "B4"): "=A4*2",
            },
        )
        target = ("S", "B3")
        candidates = [
            SimpleNamespace(formula="=A3*2", edit_kind="test", witness=None),
            SimpleNamespace(formula="=A2*3", edit_kind="test", witness=None),
        ]
        config = BehavioralConsistencyConfig()
        original_graph = WorkbookModel.dependency_graph
        original_evaluate = WorkbookModel.evaluate

        def run_with_counts(callback):
            counts = {"graph": 0, "evaluate": 0}

            def counted_graph(instance, *args, **kwargs):
                counts["graph"] += 1
                return original_graph(instance, *args, **kwargs)

            def counted_evaluate(instance, *args, **kwargs):
                counts["evaluate"] += 1
                return original_evaluate(instance, *args, **kwargs)

            with (
                patch.object(WorkbookModel, "dependency_graph", new=counted_graph),
                patch.object(WorkbookModel, "evaluate", new=counted_evaluate),
            ):
                result = callback()
            return result, counts

        expected, old_counts = run_with_counts(
            lambda: _unshared_candidate_ranking(model, target, candidates, config)
        )
        signature_targets = []
        original_signature = behavioral_consistency.build_response_signature

        def counted_signature(instance, cell, **kwargs):
            signature_targets.append(cell)
            return original_signature(instance, cell, **kwargs)

        with patch.object(
            behavioral_consistency,
            "build_response_signature",
            new=counted_signature,
        ):
            actual, new_counts = run_with_counts(
                lambda: rank_behavioral_candidates(
                    model, target, candidates, config=config
                )
            )

        self.assertEqual(actual, expected)
        self.assertLess(new_counts["graph"], old_counts["graph"])
        self.assertLess(new_counts["evaluate"], old_counts["evaluate"])
        self.assertEqual(Counter(signature_targets)[target], 1 + len(candidates))
        for peer in (("S", "B1"), ("S", "B2"), ("S", "B4")):
            self.assertEqual(Counter(signature_targets)[peer], 1)


if __name__ == "__main__":
    unittest.main()
