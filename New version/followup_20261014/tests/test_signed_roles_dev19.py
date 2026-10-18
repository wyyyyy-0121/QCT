from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from signed_roles_dev19 import RoleContext,signed_references
from formulaguard.workbook import WorkbookModel

class SignedRoleTests(unittest.TestCase):
    def test_signed_flow_context_keeps_subtraction(self):
        m=WorkbookModel({('S','A2'):'Cash inflows',('S','A3'):'Cash outflows',('S','A4'):'Net cash flow'},
                        {('S','C4'):'=C2-C3'})
        f=RoleContext(m).features('S','C4','=C2-C3','=C2+C3')
        self.assertEqual(f['role_old_outflow_minus'],1)
        self.assertEqual(f['role_new_outflow_plus'],1)
        self.assertEqual(f['role_target_net'],1)

    def test_ppmt_is_syntax_evidence_not_assumed_negative_value(self):
        m=WorkbookModel({('S','A2'):'Opening balance',('S','A3'):'Drawdowns',('S','A4'):'Principal repayment',('S','A5'):'Closing balance'},
                        {('S','C4'):'=PPMT(0.1,1,12,100)',('S','C5'):'=SUM(C2:C4)'})
        f=RoleContext(m).features('S','C5','=SUM(C2:C4)','=C2+C3-C4')
        self.assertEqual(f['role_old_repayment_plus'],1)
        self.assertEqual(f['role_new_repayment_minus'],1)
        self.assertEqual(f['role_old_upstream_ppmt'],1)

    def test_unknown_factor_or_divisor_does_not_claim_sign(self):
        refs,_=signed_references('=A2*B2+C2/D2+E2/-2')
        self.assertEqual(dict((a,sign) for s,a,sign in refs),{'A2':0,'B2':0,'C2':0,'D2':0,'E2':-1})

    def test_negative_literal_flip_and_zero_does_not_claim_positive(self):
        refs,_=signed_references('=-2*A1-A2*0')
        self.assertEqual(dict((a,sign) for s,a,sign in refs),{'A1':-1,'A2':0})

    def test_hidden_text_and_formula_cache_not_role_evidence(self):
        a=WorkbookModel({('S','A2'):'exception',('S','C2'):999},{('S','C2'):'=C1'})
        a.cell_visibility['S','A2']=False
        self.assertFalse(RoleContext(a).roles('S','C2'))

    def test_translation_and_sheet_rename_invariant(self):
        a=WorkbookModel({('One','A2'):'Opening balance'},{('One','C5'):'=C2'})
        b=WorkbookModel({('Two','D6'):'Opening balance'},{('Two','F9'):'=F6'})
        self.assertEqual(RoleContext(a).features('One','C5','=C2','=C2*2'),
                         RoleContext(b).features('Two','F9','=F6','=F6*2'))

    def test_wrong_text_is_observed_without_generating_repair(self):
        m=WorkbookModel({('S','A2'):'Cash inflows'}, {('S','C2'):'=D2-E2'})
        f=RoleContext(m).features('S','C2','=D2-E2','=D2+E2')
        self.assertEqual(f['role_target_inflow'],1)
        self.assertFalse(any('suggested' in k for k in f))

    def test_range_budget_and_unsupported_formula_recorded(self):
        c=RoleContext(WorkbookModel({},{}))
        self.assertEqual(c.formula_features('S','B1','=SUM(A1:A1000)')['range_truncated'],1)
        self.assertEqual(c.formula_features('S','B1','=SpecialRate*A1')['unsupported'],1)

    def test_distant_column_header_and_local_conflict_are_both_visible(self):
        m=WorkbookModel({('S','C1'):'Net profit',('S','A500'):'Closing balance'},
                        {('S','C500'):'=D500-E500'})
        roles=RoleContext(m).roles('S','C500')
        self.assertTrue({'net','closing','balance'}<=roles)

if __name__=='__main__':unittest.main()
