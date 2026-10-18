from copy import deepcopy
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from formulaguard.workbook import WorkbookModel
from annotation_evidence_dev14 import Notes, polynomial, same_relation, apply

class AnnotationEvidenceTests(unittest.TestCase):
    def model(self, formula='=$D$1*F2*F3*$D$4'):
        cells = {('S','B1'):'Power',('S','C1'):'MW',('S','D1'):100,
                 ('S','B2'):'Load',('S','C2'):'%',('S','B3'):'Availability',
                 ('S','C3'):'%',('S','B4'):'Hours',('S','C4'):'hours',('S','D4'):8760,
                 ('S','B5'):'Generation',('S','C5'):'MWh',
                 ('S','E5'):'Power x Load x Availability x Hours'}
        forms={}
        for c in 'FGH':
            cells['S',c+'2']=0.6; cells['S',c+'3']=0.95
            forms['S',c+'5']=f'=$D$1*{c}2*{c}3*$D$4'
        forms['S','F5']=formula
        cells.update({k:None for k in forms})
        return WorkbookModel(cells,forms)

    def run_model(self,m):
        prior={'rows':[{'cell':s+'!'+a,'status':'abstain','suggested_formula':None}
                       for s,a in m.formulas]}
        return apply(m,prior,deepcopy(prior))

    def test_exact_algebra_not_current_values(self):
        a=polynomial('=A1*(B1+C1)','S')
        self.assertTrue(same_relation('=C1*A1+A1*B1','s',a))
        self.assertFalse(same_relation('=A1*B1','S',a))
        self.assertFalse(same_relation('=9007199254740992*A1','S',
                                      polynomial('=9007199254740993*A1','S')))

    def test_absolute_markers_preserve_reference_identity(self):
        self.assertEqual(polynomial('=$A$1*B$2','S'),polynomial('=A1*$B2','S'))
        self.assertNotEqual(polynomial("='Other'!A1*B2",'S'),polynomial('=A1*B2','S'))

    def test_unsupported_and_expensive_grammar_rejected(self):
        for f in ['=A1/B1','=SUM(A1:A2)','=A1^2','=A1&"x"','=1e9999999*A1']:
            with self.subTest(f=f),self.assertRaises(ValueError):
                polynomial(f,'S')
        with self.assertRaises(ValueError):
            polynomial('='+'*'.join(['A1']*17),'S')

    def test_clean_no_repair_and_input_unchanged(self):
        m=self.model(); before=deepcopy((m.cells,m.formulas))
        r=self.run_model(m)
        self.assertTrue(all(x['status']=='abstain' for x in r['note_only']['rows']))
        self.assertEqual((m.cells,m.formulas),before)

    def test_isolated_operator_and_coefficient(self):
        for f in ['=$D$1+F2*F3*$D$4','=$D$1*F2*F3*$D$4*1.1']:
            with self.subTest(f=f):
                r=self.run_model(self.model(f))['note_only']['rows'][0]
                self.assertEqual(r['status'],'propose')
                self.assertEqual(r['suggested_formula'],'=$D$1*F2*F3*$D$4')

    def test_common_error_uses_single_edit_without_correct_peers(self):
        m=self.model()
        m.formulas={k:v.replace('*','+',1) for k,v in m.formulas.items()}
        r=self.run_model(m)['note_only']['rows']
        self.assertTrue(all(x['status']=='propose' for x in r))
        self.assertTrue(all(any(s['kind']=='single_edit' for s in x['candidate_sources']) for x in r))

    def test_hidden_note_input_unit_and_output_are_rejected(self):
        for a in ['E5','F2','C2','F5']:
            with self.subTest(a=a):
                m=self.model('=$D$1+F2*F3*$D$4')
                m.cell_visibility['S',a]=False
                with self.assertRaises(ValueError):
                    Notes(m).evidence('S','F5')

    def test_duplicate_caption_unit_conflict_and_incomplete_note(self):
        for kind in ['duplicate','units','exception','missing']:
            m=self.model('=$D$1+F2*F3*$D$4')
            if kind=='duplicate':
                m.cells.update({('S','B8'):'Load',('S','C8'):'%',('S','D8'):0.4})
            elif kind=='units':m.cells['S','C2']='Therm'
            elif kind=='exception':m.cells['S','E5']+=' except F5'
            else:m.cells.pop(('S','E5'))
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                Notes(m).evidence('S','F5')

    def test_wrong_note_can_induce_wrong_proposal(self):
        m=self.model()
        m.cells.update({('S','B8'):'Efficiency',('S','C8'):'%',('S','D8'):0.9})
        m.cells['S','E5']='Power x Efficiency x Availability x Hours'
        for c in 'GH':m.formulas['S',c+'5']=f'=$D$1*$D$8*{c}3*$D$4'
        r=self.run_model(m)['note_only']['rows'][0]
        self.assertEqual(r['status'],'propose')
        self.assertEqual(r['suggested_formula'],'=$D$1*$D$8*F3*$D$4')
        self.assertFalse(r['annotation_evidence']['note_authenticity_verified'])

    def test_real_public_source_exact_scope_and_conversion_rejection(self):
        p=ROOT.parents[1]/'data/external/hybridguard_candidate_audit_dev1/workbooks/uk_government/lcoe_calculator.xlsx'
        m=WorkbookModel.from_xlsx(p); notes=Notes(m); supported=[]
        for (s,a),f in m.formulas.items():
            try:e,v=notes.evidence(s,a)
            except ValueError:continue
            supported.append((s,a))
            self.assertTrue(same_relation(f,s,e))
        self.assertEqual(len(supported),80)
        with self.assertRaisesRegex(ValueError,'unit_conflict'):
            notes.evidence('CCGT LCOE calc','M80')

if __name__=='__main__':unittest.main()
