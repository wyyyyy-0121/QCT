"""Exact visible product-note evidence; notes and dimensions do not prove intent."""
from collections import Counter, defaultdict
from fractions import Fraction
from functools import lru_cache
import re

from formulaguard.a1 import parse_address
from formulaguard.formula import Binary, Number, Ref, Unary, parse_formula
from openpyxl.formula.translate import Translator, TranslatorError
from formula_candidates_dev1 import generate
from selector_dev11 import syntax_evidence

VERSION = 'hybridguard-visible-product-annotation-dev14-v1'
UNITS = {
    'mw': (('power',1),), 'hours': (('time',1),),
    'mwh': (('power',1),('time',1)), '%': (),
    'kgco2': (('co2_mass',1),),
    'kgco2/therm': (('co2_mass',1),('therm',-1)), 'therm': (('therm',1),),
}
PARAMETERS = {'exact_captions_only':True, 'note_grammar':'complete product of exact row captions',
              'units':UNITS,'max_polynomial_terms':32,'max_degree':16,
              'max_formula_characters':2048,'minimum_row_peer_support':2,
              'max_number_characters':128,'max_decimal_exponent':128,
              'note_authenticity_verified':False,'main_candidate_adopted':False}


def norm(text):
    return ' '.join(str(text).strip().casefold().split())


def bounded(poly):
    result = {m:c for m,c in poly.items() if c}
    if len(result)>32 or any(sum(power for _,power in mono)>16 for mono in result):
        raise ValueError('polynomial_budget')
    return result


def multiply(a,b):
    if len(a)*len(b)>1024:
        raise ValueError('multiplication_budget')
    result = defaultdict(Fraction)
    for m,c in a.items():
        for n,d in b.items():
            factors = Counter(dict(m)); factors.update(dict(n))
            key = tuple(sorted((k,v) for k,v in factors.items() if v))
            result[key] += c*d
    return bounded(result)


@lru_cache(maxsize=100000)
def polynomial(formula,sheet):
    if len(formula)>PARAMETERS['max_formula_characters'] or not syntax_evidence(formula)['supported']:
        raise ValueError('unsupported_formula')
    def convert(node):
        if isinstance(node,Number):
            literal = node.source_text
            if (len(literal)>128 or ('e' in literal.casefold()
                    and abs(int(literal.casefold().split('e')[1]))>128)):
                raise ValueError('number_budget')
            return {():Fraction(node.source_text)}
        if isinstance(node,Ref):
            key = (node.sheet or sheet).casefold()+'!'+node.address.a1.replace('$','').upper()
            return {((key,1),):Fraction(1)}
        if isinstance(node,Unary) and node.op in ('+','-'):
            factor = 1 if node.op=='+' else -1
            return {m:factor*c for m,c in convert(node.value).items()}
        if isinstance(node,Binary) and node.op in ('+','-','*'):
            a,b = convert(node.left),convert(node.right)
            if node.op=='*':
                return multiply(a,b)
            result = defaultdict(Fraction,a)
            for m,c in b.items():
                result[m] += c*(1 if node.op=='+' else -1)
            return bounded(result)
        raise ValueError('unsupported_polynomial_grammar')
    return bounded(convert(parse_formula(formula)))


def same_relation(formula,sheet,expected):
    try:
        return polynomial(formula,sheet) == expected
    except (ValueError,TypeError,OverflowError,RecursionError,ZeroDivisionError):
        return False


