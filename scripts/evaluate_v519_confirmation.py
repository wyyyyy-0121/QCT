"""V519 fixed development and post-freeze confirmation with guarded scoring."""

import argparse
import hashlib
import importlib.metadata
import json
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
from formulaguard.v5_1_8_development import SearchParameters as BaselineParameters
from formulaguard.v5_1_8_development import compose_joint_diagnosis as baseline
from formulaguard.v5_1_8_development import verify_unique_solution as verify_baseline
from formulaguard.v5_1_9_development import (
    SearchParameters,
    compose_joint_diagnosis,
    verify_unique_solution,
)
from formulaguard.v518_numeric_bounds import runtime_identity, runtime_supported
from scripts.build_v519_confirmation_cases import FAMILIES, KINDS, build_case
from scripts.score_v512_confirmation import canonical_formula, safe_path
from scripts.v518_validation_common import (
    AS_OF,
    actions,
    check_identity,
    load_model,
    sha256,
    snapshot,
    write_json,
)
from scripts.v519_validation_common import ROOT, decode, sources, verify_sources

MODES = ("baseline", "main", "components_off", "low_budget", "review_only", "reject_all")
BACKENDS = ("v4", "v511")


def configuration(mode):
    if mode not in MODES:
        raise ValueError("invalid mode")
    config = BaselineParameters() if mode=="baseline" else SearchParameters(
        components=mode!="components_off", max_nodes=1 if mode=="low_budget" else 10000)
    return config, mode if mode in {"review_only","reject_all"} else "structural"


def specifications(stage):
    if stage=="confirmation":
        return [(n,f,k,s) for n in (24,32) for f in FAMILIES for k in KINDS for s in range(2)]
    if stage=="development":
        return [(12,f,k,0) for f in FAMILIES for k in KINDS] + [(n,"product",k,0) for n in (16,24,32)
                for k in ("pair","chain","shared_bridge","component8","oversized_component")]
    if stage=="test":
        return [(4,"product",k,0) for k in ("pair","coupled_ambiguous","invalid_approval")]
    raise ValueError("invalid stage")


def environment():
    return {"numeric":runtime_identity(), "dependencies":dict(sorted(
        (d.metadata["Name"],d.version) for d in importlib.metadata.distributions() if d.metadata["Name"]))}


def freeze(output):
    if not runtime_supported():
        raise ValueError("unreviewed numerical environment")
    output.mkdir(parents=True,exist_ok=False)
    hashes=sources()
    copied=snapshot(ROOT,output,[ROOT/n for n in hashes])
    if copied!=hashes:
        raise ValueError("freeze copy mismatch")
    write_json(output/"source_lock.json",{"protocol":"v519-confirmation-1","sources":hashes,"environment":environment(),
               "frozen_at":datetime.now(UTC).isoformat(),"specifications":specifications("confirmation"),
               "modes":{m:{"configuration":asdict(configuration(m)[0]),"policy":configuration(m)[1]} for m in MODES}})


def verify_lock(lock):
    frozen=json.loads(lock.read_text())
    verify_sources(frozen["sources"])
    if frozen["sources"]!=sources() or frozen["environment"]!=environment():
        raise ValueError("frozen source population or environment changed")
    if frozen["specifications"]!=[list(s) for s in specifications("confirmation")]:
        raise ValueError("confirmation matrix changed")
    if frozen["modes"]!={m:{"configuration":asdict(configuration(m)[0]),"policy":configuration(m)[1]} for m in MODES}:
        raise ValueError("frozen configuration changed")
    if any(sha256(lock.parent/"source"/n)!=h for n,h in frozen["sources"].items()):
        raise ValueError("frozen snapshot changed")
    return frozen


