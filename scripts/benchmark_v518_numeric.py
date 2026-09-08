"""Serial repeated latency measurements, separate from parallel batch evidence."""

from __future__ import annotations

import argparse
import json
import math
import resource
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_7_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_7_development import verify_unique_solution as verify_baseline
from formulaguard.v5_1_8_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v518_numeric_cases import build_case
from scripts.evaluate_v518_numeric import (
    BACKENDS,
    MODES,
    configuration,
    current_sources,
)
from scripts.run_v512_evaluation import write_json
from scripts.v518_validation_common import AS_OF, load_model


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    sources=current_sources()
    rows=[]
    for count in (16,24,32):
        raw,document,approvals,_=build_case(count,"product","unique","serial-benchmark")
        for backend in BACKENDS:
            for repeat in range(2):
                model=load_model(raw)
                started=perf_counter()
                ranking=(v4_scores if backend=="v4" else v5_1_1_development_scores)(model)
                ranking_seconds=perf_counter()-started
                for mode in MODES:
                    config,policy=configuration(mode)
                    started=perf_counter()
                    diagnosis=(baseline if mode=="baseline" else compose_joint_diagnosis)(
                        model,ranking,backend=backend,documents=[document],approvals=approvals,as_of=AS_OF,
                        config=config,repair_policy=policy)
                    elapsed=perf_counter()-started
                    started=perf_counter()
                    if diagnosis.search.status=="unique_solution":
                        (verify_baseline if mode=="baseline" else verify_unique_solution)(
                            model,diagnosis,documents=[document],approvals=approvals,as_of=AS_OF)
                    replay_seconds=perf_counter()-started
                    row={"count":count,"backend":backend,"mode":mode,"repeat":repeat,"status":diagnosis.search.status,
                         "ranking_seconds":ranking_seconds,"diagnosis_seconds":elapsed,"replay_seconds":replay_seconds,
                         "end_to_end_seconds":ranking_seconds+elapsed,"certificate_bytes":len(json.dumps(asdict(diagnosis.search)).encode()),
                         "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
                    rows.append(row)
                print(f"Serial {count}/{backend}/repeat-{repeat} completed",flush=True)
    if current_sources()!=sources:
        raise ValueError("benchmark source changed")
    summary=[]
    for count in (16,24,32):
        for backend in BACKENDS:
            for mode in MODES:
                selected=[r for r in rows if (r["count"],r["backend"],r["mode"])==(count,backend,mode)]
                item={"count":count,"backend":backend,"mode":mode,"repetitions":len(selected)}
                for metric in ("diagnosis_seconds","end_to_end_seconds","replay_seconds","certificate_bytes","process_peak_rss_kib"):
                    values=sorted(r[metric] for r in selected)
                    item[metric]={"median":median(values),"p95":values[math.ceil(.95*len(values))-1],"max":max(values)}
                summary.append(item)
    write_json(output/"result.json",{"sources":sources,"measurements":rows,"summary":summary,
               "scope":"serial single-process; 2 repetitions; p95 equals max; RSS is process high-water, not per-call allocation"})


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    run(parser.parse_args().output)
