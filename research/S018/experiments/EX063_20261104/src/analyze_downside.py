from pathlib import Path
from hashlib import sha256
import json
import sys
import numpy as np
from czsc_trader import research_tools as d
from czsc_trader.research_tools.equity_replay import materialize_equity

ROOT=Path.cwd()
def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))
def load(row):
    ref=d.EvidenceRef.from_dict(row['account_ref']); path=ref.resolve(ROOT)
    raw=path.read_bytes(); assert sha256(raw).hexdigest()==ref.sha256
    def dependency(x):
        value=(path.parent/(x['sha256']+'.json')).read_bytes()
        assert sha256(value).hexdigest()==x['sha256']
        return value
    return materialize_equity(raw,dependency).payload['runs']['candidate']

number=int(sys.argv[1]); work=ROOT/f'research/S018/experiments/EX{number:03d}_20261104'
accounts=read(work/'others/results.json')['accounts']
base_row=read(ROOT/'research/S018/experiments/EX052_20261104/others/results.json')['accounts']['C8214']
baseline=load(base_row)
dates=[r['session'] for r in baseline['account_daily']]
equity=np.array([100000.]+[r['equity'] for r in baseline['account_daily']])
episodes=[]; peak=0; trough=0
for i in range(1,len(equity)):
    if equity[i]>=equity[peak]:
        if trough>peak:
            episodes.append((peak,trough,float(equity[trough]/equity[peak]-1)))
        peak=trough=i
    elif equity[i]<equity[trough]:
        trough=i
if trough>peak:
    episodes.append((peak,trough,float(equity[trough]/equity[peak]-1)))
episodes=sorted(episodes,key=lambda x:x[2])[:6]
def describe(run):
    daily=run['account_daily']; values=np.array([100000.]+[r['equity'] for r in daily])
    assert [r['session'] for r in daily]==dates
    result={}
    for n in (5,10,20):
        returns=values[n:]/values[:-n]-1
        cut=np.quantile(returns,.05)
        result[f'rolling_{n}_worst']=float(returns.min())
        result[f'rolling_{n}_bottom5_mean']=float(returns[returns<=cut].mean())
    result['baseline_drawdown_windows']=[dict(peak=dates[i-1] if i else 'INITIAL',trough=dates[j-1],
        baseline_return=loss,return_in_window=float(values[j]/values[i]-1)) for i,j,loss in episodes]
    fills={}; orders={r['order_id']:r for r in run['orders']}
    for r in run['fills']:
        fills.setdefault(r['cycle_id'],[]).append(r)
    details=[]
    for t in run['trades']:
        if t['status']!='CLOSED':continue
        buys=[f for f in fills[t['cycle_id']] if f['side']=='BUY']
        entry=buys[0]['interval_start'][:10]
        idx=dates.index(entry)
        details.append(dict(entry=entry,exit=t['exit_at'][:10],net_return=t['net_return'],net_pnl=t['net_pnl'],
            portfolio_contribution=t['net_pnl']/values[idx],buy_fills=len(buys),
            buy_dates=[b['interval_start'][:10] for b in buys],
            buy_costs=[b['price']*b['quantity']+b['fees'] for b in buys]))
    result['worst_portfolio_cycles']=sorted(details,key=lambda x:x['portfolio_contribution'])[:10]
    result['october_cycles']=[x for x in details if '2026-10-01'<=x['entry']<='2026-10-15']
    result['added_cycles']=sum(x['buy_fills']>1 for x in details)
    result['timing']=[(x['entry'],x['exit']) for x in details]
    return result
base=describe(baseline)
out={'baseline':'C8214','scope':'Post hoc path diagnostics only; no future labels enter signals and no extra hard gates.',
    'window_selection':'Six largest historical C8214 peak-to-trough drawdown episodes, fixed for all comparisons; selected ex post, not a prediction.',
    'rolling_limit':'Overlapping full 5/10/20-session equity returns; bottom5 means are descriptive and not independent samples.',
    'baseline_diagnostics':base,'accounts':{}}
for cid,row in accounts.items():
    run=load(row); diag=describe(run)
    diag['same_cycle_timing_as_C8214']=diag.pop('timing')==base['timing']
    out['accounts'][cid]={'config':row['config'],'metrics':row['candidate'],'gates':row['gates'],'diagnostics':diag}
    if row['candidate']==base_row['candidate']:
        economic=lambda rows:[{k:v for k,v in r.items() if not k.endswith('_id')} for r in rows]
        assert all(economic(run[key])==economic(baseline[key]) for key in ['fills','account_daily','trades','actions'])
        out['accounts'][cid]['economic_baseline_exact']=True
base.pop('timing')
(work/'others/analysis_downside.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('DIAGNOSTICS',number,len(accounts),'PASS')
for cid,row in sorted(out['accounts'].items(),key=lambda kv:kv[1]['metrics']['calmar'],reverse=True)[:12]:
    m=row['metrics']; dg=row['diagnostics']
    print(cid,'D',round(m['calmar'],4),'DD',round(m['dd'],4),'OCT',round(m['october_return'],4),
          'WORST10',round(dg['rolling_10_worst'],4),'TAIL10',round(dg['rolling_10_bottom5_mean'],4),'ADDED',dg['added_cycles'])
