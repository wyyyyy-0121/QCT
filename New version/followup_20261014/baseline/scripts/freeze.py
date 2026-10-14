from pathlib import Path
import json,hashlib,datetime
R=Path(__file__).resolve().parents[1]
if (R/'protocol/prediction_lock.json').exists():raise SystemExit('Archive existing prediction/source locks and outputs before starting a new run.')
m=json.loads((R/'protocol/data_manifest.json').read_text());(R/'protocol/public_index.json').write_text(json.dumps([{'id':x['id'],'original':x['original']} for x in m]))
files=list((R/'source').rglob('*.py'))+[R/'scripts/prepare.py',R/'scripts/predict.py']+[R/'protocol/PROTOCOL.md',R/'protocol/data_manifest.json',R/'protocol/public_index.json']+list((R/'data').rglob('*.*'))
(R/'protocol/source_lock.json').write_text(json.dumps({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':{str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}},indent=2))
print('Locked',len(files),'files')
