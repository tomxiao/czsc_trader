"""Pure-data proposed-ID/reservation tests plus current EX045 manifest check."""
import json
import runpy
from hashlib import sha256
from pathlib import Path

root = Path.cwd()
tmp = root/'.tmp/s019-stage2-resume'
api = runpy.run_path(str(tmp/'batch_runner_reversible.py'), run_name='id_probe')
scan = api['candidate_ids_in_record']
assert scan(json.dumps({'proposed_candidate_id':'C0779','candidate_id':'C0684'})) == {'C0779','C0684'}
reserved = [f'C{i:04}' for i in range(684,780)]
assert scan(json.dumps({'reserved_proposed_candidate_ids':reserved,'candidate_id':'C0684'})) == set(reserved)
manifest = json.loads((root/'research/S019/experiments/EX045_20261111/protocols/run_manifest.json').read_bytes())
assert manifest['reserved_proposed_candidate_ids'] == reserved
assert max(int(cid[1:]) for cid in scan(json.dumps(manifest)))+1 == 780
old = root/'research/S019/experiments/EX043_20261110'
assert sha256((old/'src/batch_runner.py').read_bytes()).hexdigest() == json.loads((old/'protocols/run_manifest.json').read_bytes())['runner_sha256']
result = {'status':'PASS','tests':{'tail_alias':'PASS','reserved_unasked_tail':'PASS'},
    'actual_ex045_reserved_first':reserved[0],'actual_ex045_reserved_last':reserved[-1],
    'next_candidate_start':780,'source_ex043_unchanged':True,
    'runner_sha256':sha256((tmp/'batch_runner_reversible.py').read_bytes()).hexdigest()}
(tmp/'reversible_id_probe.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('REVERSIBLE_ID_PROBE_PASS',780)
