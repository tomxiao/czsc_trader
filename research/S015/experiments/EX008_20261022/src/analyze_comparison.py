"""Reconcile both audited accounts and derive continuous-account diagnostics."""
from hashlib import sha256
import json
import numpy as np
import pandas as pd
from run_comparison import ROOT, EROOT, identities, read, save


def drawdown(dates, equities, baseline):
    values = np.r_[baseline, np.asarray(equities, dtype=float)]
    high = np.maximum.accumulate(values)
    series = values / high - 1
    trough = int(np.argmin(series))
    peak = int(np.flatnonzero(values[:trough+1] == high[trough])[-1])
    recovered = np.flatnonzero(values[trough+1:] >= high[trough])
    recovery = int(trough+1+recovered[0]) if len(recovered) else None
    labels = ['INITIAL_CAPITAL', *[str(x)[:10] for x in dates]]
    return {'magnitude': float(-series[trough]), 'peak': labels[peak], 'trough': labels[trough],
        'recovery': labels[recovery] if recovery is not None else None,
        'peak_equity': float(values[peak]), 'trough_equity': float(values[trough]),
        'peak_to_trough_sessions': trough-peak,
        'peak_to_recovery_sessions': recovery-peak if recovery is not None else None}


def main():
    protocol = read(EROOT / 'protocols/comparison.json')
    assert identities() == protocol['identities']
    stats, accounts, manifests, hashes, yearly, rolling = {}, {}, {}, {}, {}, {}
    for label in ('S011-v1', 'C0031'):
        folder = ROOT / read(EROOT / f'others/{label}_run.json')['data']['output_dir']
        a = pd.read_csv(folder/'account_daily.csv', float_precision='round_trip')
        t = pd.read_csv(folder/'trades.csv', float_precision='round_trip')
        fills = pd.read_csv(folder/'fills.csv', float_precision='round_trip')
        audit = read(folder/'audit.json')
        assert audit['status'] == 'PASS' and all(v['status']=='PASS' for v in audit['benchmarks'].values())
        metrics = read(folder/'metrics.json')['strategy']['metrics']
        m = read(folder/'manifest.json')
        assert len(a)==415 and a.date.iloc[0]=='2025-02-06' and a.date.iloc[-1]=='2026-10-21'
        assert a.cash_before.iloc[0]==100000 and a.quantity_before.iloc[0]==0
        assert np.allclose(fills.fees, fills.quantity*fills.price*.001, rtol=0, atol=1e-10)
        net = float(a.equity.iloc[-1]/100000-1)
        dd = drawdown(a.date, a.equity, 100000)
        assert abs(net-metrics['return'])<1e-12 and abs(dd['magnitude']+metrics['max_drawdown'])<1e-12
        dates = pd.DatetimeIndex(a.date)
        exits = pd.to_datetime(t.loc[t.status.eq('CLOSED'),'exit_date']).dt.normalize()
        frequency = exits.value_counts().reindex(dates,fill_value=0).rolling(60).sum().dropna()
        stats[label] = {'metrics':metrics, 'net_return':net,'annualized_return':float((1+net)**(252/415)-1),
            'final_equity':float(a.equity.iloc[-1]),'drawdown':dd,'fees_paid':float(fills.fees.sum()),
            'terminal_quantity':int(a.quantity.iloc[-1]),'terminal_cash':float(a.cash.iloc[-1]),
            'terminal_close':float(a.close.iloc[-1]),
            'rolling60_median':float(frequency.median()),'rolling60_at_least3':int((frequency>=3).sum()),
            'rolling60_windows':len(frequency),'rolling60_coverage':float((frequency>=3).mean()),
            'technical_audit':'PASS','output_dir':folder.relative_to(ROOT).as_posix()}
        prev = a.equity.shift(1,fill_value=100000)
        global_dd = a.equity/a.equity.cummax().clip(lower=100000)-1
        yearly[label] = []
        for year, group in a.groupby(pd.to_datetime(a.date).dt.year):
            start, end = int(group.index[0]), int(group.index[-1])
            baseline = float(prev.iloc[start])
            yearly[label].append({'year':int(year),'start':a.date.iloc[start],'end':a.date.iloc[end],
                'sessions':len(group),'starting_equity':baseline,'ending_equity':float(group.equity.iloc[-1]),
                'net_return':float(group.equity.iloc[-1]/baseline-1),
                'slice_drawdown':drawdown(group.date,group.equity,baseline),
                'worst_full_account_drawdown_during_year':float(-global_dd.iloc[start:end+1].min()),
                'note':'Continuous account slice; capital and positions inherited, no annual reset.'})
        rolling[label] = []
        for start in range(0,len(a)-252+1,21):
            group=a.iloc[start:start+252]
            baseline=float(prev.iloc[start])
            rolling[label].append({'start':group.date.iloc[0],'end':group.date.iloc[-1],
                'net_return':float(group.equity.iloc[-1]/baseline-1),
                'drawdown':drawdown(group.date,group.equity,baseline)['magnitude']})
        accounts[label], manifests[label] = a, m
        hashes[label]={p.name:sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}
    assert manifests['S011-v1']['request']==manifests['C0031']['request']
    assert manifests['S011-v1']['execution_data']==manifests['C0031']['execution_data']
    assert accounts['S011-v1'].date.equals(accounts['C0031'].date)
    old = read(ROOT/'outputs/1022_08_full_period_gate/assessment.json')['statistics']
    change={}
    for label, oldfolder in [('S011-v1','1022_06_S011-v1'),('C0031','1022_07_S015-C0031')]:
        olda=pd.read_csv(ROOT/'outputs'/oldfolder/'account_daily.csv',float_precision='round_trip')
        oldfills=pd.read_csv(ROOT/'outputs'/oldfolder/'fills.csv',float_precision='round_trip')
        newa=accounts[label]; common=newa[newa.date.ge('2025-02-17')].reset_index(drop=True)
        newfills=pd.read_csv(ROOT/stats[label]['output_dir']/'fills.csv',float_precision='round_trip')
        extra=newa[newa.date.lt('2025-02-17')]
        change[label]={'return_difference':stats[label]['net_return']-old[label]['metrics']['return'],
            'drawdown_difference':stats[label]['drawdown']['magnitude']-abs(old[label]['metrics']['max_drawdown']),
            'extra_sessions':len(extra),'extra_all_cash':bool(extra.quantity.eq(0).all()),
            'common_targets_equal':bool(olda.target_position.equals(common.target_position)),
            'old_first_fill':oldfills.iloc[0].to_dict(),'new_first_fill':newfills.iloc[0].to_dict(),
            'subsequent_fill_prices_equal':bool(newfills.price.iloc[1:].reset_index(drop=True).equals(oldfills.price.iloc[1:].reset_index(drop=True))),
            'first_fill_date_is_only_fill_timing_difference':bool(newfills.fill_time.iloc[1:].reset_index(drop=True).equals(oldfills.fill_time.iloc[1:].reset_index(drop=True)))}
    c,s=stats['C0031'],stats['S011-v1']
    checks={'return_strictly_higher':c['net_return']>s['net_return'],
            'drawdown_strictly_smaller':c['drawdown']['magnitude']<s['drawdown']['magnitude']}
    roll_compare=[{'start':c['start'],'end':c['end'],'return_advantage':c['net_return']-s['net_return'],
                  'drawdown_advantage':s['drawdown']-c['drawdown']}
                  for c,s in zip(rolling['C0031'],rolling['S011-v1'],strict=True)]
    result={'status':'COMPUTED','primary_checks':checks,'comparative_gate':'PASS' if all(checks.values()) else 'FAIL',
        'window':protocol['window'],'statistics':stats,'yearly_slices':yearly,'rolling252':rolling,
        'rolling252_comparison':roll_compare,'change_from_previous_408_day_comparison':change,
        'return_advantage_pp':100*(c['net_return']-s['net_return']),
        'drawdown_disadvantage_pp':100*(c['drawdown']['magnitude']-s['drawdown']['magnitude']),
        'drawdown_ratio':c['drawdown']['magnitude']/s['drawdown']['magnitude'],
        'common_execution_fingerprint':manifests['C0031']['execution_data']['fingerprint'],
        'source_files_sha256':hashes,'strategy_files_unchanged':True}
    save(EROOT/'others/assessment.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('source_files_sha256',)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
