"""Read-only replay of all 83 dev5 outputs from immutable upstream predictions."""
from pathlib import Path
import hashlib
import json
import sys
import time

from run_selector_dev5 import ROOT, BASE, RUN, read, save, sha, verify_run
from selector_dev5 import augment
from formulaguard.workbook import WorkbookModel


def replay():
    verify_run()
    accesses = set()
    def guard(event,args):
        if event=='open' and isinstance(args[0],(str,bytes)):
            name = str(args[0])
            if any(x in name.casefold() for x in ['truth.json','registration.json','data_manifest.json',
                                                 '/score','/results/','failure_audit','mutation_log','input_oracle']):
                raise PermissionError('Replay cannot access labels: '+name)
            if str(ROOT) in name: accesses.add(name)
    sys.addaudithook(guard)
    start = time.perf_counter(); cases = []
    for entry in read(RUN / 'public_index.json'):
        model = WorkbookModel.from_xlsx(ROOT / entry['input'])
        prior = read(ROOT / entry['upstream'])
        if entry['group']=='crossdomain': prior=prior['dev4']
        result = augment(model,prior,entry['parallel_sheets'])
        expected = read(RUN / 'predictions' / entry['group'] / (entry['id']+'.json.gz'))
        assert result == expected,(entry['group'],entry['id'])
        cases.append({'id':entry['id'],'group':entry['group'], 'exact_json_equal':True,
            'prediction_content_sha256':hashlib.sha256(json.dumps(result,sort_keys=True).encode()).hexdigest()})
    save(ROOT / 'qa/DEV5_REPLAY_20261015.json',{'cases':cases,'wall_seconds':time.perf_counter()-start,
        'command':[sys.executable,*sys.argv],'prediction_lock_sha256':sha(RUN / 'prediction_lock.json'),
        'labels_read':[],'accesses':sorted(accesses),'source_lock_verified':True})
    print('Replayed',len(cases),'cases: exact prediction JSON equality; no labels accessed')


if __name__=='__main__':
    replay()
