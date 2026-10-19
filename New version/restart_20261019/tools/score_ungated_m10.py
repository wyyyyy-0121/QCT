#!/usr/bin/env python3
"""Independently compare observed and ungated native candidate availability."""
from collections import Counter,defaultdict
from copy import deepcopy
import gzip
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT,EVIDENCE,verify_frozen
from spreadsheetbench2_scoring import sha256,verify_prediction_lock
from score_paper_candidate_trace import pool_diagnosis

EXPERIMENT=EVIDENCE/'model_m10_ungated'
NATURAL=EVIDENCE/'model_m9_natural'


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def require(condition,message):
    if not condition:
        raise SystemExit(message)


def reachable(trace,expected,fg):
    sg=trace['candidate_trace']['sg']
    return {cell for cell,formula in expected.items() if any(p['formula']==formula for p in fg.get(cell,[]))
            or any(p['formula']==formula for p in sg.get(cell,{}).get('candidates',[]))}


def main():
    _,baseline=verify_prediction_lock(EVIDENCE)
    verify_frozen(baseline)
    lock_path=EXPERIMENT/'input_lock.json'
    lock,terminal=read(lock_path),read(EXPERIMENT/'output_lock.json')
    for name,digest in lock['files_sha256'].items():
        require(sha256(Path(name))==digest,'Locked M10 input changed: '+name)
    require(terminal['scoring_may_begin'] and terminal['input_lock_sha256']==sha256(lock_path)
            and terminal['runtime_sha256']==sha256(EXPERIMENT/'runs/runtime.json'),'M10 output lock differs')
    runtime=read(EXPERIMENT/'runs/runtime.json')
    tasks={r['id']:r for r in runtime['tasks']}
    outputs={r['id']:r for r in terminal['outputs']}
    require(set(tasks)==set(outputs)==set(lock['task_ids']) and len(tasks)==len(runtime['tasks'])==
            len(outputs)==len(terminal['outputs'])==49 and runtime['requested_worker_count']==20,'M10 scope differs')
    for name,item in outputs.items():
        require(item['status']==tasks[name]['status'] and item['status'] in {'complete','failed','timeout'},'Invalid terminal state')
        if item['path']:
            require(Path(item['path'])==Path(tasks[name]['cwd'])/'trace.json.gz'
                    and sha256(Path(item['path']))==item['sha256'],'M10 trace changed')
        if item['status']=='complete':
            require(item['path'] and item['sha256']==tasks[name]['output_sha256']['trace.json.gz'],'Complete output not locked')
    # Separate scoring key only read after49 terminal records/output hashes checked.
    cases=read(NATURAL/'scoring/expected.json')
    originals={r['id']:r for r in read(NATURAL/'output_lock.json')['outputs']}
    require(set(cases)==set(tasks),'Scoring key scope differs')
    records=[]
    groups=defaultdict(Counter)
    statuses,partitions,reasons=Counter(),Counter(),Counter()
    source_details=[]
    for name in lock['task_ids']:
        case,item=cases[name],outputs[name]
        expected=case['candidate_targets'] if case['group']=='range_candidates' else case['errors']
        row=dict(id=name,group=case['group'],status=item['status'],targets=len(expected),known_correct_targets=len(case['correct']))
        metrics=Counter(targets=len(expected),known_correct_targets=len(case['correct']))
        if item['status']=='complete':
            trace=read(Path(item['path']))
            old=read(Path(originals[name]['path']))
            require(trace['input_sha256']==old['input_sha256']==sha256(Path(case['workbook']))
                    and trace['labels_read']==[] and trace['original_unchanged']
                    and trace['paper']==old['original_paper'] and trace['observed_formulas']==old['observed_formulas']
                    and trace['generator_parameters']==dict(radius=5,peer_min_support=2,candidate_limit=24),
                    'Baseline/provenance/default parameters differ')
            original_fg,ungated=trace['candidate_trace']['fg'],trace['ungated_fg']
            observed=trace['observed_formulas']
            require(set(ungated)==set(observed) and len(trace['additional_fg_calls'])==len(set(trace['additional_fg_calls']))
                    and set(trace['additional_fg_calls'])==set(observed)-set(original_fg), 'M10 missed or duplicated formula calls')
            require(all(ungated[c]==p for c,p in original_fg.items()),'Existing probes changed')
            require(all(len(p)<=24 for p in ungated.values()),'Candidate cap changed')
            before,after=reachable(trace,expected,original_fg),reachable(trace,expected,ungated)
            metrics.update(original_exact_reachable=len(before),ungated_exact_reachable=len(after),
                           exact_gained=len(after-before),exact_lost=len(before-after),
                           original_fg_called_on_targets=sum(c in original_fg for c in expected),
                           ungated_fg_called_on_targets=sum(c in ungated for c in expected),
                           additional_fg_calls=len(trace['additional_fg_calls']),
                           all_native_fg_candidates=sum(map(len,original_fg.values())),
                           all_ungated_fg_candidates=sum(map(len,ungated.values())),
                           correct_targets_with_changed_fg_candidate=sum(any(p['formula']!=observed.get(c) for p in ungated.get(c,[]))
                                                                        for c in case['correct']),
                           unknown_cells_with_changed_fg_candidate=sum(any(p['formula']!=observed.get(c) for p in probes)
                               for c,probes in ungated.items() if c not in set(expected)|set(case['correct'])|set(case['blank_controls'])))
            modified=deepcopy(trace)
            modified['candidate_trace']['fg']=ungated
            part,why,_,_=pool_diagnosis(modified,expected,'complete')
            require(sum(part.values())==len(expected),'Target partition changed')
            row.update(partition=dict(part),details=dict(why))
            if case['group']=='natural_errors':
                partitions.update(part);reasons.update(why)
            for cell in sorted(after-before):
                source_details.append(dict(id=name,cell=cell,scope=case['group']))
        else:
            if case['group']=='natural_errors':
                partitions[item['status']+'_unobserved_pool']+=len(expected)
        row.update(dict(metrics))
        groups[case['group']].update(metrics)
        records.append(row)
        statuses[item['status']]+=1
    natural=groups['natural_errors']
    require(natural['targets']==sum(partitions.values())==lock['natural_error_denominator']==513,'Natural513 denominator differs')
    checks=dict(all49_complete=statuses['complete']==49,original_predictions_identical=True,
                no_existing_exact_pool_loss=all(g['exact_lost']==0 for g in groups.values()),
                natural_exact_pool_strictly_increases=natural['ungated_exact_reachable']>natural['original_exact_reachable'])
    summary=dict(experiment='M10 unchanged generator without pre-generation trigger; candidate availability only',
        terminal_states=dict(statuses),by_group={k:dict(v) for k,v in groups.items()},
        natural_gap_partition=dict(partitions),natural_details=dict(reasons),continuation_checks=checks,
        continuation_gate_passed=all(checks.values()),
        decision='evaluate_fixed_scoring_next' if all(checks.values()) else 'stop_ungating_route_no_parameter_search',
        natural_by_workbook=[r for r in records if r['group'] in {'natural_errors','corrected_controls','range_candidates'}],
        model_predictions_changed=False,business_accuracy=None,final_validation_eligible=False,
        natural_validation_sources=0,natural_validation_families=0,
        input_lock_sha256=sha256(lock_path),output_lock_sha256=sha256(EXPERIMENT/'output_lock.json'),
        runtime={k:runtime[k] for k in ['requested_worker_count','worker_count','wall_seconds',
                                     'child_cpu_seconds','aggregate_peak_rss_bytes_sampled','all_tasks_complete']})
    with (EXPERIMENT/'independent_score.json').open('x') as handle:
        json.dump(dict(summary=summary,tasks=records,gained_targets=source_details),handle,ensure_ascii=False,indent=2)
        handle.write('\n')
    with (ROOT/'MODEL_M10_TRIGGER_SUMMARY.json').open('x') as handle:
        json.dump(summary,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='natural_by_workbook'},indent=2))


if __name__=='__main__':
    main()
