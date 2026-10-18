"""Observable English role features; text is evidence, never repair authority.

Prototype only. No model fitting, repair choice or expected formulas in this module.
"""
from collections import defaultdict
from functools import lru_cache
import re

from formulaguard.a1 import parse_address,num_to_col
from formulaguard.formula import Number,Ref,Range,Unary,Binary,Func,parse_formula

VERSION='hybridguard-signed-role-features-dev19-prototype'
PATTERNS={
    'net':r'\b(?:net|profit|surplus|deficit)\b',
    'income':r'\b(?:income|revenue|sales|receipts)\b',
    'cost':r'\b(?:costs?|expenses?|expenditure)\b',
    'inflow':r'\b(?:inflows?|cash received)\b',
    'outflow':r'\b(?:outflows?|cash paid)\b',
    'opening':r'\b(?:opening|beginning|initial)\b',
    'closing':r'\b(?:closing|ending|cumulative)\b',
    'balance':r'\b(?:balance|cash|inventory|stock)\b',
    'drawdown':r'\b(?:drawdowns?|borrowings?|advances?)\b',
    'repayment':r'\b(?:repayments?|principal|amorti[sz]ation)\b',
    'rate':r'\b(?:rates?|percent(?:age)?|proportions?|ratios?)\b',
    'total':r'\b(?:total|sum|aggregate)\b',
    'quantity':r'\b(?:quantity|volume|units?|output|production)\b',
    'generation':r'\b(?:generation|power|energy)\b',
    'availability':r'\b(?:availability|utili[sz]ation|efficiency|factor)\b',
    'time':r'\b(?:hours?|years?|months?|days?)\b',
    'exception':r'\b(?:exception|except|policy|contract|override)\b',
}
CHANNELS=['plus','minus','nonlinear']

class RoleContext:
    def __init__(self,model):
        self.model=model;self.rows=defaultdict(list);self.text={};self.cache={};self.headers=defaultdict(list)
        for (s,a),value in model.cells.items():
            if (s,a) not in model.formulas and isinstance(value,str) and value.strip() and model.is_visible((s,a)):
                pos=parse_address(a);self.rows[s,pos.row].append((pos.col,value.casefold()))
                self.text[s,pos.row,pos.col]=value.casefold()
                if pos.row<=2:self.headers[s,pos.col].append((pos.row,value.casefold()))

    def roles(self,sheet,address):
        key=sheet,address
        if key in self.cache:return self.cache[key]
        p=parse_address(address)
        # Nearest three left descriptors, local headers, and the two top rows
        # in this column. Conflicting blocks yield multiple roles, not authority.
        left=sorted([(c,t) for c,t in self.rows[sheet,p.row] if c<p.col],reverse=True)[:3]
        text=' '.join([t for c,t in left]+[self.text[sheet,r,p.col] for r in range(max(1,p.row-4),p.row)
                                         if (sheet,r,p.col) in self.text]+
                      [t for r,t in self.headers[sheet,p.col] if r<p.row])
        found={name for name,pattern in PATTERNS.items() if re.search(pattern,text)}
        self.cache[key]=found
        return found

    def formula_features(self,sheet,address,formula):
        out={r+'_'+c:0. for r in PATTERNS for c in CHANNELS}
        out.update(unknown_role_refs=0.,range_truncated=0.,unsupported=0.,upstream_ppmt=0.,upstream_ipmt=0.)
        try:
            refs,truncated=signed_references(formula)
        except (ValueError,TypeError,RecursionError,OverflowError):
            out['unsupported']=1.;return out
        out['range_truncated']=float(truncated)
        for s,a,sign in refs:
            s=s or sheet;roles=self.roles(s,a);channel='plus' if sign>0 else 'minus' if sign<0 else 'nonlinear'
            if not roles:out['unknown_role_refs']+=1
            for role in roles:out[role+'_'+channel]+=1
            upstream=self.model.formulas.get((s,a),'')
            for name in ['ppmt','ipmt']:
                out['upstream_'+name]+=bool(re.search(r'\b'+name+r'\s*\(',upstream,re.I))
        return out

    def features(self,sheet,address,observed,candidate):
        old=self.formula_features(sheet,address,observed);new=self.formula_features(sheet,address,candidate)
        return {**{'role_target_'+r:float(r in self.roles(sheet,address)) for r in PATTERNS},
                **{'role_old_'+k:v for k,v in old.items()},**{'role_new_'+k:v for k,v in new.items()},
                **{'role_delta_'+k:new[k]-old[k] for k in old}}

@lru_cache(maxsize=100000)
def signed_references(formula):
    refs=[];truncated=0
    def literal_sign(n):
        if isinstance(n,Number):return 1 if n.value>0 else -1 if n.value<0 else 0
        if isinstance(n,Unary) and n.op in ['+','-']:
            s=literal_sign(n.value)
            return None if s is None else s*(1 if n.op=='+' else -1)
        return None
    def visit(n,sign):
        nonlocal truncated
        if isinstance(n,Number):return
        if isinstance(n,Ref):
            refs.append((n.sheet,n.address.a1.replace('$',''),sign));return
        if isinstance(n,Range):
            r1,r2=sorted([n.start.address.row,n.end.address.row]);c1,c2=sorted([n.start.address.col,n.end.address.col])
            count=(r2-r1+1)*(c2-c1+1);truncated+=count>256
            for i in range(min(count,256)):
                refs.append((n.start.sheet or n.end.sheet,num_to_col(c1+i%(c2-c1+1))+str(r1+i//(c2-c1+1)),sign))
            return
        if isinstance(n,Unary):
            visit(n.value,sign*(1 if n.op=='+' else -1) if n.op in ['+','-'] else 0);return
        if isinstance(n,Binary):
            if n.op in ['+','-']:
                visit(n.left,sign);visit(n.right,sign*(1 if n.op=='+' else -1));return
            a,b=literal_sign(n.left),literal_sign(n.right)
            if n.op=='*':
                visit(n.left,sign*b if b is not None else 0)
                visit(n.right,sign*a if a is not None else 0);return
            if n.op=='/' and b not in [None,0]:
                visit(n.left,sign*b);visit(n.right,0);return
            visit(n.left,0);visit(n.right,0);return
        if isinstance(n,Func):
            for arg in n.args:visit(arg,sign if n.name=='SUM' else 0)
            return
        raise ValueError('unsupported_ast')
    visit(parse_formula(formula),1)
    return tuple(refs),truncated
