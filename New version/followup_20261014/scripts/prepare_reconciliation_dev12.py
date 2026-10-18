"""Author controlled development inputs; never imported by prediction.

Reference numbers use independent Fraction arithmetic and Python AST, not the
paper parser/evaluator. Controls are authored before any formula mutation.
"""
import ast
from fractions import Fraction
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_selector_dev5 import save, sha
from openpyxl import Workbook, load_workbook

DATA = ROOT / 'development/reconciliation_dev12_inputs_v1'
FAMILIES = ['cash_rollforward', 'material_conservation', 'hours_total',
            'weighted_billing', 'inventory_rollforward', 'unit_conversion']
VARIANTS = ['clean', 'isolated_error', 'shared_error', 'legitimate_exception',
            'missing_declaration', 'wrong_control', 'derived_control',
            'ambiguous_candidates', 'multiple_errors', 'hidden_control']
SHEETS = ['A', 'B', 'C', 'D', 'E']


def formula(family, r, mode='correct'):
    # Each branch states the authored mechanism, observed mutation and a
    # deliberately misleading control computation, independently of selectors.
    versions = {
        'cash_rollforward': (f'=B{r}+C{r}-D{r}', f'=B{r}+C{r}+D{r}', f'=B{r}+C{r}*D{r}'),
        'material_conservation': (f'=B{r}-C{r}-D{r}', f'=B{r}+C{r}-D{r}', f'=B{r}*C{r}-D{r}'),
        'hours_total': (f'=B{r}+C{r}+D{r}', f'=B{r}-C{r}+D{r}', f'=B{r}*C{r}+D{r}'),
        'weighted_billing': (f'=B{r}*C{r}+D{r}', f'=B{r}+C{r}+D{r}', f'=B{r}-C{r}+D{r}'),
        'inventory_rollforward': (f'=B{r}+C{r}-D{r}-E{r}', f'=B{r}+C{r}+D{r}-E{r}', f'=B{r}*C{r}+D{r}-E{r}'),
        'unit_conversion': (f'=B{r}*C{r}+D{r}-E{r}', f'=B{r}+C{r}+D{r}-E{r}', f'=B{r}-C{r}+D{r}-E{r}'),
    }
    return versions[family][{'correct': 0, 'observed': 1, 'misleading': 2}[mode]]


def business_value(family, values, exception=False, misleading=False):
    b, c, d, e = [Fraction(str(v)) for v in values]
    if misleading:
        return {'cash_rollforward': b+c*d, 'material_conservation': b*c-d,
                'hours_total': b*c+d, 'weighted_billing': b-c+d,
                'inventory_rollforward': b*c+d-e, 'unit_conversion': b-c+d-e}[family]
    if exception:
        return {'cash_rollforward': b+c+d, 'material_conservation': b+c-d,
                'hours_total': b-c+d, 'weighted_billing': b+c+d,
                'inventory_rollforward': b+c+d-e, 'unit_conversion': b+c+d-e}[family]
    return {'cash_rollforward': b+c-d, 'material_conservation': b-c-d,
            'hours_total': b+c+d, 'weighted_billing': b*c+d,
            'inventory_rollforward': b+c-d-e, 'unit_conversion': b*c+d-e}[family]


