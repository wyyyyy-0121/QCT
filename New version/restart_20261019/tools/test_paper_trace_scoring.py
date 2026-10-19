import unittest

from score_paper_candidate_trace import difference_class, pool_diagnosis


def array(text, ref):
    return dict(unsupported_formula_object='ArrayFormula', text=text, ref=ref)


class TraceScoringTests(unittest.TestCase):
    def test_single_cell_array_reference_spelling_only(self):
        self.assertEqual(difference_class(dict(input_formula=array('=A1', 'B1'),
                                              golden_formula=array('=A1', 'B1:B1'))),
                         'array_text_and_bounds_identical_representation_only')

    def test_type_conversion_and_expanding_array_are_not_normalized_away(self):
        self.assertEqual(difference_class(dict(input_formula='=A1', golden_formula=array('=A1', 'B1'))),
                         'formula_type_conversion_same_text_unknown')
        self.assertEqual(difference_class(dict(input_formula=array('=A1', 'B1'),
                                              golden_formula=array('=A1', 'B1:B2'))),
                         'array_region_changed_or_unknown')

    def test_pool_hit_and_missing_target_are_separate(self):
        trace = dict(observed_formulas={'S!B1': '=A1*3', 'S!B2': '=A2*3'},
                     paper={'rows': [dict(cell='S!B1', suggested_formula='=A1*4')]},
                     candidate_trace={'fg': {'S!B1': [dict(formula='=A1*2')]}, 'sg': {}},
                     fg_selected={'S!B1': '=A1*4'}, sg_selected={}, input_xml_types={'S!B3': 'numeric'})
        part, reasons, outside, counts = pool_diagnosis(trace, {'S!B1': '=A1*2', 'S!B2': '=A2*2',
                                                               'S!B3': '=A3*2'}, 'complete')
        self.assertEqual(part, dict(exact_in_observed_pool_but_not_final=1,
                                    no_exact_in_observed_pools=1, target_not_in_input_formula_inventory=1))
        self.assertEqual(counts['union_exact_reachable'], 1)
        self.assertEqual(outside, dict(numeric=1))
        self.assertEqual(reasons['fg_not_emitted'], 1)

    def test_timeout_keeps_all_targets_and_claims_no_pool_observation(self):
        part, _, _, counts = pool_diagnosis({}, {'S!A1': '=1', 'S!A2': '=2'}, 'timeout')
        self.assertEqual(part, dict(baseline_timeout_unobserved_pool=2))
        self.assertFalse(counts)


if __name__ == '__main__':
    unittest.main()
