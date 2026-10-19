#!/usr/bin/env python3
"""Score actual natural candidate reachability; never import inference code."""
from collections import Counter
import gzip
import json
from pathlib import Path

from resume_spreadsheetbench2_after_pilot import ROOT,EVIDENCE,verify_frozen
from spreadsheetbench2_scoring import sha256,verify_prediction_lock
from score_paper_candidate_trace import pool_diagnosis

EXPERIMENT=EVIDENCE/'natural_mechanism'
NATURAL=EVIDENCE/'model_m9_natural'


def read(path):
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def require(condition,message):
    if not condition:
        raise SystemExit(message)


def main():
    _,baseline=verify_prediction_lock(EVIDENCE)
    verify_frozen(baseline)
    lock_path=EXPERIMENT/'input_lock.json'
    lock,terminal=read(lock_path),read(EXPERIMENT/'output_lock.json')
    for name,digest in lock['files_sha256'].items():
        require(sha256(Path(name))==digest,'Observation input changed: '+name)
    require(terminal['scoring_may_begin'] and terminal['input_lock_sha256']==sha256(lock_path)
            and terminal['runtime_sha256']==sha256(EXPERIMENT/'runs/runtime.json'),'Invalid observation output lock')
    runtime=read(EXPERIMENT/'runs/runtime.json')
    tasks={r['id']:r for r in runtime['tasks']}
    outputs={r['id']:r for r in terminal['outputs']}
    require(set(tasks)==set(outputs)==set(lock['task_ids']) and len(tasks)==len(runtime['tasks'])==
            len(outputs)==len(terminal['outputs'])==7 and runtime['requested_worker_count']==20,'Task scope changed')
    for name,item in outputs.items():
        require(item['status']==tasks[name]['status'] and item['status'] in {'complete','failed','timeout'},'Invalid terminal state')
        if item['path']:
            require(Path(item['path'])==Path(tasks[name]['cwd'])/'trace.json.gz'
                    and sha256(Path(item['path']))==item['sha256'],'Trace output changed')
        if item['status']=='complete':
            require(item['path'] and item['sha256']==tasks[name]['output_sha256']['trace.json.gz'],'Complete output not locked')
    # All observations locked/verified before loading any target formula key.
    cases=read(NATURAL/'scoring/expected.json')
    originals={r['id']:r for r in read(NATURAL/'output_lock.json')['outputs']}
    records=[]
    natural_partition,natural_reasons,natural_pools,statuses=(Counter() for _ in range(4))
    for name in lock['task_ids']:
        case,item=cases[name],outputs[name]
        trace=None
        if item['status']=='complete':
            trace=read(Path(item['path']))
            old=read(Path(originals[name]['path']))
            require(trace['labels_read']==[] and trace['original_unchanged']
                    and trace['input_sha256']==old['input_sha256']==sha256(Path(case['workbook']))
                    and trace['paper']==old['original_paper']
                    and trace['observed_formulas']==old['observed_formulas'],'Original paper/inventory did not reproduce')
        expected=case['candidate_targets'] if case['group']=='range_candidates' else case['errors']
        if trace:
            part,reasons,outside,pools=pool_diagnosis(trace,expected,'complete')
        else:
            part=Counter({item['status']+'_unobserved_pool':len(expected)})
            reasons,outside,pools=Counter(),Counter(),Counter()
        require(sum(part.values())==len(expected),'Target denominator changed')
        row=dict(id=name,group=case['group'],status=item['status'],targets=len(expected),
                 partition=dict(part),details=dict(reasons),outside_types=dict(outside),pool_counts=dict(pools))
        if trace:
            row['probe_invocation_on_targets']=dict(fg=sum(c in trace['candidate_trace']['fg'] for c in expected),
                sg=sum(c in trace['candidate_trace']['sg'] for c in expected),
                fg_invoked_but_empty=sum(c in trace['candidate_trace']['fg'] and not trace['candidate_trace']['fg'][c] for c in expected))
            correct=case['correct']
            changed={r['cell'] for r in trace['paper']['rows'] if isinstance(r.get('suggested_formula'),str)
                     and r['suggested_formula'].startswith('=')
                     and r['suggested_formula']!=trace['observed_formulas'].get(r['cell'])}
            row['known_correct_targets']=len(correct)
            row['known_correct_targets_modified']=len(set(correct)&changed)
        if case['group']=='natural_errors':
            natural_partition.update(part);natural_reasons.update(reasons);natural_pools.update(pools)
        statuses[item['status']]+=1
        records.append(row)
    require(sum(natural_partition.values())==513,'Natural513 denominator changed')
    summary=dict(role='Revealed natural development; actual invoked candidate pools only; not a model change',
        terminal_states=dict(statuses),original_predictions_identical_on_complete_tasks=True,
        natural_error_denominator=513,natural_gap_partition=dict(natural_partition),
        natural_selection_and_trigger_details=dict(natural_reasons),natural_observed_pool_counts=dict(natural_pools),
        natural_text_exact_pool_oracle_coverage=natural_pools['union_exact_reachable']/513,
        tasks=records,final_validation_eligible=False,business_accuracy=None,
        limits=['No exact text in invoked pool does not rule out uninvoked or equivalent formulas',
                'Same visible workbook may have incompatible external business intents; dev29 counterexamples remain',
                '505 errors share one exposed source; neither source-balanced nor final validation'],
        input_lock_sha256=sha256(lock_path),output_lock_sha256=sha256(EXPERIMENT/'output_lock.json'),
        runtime={k:runtime[k] for k in ['requested_worker_count','worker_count','wall_seconds',
                                     'child_cpu_seconds','aggregate_peak_rss_bytes_sampled','all_tasks_complete']})
    for path in [EXPERIMENT/'independent_score.json',ROOT/'NATURAL_MECHANISM_SUMMARY.json']:
        with path.open('x') as handle:
            json.dump(summary,handle,ensure_ascii=False,indent=2);handle.write('\n')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
