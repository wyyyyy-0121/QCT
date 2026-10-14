from pathlib import Path
import json,gzip,csv,hashlib,statistics,unittest
R=Path(__file__).resolve().parents[1]
def read(p):
 if p.suffix=='.gz':
  with gzip.open(p,'rt') as f:return json.load(f)
 return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2))
def evaluate(pred,observed,truth):
 expected=truth['expected_formulas'];errors=set(truth['errors']);rows=pred['rows'];ranked=[x['cell'] for x in rows]
 assert len(ranked)==len(set(ranked))==len(expected) and set(ranked)==set(expected)
 hits=0;ap=0.
 for i,k in enumerate(ranked,1):
  if k in errors:hits+=1;ap+=hits/i
 proposals={x['cell']:(x.get('suggested_formula') or x.get('candidate_formula')) for x in rows}
 proposals={k:v for k,v in proposals.items() if v and v!=observed[k]}
 exact={k for k,v in proposals.items() if v==expected[k]};damage={k for k,v in proposals.items() if k not in errors and v!=expected[k]}
 accepted={g['group_id'] for g in pred.get('validations',[]) if g['accepted']}
 unsafe=set()
 for row in rows:
  if row.get('group_id') in accepted and row.get('suggested_formula')!=expected[row['cell']]:unsafe.add(row['group_id'])
 result={'formulas':len(expected),'errors':len(errors),'ap':ap/len(errors) if errors else None,'proposals':len(proposals),'exact_repairs':len(exact),'repair_coverage':len(exact)/len(errors) if errors else None,'proposal_precision':len(exact)/len(proposals) if proposals else None,'harmful_correct_cells':len(damage),'harmful_rate':len(damage)/(len(expected)-len(errors)) if len(expected)>len(errors) else None,'wrong_proposals':len(proposals)-len(exact),'groups_detected':len(pred.get('groups',[])),'groups_accepted':len(accepted),'unsafe_groups':len(unsafe),'representatives':len(pred.get('representatives',[]))}
 for k in [5,10,50,100,len(errors)]:result['recall_'+('matched' if k==len(errors) else str(k))]=sum(x in errors for x in ranked[:k])/len(errors) if errors else None
 for k in [5,10,50,100]:result.setdefault('recall_'+str(k),sum(x in errors for x in ranked[:k])/len(errors) if errors else None)
 return result
class MetricTests(unittest.TestCase):
 def test_precision_includes_correct_cell_damage(self):
  x=evaluate({'rows':[{'cell':'S!A1','suggested_formula':'=1'},{'cell':'S!A2','suggested_formula':'=7'}]}, {'S!A1':'=0','S!A2':'=2'}, {'errors':{'S!A1':'=1'},'expected_formulas':{'S!A1':'=1','S!A2':'=2'}})
  self.assertEqual(x['ap'],1);self.assertEqual(x['repair_coverage'],1);self.assertEqual(x['proposal_precision'],.5);self.assertEqual(x['harmful_rate'],1)
 def test_clean_ap_undefined(self):
  x=evaluate({'rows':[{'cell':'S!A1'}]}, {'S!A1':'=1'},{'errors':{},'expected_formulas':{'S!A1':'=1'}});self.assertIsNone(x['ap']);self.assertIsNone(x['proposal_precision'])
def main():
 lock=read(R/'protocol/prediction_lock.json')
 for fn,h in lock['files'].items():assert sha(R/fn)==h,fn
 source=read(R/'protocol/source_lock.json')
 for fn,h in source['files'].items():assert sha(R/fn)==h,fn
 manifest=read(R/'protocol/data_manifest.json');allrows=[];agreement=[]
 for case in manifest:
  out=R/'predictions'/case['id'];truth=read(R/'data'/case['id']/'truth.json');observed=read(out/'input_formulas.json.gz')
  assert sum(observed[k]!=v for k,v in truth['expected_formulas'].items())==case['errors']
  names=['sg','fg']+read(out/'complete.json')['configs']
  for name in names:
   pred=read(out/(name+'.json.gz'));allrows.append({'case':case['id'],'family':case['family'],'source_seed':case['source_seed'],'original':case['original'],'model':name}|evaluate(pred,observed,truth))
  if case['original']:
   old=R/'source/HybridGuard_V5_handoff_20260904/results'/case['id']/'hierarchical_ranking.csv'
   with old.open(encoding='utf-8-sig',newline='') as f:oldrows=list(csv.DictReader(f))
   new=read(out/'full.json.gz')['rows'];assert len(oldrows)==len(new)
   mismatches=[]
   for a,b in zip(oldrows,new):
    equal=(a['cell']==b['cell'] and int(a['rank'])==b['rank'] and abs(float(a['hybrid_score'])-b['hybrid_score'])<1e-12 and (a['suggested_formula'] or None)==b['suggested_formula'])
    if not equal:mismatches.append({'old':a,'new':b})
   agreement.append({'case':case['id'],'rows':len(new),'mismatches':len(mismatches),'first':mismatches[:1]})
 assert len(allrows)==309
 save(R/'results/per_case.json',allrows)
 keys=list(dict.fromkeys(k for x in allrows for k in x))
 with (R/'results/per_case.csv').open('w',newline='',encoding='utf-8-sig') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(allrows)
 grouped=[]
 for family in sorted(set(x['family'] for x in allrows)):
  for model in sorted(set(x['model'] for x in allrows if x['family']==family)):
   rows=[x for x in allrows if x['family']==family and x['model']==model];g={'family':family,'model':model,'n':len(rows)}
   for k in ['ap','repair_coverage','proposal_precision','harmful_rate','recall_5','recall_10','recall_50','recall_100','recall_matched']:
    v=[x[k] for x in rows if x.get(k) is not None];g['mean_'+k]=statistics.mean(v) if v else None
   for k in ['errors','proposals','exact_repairs','harmful_correct_cells','wrong_proposals','groups_accepted','unsafe_groups','representatives']:g['total_'+k]=sum(x[k] for x in rows)
   grouped.append(g)
 save(R/'results/summary.json',grouped);save(R/'qa/original_agreement.json',agreement)
 print('LOCKS VERIFIED; scored',len(allrows),'method/input pairs; original mismatches:',sum(x['mismatches'] for x in agreement))
 for x in grouped:
  if x['model']=='full':print(x)
if __name__=='__main__':main()
