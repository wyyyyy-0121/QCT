from pathlib import Path
import sys,json
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'source/HybridGuard_V5_handoff_20260904/src'))
from formulaguard.workbook import WorkbookModel
records=[]
for p in sorted((R/'data').glob('*/input.xlsx')):
 m=WorkbookModel.from_xlsx(p);values,errors=m.evaluate(targets=m.formula_cells)
 assert not errors,(p,errors)
 records.append({'case':p.parent.name,'formula_cells':len(m.formula_cells),'evaluation_errors':len(errors),'evaluated_formula_values':sum(k in values for k in m.formula_cells)})
(R/'qa/input_evaluation.json').write_text(json.dumps(records,indent=2));print('All',len(records),'input models evaluated without errors')
