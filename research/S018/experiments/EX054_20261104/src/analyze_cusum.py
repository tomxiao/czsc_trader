from pathlib import Path
import importlib.util
import json
import numpy as np

ROOT=Path.cwd()
reader=importlib.util.spec_from_file_location('reader',ROOT/'research/S018/experiments/EX047_20261104/src/analyze_exits.py')
module=importlib.util.module_from_spec(reader); reader.loader.exec_module(module)
read=lambda p:json.loads(p.read_text(encoding='utf-8'))
records=read(ROOT/'research/S018/experiments/EX054_20261104/others/results.json')['accounts']
base_record,base_run,base_trades=module.load('EX052_20261104','C8214')
hfq=read(ROOT/'research/S018/experiments/EX044_20261104/others/analysis_SOXX_hfq.json')
dates=[x['time_key'][:10] for x in hfq]
index={d:i for i,d in enumerate(dates)}
price=np.array([x['close'] for x in hfq])

def facts(decision):
    return {x['key']:x['text'] for x in decision['explanation']['basis']}

def entries(run,trades):
    orders={x['order_id']:x for x in run['orders']}
    decisions={x['decision_id']:x for x in run['decisions']}
    output={}
    for t in trades.values():
        fill=next(x for x in run['fills'] if x['cycle_id']==t['cycle_id'] and x['side']=='BUY')
        decision=decisions[orders[fill['order_id']]['decision_id']]
        output[t['entry_at'][:10]]=dict(trade=t,facts=facts(decision),decision=decision)
    return output

base_entries=entries(base_run,base_trades)
results={}; score_series={}
for cid,record in records.items():
    _,run,trades=module.load('EX054_20261104',cid)
    own=entries(run,trades); p=record['config']
    assert set(own)==set(base_entries)
    assert all(own[k]['trade']['exit_at']==base_entries[k]['trade']['exit_at'] for k in own)
    # Independently derive each score using the whole immutable history prefix.
    scores=[]
    for decision in run['decisions']:
        f=facts(decision); at=index[decision['observed_through'][:10]]
        last=at-p['risk_lag']; score=0.
        for j in range(last-39,last+1):
            prior=np.diff(np.log(price[j-21:j]))
            assert len(prior)==20
            sigma=float(np.std(prior,ddof=1))
            daily=float(np.log(price[j]/price[j-1]))
            score=max(0.,score-daily/sigma-p['cusum_k'])
        assert abs(score-float(f['sector_down_cusum']))<1e-10,(cid,decision['observed_through'],score,f['sector_down_cusum'])
        scores.append(score)
    changed=[]
    for day,entry in own.items():
        base=base_entries[day]; prior_budget=float(base['facts']['entry_allocation'])
        budget=float(entry['facts']['entry_allocation'])
        if abs(prior_budget-budget)>1e-12:
            changed.append(dict(entry=day,exit=entry['trade']['exit_at'][:10],
                baseline_budget=prior_budget,budget=budget,score=float(entry['facts']['sector_down_cusum']),
                risk_state=entry['facts']['risk_state']=='True',
                baseline_net_return=base['trade']['net_return'],net_return=entry['trade']['net_return'],
                baseline_actual_pnl=base['trade']['net_pnl'],actual_pnl=entry['trade']['net_pnl']))
    signal_scores=[scores[i] for i,x in enumerate(run['decisions']) if facts(x)['observed_signal']=='True']
    entry_scores=[float(x['facts']['sector_down_cusum']) for x in own.values()]
    key=f"k={p['cusum_k']};lag={p['risk_lag']}"
    if key not in score_series:
        dist=lambda values:dict(count=len(values),max=max(values),
            quantiles={str(q):float(np.quantile(values,q)) for q in [0,.25,.5,.75,.9,.95,.99,1]},
            at_least={str(h):sum(x>=h for x in values) for h in [.25,.5,1,2,4,6]})
        score_series[key]=dict(all_decisions=dist(scores),eligible_signals=dist(signal_scores),filled_entries=dist(entry_scores))
    def desc(rows):
        return dict(count=len(rows),sum_baseline_trade_return=sum(x['baseline_net_return'] for x in rows),
            sum_baseline_actual_pnl=sum(x['baseline_actual_pnl'] for x in rows),
            sum_actual_pnl=sum(x['actual_pnl'] for x in rows),
            budget_scaled_trade_return_removed=sum((x['baseline_budget']-x['budget'])*x['baseline_net_return'] for x in rows))
    octrows=[]
    for day,x in own.items():
        if '2026-10-01' <= day <= '2026-10-15':
            octrows.append(dict(entry=day,net_return=x['trade']['net_return'],net_pnl=x['trade']['net_pnl'],
                budget=float(x['facts']['entry_allocation']),score=float(x['facts']['sector_down_cusum']),risk_state=x['facts']['risk_state']))
    results[cid]=dict(config=p,metrics=record['candidate'],account_ref=record['account_ref'],
        changed_entries=len(changed),reduced_winners=desc([x for x in changed if x['baseline_net_return']>0]),
        reduced_losers=desc([x for x in changed if x['baseline_net_return']<0]),
        october_entries=octrows,changed=changed,
        prefix_score_checked=len(scores),same_entry_exit_schedule=True)
    if cid=='C8431':
        economic=lambda rows:[{k:v for k,v in x.items() if not k.endswith('_id')} for x in rows]
        for field in ('fills','account_daily','trades','actions'):
            assert economic(run[field])==economic(base_run[field]),field
        assert record['candidate']==base_record['candidate']
        results[cid]['baseline_control_exact']=['fills','account_daily','trades','actions','summary_metrics']
low_bins={}
for lo,hi in ((0,.5),(.5,1),(1,2),(2,4)):
    chosen=[x for x in results['C8424']['changed'] if lo<=x['score']<hi]
    low_bins[f'{lo} <= score < {hi}']=dict(count=len(chosen),
        positive=sum(x['baseline_net_return']>0 for x in chosen),
        mean_baseline_trade_return=sum(x['baseline_net_return'] for x in chosen)/len(chosen),
        sum_budget_scaled_baseline_trade_return=sum(x['baseline_budget']*x['baseline_net_return'] for x in chosen))
output=dict(status='PASS',baseline='C8214',baseline_ref=base_record['account_ref'],
    limits=['No account recomputation; read-only published account analysis.',
        'All scores independently checked against the exact observation prefix; late information never enters scores.',
        'Budget-scaled return sums are descriptive per-entry cash proxies, not compounded portfolio attribution.',
        'Actual pnl differences include changed preceding capital and cannot be interpreted as isolated sizing causal effects.',
        'Entry/exit schedules are identical; only quantities and resulting capital paths differ.'],
    score_distributions=score_series,lower_score_bins_k025_lag0=low_bins,accounts=results)
path=Path(__file__).resolve().parents[1]/'others/analysis_cusum.json'
path.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'status':'PASS','accounts':len(results),'decisions_checked':sum(x['prefix_score_checked'] for x in results.values()),'score_distributions':score_series},ensure_ascii=False,indent=2))
for cid,row in results.items():
    print(cid,row['config'],{k:row['metrics'][k] for k in ('calmar','dd','october_return')},
          'changed',row['changed_entries'],'wins',row['reduced_winners']['count'],'losses',row['reduced_losers']['count'])
