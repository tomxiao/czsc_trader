"""Read-only implementation, reuse, and behavioral-equivalence checks for EX056."""
from pathlib import Path
from hashlib import sha256
import json
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity
from strategy_runtime.equity_definition import equity_source_hash

ROOT=Path.cwd(); WORK=ROOT/'research/S018/experiments/EX056_20261104'
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
protocol=read(WORK/'others/protocol.json'); result=read(WORK/'others/results.json'); accounts=result['accounts']
previous=ROOT/'research/S018/experiments/EX055_20261104'
prior=read(previous/'others/results.json')['accounts']
assert (WORK/'src/strategy.py').read_bytes()==(previous/'src/strategy.py').read_bytes()
source_hash=equity_source_hash(WORK/'src',('strategy.py',))
assert source_hash==protocol['source_sha256']==read(previous/'others/protocol.json')['source_sha256']
assert len(accounts)==34 and len(protocol['reused_configurations'])==6
reuse=[]
for entry in protocol['reused_configurations']:
    assert entry['experiment']=='EX055_20261104'
    row=prior[entry['candidate']]
    assert entry['config']==row['config']
    assert row['definition']['source_sha256']==source_hash
    ref=d.EvidenceRef.from_dict(row['account_ref']); content=ref.resolve(ROOT).read_bytes()
    assert sha256(content).hexdigest()==ref.sha256
    reuse.append(dict(candidate=entry['candidate'],configuration_exact=True,source_exact=True,account_ref_verified=True,metrics_present=bool(row['candidate'])))
for cid,row in accounts.items():
    assert row['definition']['source_sha256']==source_hash
    m,b=row['candidate'],result['benchmark']
    gates=dict(calmar=m['calmar']>=1.5*b['calmar'],dd_absolute=m['dd']<=.25,dd_relative=m['dd']<=.8*b['dd'],median=m['median']>=6,coverage=m['coverage']>=.9)
    assert row['gates']==gates and all(gates.values())
def load(row):
    ref=d.EvidenceRef.from_dict(row['account_ref']); path=ref.resolve(ROOT)
    content=path.read_bytes(); assert sha256(content).hexdigest()==ref.sha256
    def artifact(v):
        raw=(path.parent/(v['sha256']+'.json')).read_bytes()
        assert sha256(raw).hexdigest()==v['sha256']
        return raw
    return materialize_equity(content,artifact).payload['runs']['candidate']
pairs=[]
for cid,row in accounts.items():
    p=row['config']
    if p['add_mode']!='repair' or p['earliest_add']<3: continue
    other=dict(p,add_mode='scheduled')
    match=[(k,v) for k,v in accounts.items() if v['config']==other]
    assert len(match)==1
    target,right=match[0]
    assert row['candidate']==right['candidate']
    left_run,right_run=load(row),load(right)
    for field in ('fills','account_daily','trades','actions'):
        economic=lambda rows:[{k:v for k,v in x.items() if not k.endswith('_id')} for x in rows]
        assert economic(left_run[field])==economic(right_run[field]),(cid,target,field)
    pairs.append(dict(mu_repair=cid,scheduled=target,metrics_exact=True,economic_fields_exact=['fills','account_daily','trades','actions']))
assert len(pairs)==6
out=dict(status='PASS',source_bytes_sha256=sha256((WORK/'src/strategy.py').read_bytes()).hexdigest(),source_identity=source_hash,
    configurations=34,passed_original_gates=34,reused= reuse,equivalent_pairs=pairs,
    interpretation='At held>=3, existing exit rule already requires MU price>anchor to remain held; MU-only repair is therefore redundant with scheduled adds. This is not independent confirmation information.',
    scope='Read-only published evidence and source checks; no account re-evaluation.')
(WORK/'others/analysis_reuse.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
