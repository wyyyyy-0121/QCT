import inspect
import unittest
from dataclasses import fields

from formulaguard.candidate_pool import (
    AST_SOURCE,
    PEER_SOURCE,
    CandidatePoolConfig,
    CandidatePoolEntry,
    build_candidate_pool,
    canonical_formula_key,
    generate_peer_translation_candidates,
)
from formulaguard.workbook import WorkbookModel


class CandidatePoolTests(unittest.TestCase):
    def test_public_builder_is_label_free_and_entries_make_no_error_claim(self):
        parameters = set(inspect.signature(build_candidate_pool).parameters)
        self.assertFalse(
            parameters & {"label", "labels", "correct_formula", "error_type"}
        )
        entry_fields = {field.name for field in fields(CandidatePoolEntry)}
        self.assertFalse(entry_fields & {"is_error", "anomaly_score", "defect_score"})

        model = WorkbookModel.from_cells(
            {("S", "A1"): 1, ("S", "A2"): 2, ("S", "A3"): 3},
            {
                ("S", "B1"): "=A1+1",
                ("S", "B2"): "=A2-1",
                ("S", "B3"): "=A3+1",
            },
        )
        pool = build_candidate_pool(model, ("S", "B2"))
        self.assertTrue(pool.candidates)
        self.assertTrue(all(not hasattr(item, "is_error") for item in pool.candidates))
        self.assertTrue(all(not hasattr(item, "anomaly_score") for item in pool.candidates))

    def test_cross_sheet_absolute_anchor_is_recovered_outside_local_component(self):
        model = WorkbookModel.from_cells(
            {
                ("Params", "B1"): 0.2,
                ("Params", "B3"): 0.4,
            },
            {
                ("Calc", "C2"): "=Params!$B$1",
                ("Calc", "C3"): "=Params!B3",
                ("Calc", "C4"): "='Params'!$B$1",
            },
        )

        candidates = generate_peer_translation_candidates(model, ("Calc", "C3"))
        wanted = canonical_formula_key("=Params!$B$1")
        match = next(item for item in candidates if item.canonical_key == wanted)

        self.assertEqual(match.formula, "='Params'!$B$1")
        self.assertEqual({vote.peer for vote in match.votes}, {("Calc", "C2"), ("Calc", "C4")})
        self.assertEqual({vote.axis for vote in match.votes}, {"column"})

    def test_observed_dependency_ancestors_and_descendants_cannot_vote(self):
        model = WorkbookModel.from_cells(
            {
                ("S", "A1"): 1,
                ("S", "A2"): 2,
                ("S", "A3"): 3,
                ("S", "A5"): 5,
            },
            {
                ("S", "C1"): "=A1",
                ("S", "C2"): "=A2",
                ("S", "C3"): "=C2",
                ("S", "A4"): "=C3",
                ("S", "C4"): "=A4",
                ("S", "C5"): "=A5",
            },
        )

        pool = build_candidate_pool(
            model,
            ("S", "C3"),
            config=CandidatePoolConfig(ast_budget=0, peer_budget=4),
        )
        wanted = canonical_formula_key("=A3")
        match = next(item for item in pool.candidates if item.canonical_key == wanted)

        self.assertEqual({vote.peer for vote in match.peer_votes}, {("S", "C1"), ("S", "C5")})
        self.assertEqual(
            set(pool.audit.dependency_excluded_peers),
            {("S", "C2"), ("S", "C4")},
        )

    def test_a_dependency_exclusion_can_reduce_consensus_below_two_votes(self):
        model = WorkbookModel.from_cells(
            {("S", "A2"): 2, ("S", "A3"): 3, ("S", "A4"): 4},
            {
                ("S", "C2"): "=A2",
                ("S", "C3"): "=C2",
                ("S", "C4"): "=A4",
            },
        )

        candidates = generate_peer_translation_candidates(model, ("S", "C3"))
        self.assertNotIn(
            canonical_formula_key("=A3"),
            {candidate.canonical_key for candidate in candidates},
        )

    def test_ast_key_deduplicates_parenthesized_peer_spellings(self):
        model = WorkbookModel.from_cells(
            {
                ("S", "A2"): 2,
                ("S", "B2"): 3,
                ("S", "A3"): 4,
                ("S", "B3"): 5,
                ("S", "A4"): 6,
                ("S", "B4"): 7,
            },
            {
                ("S", "C2"): "=A2+B2",
                ("S", "C3"): "=A3-B3",
                ("S", "C4"): "=(A4+B4)",
            },
        )

        candidates = generate_peer_translation_candidates(model, ("S", "C3"))
        wanted = canonical_formula_key("=A3+B3")
        matching = [item for item in candidates if item.canonical_key == wanted]

        self.assertEqual(canonical_formula_key("=A3+B3"), canonical_formula_key("=(A3+B3)"))
        self.assertEqual(len(matching), 1)
        self.assertEqual(len(matching[0].votes), 2)

    def test_canonical_key_preserves_meaningful_sheet_name_spaces(self):
        self.assertNotEqual(
            canonical_formula_key("='Input Data'!$A$1"),
            canonical_formula_key("=InputData!$A$1"),
        )
        model = WorkbookModel.from_cells(
            {
                ("Input Data", "A1"): 1,
                ("InputData", "A1"): 2,
            },
            {
                ("Calc", "C1"): "='Input Data'!$A$1",
                ("Calc", "C2"): "=1",
                ("Calc", "C3"): "=InputData!$A$1",
            },
        )

        self.assertEqual(
            generate_peer_translation_candidates(model, ("Calc", "C2")),
            (),
        )

    def test_peer_translation_rejects_relative_reference_underflow(self):
        model = WorkbookModel.from_cells(
            {("S", "A1"): 1, ("S", "B1"): 2},
            {
                ("S", "C1"): "=B1",
                ("S", "C2"): "=A1",
                ("S", "C3"): "=A1",
            },
        )

        self.assertEqual(
            generate_peer_translation_candidates(model, ("S", "C1")),
            (),
        )

    def test_source_budgets_are_independent_and_output_is_deterministic(self):
        cells = {
            ("S", f"A{row}"): row
            for row in range(1, 6)
        }
        cells.update({("S", f"B{row}"): row + 1 for row in range(1, 6)})
        formulas = {
            ("S", f"C{row}"): f"=A{row}+B{row}"
            for row in range(1, 6)
        }
        formulas[("S", "C3")] = "=A3-B3"
        model = WorkbookModel.from_cells(cells, formulas)
        config = CandidatePoolConfig(ast_budget=1, peer_budget=1, peer_radius=4)

        first = build_candidate_pool(model, ("S", "C3"), config=config)
        second = build_candidate_pool(model, ("S", "C3"), config=config)

        self.assertEqual(first, second)
        self.assertEqual(first.audit.ast_selected, 1)
        self.assertEqual(first.audit.peer_selected, 1)
        self.assertEqual(
            dict(first.audit.source_budgets),
            {AST_SOURCE: 1, PEER_SOURCE: 1},
        )
        self.assertEqual(first.audit.peer_radius, 4)
        self.assertEqual(first.audit.minimum_peer_votes, 2)
        self.assertTrue(any(item.ast_provenance for item in first.candidates))
        self.assertTrue(any(item.peer_votes for item in first.candidates))
        wanted = canonical_formula_key("=A3+B3")
        matching = [
            item for item in first.candidates if item.canonical_key == wanted
        ]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].sources, (AST_SOURCE, PEER_SOURCE))
        self.assertEqual(len(matching[0].ast_provenance), 1)
        self.assertEqual(len(matching[0].peer_votes), 4)

    def test_peer_search_stops_at_blank_formula_boundaries(self):
        model = WorkbookModel.from_cells(
            {("S", f"A{row}"): row for row in range(1, 6)},
            {
                ("S", "B1"): "=A1",
                ("S", "B2"): "=A2",
                ("S", "B4"): "=A4+1",
                ("S", "B5"): "=A5",
            },
        )

        candidates = generate_peer_translation_candidates(model, ("S", "B4"))
        self.assertEqual(candidates, ())

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least two"):
            CandidatePoolConfig(minimum_peer_votes=1).validate()
        with self.assertRaisesRegex(ValueError, "non-negative"):
            CandidatePoolConfig(ast_budget=-1).validate()
        with self.assertRaisesRegex(TypeError, "integer"):
            CandidatePoolConfig(peer_budget=True).validate()


if __name__ == "__main__":
    unittest.main()
