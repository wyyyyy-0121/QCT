from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from formulaguard.localize import LocalizationResult, RepairCandidate
from formulaguard.v52 import v52_from_v4, v52_scores
from formulaguard.workbook import WorkbookModel


def _result(rank: int, *, eligible: bool = False, formula_rank: int | None = None):
    return LocalizationResult(
        cell=("S", f"B{rank}"),
        score=float(20 - rank),
        candidate_formula="=A1+1" if eligible else None,
        evidence={
            "final_rank": rank,
            "formula_rank": formula_rank if formula_rank is not None else rank,
            "diagnostic_status": "strong_counterfactual" if eligible else "pattern_only",
            "intervention_responsibility_gain": 5.0 if eligible else 0.0,
            "candidate_delta": 0.12 if eligible else 0.0,
            "candidate_source": "bounded_edit,peer_translation" if eligible else "",
        },
    )


def _model():
    formulas = {("S", f"B{rank}"): f"=A{rank}+1" for rank in range(1, 9)}
    cells = {("S", f"A{rank}"): rank for rank in range(1, 9)}
    return WorkbookModel.from_cells(cells, formulas)


def _repair(source_count: int = 2, reference_quality: float = 1.0):
    sources = ("bounded_edit", "peer_translation")[:source_count]
    return RepairCandidate(
        formula="=A1+1",
        support=2,
        sources=sources,
        edit_kinds=("copy_pattern",),
        edit_cost=1.0,
        reference_quality=reference_quality,
        quality=0.9,
    )


class V52DecisionTests(unittest.TestCase):
    def test_a_adds_review_slot_without_changing_v4_core(self):
        results = [_result(rank, eligible=(rank == 6), formula_rank=1 if rank == 6 else rank)
                   for rank in range(1, 9)]
        with patch("formulaguard.v52.generate_candidates", return_value=[_repair()]):
            decision = v52_from_v4(_model(), results, variant="a")
        self.assertEqual(decision.status, "rescue")
        self.assertEqual([item.cell for item in decision.core_ranking], [item.cell for item in results])
        self.assertEqual([item.cell for item in decision.core_top5], [item.cell for item in results[:5]])
        self.assertEqual(len(decision.review_set), 6)
        self.assertEqual(decision.review_set[-1].cell, ("S", "B6"))

    def test_a_refuses_an_exact_evidence_tie(self):
        results = [_result(rank, eligible=rank in {6, 7}, formula_rank=1 if rank in {6, 7} else rank)
                   for rank in range(1, 9)]
        with patch("formulaguard.v52.generate_candidates", return_value=[_repair()]):
            decision = v52_from_v4(_model(), results, variant="a")
        self.assertEqual(decision.status, "ambiguous")
        self.assertIsNone(decision.rescue)

    def test_b_requires_a_dominance_margin_for_same_pattern_rank(self):
        results = [_result(rank, eligible=rank in {6, 7}, formula_rank=1 if rank in {6, 7} else rank)
                   for rank in range(1, 9)]
        results[6].evidence["intervention_responsibility_gain"] = 4.5
        results[6].evidence["candidate_delta"] = 0.11
        with patch("formulaguard.v52.generate_candidates", return_value=[_repair()]):
            decision = v52_from_v4(_model(), results, variant="b")
        self.assertEqual(decision.status, "ambiguous")
        self.assertIsNone(decision.rescue)

    def test_c_requires_two_distinct_repair_sources(self):
        results = [_result(rank, eligible=(rank == 6), formula_rank=1 if rank == 6 else rank)
                   for rank in range(1, 9)]
        with patch("formulaguard.v52.generate_candidates", return_value=[_repair(1)]):
            decision = v52_from_v4(_model(), results, variant="c")
        self.assertEqual(decision.status, "rejected_repair_evidence")
        with patch("formulaguard.v52.generate_candidates", return_value=[_repair(2)]):
            decision = v52_from_v4(_model(), results, variant="c")
        self.assertEqual(decision.status, "rescue")

    def test_v52_has_no_label_parameter(self):
        parameters = set(inspect.signature(v52_scores).parameters)
        self.assertEqual(parameters, {"model", "variant", "candidate_limit"})
        self.assertFalse(parameters & {"source_cell", "source_cells", "correct_formula", "labels"})

    def test_v52_rejects_a_non_v4_order(self):
        results = [_result(rank) for rank in range(1, 7)]
        results[0].evidence["final_rank"] = 2
        with self.assertRaises(ValueError):
            v52_from_v4(_model(), results, variant="a")


if __name__ == "__main__":
    unittest.main()
