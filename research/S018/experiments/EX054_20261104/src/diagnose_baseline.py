from pathlib import Path
import importlib.util
import json
import numpy as np

ROOT=Path.cwd()
spec=importlib.util.spec_from_file_location('account_reader',ROOT/'research/S018/experiments/EX047_20261104/src/analyze_exits.py')
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
record,run,trades=mod.load('EX052_20261104','C8214')
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
hfq={s:read(ROOT/f'research/S018/experiments/EX044_20261104/others/analysis_{s}_hfq.json') for s in ('MU','SOXX')}
dates=[x['time_key'][:10] for x in hfq['MU']]
assert dates==[x['time_key'][:10] for x in hfq['SOXX']]
idx={d:i for i,d in enumerate(dates)}
prices={s:np.array([x['close'] for x in bars]) for s,bars in hfq.items()}
decisions={x['decision_id']:x for x in run['decisions']}
orders={x['order_id']:x for x in run['orders']}
daily={x['session']:x for x in run['account_daily']}
rows=[]
prior=None
for t in sorted(trades.values(),key=lambda x:x['entry_at']):
    buy=next(x for x in run['fills'] if x['cycle_id']==t['cycle_id'] and x['side']=='BUY')
    decision=decisions[orders[buy['order_id']]['decision_id']]
    facts={x['key']:x['text'] for x in decision['explanation']['basis']}
    signal=decision['observed_through'][:10]; i=idx[signal]
    entry=t['entry_at'][:10]; j=idx[entry]
    exit=t['exit_at'][:10]; end=idx[exit]
    row=dict(entry=entry,exit=exit,signal=signal,net_return=t['net_return'],net_pnl=t['net_pnl'],
             common_group=facts['common_group']=='True',budget=float(facts['entry_allocation']),
             prior_net_return=None if prior is None else prior['net_return'],
             prior_exit_gap_sessions=None if prior is None else j-idx[prior['exit']],
             entry_price=t['entry_price'],exit_price=t['exit_price'])
    for symbol,p in prices.items():
        row[symbol+'_pre_returns']={str(n):float(p[i]/p[i-n]-1) for n in (2,5,10,20)}
        row[symbol+'_pre_20dd']=float(p[i]/max(p[i-19:i+1])-1)
        row[symbol+'_negative_sessions_10']=int(sum(np.diff(p[i-10:i+1])<0))
        row[symbol+'_post_signal_returns']={str(n):float(p[j+n-1]/p[i]-1) for n in (1,2,3) if j+n-1<=end}
    row['MU_first_two_days_repair']=bool(max(prices['MU'][j:j+2])>prices['MU'][i])
    rows.append(row); prior=row

def describe(items):
    return dict(count=len(items),positive=sum(x['net_return']>0 for x in items),
                mean_net_return=float(np.mean([x['net_return'] for x in items])) if items else None,
                median_net_return=float(np.median([x['net_return'] for x in items])) if items else None,
                severe_loss_below_5pct=sum(x['net_return']<-.05 for x in items),
                total_actual_pnl=sum(x['net_pnl'] for x in items))
groups={}
for horizon in (2,5,10,20):
    for common in (False,True):
        for negative in (False,True):
            key=f'common={common};SOXX{horizon}negative={negative}'
            groups[key]=describe([x for x in rows if x['common_group']==common and (x['SOXX_pre_returns'][str(horizon)]<0)==negative])
for priorloss in (False,True):
    for shortgap in (False,True):
        groups[f'previous_loss={priorloss};reentry_within3={shortgap}']=describe([x for x in rows if x['prior_net_return'] is not None and (x['prior_net_return']<0)==priorloss and (x['prior_exit_gap_sessions']<=3)==shortgap])
for repair in (False,True):
    groups[f'POSTHOC_first_two_days_repair={repair}']=describe([x for x in rows if x['MU_first_two_days_repair']==repair])
result=dict(candidate='C8214',account_ref=record['account_ref'],
    limits=['Read-only development-pool diagnosis; no new account or experiment.',
            'Pre-entry returns end at the exact completed observation bar; no future regime labels used.',
            'Post-entry repair flags are posthoc descriptions, not causal or executable entry classifiers.',
            'Trade-level return groups are not recombined portfolio backtests; capital budgets and cash paths differ.',
            'HFQ bars reuse EX044 observations verified exactly against formal preparation in EX050-53.'],
    all_trades=describe(rows),worst_by_trade_return=sorted(rows,key=lambda x:x['net_return'])[:10],
    worst_by_actual_dollars=sorted(rows,key=lambda x:x['net_pnl'])[:10],groups=groups,rows=rows)
out=Path(__file__).resolve().parents[1]/'others/analysis_baseline_diagnosis.json'
out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in result.items() if k not in ('rows','worst_by_actual_dollars')},ensure_ascii=False,indent=2))
