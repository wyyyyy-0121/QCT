"""Label-free candidate features; no paths, identities, answers or group names in vectors."""
from collections import Counter,defaultdict
from functools import lru_cache
import math
import re

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.formula.translate import Translator,TranslatorError
from formulaguard.a1 import parse_address,num_to_col
from selector_dev11 import syntax_evidence

VERSION='hybridguard-grouped-candidate-learning-dev16-v1'
ORIGINS=['paper','dev11','dev9','dev12','dev15']
WORDS=['exception','except','policy','contract','reconciliation','independent','recorded',
       'discount','shipping','price','cost','inventory','loan','budget','temperature',
       'conversion','generation','availability','total','net','factor','efficiency','control']
METRICS=['structural_score','formulaguard_v5_score','hybrid_score','group_score',
         'group_size','representative_validation_score','group_validated']
PARAMETERS={'max_iter':100,'learning_rate':.08,'max_leaf_nodes':15,'max_depth':6,
            'min_samples_leaf':20,'l2_regularization':1.,'early_stopping':False,'random_state':1618}
THRESHOLD=.90
MARGIN=.05

@lru_cache(maxsize=100000)
def tokens(formula):
    try:return tuple((x.type,x.subtype,x.value) for x in Tokenizer(formula).items if x.type!='WHITE-SPACE')
    except Exception:return ()

def finite(v):
    return float(v) if isinstance(v,(int,float)) and math.isfinite(v) else 0.

def counts(formula,prefix):
    ts=tokens(formula)
    refs=[v for t,s,v in ts if t=='OPERAND' and s=='RANGE']
    nums=[v for t,s,v in ts if t=='OPERAND' and s=='NUMBER']
    return {prefix+'length':len(formula),prefix+'tokens':len(ts),prefix+'refs':len(refs),
            prefix+'unique_refs':len(set(v.replace('$','').casefold() for v in refs)),
            prefix+'numbers':len(nums),prefix+'functions':sum(t=='FUNC' and s=='OPEN' for t,s,v in ts),
            prefix+'cross_sheet_refs':sum('!' in v for v in refs),
            prefix+'absolute_refs':sum('$' in v for v in refs),
            **{prefix+'op_'+op:sum(t=='OPERATOR-INFIX' and v==op for t,s,v in ts)
               for op in ['+','-','*','/','^','&','=','<','>']}}

def normalization(f):
    return ''.join(f.split()).casefold()

def translated(f,a,b):
    try:return Translator(f,origin=a).translate_formula(b)
    except (ValueError,TranslatorError):return None

class Context:
    def __init__(self,model,parallel):
        self.model=model; self.parallel=parallel
        self.texts={}
        self.row_texts=defaultdict(list)
        self.column_texts={}
        self.headers=defaultdict(list)
        self.index=Counter()
        for (s,a),v in model.cells.items():
            if (s,a) not in model.formulas and isinstance(v,str) and v.strip() and model.is_visible((s,a)):
                self.texts[s,a]=v.casefold()
                pos=parse_address(a)
                self.row_texts[s,pos.row].append((pos.col,v.casefold()))
                self.column_texts[s,pos.row,pos.col]=v.casefold()
                if pos.row<=2:self.headers[s].append((pos.row,pos.col,v.casefold()))
        # Each target only computes neighbor support once for all its candidates.
        self.cache={}

    def neighbors(self,sheet,address):
        key=sheet,address
        if key in self.cache:return self.cache[key]
        p=parse_address(address); rows=[]; cols=[]; cross=[]
        for step in [-2,-1,1,2]:
            for axis in ['row','col']:
                r,c=(p.row,p.col+step) if axis=='row' else (p.row+step,p.col)
                if r<1 or c<1:continue
                a=num_to_col(c)+str(r)
                if (sheet,a) in self.model.formulas and self.model.is_visible((sheet,a)):
                    f=translated(self.model.formulas[sheet,a],a,address)
                    if f:(rows if axis=='row' else cols).append(normalization(f))
        for s in self.parallel:
            if s!=sheet and (s,address) in self.model.formulas and self.model.is_visible((s,address)):
                cross.append(normalization(self.model.formulas[s,address]))
        text=[]
        # Local headers and row descriptions are observable; only fixed lexical
        # indicators enter the vector, never text itself, IDs, or coordinates.
        text += [v for c,v in self.row_texts[sheet,p.row] if c<p.col]
        text += [self.column_texts[sheet,r,p.col] for r in range(max(1,p.row-4),p.row)
                 if (sheet,r,p.col) in self.column_texts]
        text += [v for r,c,v in self.headers[sheet] if c<=p.col]
        value=(rows,cols,cross,' '.join(text)); self.cache[key]=value
        return value

    def features(self,sheet,address,formula,origins,base):
        observed=self.model.formulas[sheet,address]
        f={**counts(observed,'old_'),**counts(formula,'new_')}
        f.update({'origin_'+name:float(name in origins) for name in ORIGINS})
        f.update({name:finite(base.get(name)) for name in METRICS})
        supported=syntax_evidence(observed)['supported'] and syntax_evidence(formula)['supported']
        f['complete_ast_pair']=float(supported)
        before=tokens(observed); after=tokens(formula)
        oldrefs={v.replace('$','').casefold() for t,s,v in before if t=='OPERAND' and s=='RANGE'}
        newrefs={v.replace('$','').casefold() for t,s,v in after if t=='OPERAND' and s=='RANGE'}
        f['refs_added']=len(newrefs-oldrefs); f['refs_removed']=len(oldrefs-newrefs)
        f['same_token_count']=float(len(before)==len(after))
        f['tokens_changed_aligned']=sum(a!=b for a,b in zip(before,after))+abs(len(before)-len(after))
        f['literal_sequence_changed']=float([v for t,s,v in before if s=='NUMBER']!=[v for t,s,v in after if s=='NUMBER'])
        f['operator_sequence_changed']=float([v for t,s,v in before if t.startswith('OPERATOR')]!=[v for t,s,v in after if t.startswith('OPERATOR')])
        rows,cols,cross,text=self.neighbors(sheet,address)
        for axis,peers in [('row',rows),('column',cols),('parallel',cross)]:
            f[axis+'_peers']=len(peers)
            f[axis+'_support_candidate']=sum(v==normalization(formula) for v in peers)
            f[axis+'_support_observed']=sum(v==normalization(observed) for v in peers)
            f[axis+'_candidate_ratio']=f[axis+'_support_candidate']/len(peers) if peers else 0.
        f.update({'text_'+word:float(bool(re.search(r'\b'+word+r'\b',text))) for word in WORDS})
        for field in ['semantic_current','semantic_candidate','directional_evidence']:
            e=base.get(field) or {}
            f[field+'_available']=float(bool(e.get('available')))
            for kind in ['opposite_roles','missing_roles','violations']:
                f[field+'_'+kind]=len(e.get(kind,[]))
        f['target_visible']=float(self.model.is_visible((sheet,address)))
        assert all(math.isfinite(v) for v in f.values())
        return f

def choose(candidates,probabilities):
    ranked=sorted(zip(candidates,probabilities),key=lambda x:(-x[1],x[0]['formula']))
    eligible=[(r,p) for r,p in ranked if r['eligible']]
    if not eligible:return None
    best,p=eligible[0]; runner=eligible[1][1] if len(eligible)>1 else 0.
    if p<THRESHOLD or p-runner<MARGIN:return None
    return {'cell':best['cell'],'suggested_formula':best['formula'],'probability':float(p),
            'runner_up_probability':float(runner),'candidate_id':best['id'],'status':'propose'}
