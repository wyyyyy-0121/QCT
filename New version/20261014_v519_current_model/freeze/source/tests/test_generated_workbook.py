import unittest
from pathlib import Path

from formulaguard.workbook import WorkbookModel

SMOKE_BOOK = Path(__file__).resolve().parents[1] / "data" / "propagationbench_smoke" / "clean" / "budget_v0.xlsx"


class GeneratedWorkbookTests(unittest.TestCase):
    @unittest.skipUnless(SMOKE_BOOK.exists(), "smoke benchmark has not been generated")
    def test_generated_xlsx_can_be_parsed_and_evaluated(self):
        model = WorkbookModel.from_xlsx(SMOKE_BOOK)
        values, errors = model.evaluate()
        self.assertGreaterEqual(len(model.formulas), 20)
        self.assertFalse(errors)
        self.assertTrue(values)


if __name__ == "__main__":
    unittest.main()
