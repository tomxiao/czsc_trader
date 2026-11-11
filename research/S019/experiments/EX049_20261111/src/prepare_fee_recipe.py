"""Fix representative paired-fee diagnostics after the completed interaction round."""
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path.cwd()
BATCH = ROOT/'research/S019'
OUT = ROOT/'.tmp/s019-stage3-20261111/fee_recipe.json'

def read(path):
    return json.loads(path.read_bytes())

previous = BATCH/'experiments/EX048_20261111'
assert read(previous/'others/results.json')['status'] == 'COMPLETE'
assert read(previous/'others/publication.json')['validation']['status'] == 'PASS'
assert read(previous/'others/budget_settlement.json')['used_after'] == 2
orig = BATCH/'experiments/EX046_20261111'
search = BATCH/'experiments/EX047_20261111'
sources = []
for label,row in read(orig/'others/results.json')['accounts'].items():
    sources.append((row['candidate_id'],orig/f'others/{label}_account.json',row['definition']))
for row in read(search/'others/summary.json').values():
    sources.append((row['id'],search/f"others/trials/{row['name']}_account.json",row['definition']))
for label,row in read(previous/'others/results.json')['accounts'].items():
    if row['role'] != 'REUSED_EVIDENCE':
        sources.append((row['candidate_id'],previous/f'others/{label}_account.json',row['definition']))
by_id = {cid:(path,definition) for cid,path,definition in sources}
ids = ('C0798','C0801','C0804','C0966','C1010','C1045','C0909')
pairs = []
for cid in ids:
    path,definition = by_id[cid]
    assert path.is_file()
    ref = read(path)
    assert ref['experiment']['strategy_id'] == 'S019'
    source = BATCH/'experiments'/ref['experiment']['experiment_id']/'src'
    assert (source/'strategy.py').read_bytes() == (orig/'src/strategy.py').read_bytes()
    pairs.append({'label':cid,'candidate_id':cid,'standard_account':path.relative_to(ROOT).as_posix(),
                  'source_root':source.relative_to(ROOT).as_posix()})
value = {'standard_fee_rate':.001,'pressure_fee_rate':.002,
    'round_budget':{'allocated_rounds':10,'round_index':3,'total_round':3,'remaining_after_completion':7},
    'pairs':pairs}
assert not OUT.exists()
OUT.write_bytes((json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())
print('FEE_RECIPE_READY',len(pairs),sha256(OUT.read_bytes()).hexdigest())
