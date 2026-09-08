import unittest

from formulaguard.shared_formula_integrity import (
    analyze_shared_formula_integrity,
    discover_shared_formula_integrity_certificates,
    v4_sfri_fifth,
)
from formulaguard.workbook import SharedFormulaRegion, WorkbookModel


def _model(
    target_formula: str = "=A5-B5",
    *,
    members: tuple[str, ...] = ("C2", "C3", "C4", "C6"),
    target_visible: bool = True,
    target_kind: str = "normal",
    extra_formulas: dict[tuple[str, str], str] | None = None,
) -> WorkbookModel:
    formulas = {
        ("Model", "C2"): "=A2+B2",
        ("Model", "C3"): "=A3+B3",
        ("Model", "C4"): "=A4+B4",
        ("Model", "C5"): target_formula,
        ("Model", "C6"): "=A6+B6",
        **(extra_formulas or {}),
    }
    group = "Model:7"
    groups = {("Model", address): group for address in members}
    kinds = {("Model", "C5"): target_kind}
    return WorkbookModel.from_cells(
        {},
        formulas,
        cell_visibility={("Model", "C5"): target_visible},
        formula_kinds=kinds,
        shared_formula_groups=groups,
        shared_formula_regions=(
            SharedFormulaRegion(
                sheet="Model",
                group_id=group,
                master_cell=("Model", "C2"),
                start="C2",
                end="C6",
                master_formula="=A2+B2",
                members=tuple(("Model", address) for address in members),
            ),
        ),
    )


class SharedFormulaIntegrityTests(unittest.TestCase):
    def test_single_hole_candidate_is_derived_from_master(self):
        result = analyze_shared_formula_integrity(_model())

        self.assertIsNone(result.abstain_reason)
        self.assertEqual(result.disagreement_cells, (("Model", "C5"),))
        comparison = result.deterministic_candidate
        self.assertIsNotNone(comparison)
        assert comparison is not None
        self.assertEqual(comparison.candidate_formula, "=A5+B5")
        self.assertEqual(comparison.observed_formula, "=A5-B5")
        self.assertTrue(comparison.observed_disagrees)
        self.assertTrue(
            comparison.certificate.candidate_derived_without_observed_target
        )
        self.assertFalse(comparison.certificate.can_identify_formula_error)

    def test_candidate_derivation_does_not_depend_on_target_formula(self):
        first = discover_shared_formula_integrity_certificates(
            _model("=A5-B5")
        )
        second = discover_shared_formula_integrity_certificates(
            _model("=SUM(A5:B5)")
        )

        self.assertEqual(first, second)

    def test_matching_ordinary_formula_is_audited_agreement(self):
        result = analyze_shared_formula_integrity(_model("=A5+B5"))

        self.assertEqual(result.abstain_reason, "no_schema_disagreement")
        self.assertEqual(len(result.certificates), 1)
        self.assertEqual(result.disagreement_cells, ())
        self.assertIsNone(result.deterministic_candidate)

    def test_multiple_holes_are_not_certified(self):
        result = analyze_shared_formula_integrity(
            _model(members=("C2", "C3", "C6"))
        )

        self.assertEqual(result.abstain_reason, "no_eligible_region")
        self.assertEqual(result.certificates, ())

    def test_nonordinary_or_invisible_target_is_not_certified(self):
        for name, model in {
            "hidden": _model(target_visible=False),
            "array": _model(target_kind="array"),
        }.items():
            with self.subTest(name=name):
                self.assertEqual(
                    discover_shared_formula_integrity_certificates(model),
                    (),
                )

    def test_target_in_another_shared_group_is_not_certified(self):
        model = _model()
        model.shared_formula_groups[("Model", "C5")] = "Model:other"

        self.assertEqual(
            discover_shared_formula_integrity_certificates(model),
            (),
        )

    def test_overlapping_shared_formula_regions_are_not_certified(self):
        first = _model()
        formulas = dict(first.formulas)
        formulas.update(
            {
                ("Model", f"{column}5"): f"={column}4+1"
                for column in ("D", "E", "F", "G")
            }
        )
        groups = dict(first.shared_formula_groups)
        groups.update(
            {
                ("Model", f"{column}5"): "Model:8"
                for column in ("D", "E", "F", "G")
            }
        )
        model = WorkbookModel.from_cells(
            {},
            formulas,
            shared_formula_groups=groups,
            shared_formula_regions=(
                *first.shared_formula_regions,
                SharedFormulaRegion(
                    sheet="Model",
                    group_id="Model:8",
                    master_cell=("Model", "D5"),
                    start="C5",
                    end="G5",
                    master_formula="=D4+1",
                    members=tuple(
                        ("Model", f"{column}5")
                        for column in ("D", "E", "F", "G")
                    ),
                ),
            ),
        )

        self.assertEqual(
            discover_shared_formula_integrity_certificates(model),
            (),
        )

    def test_multiple_disagreements_force_abstention(self):
        first = _model()
        formulas = dict(first.formulas)
        formulas.update(
            {
                ("Model", "E2"): "=A2*B2",
                ("Model", "E3"): "=A3*B3",
                ("Model", "E4"): "=A4*B4",
                ("Model", "E5"): "=A5/B5",
                ("Model", "E6"): "=A6*B6",
            }
        )
        groups = dict(first.shared_formula_groups)
        groups.update(
            {
                ("Model", address): "Model:8"
                for address in ("E2", "E3", "E4", "E6")
            }
        )
        model = WorkbookModel.from_cells(
            {},
            formulas,
            shared_formula_groups=groups,
            shared_formula_regions=(
                *first.shared_formula_regions,
                SharedFormulaRegion(
                    sheet="Model",
                    group_id="Model:8",
                    master_cell=("Model", "E2"),
                    start="E2",
                    end="E6",
                    master_formula="=A2*B2",
                    members=tuple(
                        ("Model", address)
                        for address in ("E2", "E3", "E4", "E6")
                    ),
                ),
            ),
        )

        result = analyze_shared_formula_integrity(model)

        self.assertEqual(result.abstain_reason, "multiple_schema_disagreements")
        self.assertEqual(
            result.disagreement_cells,
            (("Model", "C5"), ("Model", "E5")),
        )
        self.assertIsNone(result.deterministic_candidate)

    def test_v4_adapter_preserves_top_four_and_places_candidate_fifth(self):
        model = _model(
            extra_formulas={
                ("Model", "D2"): "=A2-B2",
                ("Model", "D3"): "=A3-B3",
            }
        )
        ranking = (
            ("Model", "C2"),
            ("Model", "C3"),
            ("Model", "C4"),
            ("Model", "C6"),
            ("Model", "D2"),
            ("Model", "D3"),
            ("Model", "C5"),
        )

        adapted = v4_sfri_fifth(model, ranking)

        self.assertEqual(adapted[:5], (*ranking[:4], ("Model", "C5")))
        self.assertEqual(adapted[5:], (("Model", "D2"), ("Model", "D3")))
        self.assertEqual(set(adapted), set(ranking))

    def test_v4_adapter_is_identity_without_one_disagreement(self):
        model = _model("=A5+B5")
        ranking = tuple(model.formula_cells)

        self.assertEqual(v4_sfri_fifth(model, ranking), ranking)

    def test_v4_adapter_rejects_incomplete_ranking(self):
        model = _model()

        with self.assertRaisesRegex(ValueError, "every formula cell"):
            v4_sfri_fifth(model, tuple(model.formula_cells[:-1]))


if __name__ == "__main__":
    unittest.main()
