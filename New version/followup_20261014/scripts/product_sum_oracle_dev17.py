"""Independent exact symbolic relation oracle for reviewed public scopes; never predictor input."""
import re
import sympy
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import range_boundaries,get_column_letter
from fractions import Fraction

def split_ref(value,sheet):
    if '!' in value:
        prefix,value=value.rsplit('!',1)
        sheet=prefix.strip("'").replace("''","'")
    return sheet,value.replace('$','').upper()

def expression(formula,sheet,lookup):
    values=[];ops=[]
    prec={'+':1,'-':1,'*':2,'/':2,'u+':3,'u-':3}
    def reduce():
        op=ops.pop()
        if op in ['u+','u-']:
            value=scalar(values.pop());values.append(value*(1 if op=='u+' else -1));return
        b=scalar(values.pop());a=scalar(values.pop())
        if op=='+':v=a+b
        elif op=='-':v=a-b
        elif op=='*':v=a*b
        elif op=='/':
            if b==0:raise ValueError('zero_divisor')
            v=a/b
        else:raise ValueError('operator')
        values.append(v)
    def scalar(value):
        if isinstance(value,list):
            if len(value)!=1:raise ValueError('range_in_scalar_arithmetic')
            value=value[0]
        if value is None:return sympy.Integer(0)
        if isinstance(value,str):raise ValueError('text_in_scalar_arithmetic')
        return value
    for t in Tokenizer(formula).items:
        if t.type=='WHITE-SPACE':continue
        if t.type=='OPERAND':
            if t.subtype=='NUMBER':
                if len(t.value)>128:raise ValueError('numeric_budget')
                values.append(sympy.Rational(t.value))
            elif t.subtype=='RANGE':
                s,ref=split_ref(t.value,sheet)
                if not re.fullmatch(r'[A-Z]{1,3}[1-9][0-9]*(?::[A-Z]{1,3}[1-9][0-9]*)?',ref):
                    raise ValueError('unsupported_ref')
                left,top,right,bottom=range_boundaries(ref)
                if (right-left+1)*(bottom-top+1)>256:raise ValueError('range_budget')
                vs=[lookup(s,f'{get_column_letter(c)}{r}') for r in range(top,bottom+1) for c in range(left,right+1)]
                values.append(vs if ':' in ref else vs[0])
            else:raise ValueError('unsupported_operand')
        elif t.type=='OPERATOR-PREFIX' and t.value in '+-':ops.append('u'+t.value)
        elif t.type=='OPERATOR-INFIX' and t.value in ['+','-','*','/']:
            while ops and ops[-1] not in ['(','SUM('] and prec[ops[-1]]>=prec[t.value]:reduce()
            ops.append(t.value)
        elif t.type=='PAREN' and t.subtype=='OPEN':ops.append('(')
        elif t.type=='FUNC' and t.subtype=='OPEN' and t.value.casefold()=='sum(':
            ops.append('SUM(');values.append(('sum_marker',))
        elif t.type=='SEP' and t.subtype=='ARG':
            while ops and ops[-1] not in ['SUM(','(']:reduce()
        elif t.subtype=='CLOSE' and t.type in ['PAREN','FUNC']:
            expected='SUM(' if t.type=='FUNC' else '('
            while ops and ops[-1] not in ['SUM(','(']:reduce()
            if not ops or ops.pop()!=expected:raise ValueError('parentheses')
            if expected=='SUM(':
                args=[]
                while values and not (isinstance(values[-1],tuple) and values[-1]==('sum_marker',)):
                    v=values.pop();args.extend(v if isinstance(v,list) else [v])
                if not values:raise ValueError('sum_marker')
                values.pop();values.append(sum((v for v in args if v is not None and not isinstance(v,str)),sympy.Integer(0)))
        else:raise ValueError('unsupported_token:'+t.type+':'+t.value)
    while ops:reduce()
    if len(values)!=1:raise ValueError('oracle_stack')
    v=scalar(values[0])
    if not v.is_rational_function():raise ValueError('not_rational_expression')
    return v

def symbolic(formula,sheet,workbook):
    def lookup(s,a):
        value=workbook[s][a].value
        if value is None:return None
        if isinstance(value,str) and not value.startswith('='):return value
        if isinstance(value,bool):raise ValueError('boolean_input')
        return sympy.Symbol(s.casefold()+'!'+a)
    return expression(formula,sheet,lookup)

def equivalent(a,b,sheet,workbook):
    try:return sympy.cancel(symbolic(a,sheet,workbook)-symbolic(b,sheet,workbook))==0
    except (ValueError,TypeError,IndexError,KeyError,ZeroDivisionError):return False

def witness(a,b,sheet,workbook):
    va,vb=symbolic(a,sheet,workbook),symbolic(b,sheet,workbook)
    symbols=sorted(va.free_symbols|vb.free_symbols,key=str)
    for seed in [1,3,7,13]:
        assignments={s:sympy.Rational(31+seed*i+seed,7+i) for i,s in enumerate(symbols)}
        x,y=va.subs(assignments),vb.subs(assignments)
        if x.is_finite and y.is_finite and x!=y:
            return {'inputs':{str(s):str(v) for s,v in assignments.items()},
                    'observed':str(x),'expected':str(y),
                    'scope':'exact rational relation counterexample, not actual full-workbook Excel values'}
    raise ValueError('no_difference_witness')
