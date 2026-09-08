"""Serial V518/V519 comparison and separately labelled read-only cost profiling."""

import argparse
import json
import resource
import sys
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_8_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_8_development import verify_unique_solution as verify_baseline
from formulaguard.v5_1_9_development import (
    compose_joint_diagnosis,
    verify_unique_solution,
)
from scripts.build_v519_confirmation_cases import build_case
from scripts.v518_validation_common import AS_OF, load_model, write_json
from scripts.v519_validation_common import sources, verify_sources


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    hashes=sources()
    measurements,profiles=[],[]
    for count in (16,24,32):
        for backend in ("v4","v511"):
            for repeat in range(5):
                started=perf_counter()
                raw,document,approvals,_=build_case(count,"product","pair","serial-v519")
                model=load_model(raw)
                input_seconds=perf_counter()-started
                started=perf_counter()
                ranking=(v4_scores if backend=="v4" else v5_1_1_development_scores)(model)
                ranking_seconds=perf_counter()-started
                args={"documents":[document],"approvals":approvals,"as_of":AS_OF}
                for mode in (("baseline","main") if repeat%2==0 else ("main","baseline")):
                    started=perf_counter()
                    diagnosis=(baseline if mode=="baseline" else compose_joint_diagnosis)(model,ranking,backend=backend,**args)
                    elapsed=perf_counter()-started
                    started=perf_counter()
                    if diagnosis.search.status=="unique_solution":
                        if mode=="baseline":
                            verify_baseline(model,diagnosis,**args)
                        else:
                            verify_unique_solution(model,diagnosis,localization=ranking,**args)
                    replay_seconds=perf_counter()-started
                    started=perf_counter()
                    encoded=json.dumps(asdict(diagnosis)).encode()
                    serialization_seconds=perf_counter()-started
                    measurements.append({"count":count,"backend":backend,"repeat":repeat,"mode":mode,
                        "status":diagnosis.search.status,"input_seconds":input_seconds,"ranking_seconds":ranking_seconds,
                        "diagnosis_seconds":elapsed,"replay_seconds":replay_seconds,"serialization_seconds":serialization_seconds,
                        "full_in_memory_seconds":input_seconds+ranking_seconds+elapsed+replay_seconds+serialization_seconds,
                        "diagnosis_bytes":len(encoded),"certificate_bytes":len(json.dumps(asdict(diagnosis.search)).encode()),
                        "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                        "preparation_evaluations":diagnosis.search.preparation_evaluations,
                        "visited":diagnosis.search.visited,"evaluated":diagnosis.search.evaluated})
                print(f"Serial {count}/{backend}/{repeat} complete",flush=True)
            if count==32:
                totals=defaultdict(float)
                starts={}

                def observer(frame,event,arg,starts=starts,totals=totals):
                    name=frame.f_code.co_name
                    if name not in {"compose_edge_diagnosis","_prepare","build_component_tables"}:
                        return
                    if event=="call":
                        starts[id(frame)]=perf_counter()
                    elif event=="return" and id(frame) in starts:
                        totals[name]+=perf_counter()-starts.pop(id(frame))

                started=perf_counter()
                sys.setprofile(observer)
                try:
                    diagnosis=compose_joint_diagnosis(model,ranking,backend=backend,**args)
                finally:
                    sys.setprofile(None)
                elapsed=perf_counter()-started
                profiles.append({"backend":backend,"count":count,"profiled_diagnosis_seconds":elapsed,
                                 "candidate_preparation_seconds":totals["compose_edge_diagnosis"],
                                 "bounds_and_table_preparation_seconds":totals["_prepare"],
                                 "component_table_seconds_included_in_preparation":totals["build_component_tables"],
                                 "residual_search_dispatch_initial_checks_seconds":elapsed-totals["_prepare"]-totals["compose_edge_diagnosis"],
                                 "status":diagnosis.search.status})
    verify_sources(hashes)
    summary=[]
    for count in (16,24,32):
        for backend in ("v4","v511"):
            for mode in ("baseline","main"):
                rows=[r for r in measurements if (r["count"],r["backend"],r["mode"])==(count,backend,mode)]
                summary.append({"count":count,"backend":backend,"mode":mode,"repetitions":len(rows),
                    **{key:{"median":median(r[key] for r in rows),"min":min(r[key] for r in rows),"max":max(r[key] for r in rows)}
                       for key in ("diagnosis_seconds","ranking_seconds","replay_seconds","full_in_memory_seconds","certificate_bytes")}})
    write_json(output/"result.json",{"sources":hashes,"measurements":measurements,"summary":summary,"profiles":profiles,
               "scope":"serial five repetitions; alternating modes; shared rank within repetition; RSS high-water; no XLSX I/O; profiler overhead reported separately"})


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",type=Path,required=True)
    run(parser.parse_args().output)
