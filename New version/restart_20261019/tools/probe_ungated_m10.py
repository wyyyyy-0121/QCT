#!/usr/bin/env python3
"""Probe previously untriggered formulas with the unchanged paper generator."""
import argparse
from dataclasses import asdict
import gzip
import json
import os
from pathlib import Path
import sys

from spreadsheetbench2_scoring import sha256
from trace_paper_candidates import predict, xml_inventory


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    source,output=args.input.resolve(),args.output.resolve()
    if not source.is_file() or source.suffix!='.xlsx' or output.exists() or source==output:
        raise SystemExit('Read-only xlsx and new output required')
    before=sha256(source)

    def guard(event,values):
        if event!='open' or not values or not isinstance(values[0],(str,bytes,os.PathLike)):
            return
        path=Path(os.fsdecode(values[0])).resolve()
        if path==source:
            mode,flags=values[1:3]
            if (isinstance(mode,str) and any(c in mode for c in 'wa+')) or (
                    isinstance(flags,int) and flags&(os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
                raise PermissionError('Original is read-only')
        elif path!=output and (path.suffix.lower() in {'.xlsx','.xls','.xlsm','.ods','.properties'}
                or 'scoring' in path.parts or any(token in path.name.lower() for token in
                    ('truth','golden','expected.json','prediction.json','score_inventory'))):
            raise PermissionError('Other workbook/label/frozen-output access denied')

    sys.addaudithook(guard)
    trace=predict(source)
    import formulaguard.v5_structural_guard as fg
    from formulaguard.workbook import WorkbookModel
    model=WorkbookModel.from_xlsx(source)
    observed={s+'!'+a:f for (s,a),f in model.formulas.items()}
    if observed!=trace['observed_formulas']:
        raise SystemExit('Repeated formula inventory differs')
    constraints=fg._constraint_cells(model)
    residuals=fg._constraint_residuals(model,constraints)
    graph=model.dependency_graph()
    parameters=dict(radius=fg.DEFAULT_RADIUS,peer_min_support=fg.DEFAULT_PEER_MIN_SUPPORT,
                    candidate_limit=fg.DEFAULT_CANDIDATE_LIMIT)
    if parameters!=dict(radius=5,peer_min_support=2,candidate_limit=24):
        raise SystemExit('Frozen generator defaults changed')
    probes=dict(trace['candidate_trace']['fg'])
    new_calls=[]
    for cell in model.formula_cells:
        label=cell[0]+'!'+cell[1]
        if label not in probes:
            probes[label]=[asdict(p) for p in fg._candidate_probes(model,cell,residuals,graph,**parameters)]
            new_calls.append(label)
    trace.update(ungated_fg=probes,additional_fg_calls=new_calls,generator_parameters=parameters,
                 input_sha256=before,input_xml_types=xml_inventory(source),labels_read=[],
                 original_unchanged=sha256(source)==before,final_validation_eligible=False,
                 scope='Candidate availability only; original predictions and decisions unmodified')
    if not trace['original_unchanged']:
        raise SystemExit('Original changed')
    with output.open('xb') as raw:
        with gzip.open(raw,'wt',encoding='utf-8') as handle:
            json.dump(trace,handle,ensure_ascii=False,sort_keys=True,separators=(',',':'))


if __name__=='__main__':
    main()
