"""Descriptive development-pool diagnostics from authenticated full accounts."""
import json
from hashlib import sha256
import numpy as np
import pandas as pd
from run_strategy_study import ROOT, WORK, save


def evidence(row):
    ref=row['evidence']
    path=ROOT/'research/S015/assets/evidence/EX003_20261021'/ref['evidence_id']
    raw=path.read_bytes()
    if sha256(raw).hexdigest()!=ref['sha256']:
        raise ValueError('account bytes changed')
    return json.loads(raw)


def rows():
    found=[]
    for name in ('grid_results.json','extension_results.json','counter_results.json'):
        path=WORK/name
        if path.exists():
            found+=json.loads(path.read_text(encoding='utf-8'))
    return found


def frontier(items):
    return [r for r in items if not any(
        s['observation']['net_cagr']>=r['observation']['net_cagr'] and
        abs(s['observation']['max_drawdown'])<=abs(r['observation']['max_drawdown']) and
        (s['observation']['net_cagr']>r['observation']['net_cagr'] or
         abs(s['observation']['max_drawdown'])<abs(r['observation']['max_drawdown']))
        for s in items)]


def account_details(row):
    data=evidence(row)
    run=data['runs'][0]
    a=pd.DataFrame(run['ledgers']['account_daily']['data'])
    trade_data=run['ledgers']['trades']
    t=pd.DataFrame(trade_data['data'],columns=[f['name'] for f in trade_data['schema']['fields']])
    a['date']=pd.to_datetime(a['date'])
    eq=a['equity'].to_numpy(float)
    # The benchmark's retained ledger schema is detected explicitly below, never replaced by prices.
    b=pd.DataFrame(run['buyhold']['account_daily']['data'])
    beq=b['equity'].to_numpy(float)
    assert len(a)==len(b)==434
    prior=np.r_[100000.,eq[:-1]]
    bprior=np.r_[100000.,beq[:-1]]
    full_drawdown=eq/np.maximum.accumulate(np.r_[100000.,eq])[1:]-1
    benchmark_drawdown=beq/np.maximum.accumulate(np.r_[100000.,beq])[1:]-1
    annual=[]
    for year in sorted(a.date.dt.year.unique()):
        ids=np.flatnonzero(a.date.dt.year.to_numpy()==year)
        lo,hi=ids[0],ids[-1]
        annual.append({'year':int(year),'partial':bool(year==2026),'days':len(ids),
            'strategy_return':eq[hi]/prior[lo]-1,'benchmark_return':beq[hi]/bprior[lo]-1,
            'strategy_drawdown':float(full_drawdown[ids].min()),
            'benchmark_drawdown':float(benchmark_drawdown[ids].min()),
            'drawdown_basis':'inherited full-account high-water mark'})
    rolling=[]
    for start in range(0,len(a)-251,21):
        end=start+251
        rolling.append({'start':str(a.date.iloc[start].date()),'end':str(a.date.iloc[end].date()),
            'strategy_return':eq[end]/prior[start]-1,'benchmark_return':beq[end]/bprior[start]-1,
            'strategy_drawdown':float(full_drawdown[start:end+1].min()),
            'benchmark_drawdown':float(benchmark_drawdown[start:end+1].min())})
    longest,current=0,0
    for r in rolling:
        r['excess']=r['strategy_return']-r['benchmark_return']
        current=current+1 if r['excess']<0 else 0
        longest=max(longest,current)
    # This is a descriptive realized-contribution diagnostic, never a trade-deletion backtest.
    closed=t[t.status=='CLOSED']
    pnl=(closed.exit_price.astype(float)*(1-.001)-closed.entry_price.astype(float)*(1+.001))*closed.quantity.astype(float)
    profit=float(pnl[pnl>0].sum())
    return {'annual':annual,'rolling252':rolling,'longest_underperforming_rolling_run':longest,
        'largest_winner_share_of_positive_closed_pnl':float(pnl.max()/profit) if profit else None,
        'top5_share_of_positive_closed_pnl':float(pnl.nlargest(5).clip(lower=0).sum()/profit) if profit else None,
        'time_in_market_fraction':float((a.quantity.astype(float)>0).mean()),
        'open_tail_quantity':float(a.quantity.iloc[-1]),
        'realized_closed_pnl':float(pnl.sum())}


def main():
    all_rows=rows()
    valid=[r for r in all_rows if 'observation' in r]
    front=frontier(valid)
    passed=[r for r in valid if r['passed']]
    groups={}
    for r in valid:
        groups.setdefault(r['economic_path_sha256'],[]).append(r['candidate_id'])
    by_params={tuple(sorted(r['parameters'].items())):r for r in valid}
    paired=[]
    for r in valid:
        if r['parameters']['range_cap']==0:
            counterpart=by_params.get(tuple(sorted({**r['parameters'],'range_cap':1.5}.items())))
            if counterpart:
                paired.append({'plain':r['candidate_id'],'filtered':counterpart['candidate_id'],
                    'cagr_difference':counterpart['observation']['net_cagr']-r['observation']['net_cagr'],
                    'drawdown_magnitude_difference':abs(counterpart['observation']['max_drawdown'])-abs(r['observation']['max_drawdown']),
                    'closed_trades_difference':counterpart['observation']['closed_trades']-r['observation']['closed_trades']})
    result={'count':len(all_rows),'succeeded':len(valid),'passed':len(passed),'frontier':[r['candidate_id'] for r in front],
        'passed_ids':[r['candidate_id'] for r in passed],'economic_path_groups':groups,
        'range_pairs':paired,'best_return':max(valid,key=lambda r:r['observation']['net_cagr'])['candidate_id'] if valid else None,
        'benchmark_cagr':valid[0]['benchmark_cagr'] if valid else None}
    save(WORK/'analysis.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('economic_path_groups','range_pairs')},ensure_ascii=False))


if __name__=='__main__':
    main()