def independent_evaluate(expression, lookup, active=None):
    active = set() if active is None else active
    def evaluate(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Fraction(str(node.value))
        if isinstance(node, ast.Name) and re.fullmatch('[A-Z]+[1-9][0-9]*', node.id):
            if node.id in active:
                raise ValueError('oracle cycle')
            value = lookup(node.id)
            return (independent_evaluate(value, lookup, active | {node.id})
                    if isinstance(value, str) and value.startswith('=') else Fraction(str(value)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            result = evaluate(node.operand)
            return result if isinstance(node.op, ast.UAdd) else -result
        if isinstance(node, ast.BinOp):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add): return left+right
            if isinstance(node.op, ast.Sub): return left-right
            if isinstance(node.op, ast.Mult): return left*right
            if isinstance(node.op, ast.Div): return left/right
        raise ValueError('oracle grammar')
    return evaluate(ast.parse(expression.removeprefix('='), mode='eval').body)


def prepare():
    if DATA.exists():
        raise SystemExit('Preserve authored dev12 inputs')
    DATA.mkdir(parents=True)
    truths, index, oracle = [], [], []
    for fi, family in enumerate(FAMILIES):
        for vi, variant in enumerate(VARIANTS):
            case = f'rc{fi+1:02d}_{vi+1:02d}'
            workbook = Workbook(); workbook.remove(workbook.active)
            expected, observed, values, controls = {}, {}, {}, {}
            for si, sheet in enumerate(SHEETS):
                ws = workbook.create_sheet(sheet)
                headers = ['Record', 'Opening / input [units]', 'Input / scale',
                           'Adjustment', 'Loss / offset', 'Calculated output',
                           'Independent recorded output', 'Explicit reconciliation']
                ws.append(headers)
                for r in range(2, 10):
                    v = [173+si*47+r*11+fi*3, 7+si*3+r*2, 3+r+fi, 2+si+r*3]
                    if variant == 'ambiguous_candidates' and r == 2 and sheet == 'A':
                        # A documented degeneracy: distinct operator repairs
                        # evaluate equally for these observed inputs.
                        if family in ['cash_rollforward', 'material_conservation']:
                            v = [4, 2, 2, 5]
                        elif family == 'hours_total':
                            v = [2, 2, 3, 5]
                        elif family in ['weighted_billing', 'unit_conversion']:
                            v = [4, 2, 4, 5]
                        else:
                            v = [4, 2, 2, 5]
                    exception = variant == 'legitimate_exception' and sheet == 'A' and r == 2
                    correct = formula(family, r, 'observed' if exception else 'correct')
                    output = business_value(family, v, exception=exception)
                    # Controls and declarations are written before any mutation.
                    for col, value in zip('BCDE', v): ws[f'{col}{r}'] = value
                    ws[f'A{r}'] = r-1
                    ws[f'F{r}'] = correct
                    ws[f'G{r}'] = float(output)
                    ws[f'H{r}'] = (f'Reconciliation: target=F{r}; expression=F{r}-G{r}; '
                                    'expected=0; tolerance=0.000001.')
                    label = sheet+f'!F{r}'
                    expected[label] = correct; values[label] = str(output)
                    controls[label] = {'authored_before_mutation': True,
                                       'provenance': 'independent_development_record'}
                    if variant == 'missing_declaration': ws[f'H{r}'] = None
                    if variant == 'derived_control':
                        ws[f'G{r}'] = correct
                        controls[label]['provenance'] = 'derived_from_output_inputs'
                if variant == 'hidden_control': ws.column_dimensions['G'].hidden = True
            # Inject only after the clean workbook and declarations exist.
            for si, sheet in enumerate(SHEETS):
                ws = workbook[sheet]
                for r in range(2, 10):
                    is_target = sheet == 'A' and r == 2
                    mutate = variant not in ['clean', 'legitimate_exception'] and is_target
                    mutate |= variant == 'shared_error' and r == 2
                    mutate |= variant == 'multiple_errors' and sheet in ['A', 'B'] and r in [2, 5, 8]
                    if mutate: ws[f'F{r}'] = formula(family, r, 'observed')
                    if variant == 'wrong_control' and is_target:
                        v = [ws[f'{c}{r}'].value for c in 'BCDE']
                        ws[f'G{r}'] = float(business_value(family, v, misleading=True))
                        controls[sheet+f'!F{r}']['provenance'] = 'deliberately_wrong_record'
                    observed[sheet+f'!F{r}'] = ws[f'F{r}'].value
                    if variant == 'derived_control':
                        # Verify target-dependent controls, not just shared-input controls.
                        ws[f'G{r}'] = f'=F{r}'
                        expected[sheet+f'!G{r}'] = observed[sheet+f'!G{r}'] = f'=F{r}'
            path = DATA / 'inputs' / (case+'.xlsx'); path.parent.mkdir(exist_ok=True)
            workbook.save(path)
            loaded = load_workbook(path, data_only=False)
            checked, silent = 0, 0
            for sheet in SHEETS:
                ws = loaded[sheet]
                def lookup(address): return ws[address].value
                for r in range(2, 10):
                    key = sheet+f'!F{r}'
                    correct = independent_evaluate(expected[key], lookup)
                    assert correct == Fraction(values[key]), (case, key)
                    actual = independent_evaluate(observed[key], lookup)
                    if observed[key] != expected[key]:
                        assert actual != correct, ('non-silent mutation', case, key)
                        silent += 1
                    checked += 1
            loaded.close()
            truths.append({'id': case, 'family': family, 'scenario': variant,
                           'expected_formulas': expected, 'observed_formulas': observed,
                           'errors': sorted(k for k in expected if expected[k] != observed[k]),
                           'expected_values_fraction': values, 'control_provenance': controls})
            index.append({'id': case, 'input': str(path.relative_to(ROOT)),
                          'input_sha256': sha(path), 'parallel_sheets': SHEETS,
                          'group': 'controlled_reconciliation'})
            oracle.append({'id': case, 'correct_outputs_checked': checked,
                           'silent_numeric_mutations_checked': silent})
    save(DATA / 'public_index.json', index)
    save(DATA / 'truth.json', {'cases': truths, 'final_validation_eligible': False})
    save(DATA / 'input_oracle.json', {'cases': oracle, 'independent_engine': 'Python AST + Fraction',
         'all_expected_outputs_checked': True, 'all_mutations_numeric_and_different': True})
    save(DATA / 'registration.json', {'families': FAMILIES, 'variants': VARIANTS,
         'case_count': len(index), 'new_final_sources': 0, 'new_final_families': 0,
         'controls_authored_before_mutation': True, 'final_validation_eligible': False,
         'protocol_sha256': sha(ROOT / 'DEV12_EXPERIMENT_PLAN_20261018.md'),
         'generator_sha256': sha(Path(__file__)),
         'files': {str(p.relative_to(DATA)): sha(p) for p in sorted(DATA.rglob('*')) if p.is_file()}})
    print('AUTHORED', len(index), 'controlled development workbooks; oracle checked',
          sum(v['correct_outputs_checked'] for v in oracle), 'correct outputs;',
          sum(v['silent_numeric_mutations_checked'] for v in oracle), 'injected errors')


if __name__ == '__main__': prepare()
