from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'baseline/source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
from selector_dev4 import interpret, check
from selector_dev3 import policy_notes


class PolicyInterpretationTests(unittest.TestCase):
    def test_row_scoped_waiver_does_not_remove_other_expenses(self):
        model = WorkbookModel.from_cells({('A','H1'):'Business policy',
            ('A','H2'):'Row 10: seller absorbs shipping; exclude Shipping from this profit calculation.',
            ('A','A10'):3,('A','B10'):20,('A','C10'):4,('A','D10'):2}, {})
        rules = interpret(model,'A',policy_notes(model)['A'],{10,11})
        roles = {2:('unit price',1),3:('unit cost',-1),4:('shipping',-1)}
        self.assertEqual(check(model,'=A10*B10-A10*C10','A','F10',roles,rules)['violations'],[])
        self.assertEqual(check(model,'=A10*B10+A10*C10','A','F10',roles,rules)['violations'],['unit cost'])

    def test_unknown_prose_is_not_silently_interpreted(self):
        model=WorkbookModel.from_cells({('A','H1'):'Business policy',('A','H2'):'Use current contract terms.'},{})
        self.assertIsNone(interpret(model,'A',policy_notes(model)['A'],{2}))

    def test_out_of_scope_row_rejected(self):
        model=WorkbookModel.from_cells({('A','H1'):'Business policy',
            ('A','H2'):'Row 100: seller absorbs shipping; exclude Shipping from this profit calculation.'},{})
        self.assertIsNone(interpret(model,'A',policy_notes(model)['A'],{2}))


if __name__ == '__main__':
    unittest.main()
