"""Seal local source/proof, never publish or read native results."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
proof = json.loads((HERE/'focused.json').read_text('utf-8'))
assert proof['status']=='PURE_PASS' and proof['capability_calls']==[]
assert sha256((HERE/'postprocess.py').read_bytes()).hexdigest()==proof['source_sha256']
target = HERE/'freeze.json'
if target.exists():
    raise ValueError('Frozen source cannot be overwritten')
files = sorted(p for p in HERE.iterdir() if p.suffix in ('.py','.json') and p.name!='freeze.json')
manifest = {'status':'SOURCE_ONLY_READY','frozen_files':{p.name:sha256(p.read_bytes()).hexdigest() for p in files},
    'actual_native_accounts_read':0,'new_account_preparations':0,'new_account_evaluations':0,
    'publications_registrations_assemblies':0,'check_count':proof['check_count'],
    'ruff':'PASS','help':'PASS','execution_runner_unchanged':True,
    'root_future_scope':'Only finish EX065 CandidateSet57/FULL then honor user pause; no new mechanism/experiment.'}
target.write_text(json.dumps(manifest,indent=2,allow_nan=False)+'\n','utf-8')
print(json.dumps({'status':manifest['status'],'source_sha256':proof['source_sha256'],
    'proof_sha256':sha256((HERE/'focused.json').read_bytes()).hexdigest(),
    'freeze_sha256':sha256(target.read_bytes()).hexdigest()}))
