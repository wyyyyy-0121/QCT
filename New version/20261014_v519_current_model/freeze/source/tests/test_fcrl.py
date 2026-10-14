import unittest

from formulaguard.fcrl import (
    FCRLAdapterError,
    build_masked_context_input,
    build_table_input,
    formula_prefix_key,
    formula_to_prefix,
    independently_supported_alternatives,
    local_peer_completion_keys,
    translated_peer_candidates,
)
from formulaguard.workbook import WorkbookModel


def simple_workbook(formula="=SUM(B2:B3)", cached=24):
    cells = {
        ("Sheet", "A1"): "Item",
        ("Sheet", "B1"): "Value",
        ("Sheet", "A2"): "First",
        ("Sheet", "B2"): 11,
        ("Sheet", "A3"): "Second",
        ("Sheet", "B3"): 13,
        ("Sheet", "A4"): "Total",
        ("Sheet", "B4"): cached,
    }
    return WorkbookModel.from_cells(cells, {("Sheet", "B4"): formula})


class FCRLFormulaPrefixTests(unittest.TestCase):
    def test_maps_qct_ast_to_fortap_prefix(self):
        prefix = formula_to_prefix("=SUM(B2:B3)+A1*2")
        self.assertEqual(
            prefix.tokens,
            ("+", "SUM", "B2", ":", "B3", "*", "A1", "2"),
        )
        self.assertEqual(
            prefix.token_types,
            ("OP", "FUNC", "CELL", "SPECIAL", "CELL", "OP", "CELL", "NUMBER"),
        )
        self.assertEqual(prefix.reference_addresses, ("B2", "B3", "A1"))

    def test_rejects_cross_sheet_and_unknown_function(self):
        with self.assertRaisesRegex(FCRLAdapterError, "cross_sheet_reference"):
            formula_to_prefix("='Other'!A1+1")
        with self.assertRaisesRegex(FCRLAdapterError, "unsupported_formula_function"):
            formula_to_prefix("=MEDIAN(A1:A3)")

    def test_rejects_formula_without_pointer_target(self):
        with self.assertRaisesRegex(FCRLAdapterError, "formula_without_reference"):
            formula_to_prefix("=1+2")

    def test_prefix_key_collapses_numeric_literals(self):
        self.assertEqual(
            formula_prefix_key(formula_to_prefix("=A1*2.5+17")),
            "+ * A1 C-NUM C-NUM",
        )


class FCRLTableAdapterTests(unittest.TestCase):
    def test_target_formula_and_cached_value_do_not_change_encoder_material(self):
        first = build_table_input(simple_workbook("=SUM(B2:B3)", 24), ("Sheet", "B4"))
        second = build_table_input(simple_workbook("=B2+B3", 999), ("Sheet", "B4"))
        self.assertEqual(first.encoder_material_hash(), second.encoder_material_hash())
        self.assertEqual(first.string_matrix[3][1], "")
        self.assertEqual(first.format_matrix[3][1][7], 1.0)
        self.assertEqual(first.header_rows, 1)
        self.assertEqual(first.header_columns, 1)

    def test_rejects_reference_outside_contiguous_table_component(self):
        workbook = simple_workbook("=Z4+1")
        with self.assertRaisesRegex(FCRLAdapterError, "reference_outside_component"):
            build_table_input(workbook, ("Sheet", "B4"))

    def test_flat_positions_are_local_row_and_column_indices(self):
        table = build_table_input(simple_workbook(), ("Sheet", "B4"))
        self.assertEqual(table.shape, (4, 2))
        self.assertEqual(table.top_positions[0], (-1, -1, -1, 0))
        self.assertEqual(table.top_positions[1], (-1, -1, -1, 1))
        self.assertEqual(table.left_positions[0], (-1, -1, -1, 0))
        self.assertEqual(table.left_positions[-1], (-1, -1, -1, 3))

    def test_masked_context_does_not_parse_or_follow_target_formula(self):
        first = build_masked_context_input(simple_workbook("=MEDIAN(Z1:Z9)", 24), ("Sheet", "B4"))
        second = build_masked_context_input(simple_workbook("=1+2", 999), ("Sheet", "B4"))
        self.assertEqual(first.encoder_material_hash(), second.encoder_material_hash())
        self.assertEqual(first.table_range, second.table_range)
        self.assertEqual(first.formula_prefix.tokens, ("B4",))
        self.assertEqual(first.string_matrix[3][1], "")

    def test_masked_context_bounds_target_position_and_shape(self):
        cells = {
            ("Sheet", f"{column}{row}"): row
            for column in ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L")
            for row in range(1, 13)
        }
        workbook = WorkbookModel.from_cells(cells, {("Sheet", "L12"): "=A1"})
        table = build_masked_context_input(workbook, ("Sheet", "L12"))
        self.assertLessEqual(table.shape[0], 10)
        self.assertLessEqual(table.shape[1], 10)
        self.assertLessEqual(table.target_row, 5)
        self.assertLessEqual(table.target_column, 5)


class FCRLPeerSupportTests(unittest.TestCase):
    def test_local_peer_completion_does_not_read_target_formula(self):
        cells = {
            ("Sheet", f"{column}{row}"): row
            for column in ("A", "B")
            for row in range(1, 7)
        }
        peers = {
            ("Sheet", "B2"): "=A2",
            ("Sheet", "B3"): "=A3",
            ("Sheet", "B5"): "=A5",
            ("Sheet", "B6"): "=A6",
        }
        first = WorkbookModel.from_cells(
            cells,
            {**peers, ("Sheet", "B4"): "=A4+1"},
        )
        second = WorkbookModel.from_cells(
            cells,
            {**peers, ("Sheet", "B4"): "=SUM(A1:A4)"},
        )
        self.assertEqual(
            local_peer_completion_keys(first, ("Sheet", "B4")),
            local_peer_completion_keys(second, ("Sheet", "B4")),
        )

    def test_contiguous_translated_peers_count_as_one_block(self):
        cells = {}
        for row in range(1, 9):
            cells[("Sheet", f"A{row}")] = row
            cells[("Sheet", f"B{row}")] = row
        formulas = {
            ("Sheet", "B2"): "=A2",
            ("Sheet", "B3"): "=A3",
            ("Sheet", "B5"): "=B4",
            ("Sheet", "B7"): "=A7",
            ("Sheet", "B8"): "=A8",
        }
        workbook = WorkbookModel.from_cells(cells, formulas)
        candidates = translated_peer_candidates(workbook, ("Sheet", "B5"))
        candidate = next(item for item in candidates if item.normalized == "=A5")
        self.assertEqual(len(candidate.block_ids), 2)
        self.assertEqual(
            independently_supported_alternatives("=B4", candidates, []),
            ("=A5",),
        )

    def test_one_peer_block_requires_decoder_agreement(self):
        cells = {("Sheet", f"A{row}"): row for row in range(1, 6)}
        cells.update({("Sheet", f"B{row}"): row for row in range(1, 6)})
        formulas = {
            ("Sheet", "B2"): "=A2",
            ("Sheet", "B3"): "=A3",
            ("Sheet", "B5"): "=B4",
        }
        workbook = WorkbookModel.from_cells(cells, formulas)
        candidates = translated_peer_candidates(workbook, ("Sheet", "B5"))
        self.assertEqual(independently_supported_alternatives("=B4", candidates, []), ())
        self.assertEqual(
            independently_supported_alternatives("=B4", candidates, ["=A5"]),
            ("=A5",),
        )


if __name__ == "__main__":
    unittest.main()
