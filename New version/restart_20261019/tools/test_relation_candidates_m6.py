from copy import deepcopy
import unittest

from relation_candidates_m6 import review


class RelationGenerationTests(unittest.TestCase):
    def request(self, **changes):
        data = dict(sheet='S', cell='D2', symbols={'q': {'units': {'flow': 1}}, 'd': {'units': {}}},
                    output_units={'flow': 1}, references={'B2': 'q', 'C2': 'd'},
                    relations=[dict(lhs='y*d', rhs='q')])
        data.update(changes)
        return data

    def test_missing_native_candidate_is_generated_without_provided_formula(self):
        request = self.request()
        original = deepcopy(request)
        result = review(request, '=B2*(3-C2)/2', [])
        self.assertEqual(result['suggested_formula'], '=(B2/C2)')
        self.assertFalse(result['native_pool_has_equivalent'])
        self.assertEqual(request, original)

    def test_absent_conflicting_and_nonunique_relations_do_not_propose(self):
        for relations in ([], [dict(lhs='y*d', rhs='q'), dict(lhs='y', rhs='q*(2-d)')],
                          [dict(lhs='y*(d-1)', rhs='q')], [dict(lhs='y*y', rhs='q')]):
            result = review(self.request(relations=relations), '=B2*(3-C2)/2', [])
            self.assertNotEqual(result['status'], 'propose')

    def test_original_correct_and_business_exception_stay_unchanged(self):
        self.assertEqual(review(self.request(), '=B2/C2', [])['reason'], 'original_satisfies_contract')
        exception = self.request(relations=[dict(lhs='y', rhs='q*(2-d)')])
        self.assertEqual(review(exception, '=B2*(2-C2)', [])['reason'], 'original_satisfies_contract')

    def test_mapping_units_and_manual_candidates_are_checked(self):
        for changes in (dict(references={'B2': 'q'}), dict(references={'B2': 'q', 'D2': 'd'}),
                        dict(references={'B2': 'q', 'C2': 'd', 'C3': 'd'}),
                        dict(output_units={'mass': 1}), dict(candidates=['=B2/C2'])):
            with self.subTest(changes=changes):
                result = review(self.request(**changes), '=B2*(3-C2)/2', [])
                self.assertEqual(result['status'], 'unsupported')

    def test_if_prefix_preserves_spacing_quoted_commas_and_escaped_quotes(self):
        observed = '=IF( A1="a,b" , IF(A2=0,"x""y",B2) ,B2*(3-C2)/2)'
        request = self.request(branch={'guard': 'A1="a,b"', 'inactive': 'IF(A2=0,"x""y",B2)'})
        result = review(request, observed, [])
        self.assertEqual(result['status'], 'propose')
        self.assertTrue(result['suggested_formula'].startswith('=IF( A1="a,b" , IF(A2=0,"x""y",B2) ,'))

    def test_existing_equivalent_pool_candidate_does_not_count_as_generation_gain(self):
        result = review(self.request(), '=B2*(3-C2)/2', ['=B2/C2'])
        self.assertTrue(result['native_pool_has_equivalent'])
        self.assertEqual(result['suggested_formula'], '=B2/C2')


if __name__ == '__main__':
    unittest.main()
