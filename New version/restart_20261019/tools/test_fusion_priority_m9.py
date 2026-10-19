from copy import deepcopy
import unittest

from fusion_priority_m9 import apply


class FusionPriorityTests(unittest.TestCase):
    def trace(self):
        return dict(observed_formulas={'S!C2': '=A2*3'},
                    fg_selected={'S!C2': '=A2*2'}, sg_selected={'S!C2': '=A2*4'},
                    paper=dict(rows=[dict(cell='S!C2', suggested_formula='=A2*2', suggestion_source='formulaguard-v5',
                                          rank=1, status='local_anomaly', hybrid_score=.8)]))

    def test_only_formula_source_and_audit_fields_change(self):
        trace = self.trace()
        original = deepcopy(trace)
        result = apply(trace)
        row = result['paper']['rows'][0]
        self.assertEqual(row['suggested_formula'], '=A2*4')
        self.assertEqual(result['changed_selection_count'], 1)
        self.assertEqual((row['rank'], row['status'], row['hybrid_score']), (1, 'local_anomaly', .8))
        self.assertEqual(trace, original)

    def test_validated_group_and_non_fg_outputs_untouched(self):
        for source in ['validated-parallel-sheet:Other', 'peer:S!C1', None]:
            trace = self.trace()
            trace['paper']['rows'][0]['suggestion_source'] = source
            self.assertEqual(apply(trace)['paper'], trace['paper'])

    def test_sg_absent_or_equal_original_or_same_as_fg_keeps_original(self):
        for sg in [None, '=A2*3', '=A2*2', 'Not a formula']:
            trace = self.trace()
            trace['sg_selected']['S!C2'] = sg
            self.assertEqual(apply(trace)['changed_selection_count'], 0)

    def test_fg_not_actually_emitted_or_not_a_change_does_not_switch(self):
        for fg in [None, '=A2*3', '=A2*5']:
            trace = self.trace()
            trace['fg_selected']['S!C2'] = fg
            self.assertEqual(apply(trace)['changed_selection_count'], 0)

    def test_reapplying_does_not_create_more_switches(self):
        trace = self.trace()
        result = apply(trace)
        trace['paper'] = result['paper']
        again = apply(trace)
        self.assertEqual(again['paper'], result['paper'])
        self.assertEqual(again['changed_selection_count'], 0)

    def test_fixed_precedence_cannot_identify_legitimate_business_exception(self):
        # Identical visible inputs: the correct formula depends on an external business definition.
        result = apply(self.trace())['paper']['rows'][0]['suggested_formula']
        self.assertEqual(result, '=A2*4')
        self.assertNotEqual(result, '=A2*2')  # If FG is the lawful exception, this is an incorrect switch.


if __name__ == '__main__':
    unittest.main()
