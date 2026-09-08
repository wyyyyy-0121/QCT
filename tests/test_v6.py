import inspect
import unittest

from formulaguard.api import localize
from formulaguard.formula import normalized_formula
from formulaguard.localize import v4_scores
from formulaguard.v6 import (
    _select_promotion,
    relative_ast_signature,
    semantic_candidates,
    semantic_peers,
    v6_ablation_scores,
    v6_scores,
)
from formulaguard.workbook import WorkbookModel


def family_model(error_formula="=MIN(B5:D5)"):
    cells = {}
    formulas = {}
    for row in range(2, 9):
        for col, value in zip("BCD", (row, row + 2, row + 4)):
            cells[("Data", f"{col}{row}")] = value
        formulas[("Data", f"E{row}")] = f"=SUM(B{row}:D{row})"
        formulas[("Data", f"F{row}")] = f"=E{row}*2"
    formulas[("Data", "E5")] = error_formula
    formulas[("Data", "G9")] = "=SUM(F2:F8)"
    return WorkbookModel.from_cells(cells, formulas)


class V6Tests(unittest.TestCase):
    def test_public_interface_has_no_label_fields(self):
        parameters = set(inspect.signature(v6_scores).parameters)
        self.assertFalse(parameters & {"source_cell", "error_type", "correct_formula", "labels"})

    def test_relative_signature_translates_copy_family(self):
        self.assertEqual(
            relative_ast_signature("=SUM(B2:D2)", "E2"),
            relative_ast_signature("=SUM(B8:D8)", "E8"),
        )

    def test_contiguous_peer_directions(self):
        peers = semantic_peers(family_model(), ("Data", "E5"))
        self.assertEqual({direction for _, direction in peers}, {"up", "down"})
        self.assertEqual(len(peers), 6)

    def test_function_family_candidate_is_generated(self):
        items = semantic_candidates(family_model(), ("Data", "E5"), semantic_candidate_limit=25)
        wanted = normalized_formula("=SUM(B5:D5)")
        match = next(item for item in items if normalized_formula(item.candidate.formula) == wanted)
        self.assertGreaterEqual(match.support_count, 3)
        self.assertGreaterEqual(match.family_support, 0.6)
        self.assertIn("aggregate_function", match.candidate.edit_kinds)
        self.assertIn("family_consensus", match.candidate.sources)

    def test_range_boundary_candidate_is_generated(self):
        model = family_model("=SUM(B5:C5)")
        items = semantic_candidates(model, ("Data", "E5"), semantic_candidate_limit=25)
        wanted = normalized_formula("=SUM(B5:D5)")
        match = next(item for item in items if normalized_formula(item.candidate.formula) == wanted)
        self.assertGreaterEqual(match.boundary_support, 0.6)
        self.assertIn("range_boundary", match.candidate.edit_kinds)

    def test_full_ranking_and_legacy_relative_order(self):
        model = family_model()
        base = [item.cell for item in v4_scores(model)]
        v6 = v6_scores(model, variant="c")
        cells = [item.cell for item in v6]
        self.assertEqual(len(cells), len(model.formula_cells))
        self.assertEqual(len(set(cells)), len(cells))
        promoted = [item.cell for item in v6 if item.evidence["promotion_target"]]
        remainder_base = [cell for cell in base if cell not in promoted]
        remainder_v6 = [cell for cell in cells if cell not in promoted]
        self.assertEqual(remainder_base, remainder_v6)

    def test_semantic_evidence_never_demotes_a_v4_cell(self):
        model = family_model()
        base_rank = {item.cell: rank for rank, item in enumerate(v4_scores(model), 1)}
        results = v6_scores(model, variant="c")
        new_rank = {item.cell: rank for rank, item in enumerate(results, 1)}
        promoted = [item.cell for item in results if item.evidence["promotion_target"]]
        for cell in promoted:
            self.assertLess(new_rank[cell], base_rank[cell])

    def test_api_dispatches_v6(self):
        results = localize(family_model(), "formulaguard_v6_c", candidate_limit=15)
        self.assertTrue(results)
        self.assertTrue(all(row.evidence["model_version"] == "v6-semantic-r1" for row in results))

    def test_ablations_are_variant_matched(self):
        model = family_model("=SUM(B5:C5)")
        a = v6_ablation_scores(model, "no_bss", variant="a")
        b = v6_ablation_scores(model, "no_bss", variant="b")
        self.assertEqual([row.cell for row in a], [row.cell for row in b])
        with self.assertRaises(ValueError):
            v6_ablation_scores(model, "no_bss", variant="z")

    def test_special_correct_formula_does_not_force_promotion(self):
        model = family_model("=SUM(B5:D5)")
        results = v6_scores(model, variant="c")
        self.assertLessEqual(sum(bool(item.evidence["promotion_target"]) for item in results), 1)

    def test_safe_variant_rejects_an_exact_evidence_tie(self):
        row = {"candidate": object()}
        first = ((2, 3, .4, .2, 5.0, .9, -8), ("S", "A1"), row, "strong", 3)
        second = ((2, 3, .4, .2, 5.0, .8, -9), ("S", "B1"), row, "strong", 3)
        self.assertIsNone(_select_promotion([first, second], variant="c"))
        self.assertIsNotNone(_select_promotion([first, second], variant="b"))


if __name__ == "__main__":
    unittest.main()
