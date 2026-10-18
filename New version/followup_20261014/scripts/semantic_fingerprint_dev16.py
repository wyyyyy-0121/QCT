"""Complete currently supported workbook observations, excluding paths/parser caches."""
from dataclasses import fields,is_dataclass
import hashlib
import json
FIELDS=['cells','formulas','cell_visibility','number_formats','sheet_visibility','formula_kinds',
        'shared_formula_groups','shared_formula_regions','header_partition_metadata_complete',
        'hidden_rows','hidden_columns','merged_ranges','formula_regions']
def typed(value):
    if is_dataclass(value):
        return ['dataclass',type(value).__name__,{f.name:typed(getattr(value,f.name)) for f in fields(value)}]
    if isinstance(value,dict):
        entries=[[typed(k),typed(v)] for k,v in value.items()]
        return ['dict',sorted(entries,key=lambda p:json.dumps(p[0],sort_keys=True))]
    if isinstance(value,(set,frozenset)):
        return ['set',sorted([typed(v) for v in value],key=lambda p:json.dumps(p,sort_keys=True))]
    if isinstance(value,(tuple,list)):return [type(value).__name__,[typed(v) for v in value]]
    if hasattr(value,'isoformat'):return [type(value).__name__,value.isoformat()]
    if value is None or isinstance(value,(str,int,float,bool)):return [type(value).__name__,value]
    raise TypeError(type(value).__name__)
def fingerprint(model,parallel_sheets):
    payload={field:typed(getattr(model,field)) for field in FIELDS}
    payload['parallel_sheets']=parallel_sheets
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
