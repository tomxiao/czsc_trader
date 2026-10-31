"""Descriptive state buckets of one already-certified account; no alternative replay."""
import sys,json,math
from pathlib import Path
from hashlib import sha256
from collections import defaultdict
sys.path.insert(0,str(Path.cwd()/'research/S017/experiments/EX043_20261031/src'))
from common import ROOT,WORK,read,authenticate
from czsc_trader.research_tools.equity_replay import materialize_equity
record=read(WORK/'others/accounts.json')['C0086'];path=authenticate(record['evidence']);env=read(path);allowed={(env[k]['kind'],env[k]['sha256']) for k in ('input_ref','candidate_ref','benchmark_ref')}
def resolve(r):
 assert (r['kind'],r['sha256']) in allowed
 p=path.parent/(r['sha256']+'.json');b=p.read_bytes();assert sha256(b).hexdigest()==r['sha256'];return b
run=materialize_equity(path.read_bytes(),resolve).payload['runs']['candidate'];analysis=read(WORK/'others/analysis.json')['summaries']['C0086']['candidate'];peak=analysis['max_drawdown_path']['peak'];trough=analysis['max_drawdown_path']['trough'];groups=defaultdict(lambda:{'bars':0,'equity_change':0.,'max_dd_interval_equity_change':0.,'positive_intervals':0,'sum_interval_return':0.,'years':{}});previous=100000.
for d,p in zip(run['decisions'],run['account_points'],strict=True):
 assert d['execution_end']==p['time'];f={r['key']:r['text'] for r in d['explanation']['basis']}
 if f['held']!='True':bucket='ENTRY_OR_FLAT'
 elif f['exit_due']=='True':bucket='EXIT_LOCKED'
 elif f.get('trend_active')!='True':bucket='M005_BEFORE26'
 elif f['trend_ready']=='True':bucket='SUSTAINED_U'
 else:
  assert f['trend_failed']=='False';bucket='NEUTRAL_HOLD'
 g=groups[bucket];delta=p['equity']-previous;g['bars']+=1;g['equity_change']+=delta;g['sum_interval_return']+=p['equity']/previous-1;g['positive_intervals']+=delta>0
 if (peak is None or p['time']>peak) and p['time']<=trough:g['max_dd_interval_equity_change']+=delta
 year=p['session'][:4];y=g['years'].setdefault(year,{'bars':0,'equity_change':0.});y['bars']+=1;y['equity_change']+=delta;previous=p['equity']
assert math.isclose(sum(g['equity_change'] for g in groups.values()),previous-100000.,abs_tol=1e-7)
result={'schema':'s017-certified-account-state-diagnostic/v1','status':'PASS','source_account':record['evidence'],'analysis_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),'max_drawdown_path':analysis['max_drawdown_path'],'groups':dict(groups),'reconciled_total_equity_change':previous-100000.,'limitations':'Descriptive regrouping of the original fixed position path by decision-visible state. Dollar changes are not independent strategy returns or a causal promise for removing neutral exposure. Reentry, capital and future membership would change. No new account, SE, future test or parameter search.'}
(WORK/'others/neutral_state_diagnostic.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode());print(json.dumps(result,ensure_ascii=False))
