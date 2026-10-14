"""Frozen paper adapter. Prediction entry never opens truth JSON; original package is unedited."""
from pathlib import Path
import sys,json,gzip,time,math,hashlib,resource,dataclasses,concurrent.futures,argparse
R=Path(__file__).resolve().parents[1];S=R/'source/HybridGuard_V5_handoff_20260904'
sys.path.insert(0,str(S/'src'))
from formulaguard.workbook import WorkbookModel
from formulaguard.v5_structural_guard import v5_structural_guard_scores
from structuralguard.detector import analyze_workbook
from hybridguard.hybrid import build_parallel_group_evidence,fuse_hierarchical
import hybridguard.representative as rp
from hybridguard.representative import GroupValidation
CONFIGS={
 'full':{},'no_sg':{'no_sg':True},'no_fg':{'no_fg':True},'no_groups':{'no_groups':True},'no_validation':{'no_validation':True},
 'support4':{'support':4},'support5':{'support':5},'weight050':{'weight':.5},'weight080':{'weight':.8},'reps1':{'reps':1},'reps5':{'reps':5}}
DEFAULTS={'support':3,'weight':.65,'reps':3}
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
 p.parent.mkdir(parents=True,exist_ok=True)
 if p.suffix=='.gz':
  with gzip.GzipFile(filename=str(p),mode='wb',mtime=0) as f:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
 else:p.write_text(json.dumps(x,ensure_ascii=False,indent=2))
def deny_truth(event,args):
 if event=='open' and isinstance(args[0],(str,bytes)):
  p=str(args[0])
  if p.endswith('truth.json') or '_truth.json' in p:raise PermissionError('Prediction cannot open truth: '+p)
def features(case):
 model=WorkbookModel.from_xlsx(R/'data'/case/'input.xlsx')
 s=analyze_workbook(R/'data'/case/'input.xlsx')['results']
 f=[{'rank':i,'cell':v.cell_label,'score':v.score,'candidate_formula':v.candidate_formula,'evidence':v.evidence} for i,v in enumerate(v5_structural_guard_scores(model),1)]
 forms={s+'!'+a:v for (s,a),v in model.formulas.items()}
 public=json.loads((R/'data'/case/'public.json').read_text())
 return model,s,f,forms,public['parallel_sheets']
def hybrid(feat,config):
 model,s,f,forms,sheets=feat;c=DEFAULTS|config
 if c.get('no_groups'):bc,groups={},[]
 else:bc,groups=build_parallel_group_evidence(forms,sheets,minimum_consensus=c['support'])
 if c['weight']!=.65:
  def change(g):return dataclasses.replace(g,group_score=min(1.,c['weight']*g.consensus_ratio+(1-c['weight'])*min(1.,math.log1p(g.size)/math.log1p(300))))
  groups=[change(g) for g in groups];bc={k:change(g) for k,g in bc.items()}
 if c.get('no_validation'):
  reps=[];valid={g.group_id:GroupValidation(g.group_id,0,0,True,1.) for g in groups}
 else:
  old=rp.representative_rows
  if c['reps']!=3:
   n=c['reps']
   rp.representative_rows=lambda g: ([(g.start_row+g.end_row)//2] if n==1 else sorted({g.start_row+(g.end_row-g.start_row)*i//(n-1) for i in range(n)}))
  try:reps,valid=rp.validate_group_representatives(model,groups,bc)
  finally:rp.representative_rows=old
 rows=fuse_hierarchical([] if c.get('no_sg') else s,[] if c.get('no_fg') else f,forms,bc,valid)
 return {'rows':rows,'groups':[dataclasses.asdict(g) for g in groups],'validations':[dataclasses.asdict(v) for v in valid.values()],'representatives':[dataclasses.asdict(v) for v in reps]}
def run_case(entry):
 sys.addaudithook(deny_truth)
 case=entry['id'];out=R/'predictions'/case;done=out/'complete.json'
 if done.exists():return case+' cached'
 start=time.perf_counter();feat=features(case);feature_seconds=time.perf_counter()-start
 write(out/'input_formulas.json.gz',feat[3])
 sg=[dict(x,cell=x['sheet']+'!'+x['cell']) for x in feat[1]]
 write(out/'sg.json.gz',{'rows':sg});write(out/'fg.json.gz',{'rows':feat[2]})
 names=list(CONFIGS) if entry['original'] else list(CONFIGS)[:5]
 for name in names:write(out/(name+'.json.gz'),hybrid(feat,CONFIGS[name]))
 write(done,{'id':case,'configs':names,'input_sha256':sha(R/'data'/case/'input.xlsx'),'public_sha256':sha(R/'data'/case/'public.json'),'feature_seconds':feature_seconds,'total_seconds':time.perf_counter()-start,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024})
 return case+' complete'
def main():
 a=argparse.ArgumentParser();a.add_argument('--workers',type=int,default=4);a.add_argument('--benchmark');args=a.parse_args()
 if args.benchmark:
  sys.addaudithook(deny_truth);t=time.perf_counter();feat=features(args.benchmark);pred=hybrid(feat,{})
  content=json.dumps(pred,sort_keys=True,separators=(',',':')).encode()
  print(json.dumps({'case':args.benchmark,'wall_seconds':time.perf_counter()-t,'peak_rss_mib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'prediction_sha256':hashlib.sha256(content).hexdigest()}));return
 entries=json.loads((R/'protocol/public_index.json').read_text())
 with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers,max_tasks_per_child=1) as ex:
  for v in ex.map(run_case,entries):print(v,flush=True)
 files=sorted((R/'predictions').rglob('*.gz'));complete=list((R/'predictions').glob('*/complete.json'))
 assert len(complete)==39 and len(files)==348,(len(complete),len(files)) # 39*(input+SG+FG+5) + 6*6
 write(R/'protocol/prediction_lock.json',{'completed_utc':__import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(),'files':{str(p.relative_to(R)):sha(p) for p in files},'source_lock_sha256':sha(R/'protocol/source_lock.json')})
 print('PREDICTION LOCK COMPLETE',len(files),flush=True)
if __name__=='__main__':main()