class Notes:
    def __init__(self,model):
        self.model = model
        self.rows = defaultdict(list)
        for (sheet,address),value in model.cells.items():
            self.rows[sheet,parse_address(address).row].append((parse_address(address).col,address,value))
        self.captions = defaultdict(list)
        self.row_meta = {}
        for (sheet,row),entries in self.rows.items():
            entries.sort()
            texts = [(col,address,value) for col,address,value in entries
                     if (sheet,address) not in model.formulas and isinstance(value,str)
                     and value.strip() and model.is_visible((sheet,address))]
            if not texts:
                continue
            col,address,caption = texts[0]
            unit = next((v for c,a,v in texts if c==col+1),None)
            self.row_meta[sheet,row] = {'caption':caption,'caption_cell':address,
                                       'caption_col':col,'unit':unit}
            self.captions[sheet,norm(caption)].append(row)

    def bind(self,sheet,caption,target_col,target_row):
        rows = self.captions.get((sheet,norm(caption)),[])
        if len(rows)!=1 or rows[0]==target_row:
            raise ValueError('ambiguous_missing_or_self_caption:'+caption)
        row = rows[0]; meta = self.row_meta[sheet,row]
        if norm(meta['unit']) not in UNITS:
            raise ValueError('unknown_input_unit')
        values = [(col,address) for col,address,value in self.rows[sheet,row]
                  if col>meta['caption_col']+1
                  and ((sheet,address) in self.model.formulas or type(value) in (int,float))]
        matching = [address for col,address in values if col==target_col]
        if len(matching)==1:
            address = matching[0]; kind = 'same_column'
        elif len(values)==1:
            address = values[0][1]; kind = 'unique_scalar'
        else:
            raise ValueError('ambiguous_input_value')
        if not self.model.is_visible((sheet,address)):
            raise ValueError('hidden_input')
        return {'caption':caption,'caption_cell':meta['caption_cell'],
                'value_cell':address,'binding':kind,'unit':meta['unit']}

    def evidence(self,sheet,address):
        pos = parse_address(address)
        if not self.model.is_visible((sheet,address)):
            raise ValueError('hidden_output')
        meta = self.row_meta.get((sheet,pos.row))
        if not meta or norm(meta['unit']) not in UNITS:
            raise ValueError('unknown_output_unit')
        notes = []
        for col,cell,text in self.rows[sheet,pos.row]:
            if (meta['caption_col']+1<col<pos.col and (sheet,cell) not in self.model.formulas
                    and isinstance(text,str) and re.search(r'\s+[x*]\s+|×',text)):
                notes.append((cell,text))
        if len(notes)!=1:
            raise ValueError('missing_or_multiple_product_notes')
        note,text = notes[0]
        if not self.model.is_visible((sheet,note)):
            raise ValueError('hidden_note')
        terms = re.split(r'\s+[x*]\s+|\s*×\s*',text.strip())
        if not 2<=len(terms)<=12 or any(not term.strip() for term in terms):
            raise ValueError('note_product_budget')
        bindings = [self.bind(sheet,term.strip(),pos.col,pos.row) for term in terms]
        dimensions = Counter()
        expected = {():Fraction(1)}
        for binding in bindings:
            dimensions.update(dict(UNITS[norm(binding['unit'])]))
            key = sheet.casefold()+'!'+binding['value_cell'].upper()
            expected = multiply(expected,{((key,1),):Fraction(1)})
        actual_dimensions = tuple(sorted((k,v) for k,v in dimensions.items() if v))
        if actual_dimensions != tuple(sorted(UNITS[norm(meta['unit'])])):
            raise ValueError('annotation_output_unit_conflict')
        return expected, {'note_cell':sheet+'!'+note,'note_text':text,
                          'output_caption':meta['caption'],'output_unit':meta['unit'],
                          'bindings':bindings,'complete_exact_caption_mapping':True,
                          'units_consistent':True,'note_authenticity_verified':False,
                          'business_correctness_proven':False}


def apply(model,prior,paper):
    notes = Notes(model)
    paper_rows = {r['cell']:r for r in paper['rows']}
    note_rows = []
    for old in prior['rows']:
        label = old['cell']; sheet,address = label.rsplit('!',1)
        observed = model.formulas[sheet,address]
        row = {'cell':label,'status':'abstain','suggested_formula':None,
               'reason':'no_complete_product_note','selector_version':VERSION}
        try:
            expected,evidence = notes.evidence(sheet,address)
        except ValueError as error:
            row['reason'] = str(error); note_rows.append(row); continue
        row['annotation_evidence'] = evidence
        if same_relation(observed,sheet,expected):
            row['reason'] = 'observed_matches_visible_relation'; note_rows.append(row); continue
        row.update(status='review',reason='visible_relation_conflict')
        pool = defaultdict(list)
        if paper_rows[label].get('suggested_formula'):
            pool[paper_rows[label]['suggested_formula']].append({'kind':'paper_candidate'})
        target = parse_address(address)
        for col,peer,text in notes.rows[sheet,target.row]:
            if (peer==address or (sheet,peer) not in model.formulas
                    or not model.is_visible((sheet,peer))):
                continue
            try:
                candidate = Translator(model.formulas[sheet,peer],origin=peer).translate_formula(address)
                pool[candidate].append({'kind':'same_row_peer','cell':sheet+'!'+peer})
            except (ValueError,TranslatorError):
                pass
        generated = generate(observed)
        if generated['search_truncated']:
            row['reason'] = 'candidate_search_truncated'; note_rows.append(row); continue
        for candidate in generated['candidates']:
            pool[candidate['formula']].append({'kind':'single_edit','edits':candidate['edits']})
        pool.pop(observed,None)
        matching = {formula:sources for formula,sources in pool.items()
                    if same_relation(formula,sheet,expected)}
        peer_supported = {formula:sources for formula,sources in matching.items()
                          if sum(s['kind']=='same_row_peer' for s in sources)>=2}
        qualified = peer_supported if peer_supported else {
            formula:sources for formula,sources in matching.items()
            if any(s['kind']=='single_edit' for s in sources)}
        row['matching_candidates'] = len(matching)
        if len(qualified)==1:
            candidate,sources = next(iter(qualified.items()))
            row.update(status='propose',suggested_formula=candidate,
                       reason='unique_candidate_matches_complete_visible_product',
                       candidate_sources=sources)
        elif len(qualified)>1:
            row['reason'] = 'multiple_relation_matching_syntax_candidates'
        note_rows.append(row)
    blended = []
    for old,new in zip(prior['rows'],note_rows):
        blended.append(dict(new) if old.get('status')!='propose' and new['status']=='propose' else dict(old))
    common = {'automatic_edit_applied':False,'labels_read':[],
              'note_authenticity_verified':False,'final_validation_eligible':False}
    return {'note_only':{**common,'rows':note_rows,'selector_version':VERSION},
            'dev11_plus_note':{**common,'rows':blended,'selector_version':VERSION+'-blend'}}
