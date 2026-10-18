"""Independent FormulaGuard AST symbolic recount and original/provenance verification."""
from collections import Counter,defaultdict
from pathlib import Path
import sys
import sympy
ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'baseline/source/HybridGuard_V5_handoff_20260904/src')]
from run_multisource_dev17 import RUN,DATA,NAMES,verify
from run_selector_dev5 import read,save,sha
from formulaguard.formula import Number,Ref,Range,Unary,Binary,Func,parse_formula
from formulaguard.a1 import num_to_col
from selector_dev11 import syntax_evidence
from openpyxl import load_workbook
from openpyxl.formula.translate import Translator

def ast_expression(formula,sheet,w):
    if not syntax_evidence(formula)['supported']:raise ValueError('unsupported_full_ast')
    def lookup(s,a):
        value=w[s][a].value
        if value is None:return None
        if isinstance(value,str) and not value.startswith('='):return value
        if isinstance(value,bool):raise ValueError('boolean')
        return sympy.Symbol(s.casefold()+'!'+a)
    def scalar(x):
        if x is None:return sympy.Integer(0)
        if isinstance(x,(str,list)):raise ValueError('scalar')
        return x
    def visit(n):
        if isinstance(n,Number):return sympy.Rational(n.source_text)
        if isinstance(n,Ref):return lookup(n.sheet or sheet,n.address.a1.replace('$',''))
        if isinstance(n,Range):
            a,b=n.start,n.end
            if (a.sheet or sheet)!=(b.sheet or a.sheet or sheet):raise ValueError('sheet_range')
            return [lookup(a.sheet or sheet,num_to_col(col)+str(row))
                    for row in range(a.address.row,b.address.row+1)
                    for col in range(a.address.col,b.address.col+1)]
        if isinstance(n,Unary):
            v=scalar(visit(n.value))
            if n.op=='+':return v
            if n.op=='-':return -v
        if isinstance(n,Binary):
            a,b=scalar(visit(n.left)),scalar(visit(n.right))
            if n.op=='+':return a+b
            if n.op=='-':return a-b
            if n.op=='*':return a*b
            if n.op=='/' and b!=0:return a/b
        if isinstance(n,Func) and n.name.casefold()=='sum':
            vs=[]
            for arg in n.args:
                value=visit(arg);vs.extend(value if isinstance(value,list) else [value])
            return sum((x for x in vs if x is not None and not isinstance(x,str)),sympy.Integer(0))
        raise ValueError('audit_unsupported_ast')
    return scalar(visit(parse_formula(formula)))

def equals(a,b,sheet,w):
    try:return sympy.cancel(ast_expression(a,sheet,w)-ast_expression(b,sheet,w))==0
    except (ValueError,TypeError,IndexError,KeyError,ZeroDivisionError):return False

def main():
    verify();truth=read(DATA/'truth.json');score=read(RUN/'score.json');total={n:Counter() for n in NAMES}
    all_count_checks=0;peer_checks=0;witness_count=0;neutral=[]
    for source in truth['sources']:assert sha(REPO/source['relative_path'])==source['sha256']
    for item,t,scored in zip(read(RUN/'public_index.json'),truth['cases'],score['cases']):
        assert item['id']==t['id']==scored['id']
        w=load_workbook(ROOT/item['input']);p=read(RUN/'predictions'/(item['id']+'.json.gz'))
        observed={ws.title+'!'+c.coordinate:c.value for ws in w for row in ws for c in row if c.data_type=='f'}
        assert observed==p['observed_formulas']==t['observed_formulas']
        errors={k for k,f in t['expected_formulas'].items() if not equals(observed[k],f,k.rsplit('!',1)[0],w)}
        assert errors==set(t['errors'])
        for label,record in t['rational_difference_witnesses'].items():
            s,a=label.rsplit('!',1);mapping={sympy.Symbol(k):sympy.Rational(v) for k,v in record['inputs'].items()}
            x=ast_expression(observed[label],s,w).subs(mapping)
            y=ast_expression(t['expected_formulas'][label],s,w).subs(mapping)
            assert x!=y and str(x)==record['observed'] and str(y)==record['expected']
            witness_count+=1
        for change in t['changes']:
            if change['kind']=='formula_error_injection':
                label=change['sheet']+'!'+change['cell']
                if label not in errors:neutral.append({'id':item['id'],**change})
        for name in NAMES:
            rows=[r for r in p[name]['rows'] if r.get('suggested_formula')
                  and r['suggested_formula']!=observed[r['cell']]
                  and (name=='paper' or r.get('status')=='propose')]
            assert len(rows)==len({r['cell'] for r in rows})
            count=Counter(suggestions=len(rows),errors=len(errors))
            for r in rows:
                label=r['cell'];s,a=label.rsplit('!',1)
                if label not in t['expected_formulas']:count['unknown']+=1
                elif label not in errors:count['wrong']+=1;count['unnecessary']+=1
                elif equals(r['suggested_formula'],t['expected_formulas'][label],s,w):count['correct']+=1;count['correct_errors']+=1
                else:count['wrong']+=1
            for k in ['suggestions','correct','wrong','unknown','errors','correct_errors','unnecessary']:
                assert count[k]==scored[name][k],(item['id'],name,k,count[k],scored[name][k])
                total[name][k]+=count[k];all_count_checks+=1
        ceiling=set()
        for candidate in p['candidate_pool']:
            label=candidate['cell'];s,a=label.rsplit('!',1)
            if candidate['eligible'] and label in errors and equals(candidate['formula'],t['expected_formulas'][label],s,w):
                ceiling.add(label)
            for peer in candidate['peer_evidence']:
                assert peer['support']==len(peer['peers'])>=2
                for label in peer['peers']:
                    ps,pa=label.rsplit('!',1)
                    actual=Translator(w[ps][pa].value,origin=pa).translate_formula(a)
                    assert actual==candidate['formula']
                    peer_checks+=1
        assert len(ceiling)==scored['candidate_pool_correct_error_ceiling']
        w.close()
    for name,c in total.items():
        old=score['all'][name]
        for k,v in c.items():assert old[k]==v
        assert old['coverage']==(c['correct_errors']/c['errors'] if c['errors'] else None)
        assert old['precision_confirmed_lower_bound']==(c['correct']/c['suggestions'] if c['suggestions'] else None)
    for origin,methods in score['by_origin'].items():
        rows=[r for r in score['cases'] if r['origin']==origin]
        for name,m in methods.items():
            for key in ['suggestions','correct','wrong','unknown','errors','correct_errors','unnecessary']:
                assert m[key]==sum(r[name][key] for r in rows)
    out=ROOT/'qa/MULTISOURCE_DEV17_INDEPENDENT_AUDIT_20261018.json';assert not out.exists()
    save(out,{'cases':len(score['cases']),'independent_ast_engine':'FormulaGuard AST + exact SymPy; scorer used openpyxl token stack',
              'case_method_count_checks':all_count_checks,'peer_translations_checked':peer_checks,
              'rational_witnesses_checked':witness_count,'neutral_mutations_preserved':neutral,
              'aggregate_counts':total,'all_counts_match':True,'all_original_source_hashes_match':True,
              'audit_script_sha256':sha(Path(__file__)),'prediction_lock_sha256':sha(RUN/'prediction_lock.json'),
              'main_candidate_adopted':False,'final_validation_eligible':False})
    print('independent audit passed',all_count_checks,'peer checks',peer_checks,'witnesses',witness_count,flush=True)
if __name__=='__main__':main()
