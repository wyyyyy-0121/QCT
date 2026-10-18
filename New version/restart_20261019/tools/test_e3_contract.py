import unittest

from e3_contract import select


class ContractTests(unittest.TestCase):
    def request(self, **changes):
        request = dict(symbols={'q': {'units': {'flow': 1}}, 'd': {'units': {}}},
                       references={'B2': 'q', 'C2': 'd'}, constraints=['q/d'],
                       candidates=['=B2*(2-C2)', '=B2/C2'])
        request.update(changes)
        return request

    def test_current_value_coincidence_is_not_identity(self):
        out = select(self.request(), '=B2*(2-C2)')
        self.assertEqual(out['suggested_formula'], '=B2/C2')
        self.assertFalse(out['candidate_diagnostics'][0]['matches'])

    def test_opposite_contracts_reverse_candidate_selection(self):
        candidates = ['=B2/C2', '=B2*(2-C2)']
        ratio = select(self.request(constraints=['q/d'], candidates=candidates), '=B2*(3-C2)/2')
        affine = select(self.request(constraints=['q*(2-d)'], candidates=candidates), '=B2*(3-C2)/2')
        self.assertEqual(ratio['suggested_formula'], '=B2/C2')
        self.assertEqual(affine['suggested_formula'], '=B2*(2-C2)')

    def test_missing_and_conflicting_relations_abstain(self):
        for constraints in ([], ['q/d', 'q*(2-d)']):
            self.assertEqual(select(self.request(constraints=constraints), '=B2*(2-C2)')['status'], 'abstain')

    def test_unknown_reference_and_function_are_unsupported(self):
        for formula in ('=B2/Z9', '=SUM(B2:C2)'):
            self.assertEqual(select(self.request(candidates=[formula]), '=B2*(2-C2)')['status'], 'unsupported')

    def test_unsupported_domain_and_units_are_not_accepted(self):
        for formula in ('=B2/(1-C2)', '=B2+C2', '=B2**C2'):
            self.assertEqual(select(self.request(candidates=[formula]), '=B2*(2-C2)')['status'], 'unsupported')

    def test_if_envelope_cannot_be_changed(self):
        request = self.request(branch={'guard': 'A1="off"', 'inactive': 'B2'},
                               candidates=['=IF(A1="on",B2,B2/C2)'])
        self.assertEqual(select(request, '=IF(A1="off",B2,B2*(2-C2))')['status'], 'unsupported')

    def test_epa_branch_selects_ratio_without_changing_guard_or_inactive(self):
        guard = 'D35="Not applicable"'
        inactive = "'Data Inputs'!B23"
        original = f'=IF({guard},{inactive},(({inactive}*(1-D34))+{inactive}))'
        corrected = f'=IF({guard},{inactive},({inactive}/D34))'
        request = dict(
            symbols={'q': {'units': {'flow': 1}}, 'd': {'units': {}}},
            references={"'Data Inputs'!B23": 'q', 'D34': 'd'},
            constraints=['q/d'], candidates=[original, corrected],
            branch={'guard': guard, 'inactive': inactive})
        out = select(request, original)
        self.assertEqual(out['status'], 'propose')
        self.assertEqual(out['suggested_formula'], corrected)


if __name__ == '__main__':
    unittest.main()
