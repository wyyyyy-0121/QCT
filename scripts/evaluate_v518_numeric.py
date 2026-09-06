"""V518 development, frozen confirmation, prediction locks and strict scoring."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import resource
import secrets
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

from formulaguard.localize import v4_scores
from formulaguard.v5_1_1_development import v5_1_1_development_scores
from formulaguard.v5_1_5_development import model_binding
from formulaguard.v5_1_7_development import SearchParameters as BaselineParameters
from formulaguard.v5_1_7_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_7_development import verify_unique_solution as verify_baseline
from formulaguard.v5_1_8_development import (
    SearchParameters,
    compose_joint_diagnosis,
    verify_unique_solution,
)
from formulaguard.v518_numeric_bounds import runtime_identity, runtime_supported
from scripts.build_v518_numeric_cases import FAMILIES, KINDS, build_case
from scripts.evaluate_v514_edges import verify_source
from scripts.run_v512_evaluation import write_json
from scripts.score_v512_confirmation import canonical_formula, safe_path, sha256
from scripts.v518_validation_common import (
    AS_OF,
    actions,
    check_identity,
    decode,
    load_model,
    snapshot,
)

ROOT = Path(__file__).resolve().parents[1]
MODES = ("baseline", "numeric", "numeric_off", "low_budget", "review_only", "reject_all")
BACKENDS = ("v4", "v511")


def configuration(mode):
    if mode not in MODES:
        raise ValueError("unknown mode")
    config = BaselineParameters() if mode == "baseline" else SearchParameters(
        numeric_bounds=mode != "numeric_off", max_nodes=1 if mode == "low_budget" else 10000)
    policy = mode if mode in {"review_only", "reject_all"} else "structural"
    return config, policy


def specifications(stage):
    if stage == "confirmation":
        return [(n,f,k,s) for n in (24,32) for f in FAMILIES for k in KINDS for s in range(2)]
    if stage == "development":
        return [(n,f,k,0) for n in (16,24,32) for f in FAMILIES for k in ("unique","mixed_subtotals")] + [
            (n,"product",k,0) for n in (16,24,32) for k in KINDS if k not in {"unique","mixed_subtotals"}]
    if stage == "test":
        return [(3,"product",k,0) for k in ("unique","ambiguous","invalid_approval")]
    raise ValueError("unknown experiment stage")


def source_files():
    return sorted([*ROOT.glob("formulaguard/*.py"),*ROOT.glob("scripts/*.py"),*ROOT.glob("tests/*.py"),
                   ROOT/"pyproject.toml",ROOT/"research/V518_NUMERIC_PROTOCOL.md",
                   ROOT/"research/V518_EXPERIMENT_PROTOCOL.md",ROOT/"research/V518_DEVELOPMENT_PLAN.md"])


def current_sources():
    return {p.relative_to(ROOT).as_posix():sha256(p) for p in source_files()}


def freeze(output):
    if not runtime_supported():
        raise ValueError("unreviewed numeric environment")
    output.mkdir(parents=True,exist_ok=False)
    hashes=snapshot(ROOT,output,source_files())
    write_json(output/"source_lock.json",{"protocol":"v518_numeric_v1","artifacts":hashes,
               "python":platform.python_version(),"dependencies":{},"runtime":runtime_identity(),
               "frozen_at":datetime.now(UTC).isoformat(),"modes":MODES,"backends":BACKENDS,
               "configurations":{m:{"search":asdict(configuration(m)[0]),"policy":configuration(m)[1]} for m in MODES},
               "confirmation_specifications":specifications("confirmation")})


def build(output,stage,lock=None):
    if stage == "confirmation" and not lock:
        raise ValueError("confirmation requires prior source freeze")
    if lock:
        frozen=verify_source(lock)
        if frozen["runtime"]!=runtime_identity():
            raise ValueError("numeric environment changed")
    output.mkdir(parents=True,exist_ok=False)
    seed=secrets.token_hex(24) if stage=="confirmation" else f"v518-{stage}-01"
    commitment=hashlib.sha256(seed.encode()).hexdigest()
    rows,labels,registry=[],[],{}
    for slot,(count,family,kind,repeat) in enumerate(specifications(stage)):
        case_id=hashlib.sha256(f"{commitment}:{slot}".encode()).hexdigest()[:24]
        raw,doc,approvals,label=build_case(count,family,kind,f"{seed}:{repeat}")
        workbook_path,document_path=f"workbooks/{case_id}.json",f"documents/{case_id}.json"
        write_json(output/"PUBLIC"/workbook_path,raw)
        target=output/"PUBLIC"/document_path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(doc)
        registry[case_id]=approvals
        rows.append({"case_id":case_id,"slot":slot,"workbook_path":workbook_path,"document_path":document_path,
                     "workbook_sha256":sha256(output/"PUBLIC"/workbook_path),"document_sha256":sha256(target)})
        labels.append({**label,"case_id":case_id,"slot":slot})
    write_json(output/"PUBLIC/manifest.json",{"stage":stage,"cases":rows,"as_of":AS_OF.isoformat()})
    write_json(output/"APPROVALS.json",registry)
    write_json(output/"labels.json",{"seed":seed,"cases":labels})
    write_json(output/"release_receipt.json",{"stage":stage,"seed_commitment":commitment,
               "source_lock_sha256":sha256(lock) if lock else None,"cases":len(rows),
               "manifest_sha256":sha256(output/"PUBLIC/manifest.json"),"approvals_sha256":sha256(output/"APPROVALS.json"),
               "labels_sha256":sha256(output/"labels.json"),"generated_at":datetime.now(UTC).isoformat()})


def release_context(release,lock=None):
    receipt=json.loads((release/"release_receipt.json").read_text())
    if receipt["source_lock_sha256"] is not None:
        if not lock or sha256(lock)!=receipt["source_lock_sha256"]:
            raise ValueError("missing or changed frozen source lock")
        frozen=verify_source(lock)
        if frozen["runtime"]!=runtime_identity():
            raise ValueError("numeric environment changed")
    elif receipt["stage"]=="confirmation":
        raise ValueError("unfrozen confirmation")
    if sha256(release/"PUBLIC/manifest.json")!=receipt["manifest_sha256"] or sha256(release/"APPROVALS.json")!=receipt["approvals_sha256"]:
        raise ValueError("release context changed")
    manifest=json.loads((release/"PUBLIC/manifest.json").read_text())
    rows=manifest["cases"]
    specs=specifications(receipt["stage"])
    if receipt["cases"]!=len(specs) or len(rows)!=len(specs) or {r["slot"] for r in rows}!=set(range(len(specs))):
        raise ValueError("incomplete predeclared population")
    if manifest["stage"]!=receipt["stage"] or manifest["as_of"]!=AS_OF.isoformat():
        raise ValueError("release stage or date mismatch")
    registry=json.loads((release/"APPROVALS.json").read_text())
    for row in rows:
        expected=hashlib.sha256(f"{receipt['seed_commitment']}:{row['slot']}".encode()).hexdigest()[:24]
        if row["case_id"]!=expected:
            raise ValueError("population identity changed")
        for key in ("workbook","document"):
            if sha256(safe_path(release/"PUBLIC",row[key+"_path"]))!=row[key+"_sha256"]:
                raise ValueError("input hash mismatch")
    if set(registry)!={r["case_id"] for r in rows}:
        raise ValueError("approval population mismatch")
    return receipt,rows,registry


def compute(task):
    release,output,row,approval=task
    release,output=Path(release),Path(output)
    model=load_model(json.loads(safe_path(release/"PUBLIC",row["workbook_path"]).read_text()))
    document=safe_path(release/"PUBLIC",row["document_path"]).read_bytes()
    before=model_binding(model)
    hashes={}
    for backend in BACKENDS:
        started=perf_counter()
        ranking=(v4_scores if backend=="v4" else v5_1_1_development_scores)(model)
        ranking_seconds=perf_counter()-started
        reference=None
        for mode in MODES:
            config,policy=configuration(mode)
            started=perf_counter()
            diagnosis=(baseline if mode=="baseline" else compose_joint_diagnosis)(model,ranking,backend=backend,
                      documents=[document],approvals=approval,as_of=AS_OF,config=config,repair_policy=policy)
            elapsed=perf_counter()-started
            if reference is None:
                reference=diagnosis
            check_identity(model,reference,diagnosis)
            shard={"case_id":row["case_id"],"backend":backend,"mode":mode,"configuration":asdict(config),
                   "policy":policy,"workbook_sha256":row["workbook_sha256"],"document_sha256":row["document_sha256"],
                   "diagnosis":asdict(diagnosis),"ranking_seconds":ranking_seconds,"diagnosis_seconds":elapsed,
                   "end_to_end_seconds":ranking_seconds+elapsed,"process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   "certificate_bytes":len(json.dumps(asdict(diagnosis.search)).encode())}
            name=f"shards/{backend}_{mode}/{row['case_id']}.json"
            write_json(output/name,shard)
            hashes[name]=sha256(output/name)
    if model_binding(model)!=before:
        raise ValueError("workbook mutated")
    return hashes


def predict(release,output,lock=None,workers=4):
    receipt,rows,registry=release_context(release,lock)
    output.mkdir(parents=True,exist_ok=False)
    sources=current_sources()
    hashes={}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        tasks=[(str(release),str(output),row,registry[row["case_id"]]) for row in rows]
        for index,chunk in enumerate(pool.map(compute,tasks),1):
            hashes.update(chunk)
            print(f"Predicted {index}/{len(rows)} workbooks",flush=True)
    if current_sources()!=sources:
        raise ValueError("prediction source changed")
    release_context(release,lock)
    write_json(output/"prediction_lock.json",{"protocol":"v518_numeric_v1","sources":sources,
               "release_receipt_sha256":sha256(release/"release_receipt.json"),"source_lock_sha256":receipt["source_lock_sha256"],
               "runtime":runtime_identity(),"labels_read":[],"workers":workers,"cases":len(rows),"shards":hashes,
               "completed_at":datetime.now(UTC).isoformat()})


def verify_case(task):
    release,predictions,row,approval=task
    release,predictions=Path(release),Path(predictions)
    model=load_model(json.loads(safe_path(release/"PUBLIC",row["workbook_path"]).read_text()))
    document=safe_path(release/"PUBLIC",row["document_path"]).read_bytes()
    records=[]
    for backend in BACKENDS:
        ranking=(v4_scores if backend=="v4" else v5_1_1_development_scores)(model)
        identity_reference=baseline(model,ranking,backend=backend,documents=[document],approvals=approval,
                                    as_of=AS_OF,config=BaselineParameters(max_nodes=1,max_evaluations=1))
        baseline_actions=None
        for mode in MODES:
            shard=json.loads((predictions/f"shards/{backend}_{mode}/{row['case_id']}.json").read_text())
            config,policy=configuration(mode)
            if (shard["case_id"],shard["backend"],shard["mode"],shard["configuration"],shard["policy"])!=(row["case_id"],backend,mode,asdict(config),policy):
                raise ValueError("shard mode, policy or budget changed")
            if any(shard[key+"_sha256"]!=row[key+"_sha256"] for key in ("workbook","document")):
                raise ValueError("shard input identity changed")
            diagnosis=decode(shard["diagnosis"])
            if diagnosis.backend!=backend or diagnosis.repair_policy!=policy:
                raise ValueError("diagnosis mode identity changed")
            check_identity(model,identity_reference,diagnosis)
            audit=diagnosis.search
            if audit.visited>config.max_nodes or audit.preparation_evaluations>config.max_preparations or audit.evaluated>config.max_evaluations:
                raise ValueError("declared budget violated")
            accepted=actions(diagnosis)
            if mode=="baseline":
                baseline_actions=accepted
            if audit.status=="unique_solution":
                (verify_baseline if mode=="baseline" else verify_unique_solution)(model,diagnosis,documents=[document],approvals=approval,as_of=AS_OF)
            elif accepted and not (audit.status.startswith("constraint_rejected:") or audit.status=="no_approved_constraints"):
                raise ValueError("nonunique joint actions")
            elif accepted and accepted!=baseline_actions:
                raise ValueError("legacy fallback changed")
            if policy!="structural" and accepted:
                raise ValueError("nonaccepting policy has actions")
            records.append({"case_id":row["case_id"],"backend":backend,"mode":mode,"status":audit.status,
                    "engine":audit.engine,"fallback_reason":audit.fallback_reason,"space_size":audit.space_size,
                    "visited":audit.visited,"evaluated":audit.evaluated,"preparation_evaluations":audit.preparation_evaluations,
                    "pruned_states":audit.pruned_states,"complete":audit.complete,"solutions_seen":audit.solutions_seen,
                    "proof_replayed":audit.status=="unique_solution","actions":[[*c,f] for c,f in sorted(accepted.items())],
                    "diagnosis_seconds":shard["diagnosis_seconds"],"ranking_seconds":shard["ranking_seconds"],
                    "end_to_end_seconds":shard["end_to_end_seconds"],"certificate_bytes":shard["certificate_bytes"],
                    "process_peak_rss_kib":shard["process_peak_rss_kib"]})
    return records


def score(release,predictions,output,lock=None,workers=4):
    receipt,rows,registry=release_context(release,lock)
    prediction=json.loads((predictions/"prediction_lock.json").read_text())
    if prediction["sources"]!=current_sources() or prediction["runtime"]!=runtime_identity() or prediction["labels_read"]!=[]:
        raise ValueError("source, environment or label boundary mismatch")
    if prediction["release_receipt_sha256"]!=sha256(release/"release_receipt.json") or prediction["source_lock_sha256"]!=receipt["source_lock_sha256"]:
        raise ValueError("prediction release mismatch")
    expected={f"shards/{b}_{m}/{r['case_id']}.json" for b in BACKENDS for m in MODES for r in rows}
    actual={p.relative_to(predictions).as_posix() for p in (predictions/"shards").rglob("*") if p.is_file()}
    if prediction["cases"]!=len(rows) or set(prediction["shards"])!=expected or actual!=expected:
        raise ValueError("incomplete prediction population")
    if any(sha256(safe_path(predictions,name))!=value for name,value in prediction["shards"].items()):
        raise ValueError("prediction hash mismatch")
    records=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        tasks=[(str(release),str(predictions),row,registry[row["case_id"]]) for row in rows]
        for index,chunk in enumerate(pool.map(verify_case,tasks),1):
            records.extend(chunk)
            print(f"Verified {index}/{len(rows)} workbooks before label scoring",flush=True)
    if current_sources()!=prediction["sources"]:
        raise ValueError("verification source changed")
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/"reveal_authorization.json",{"authorized_at":datetime.now(UTC).isoformat(),
               "prediction_lock_sha256":sha256(predictions/"prediction_lock.json"),"all_inputs_rankings_proofs_verified":True})
    if sha256(release/"labels.json")!=receipt["labels_sha256"]:
        raise ValueError("label hash mismatch")
    labels=json.loads((release/"labels.json").read_text())
    if hashlib.sha256(labels["seed"].encode()).hexdigest()!=receipt["seed_commitment"]:
        raise ValueError("seed commitment mismatch")
    by_case={r["case_id"]:r for r in labels["cases"]}
    if len(by_case)!=len(rows) or len(labels["cases"])!=len(rows) or set(by_case)!={r["case_id"] for r in rows}:
        raise ValueError("label population mismatch")
    summaries=defaultdict(lambda:{"workbooks":0,"required_cells":0,"correct_cells":0,"accepted_cells":0,"accepted_groups":0,"unsafe_groups":0,"statuses":Counter()})
    for record in records:
        label=by_case[record["case_id"]]
        expected_spec=specifications(receipt["stage"])[label["slot"]]
        if (label["count"],label["family"],label["kind"])!=tuple(expected_spec[:3]):
            raise ValueError("label stratum changed")
        truth={(e["sheet"],e["cell"]):canonical_formula(e["expected_formula"]) for e in label["errors"]}
        accepted={(s,c):canonical_formula(f) for s,c,f in record["actions"]}
        correct=sum(truth.get(cell)==formula for cell,formula in accepted.items())
        unsafe=bool(accepted) and (correct!=len(accepted) or label["decision"] in {"abstain","no_action"})
        record.update(family=label["family"],kind=label["kind"],count=label["count"],required_cells=len(truth),
                      correct_cells=correct,unsafe_group=unsafe,cluster_id=label["cluster_id"])
        summary=summaries[record["backend"]+"_"+record["mode"]]
        summary["workbooks"]+=1
        summary["required_cells"]+=len(truth)
        summary["correct_cells"]+=correct
        summary["accepted_cells"]+=len(accepted)
        summary["accepted_groups"]+=bool(accepted)
        summary["unsafe_groups"]+=unsafe
        summary["statuses"][record["status"]]+=1
    for summary in summaries.values():
        summary["coverage"]=summary["correct_cells"]/summary["required_cells"] if summary["required_cells"] else 0.0
    passed=all(s["unsafe_groups"]==0 for s in summaries.values())
    write_json(output/"result.json",{"stage":receipt["stage"],"workbooks":len(rows),"diagnoses":len(records),
               "completed_at":datetime.now(UTC).isoformat(),"gate_passed":passed,"summaries":dict(summaries),"records":records,
               "ranking_changes":0,"candidate_changes":0,"scope":"known-family synthetic evidence; not independent third-party blind testing"})
    if not passed:
        raise ValueError("unsafe accepted group: complete results retained")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("freeze","build","predict","score"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--release",type=Path)
    parser.add_argument("--predictions",type=Path)
    parser.add_argument("--lock",type=Path)
    parser.add_argument("--stage",choices=("development","confirmation","test"),default="development")
    parser.add_argument("--workers",type=int,default=4)
    args=parser.parse_args()
    if args.command=="freeze":
        freeze(args.output)
    elif args.command=="build":
        build(args.output,args.stage,args.lock)
    elif args.command=="predict":
        predict(args.release,args.output,args.lock,args.workers)
    else:
        score(args.release,args.predictions,args.output,args.lock,args.workers)
