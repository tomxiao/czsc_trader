"""Root bindings for the technical existing-request repair; no evaluation."""
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.tmp/s013-price-event-binding-r2'
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
def digest(path):
    return sha256(path.read_bytes()).hexdigest()
phase = sys.argv[1]
assert phase in {'declare','prepare','execute','verify'}
freeze = read(WORK / 'centre_source_freeze.json')
for path, expected in freeze['files'].items():
    assert digest(ROOT / path) == expected, path
assert read(WORK / 'proof.json')['status'] == 'PASS'
assert digest(ROOT / '.tmp/s013-price-event-policy/policy.py') == '1fba931ae8c0a8322594d8fa684c7dc092a70796eb43659df0262b2be92b5a6b'
assert digest(ROOT / '.tmp/s013-mechanism-EX058/N0.pkl.gz') == 'ceded25c20adb4e698ec4dfecd677d26db62c342f339d83be3c0b592a451d26c'
authority = {'phase':phase,'candidate_id':'C9078','source_freeze_sha256':digest(WORK / 'centre_source_freeze.json'),'account_budget':1 if phase=='execute' else 0,'basis':'Approved original single-centre research; repair only exact existing request identities, not policy or economic goals'}
if phase != 'declare':
    path = ROOT / 'research/S013/experiments/EX077_20261012/technical_binding/protocols'
    authority['plan_reference'] = read(path / 'plan_reference.json')
    if phase == 'execute':
        authority['prepare_reference'] = read(path / 'prepare_reference.json')
        assert read(WORK / 'centre_prepare.json')['status'] == 'PASS'
    if phase == 'verify':
        authority['centre_reference'] = read(path / 'centre_reference.json')
        assert read(WORK / 'centre_execution.json')['new_accounts'] == 1
target = WORK / ('root_'+phase+'_authority.json')
with target.open('x',encoding='utf-8') as stream:
    stream.write(json.dumps(authority,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
print(json.dumps({'status':'ROOT_AUTHORIZED','phase':phase,'path':target.relative_to(ROOT).as_posix(),'sha256':digest(target),'account_budget':authority['account_budget']},ensure_ascii=False))