def build(output, stage, lock=None):
    if stage=="confirmation" and lock is None:
        raise ValueError("confirmation requires prior freeze")
    if lock:
        verify_lock(lock)
    output.mkdir(parents=True,exist_ok=False)
    seed=secrets.token_hex(24) if stage=="confirmation" else "v519-"+stage+"-01"
    commitment=hashlib.sha256(seed.encode()).hexdigest()
    rows,labels,registry=[],[],{}
    for slot,(count,family,kind,repeat) in enumerate(specifications(stage)):
        case_id=hashlib.sha256(f"{commitment}:{slot}".encode()).hexdigest()[:24]
        raw,document,approval,label=build_case(count,family,kind,f"{seed}:{repeat}")
        workbook_path,document_path=f"workbooks/{case_id}.json",f"documents/{case_id}.json"
        write_json(output/"PUBLIC"/workbook_path,raw)
        target=output/"PUBLIC"/document_path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(document)
        registry[case_id]=approval
        rows.append({"slot":slot,"case_id":case_id,"workbook_path":workbook_path,"document_path":document_path,
                     "workbook_sha256":sha256(output/"PUBLIC"/workbook_path),"document_sha256":sha256(target)})
        labels.append({**label,"case_id":case_id,"slot":slot})
    write_json(output/"PUBLIC/manifest.json",{"stage":stage,"cases":rows,"as_of":AS_OF.isoformat()})
    write_json(output/"APPROVALS.json",registry)
    write_json(output/"labels.json",{"seed":seed,"cases":labels})
    write_json(output/"release_receipt.json",{"stage":stage,"cases":len(rows),"seed_commitment":commitment,
               "source_lock_sha256":sha256(lock) if lock else None,"manifest_sha256":sha256(output/"PUBLIC/manifest.json"),
               "approvals_sha256":sha256(output/"APPROVALS.json"),"labels_sha256":sha256(output/"labels.json"),
               "generated_at":datetime.now(UTC).isoformat()})


