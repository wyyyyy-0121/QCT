"""Row and column hypotheses only; repeated formulas do not prove intent."""
from collections import Counter,defaultdict
from openpyxl.formula.translate import Translator,TranslatorError
from formulaguard.a1 import parse_address,num_to_col
def candidates(model,sheet,address):
    p=parse_address(address);pool=defaultdict(list)
    for axis in ['row','column']:
        translated=defaultdict(list)
        for d in [-2,-1,1,2]:
            r,c=(p.row,p.col+d) if axis=='row' else (p.row+d,p.col)
            if r<1 or c<1:continue
            a=num_to_col(c)+str(r)
            if (sheet,a) not in model.formulas or not model.is_visible((sheet,a)):continue
            try:f=Translator(model.formulas[sheet,a],origin=a).translate_formula(address)
            except (ValueError,TranslatorError):continue
            translated[f].append(sheet+'!'+a)
        for formula,peers in translated.items():
            if len(peers)>=2 and formula!=model.formulas[sheet,address]:
                pool[formula].append({'axis':axis,'peers':peers,'support':len(peers)})
    return dict(pool)
