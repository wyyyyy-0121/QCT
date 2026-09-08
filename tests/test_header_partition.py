import unittest
from unittest import mock

from formulaguard import header_partition
from formulaguard.a1 import num_to_col
from formulaguard.header_partition import (
    ColumnInterval,
    analyze_header_partitions,
    discover_header_partition_certificates,
    normalize_header,
)
from formulaguard.workbook import WorkbookModel


def _fixture_parts(
    *,
    sheet="S",
    rows=range(4, 7),
    target_kind="omission",
    target_cache_base=-999,
):
    cells = {}
    for column in (*range(3, 13), *range(19, 22)):
        cells[(sheet, f"{num_to_col(column)}1")] = "PALO VERDE"
    for column in (*range(13, 18), *range(22, 25)):
        cells[(sheet, f"{num_to_col(column)}1")] = "FOUR CORNERS"
    for column in range(25, 28):
        cells[(sheet, f"{num_to_col(column)}1")] = "EDDY"
    cells.update(
        {
            (sheet, "AC2"): "TOTAL NET",
            (sheet, "AD2"): "NET PALO VERDE",
            (sheet, "AE2"): "NET FOUR CORNERS",
            (sheet, "AF2"): "NET EDDY",
        }
    )

    formulas = {}
    for row in rows:
        for column in (*range(3, 18), *range(19, 28)):
            cells[(sheet, f"{num_to_col(column)}{row}")] = row * 100 + column
        formulas[(sheet, f"AC{row}")] = f"=SUM(C{row}:AA{row})"
        formulas[(sheet, f"AD{row}")] = f"=SUM(C{row}:L{row},S{row}:U{row})"
        if target_kind == "omission":
            target = f"=SUM(M{row}:Q{row},V{row})"
        elif target_kind == "other_omission":
            target = f"=SUM(M{row}:P{row},V{row}:X{row})"
        elif target_kind == "correct":
            target = f"=SUM(M{row}:Q{row},V{row}:X{row})"
        else:
            target = str(target_kind).format(row=row)
        formulas[(sheet, f"AE{row}")] = target
        formulas[(sheet, f"AF{row}")] = f"=SUM(Y{row}:AA{row})"
        cells[(sheet, f"AE{row}")] = target_cache_base - row
    return cells, formulas


def _model_from_parts(
    cells,
    formulas,
    *,
    sheet_visibility=None,
    cell_visibility=None,
    merged_ranges=None,
    formula_kinds=None,
    shared_formula_groups=None,
):
    return WorkbookModel(
        cells,
        formulas,
        source="header-partition-fixture",
        cell_visibility=cell_visibility,
        sheet_visibility=sheet_visibility,
        merged_ranges=merged_ranges,
        formula_kinds=formula_kinds,
        shared_formula_groups=shared_formula_groups,
        header_partition_metadata_complete=True,
    )


def _model(
    *,
    sheet="S",
    rows=range(4, 7),
    target_kind="omission",
    target_cache_base=-999,
    cell_visibility=None,
    merged_ranges=None,
    formula_kinds=None,
    shared_formula_groups=None,
):
    cells, formulas = _fixture_parts(
        sheet=sheet,
        rows=rows,
        target_kind=target_kind,
        target_cache_base=target_cache_base,
    )
    return _model_from_parts(
        cells,
        formulas,
        cell_visibility=cell_visibility,
        sheet_visibility={sheet: True},
        merged_ranges=merged_ranges,
        formula_kinds=formula_kinds,
        shared_formula_groups=shared_formula_groups,
    )


def _target_certificate(model, target=("S", "AE4")):
    return next(
        certificate
        for certificate in discover_header_partition_certificates(model)
        if certificate.target_formula_cell == target
    )