def context(release,lock=None):
    receipt=json.loads((release/"release_receipt.json").read_text())
    if receipt["source_lock_sha256"] is not None:
        if lock is None or sha256(lock)!=receipt["source_lock_sha256"]:
            raise ValueError("missing or changed source lock")
        verify_lock(lock)
    elif receipt["stage"]=="confirmation":
        raise ValueError("unfrozen confirmation")
    if sha256(release/"PUBLIC/manifest.json")!=receipt["manifest_sha256"] or sha256(release/"APPROVALS.json")!=receipt["approvals_sha256"]:
        raise ValueError("release context changed")
    manifest=json.loads((release/"PUBLIC/manifest.json").read_text())
    rows=manifest["cases"]
    if receipt["cases"]!=len(specifications(receipt["stage"])) or len(rows)!=receipt["cases"] or {r["slot"] for r in rows}!=set(range(len(rows))):
        raise ValueError("incomplete expected population")
    if manifest["stage"]!=receipt["stage"] or manifest["as_of"]!=AS_OF.isoformat():
        raise ValueError("manifest stage/date changed")
    registry=json.loads((release/"APPROVALS.json").read_text())
    if set(registry)!={r["case_id"] for r in rows}:
        raise ValueError("approval population changed")
    for row in rows:
        if row["case_id"]!=hashlib.sha256(f"{receipt['seed_commitment']}:{row['slot']}".encode()).hexdigest()[:24]:
            raise ValueError("case identity changed")
        for key in ("workbook","document"):
            if sha256(safe_path(release/"PUBLIC",row[key+"_path"]))!=row[key+"_sha256"]:
                raise ValueError("input hash changed")
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
            path=f"shards/{backend}_{mode}/{row['case_id']}.json"
            write_json(output/path,{"case_id":row["case_id"],"backend":backend,"mode":mode,"configuration":asdict(config),
                       "policy":policy,"workbook_sha256":row["workbook_sha256"],"document_sha256":row["document_sha256"],
                       "diagnosis":asdict(diagnosis),"diagnosis_seconds":elapsed,"ranking_seconds":ranking_seconds,
                       "ranking_plus_diagnosis_seconds":ranking_seconds+elapsed,
                       "certificate_bytes":len(json.dumps(asdict(diagnosis.search)).encode()),
                       "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
            hashes[path]=sha256(output/path)
    if model_binding(model)!=before:
        raise ValueError("workbook mutated")
    return hashes


def predict(release,output,lock=None,workers=4):
    receipt,rows,registry=context(release,lock)
    output.mkdir(parents=True,exist_ok=False)
    hashes,source_hashes={},sources()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index,chunk in enumerate(pool.map(compute,((str(release),str(output),r,registry[r["case_id"]]) for r in rows)),1):
            hashes.update(chunk)
            print(f"Predicted {index}/{len(rows)} workbooks",flush=True)
    if source_hashes!=sources():
        raise ValueError("prediction source changed")
    context(release,lock)
    write_json(output/"prediction_lock.json",{"sources":source_hashes,"environment":environment(),"labels_read":[],
               "release_receipt_sha256":sha256(release/"release_receipt.json"),"source_lock_sha256":receipt["source_lock_sha256"],
               "cases":len(rows),"shards":hashes,"completed_at":datetime.now(UTC).isoformat()})


def verify_case(task):
    release,predictions,row,approval=task
    release,predictions=Path(release),Path(predictions)
    model=load_model(json.loads(safe_path(release/"PUBLIC",row["workbook_path"]).read_text()))
    document=safe_path(release/"PUBLIC",row["document_path"]).read_bytes()
    records=[]
    for backend in BACKENDS:
        ranking=(v4_scores if backend=="v4" else v5_1_1_development_scores)(model)
        reference=baseline(model,ranking,backend=backend,documents=[document],approvals=approval,as_of=AS_OF,
                           config=BaselineParameters(max_nodes=1))
        baseline_actions=None
        for mode in MODES:
            shard=json.loads((predictions/f"shards/{backend}_{mode}/{row['case_id']}.json").read_text())
            config,policy=configuration(mode)
            if (shard["case_id"],shard["backend"],shard["mode"],shard["configuration"],shard["policy"])!=(row["case_id"],backend,mode,asdict(config),policy):
                raise ValueError("mode/configuration/policy changed")
            if any(shard[k+"_sha256"]!=row[k+"_sha256"] for k in ("workbook","document")):
                raise ValueError("shard input changed")
            diagnosis=decode(shard["diagnosis"])
            if diagnosis.backend!=backend or diagnosis.repair_policy!=policy:
                raise ValueError("diagnosis mode changed")
            check_identity(model,reference,diagnosis)
            audit=diagnosis.search
            if any(type(getattr(audit,k)) is not int or getattr(audit,k)<0 for k in (
                    "visited","evaluated","preparation_evaluations","space_size","pruned_states","solutions_seen")):
                raise ValueError("invalid search counter")
            if mode!="baseline" and json.loads(audit.configuration_json)!=asdict(config):
                raise ValueError("diagnosis configuration changed")
            if audit.visited>config.max_nodes or audit.evaluated>config.max_evaluations or audit.preparation_evaluations>config.max_preparations:
                raise ValueError("search budget violated")
            accepted=actions(diagnosis)
            if mode=="baseline":
                baseline_actions=accepted
            if audit.status=="unique_solution":
                args={"documents":[document],"approvals":approval,"as_of":AS_OF}
                if mode=="baseline":
                    verify_baseline(model,diagnosis,**args)
                else:
                    verify_unique_solution(model,diagnosis,config=config,localization=ranking,**args)
            elif accepted and (not (audit.status.startswith("constraint_rejected:") or audit.status=="no_approved_constraints") or accepted!=baseline_actions):
                raise ValueError("unverified nonunique acceptance")
            if policy!="structural" and accepted:
                raise ValueError("nonaccepting policy has actions")
            records.append({"case_id":row["case_id"],"backend":backend,"mode":mode,"status":audit.status,
                    "engine":audit.engine,"fallback_reason":audit.fallback_reason,"space_size":audit.space_size,
                    "visited":audit.visited,"evaluated":audit.evaluated,"preparation_evaluations":audit.preparation_evaluations,
                    "actual_evaluations":getattr(audit,"actual_evaluations",None),"pruned_states":audit.pruned_states,
                    "complete":audit.complete,"solutions_seen":audit.solutions_seen,"proof_replayed":audit.status=="unique_solution",
                    "actions":[[*c,f] for c,f in sorted(accepted.items())],"diagnosis_seconds":shard["diagnosis_seconds"],
                    "ranking_seconds":shard["ranking_seconds"],"certificate_bytes":shard["certificate_bytes"],
                    "process_peak_rss_kib":shard["process_peak_rss_kib"]})
    return records


def score(release,predictions,output,lock=None,workers=4):
    receipt,rows,registry=context(release,lock)
    prediction=json.loads((predictions/"prediction_lock.json").read_text())
    if prediction["sources"]!=sources() or prediction["environment"]!=environment() or prediction["labels_read"]!=[]:
        raise ValueError("prediction source/environment/label boundary changed")
    if prediction["release_receipt_sha256"]!=sha256(release/"release_receipt.json") or prediction["source_lock_sha256"]!=receipt["source_lock_sha256"]:
        raise ValueError("prediction release changed")
    expected={f"shards/{b}_{m}/{r['case_id']}.json" for b in BACKENDS for m in MODES for r in rows}
    actual={p.relative_to(predictions).as_posix() for p in (predictions/"shards").rglob("*") if p.is_file()}
    if prediction["cases"]!=len(rows) or set(prediction["shards"])!=expected or actual!=expected:
        raise ValueError("incomplete prediction population")
    if any(sha256(safe_path(predictions,n))!=h for n,h in prediction["shards"].items()):
        raise ValueError("prediction hash changed")
    records=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for index,chunk in enumerate(pool.map(verify_case,((str(release),str(predictions),r,registry[r["case_id"]]) for r in rows)),1):
            records.extend(chunk)
            print(f"Verified {index}/{len(rows)} workbooks before label scoring",flush=True)
    if prediction["sources"]!=sources():
        raise ValueError("verification source changed")
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/"reveal_authorization.json",{"authorized_at":datetime.now(UTC).isoformat(),
               "prediction_lock_sha256":sha256(predictions/"prediction_lock.json"),"all_inputs_rankings_proofs_verified":True})
    if sha256(release/"labels.json")!=receipt["labels_sha256"]:
        raise ValueError("label hash changed")
    labels=json.loads((release/"labels.json").read_text())
    if hashlib.sha256(labels["seed"].encode()).hexdigest()!=receipt["seed_commitment"]:
        raise ValueError("seed commitment changed")
    by_case={r["case_id"]:r for r in labels["cases"]}
    if len(by_case)!=len(rows) or len(labels["cases"])!=len(rows) or set(by_case)!={r["case_id"] for r in rows}:
        raise ValueError("label population changed")
    if any(by_case[r["case_id"]]["slot"]!=r["slot"] for r in rows):
        raise ValueError("label slot changed")
    summaries=defaultdict(lambda:{"workbooks":0,"required_cells":0,"correct_cells":0,"accepted_cells":0,
                                  "accepted_groups":0,"unsafe_groups":0,"statuses":Counter(),"paths":Counter()})
    for record in records:
        label=by_case[record["case_id"]]
        if (label["count"],label["family"],label["kind"])!=tuple(specifications(receipt["stage"])[label["slot"]][:3]):
            raise ValueError("label stratum changed")
        truth={(e["sheet"],e["cell"]):canonical_formula(e["expected_formula"]) for e in label["errors"]}
        accepted={(s,c):canonical_formula(f) for s,c,f in record["actions"]}
        correct=sum(truth.get(c)==f for c,f in accepted.items())
        unsafe=bool(accepted) and (correct!=len(accepted) or label["decision"] in {"abstain","no_action"})
        record.update(kind=label["kind"],family=label["family"],count=label["count"],required_cells=len(truth),
                      correct_cells=correct,unsafe_group=unsafe,cluster_id=label["cluster_id"])
        summary=summaries[record["backend"]+"_"+record["mode"]]
        summary["workbooks"]+=1
        summary["required_cells"]+=len(truth)
        summary["correct_cells"]+=correct
        summary["accepted_cells"]+=len(accepted)
        summary["accepted_groups"]+=bool(accepted)
        summary["unsafe_groups"]+=unsafe
        summary["statuses"][record["status"]]+=1
        summary["paths"][record["engine"]+":"+record["fallback_reason"]]+=1
    for summary in summaries.values():
        summary["coverage"]=summary["correct_cells"]/summary["required_cells"] if summary["required_cells"] else 0.0
    safe=all(s["unsafe_groups"]==0 for s in summaries.values())
    improved=all(summaries[b+"_main"]["coverage"]>summaries[b+"_baseline"]["coverage"] for b in BACKENDS)
    write_json(output/"result.json",{"stage":receipt["stage"],"workbooks":len(rows),"diagnoses":len(records),
               "gate_passed":safe and improved,"safe":safe,"coverage_improved":improved,"summaries":dict(summaries),
               "ranking_changes":0,"candidate_changes":0,"records":records,"completed_at":datetime.now(UTC).isoformat(),
               "scope":"known-generator synthetic evidence; not independent third-party blind testing"})
    if not safe or (receipt["stage"]!="test" and not improved):
        raise ValueError("G5 scoring gate failed; complete results retained")


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("command",choices=("freeze","build","predict","score"))
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--release",type=Path)
    parser.add_argument("--predictions",type=Path)
    parser.add_argument("--lock",type=Path)
    parser.add_argument("--stage",choices=("test","development","confirmation"),default="development")
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
