import unittest

from formulaguard.fcrl import (
    FCRLAdapterError,
    build_table_input,
    formula_to_prefix,
    independently_supported_alternatives,
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


class FCRLPeerSupportTests(unittest.TestCase):
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