class HeaderPartitionTests(unittest.TestCase):
    def test_header_grounded_candidate_has_explicit_claim_boundary(self):
        result = analyze_header_partitions(_model())

        self.assertIsNone(result.abstain_reason)
        self.assertEqual(len(result.qualified_blocks), 1)
        self.assertEqual(result.deterministic_representative.target, ("S", "AE4"))
        self.assertEqual(
            result.deterministic_representative.candidate_formula,
            "=SUM(M4:Q4,V4:X4)",
        )
        self.assertEqual(result.deterministic_representative.missing_columns, (23, 24))
        self.assertEqual(result.deterministic_representative.extra_columns, ())
        self.assertEqual(
            result.deterministic_representative.interpretation,
            "workbook_internal_schema_disagreement",
        )
        self.assertTrue(result.deterministic_representative.observed_disagrees)
        self.assertTrue(result.deterministic_representative.candidate_identified)
        self.assertTrue(
            result.deterministic_representative.candidate_derived_without_observed_target
        )
        self.assertTrue(
            result.deterministic_representative.observed_target_used_for_comparison
        )
        self.assertFalse(result.deterministic_representative.target_excluded)
        self.assertTrue(
            result.deterministic_representative.actionable_schema_disagreement
        )
        self.assertFalse(
            result.deterministic_representative.can_identify_formula_error
        )

        block = result.qualified_blocks[0]
        self.assertEqual(len(block.cells), 3)
        self.assertEqual(
            block.selection_basis, "coordinate_canonicalization_only"
        )
        self.assertFalse(block.within_block_ranking_supported)
        self.assertEqual(
            block.deterministic_representative,
            result.deterministic_representative,
        )
        self.assertEqual(
            block.tied_candidate_cells,
            (("S", "AE4"), ("S", "AE5"), ("S", "AE6")),
        )
        self.assertEqual(block.formula_cell_review_cost, 3)
        self.assertEqual(block.incomparable_formula_cell_review_cost, 0)
        self.assertEqual(
            block.reviewed_formula_cells,
            (("S", "AE4"), ("S", "AE5"), ("S", "AE6")),
        )
        self.assertEqual(block.schema_block_review_cost, 1)
        certificate = block.certificate
        self.assertEqual(certificate.row_start, 4)
        self.assertEqual(certificate.row_end, 6)
        self.assertEqual(certificate.source_header_row, 1)
        self.assertEqual(certificate.output_header_row, 2)
        self.assertEqual(certificate.target_role_tokens, ("four", "corners"))
        self.assertEqual(
            certificate.target_intervals,
            (ColumnInterval(13, 17), ColumnInterval(22, 24)),
        )
        self.assertEqual(certificate.unmapped_columns, (18,))
        self.assertEqual(
            certificate.excluded_target_cells,
            (("S", "AE4"), ("S", "AE5"), ("S", "AE6")),
        )
        self.assertEqual(len(certificate.sibling_witnesses), 2)
        self.assertEqual(
            {item.output_header for item in certificate.sibling_witnesses},
            {"NET PALO VERDE", "NET EDDY"},
        )
        self.assertTrue(certificate.candidate_identified)
        self.assertTrue(certificate.candidate_derived_without_observed_target)
        self.assertFalse(certificate.observed_target_used_for_comparison)
        self.assertTrue(certificate.target_excluded)
        self.assertFalse(certificate.can_identify_formula_error)
        self.assertTrue(certificate.formula_role_provenance_disjoint)
        self.assertFalse(
            certificate.repeated_rows_are_independent_author_witnesses
        )
        self.assertTrue(certificate.target_input_domain_has_observed_values)
        self.assertEqual(
            certificate.interpretation, "header_grounded_partition_candidate"
        )
        self.assertEqual(certificate.candidate_scope, "repeated_formula_block")
        self.assertFalse(certificate.within_block_ranking_supported)

    def test_candidate_certificate_is_invariant_to_target_formula_and_cache(self):
        models = [
            _model(target_kind="omission", target_cache_base=10_000),
            _model(target_kind="other_omission", target_cache_base=20_000),
            _model(target_kind="correct", target_cache_base=30_000),
        ]
        certificates = [_target_certificate(model) for model in models]

        self.assertEqual(certificates[0], certificates[1])
        self.assertEqual(certificates[1], certificates[2])
        self.assertEqual(
            analyze_header_partitions(
                models[0]
            ).deterministic_representative.candidate_formula,
            "=SUM(M4:Q4,V4:X4)",
        )
        self.assertEqual(
            analyze_header_partitions(
                models[1]
            ).deterministic_representative.candidate_formula,
            "=SUM(M4:Q4,V4:X4)",
        )
        correct = analyze_header_partitions(models[2])
        self.assertEqual(correct.qualified_blocks, ())
        self.assertEqual(correct.abstain_reason, "no_qualified_block")
        observation = next(
            item
            for item in correct.observations
            if item.certificate.target_formula_cell == ("S", "AE4")
        )
        self.assertTrue(
            all(cell.observed_disagrees is False for cell in observation.cells)
        )
        self.assertTrue(all(cell.comparison_supported for cell in observation.cells))
        self.assertTrue(all(cell.candidate_identified for cell in observation.cells))
        self.assertTrue(
            all(
                cell.candidate_derived_without_observed_target
                for cell in observation.cells
            )
        )
        self.assertTrue(
            all(cell.observed_target_used_for_comparison for cell in observation.cells)
        )
        self.assertTrue(all(not cell.target_excluded for cell in observation.cells))
        self.assertTrue(
            all(
                not cell.actionable_schema_disagreement
                for cell in observation.cells
            )
        )
        self.assertTrue(
            all(not cell.can_identify_formula_error for cell in observation.cells)
        )

    def test_mixed_observation_block_retains_every_row_and_full_review_cost(self):
        cells, formulas = _fixture_parts(target_kind="correct")
        formulas[("S", "AE5")] = "=SUM(M5:Q5,V5)"
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )

        result = analyze_header_partitions(model)

        self.assertEqual(len(result.qualified_blocks), 1)
        block = result.qualified_blocks[0]
        self.assertEqual(len(block.cells), 3)
        self.assertEqual(block.tied_candidate_cells, (("S", "AE5"),))
        self.assertEqual(block.formula_cell_review_cost, 3)
        self.assertEqual(block.deterministic_representative.target, ("S", "AE5"))
        observation = next(
            item
            for item in result.observations
            if item.certificate.target_formula_cell == ("S", "AE4")
        )
        self.assertEqual(
            tuple(cell.observed_disagrees for cell in observation.cells),
            (False, True, False),
        )

    def test_incomparable_row_preserves_whole_block_and_forces_abstention(self):
        cells, formulas = _fixture_parts()
        formulas[("S", "AE5")] = "=AVERAGE(M5:Q5,V5:X5)"
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )

        result = analyze_header_partitions(model)

        self.assertEqual(len(result.qualified_blocks), 1)
        self.assertIsNone(result.deterministic_representative)
        self.assertEqual(
            result.abstain_reason,
            "qualified_block_contains_incomparable_rows",
        )
        block = result.qualified_blocks[0]
        self.assertEqual(
            block.reviewed_formula_cells,
            (("S", "AE4"), ("S", "AE5"), ("S", "AE6")),
        )
        self.assertEqual(
            block.tied_candidate_cells,
            (("S", "AE4"), ("S", "AE6")),
        )
        self.assertEqual(
            tuple(cell.target for cell in block.incomparable_cells),
            (("S", "AE5"),),
        )
        self.assertEqual(block.formula_cell_review_cost, 3)
        self.assertEqual(block.incomparable_formula_cell_review_cost, 1)
        self.assertTrue(
            all(
                not cell.actionable_schema_disagreement
                for cell in block.incomparable_cells
            )
        )

    def test_empty_target_input_domain_is_schema_disagreement_but_not_action(self):
        cells, formulas = _fixture_parts()
        target_input_columns = (*range(13, 18), *range(22, 25))
        for row in range(4, 7):
            for column in target_input_columns:
                cells.pop(("S", f"{num_to_col(column)}{row}"))
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )

        result = analyze_header_partitions(model)

        self.assertEqual(len(result.qualified_blocks), 1)
        self.assertIsNone(result.deterministic_representative)
        self.assertEqual(result.abstain_reason, "target_input_domain_empty")
        block = result.qualified_blocks[0]
        self.assertEqual(block.formula_cell_review_cost, 3)
        self.assertFalse(
            block.certificate.target_input_domain_has_observed_values
        )
        self.assertTrue(
            all(cell.observed_disagrees is True for cell in block.cells)
        )
        self.assertTrue(
            all(
                cell.interpretation
                == "workbook_internal_schema_disagreement_inactive_target_domain"
                for cell in block.cells
            )
        )
        self.assertTrue(
            all(
                not cell.actionable_schema_disagreement for cell in block.cells
            )
        )

    def test_partial_empty_target_input_row_forces_conservative_block_abstention(self):
        cells, formulas = _fixture_parts()
        target_input_columns = (*range(13, 18), *range(22, 25))
        for column in target_input_columns:
            cells.pop(("S", f"{num_to_col(column)}5"))
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )

        result = analyze_header_partitions(model)

        # Rows 4 and 6 still contain values, but must not activate the block
        # while row 5 has no observed target-domain input.
        self.assertEqual(len(result.qualified_blocks), 1)
        self.assertIsNone(result.deterministic_representative)
        self.assertEqual(result.abstain_reason, "target_input_domain_empty")
        block = result.qualified_blocks[0]
        self.assertFalse(
            block.certificate.target_input_domain_has_observed_values
        )
        self.assertTrue(
            all(
                cell.interpretation
                == "workbook_internal_schema_disagreement_inactive_target_domain"
                for cell in block.cells
            )
        )
        self.assertTrue(
            all(not cell.actionable_schema_disagreement for cell in block.cells)
        )

    def test_derivation_receives_target_formula_and_cache_masked_model(self):
        cells, formulas = _fixture_parts()
        cells[("S", "AE100")] = 314159
        formulas[("S", "AE100")] = "=A100"
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        original = header_partition._source_header_candidates
        with mock.patch.object(
            header_partition,
            "_source_header_candidates",
            wraps=original,
        ) as derive:
            certificates = discover_header_partition_certificates(model)

        self.assertTrue(certificates)
        target_calls = [
            call
            for call in derive.call_args_list
            if call.kwargs["target_index"] == 1
        ]
        self.assertTrue(target_calls)
        for call in target_calls:
            masked = call.args[0]
            for row in range(4, 7):
                key = ("S", f"AE{row}")
                self.assertNotIn(key, masked.formulas)
                self.assertNotIn(key, masked.cells)
            self.assertEqual(masked.cells[("S", "AE100")], 314159)
            self.assertEqual(masked.formulas[("S", "AE100")], "=A100")
        certificate = next(
            item
            for item in certificates
            if item.target_formula_cell == ("S", "AE4")
        )
        self.assertEqual(
            certificate.excluded_target_cells,
            (("S", "AE4"), ("S", "AE5"), ("S", "AE6")),
        )

    def test_four_component_partition_with_distinct_layout_is_supported(self):
        cells = {
            ("Ledger", "A3"): "EAST",
            ("Ledger", "B3"): "EAST",
            ("Ledger", "C3"): "WEST",
            ("Ledger", "D3"): "WEST",
            ("Ledger", "E3"): "NORTH",
            ("Ledger", "F3"): "NORTH",
            ("Ledger", "G3"): "SOUTH",
            ("Ledger", "H3"): "SOUTH",
            ("Ledger", "J4"): "TOTAL FLOW",
            ("Ledger", "K4"): "FLOW EAST",
            ("Ledger", "L4"): "FLOW WEST",
            ("Ledger", "M4"): "FLOW NORTH",
            ("Ledger", "N4"): "FLOW SOUTH",
        }
        formulas = {}
        for row in range(6, 9):
            for column in range(1, 9):
                cells[("Ledger", f"{num_to_col(column)}{row}")] = row * 10 + column
            formulas[("Ledger", f"J{row}")] = f"=SUM(A{row}:H{row})"
            formulas[("Ledger", f"K{row}")] = f"=SUM(A{row})"
            formulas[("Ledger", f"L{row}")] = f"=SUM(C{row}:D{row})"
            formulas[("Ledger", f"M{row}")] = f"=SUM(E{row}:F{row})"
            formulas[("Ledger", f"N{row}")] = f"=SUM(G{row}:H{row})"
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"Ledger": True},
        )

        result = analyze_header_partitions(model)

        self.assertEqual(len(result.qualified_blocks), 1)
        candidate = result.deterministic_representative
        self.assertEqual(candidate.target, ("Ledger", "K6"))
        self.assertEqual(candidate.candidate_formula, "=SUM(A6:B6)")
        self.assertEqual(candidate.missing_columns, (2,))
        certificate = result.qualified_blocks[0].certificate
        self.assertEqual(certificate.component_columns, (11, 12, 13, 14))
        self.assertEqual(certificate.target_intervals, (ColumnInterval(1, 2),))
        self.assertEqual(len(certificate.sibling_witnesses), 3)
        self.assertEqual(
            certificate.excluded_target_cells,
            (("Ledger", "K6"), ("Ledger", "K7"), ("Ledger", "K8")),
        )

    def test_grand_header_rejects_role_tokens_beyond_exact_shared_tokens(self):
        cells, formulas = _fixture_parts()
        cells[("S", "AC2")] = "TOTAL NET PORTFOLIO"
        model = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )

        self.assertEqual(discover_header_partition_certificates(model), ())

    def test_reverse_ranges_nested_sums_and_formula_inputs_are_rejected(self):
        cells, formulas = _fixture_parts()
        for row in range(4, 7):
            formulas[("S", f"AC{row}")] = f"=SUM(AA{row}:C{row})"
        reverse = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(discover_header_partition_certificates(reverse), ())

        cells, formulas = _fixture_parts()
        for row in range(4, 7):
            formulas[("S", f"AD{row}")] = (
                f"=SUM(C{row}:L{row},SUM(S{row}:U{row}))"
            )
        nested = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(discover_header_partition_certificates(nested), ())

        cells, formulas = _fixture_parts()
        for row in range(4, 7):
            cells.pop(("S", f"W{row}"))
            formulas[("S", f"W{row}")] = f"=C{row}"
        formula_input = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(discover_header_partition_certificates(formula_input), ())

    def test_hidden_or_merged_structural_evidence_is_rejected_for_every_role(self):
        cases = {
            "source_header_hidden": _model(
                cell_visibility={("S", "W1"): False}
            ),
            "source_header_merged": _model(
                merged_ranges={"S": (("M1", "Q1"),)}
            ),
            "output_header_hidden": _model(
                cell_visibility={("S", "AE2"): False}
            ),
            "output_header_merged": _model(
                merged_ranges={"S": (("AE2", "AF2"),)}
            ),
            "source_value_hidden": _model(
                cell_visibility={("S", "M5"): False}
            ),
            "source_value_merged": _model(
                merged_ranges={"S": (("M5", "N5"),)}
            ),
            "formula_evidence_hidden": _model(
                cell_visibility={("S", "AF5"): False}
            ),
            "formula_evidence_merged": _model(
                merged_ranges={"S": (("AF5", "AF6"),)}
            ),
            "target_formula_hidden": _model(
                cell_visibility={("S", "AE5"): False}
            ),
            "target_formula_merged": _model(
                merged_ranges={"S": (("AE5", "AE6"),)}
            ),
        }
        for name, model in cases.items():
            with self.subTest(name=name):
                self.assertEqual(
                    discover_header_partition_certificates(model),
                    (),
                )

        cells, formulas = _fixture_parts()
        cells.pop(("S", "W1"))
        formulas[("S", "W1")] = "=C1"
        formula_header = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(discover_header_partition_certificates(formula_header), ())

    def test_unknown_or_active_unmapped_headers_are_rejected(self):
        cells, formulas = _fixture_parts()
        cells[("S", "R1")] = "PALO VERDE / FOUR CORNERS"
        for row in range(4, 7):
            cells[("S", f"R{row}")] = 1
        ambiguous = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(discover_header_partition_certificates(ambiguous), ())

        cells, formulas = _fixture_parts()
        for row in range(4, 7):
            cells[("S", f"R{row}")] = 1
        active_spacer = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(discover_header_partition_certificates(active_spacer), ())

    def test_repeat_and_sibling_witness_minima_are_enforced(self):
        self.assertEqual(
            discover_header_partition_certificates(
                _model(rows=range(4, 6))
            ),
            (),
        )

        cells, formulas = _fixture_parts()
        for row in range(4, 7):
            formulas.pop(("S", f"AF{row}"))
        no_third_sibling = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        self.assertEqual(
            discover_header_partition_certificates(no_third_sibling), ()
        )

    def test_array_target_is_not_promoted_from_formula_occupancy(self):
        kinds = {("S", f"AE{row}"): "array" for row in range(4, 7)}
        result = analyze_header_partitions(_model(formula_kinds=kinds))

        self.assertTrue(_target_certificate(_model(formula_kinds=kinds)))
        self.assertEqual(result.qualified_blocks, ())
        self.assertEqual(result.abstain_reason, "observed_target_incomparable")
        observation = next(
            item
            for item in result.observations
            if item.certificate.target_formula_cell == ("S", "AE4")
        )
        self.assertTrue(
            all(cell.observed_disagrees is None for cell in observation.cells)
        )
        self.assertTrue(
            all(not cell.comparison_supported for cell in observation.cells)
        )

    def test_shared_formula_groups_must_be_independent_of_target_and_each_other(self):
        target_and_sibling = {
            ("S", f"AE{row}"): "S:target-derived"
            for row in range(4, 7)
        }
        target_and_sibling.update(
            {
                ("S", f"AD{row}"): "S:target-derived"
                for row in range(4, 7)
            }
        )
        self.assertEqual(
            discover_header_partition_certificates(
                _model(shared_formula_groups=target_and_sibling)
            ),
            (),
        )

        coupled_witnesses = {
            ("S", f"AD{row}"): "S:coupled-witnesses"
            for row in range(4, 7)
        }
        coupled_witnesses.update(
            {
                ("S", f"AF{row}"): "S:coupled-witnesses"
                for row in range(4, 7)
            }
        )
        self.assertEqual(
            discover_header_partition_certificates(
                _model(shared_formula_groups=coupled_witnesses)
            ),
            (),
        )

        cross_row_roles = {
            ("S", "AE4"): "S:cross-row-role",
            ("S", "AD5"): "S:cross-row-role",
        }
        cross_row_certificates = discover_header_partition_certificates(
            _model(shared_formula_groups=cross_row_roles)
        )
        self.assertFalse(
            any(
                certificate.target_formula_cell == ("S", "AE4")
                for certificate in cross_row_certificates
            )
        )

        cross_row_grand_and_sibling = {
            ("S", "AC6"): "S:cross-row-grand-sibling",
            ("S", "AF4"): "S:cross-row-grand-sibling",
        }
        cross_grand_certificates = discover_header_partition_certificates(
            _model(shared_formula_groups=cross_row_grand_and_sibling)
        )
        self.assertFalse(
            any(
                certificate.target_formula_cell == ("S", "AE4")
                for certificate in cross_grand_certificates
            )
        )

        independent_groups = {
            ("S", f"AC{row}"): "S:grand"
            for row in range(4, 7)
        }
        for column, group in (
            ("AD", "S:palo"),
            ("AE", "S:four-corners"),
            ("AF", "S:eddy"),
        ):
            independent_groups.update(
                {("S", f"{column}{row}"): group for row in range(4, 7)}
            )
        certificate = _target_certificate(
            _model(shared_formula_groups=independent_groups)
        )
        self.assertTrue(certificate.formula_role_provenance_disjoint)
        self.assertFalse(
            certificate.repeated_rows_are_independent_author_witnesses
        )

    def test_multiple_workbook_blocks_force_abstention(self):
        left_cells, left_formulas = _fixture_parts(sheet="S")
        right_cells, right_formulas = _fixture_parts(sheet="T")
        model = _model_from_parts(
            {**left_cells, **right_cells},
            {**left_formulas, **right_formulas},
            sheet_visibility={"S": True, "T": True},
        )

        result = analyze_header_partitions(model)
        self.assertEqual(len(result.qualified_blocks), 2)
        self.assertIsNone(result.deterministic_representative)
        self.assertEqual(result.abstain_reason, "multiple_qualified_blocks")

    def test_output_is_stable_under_mapping_insertion_order(self):
        cells, formulas = _fixture_parts()
        forward = _model_from_parts(
            cells,
            formulas,
            sheet_visibility={"S": True},
        )
        reverse = _model_from_parts(
            dict(reversed(tuple(cells.items()))),
            dict(reversed(tuple(formulas.items()))),
            sheet_visibility={"S": True},
        )

        self.assertEqual(
            analyze_header_partitions(forward), analyze_header_partitions(reverse)
        )

    def test_incomplete_metadata_abstains_explicitly(self):
        cells, formulas = _fixture_parts()
        result = analyze_header_partitions(WorkbookModel(cells, formulas))

        self.assertEqual(result.certificates, ())
        self.assertEqual(result.observations, ())
        self.assertEqual(result.qualified_blocks, ())
        self.assertIsNone(result.deterministic_representative)
        self.assertEqual(result.abstain_reason, "structure_metadata_unavailable")

    def test_header_normalization_is_case_stable_but_does_not_stem_plurals(self):
        self.assertEqual(
            normalize_header(" FOUR Corners "), ("four", "corners")
        )
        self.assertNotEqual(
            normalize_header("FOUR CORNERS"), normalize_header("four corner")
        )
        self.assertEqual(normalize_header("STATUS"), ("status",))

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least three"):
            header_partition.HeaderPartitionConfig(min_components=2).validate()
        with self.assertRaisesRegex(ValueError, "smaller"):
            header_partition.HeaderPartitionConfig(
                min_components=4, max_components=3
            ).validate()
        with self.assertRaisesRegex(TypeError, "integer"):
            header_partition.HeaderPartitionConfig(min_repeat_rows=True).validate()
        for value in (0, 1, 2):
            with self.subTest(min_repeat_rows=value), self.assertRaises(ValueError):
                header_partition.HeaderPartitionConfig(
                    min_repeat_rows=value
                ).validate()
        with self.assertRaisesRegex(ValueError, "frozen bound of eight"):
            header_partition.HeaderPartitionConfig(min_grand_width=7).validate()
        with self.assertRaisesRegex(ValueError, "bound of six"):
            header_partition.HeaderPartitionConfig(max_components=7).validate()
        with self.assertRaisesRegex(ValueError, "bound of five"):
            header_partition.HeaderPartitionConfig(
                output_header_lookback=6
            ).validate()


if __name__ == "__main__":
    unittest.main()
