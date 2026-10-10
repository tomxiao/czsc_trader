"""Reconcile ledgers, literal economic gates, and paired mechanism paths."""
from hashlib import sha256
import importlib.util
import numpy as np
import pandas as pd
from common import SRC, ROOT, RUNS, CACHE, PROTOCOLS, read, write, cache_read, context

def helpers():
    original=ROOT/'research/S013/experiments/EX007_20261009/src/trade_attribution.py'
    source=original.read_text(encoding='utf-8')
    pure='import numpy as np\nimport pandas as pd\n\n'+source[source.index('def plain('):source.index('\ndef main():')]
    path=SRC/'ledger_reference.py'
    path.write_text(pure,encoding='utf-8',newline='\n')
    spec=importlib.util.spec_from_file_location('s013_ex012_ledger_reference',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    audit_origin=ROOT/'research/S013/experiments/EX007_20261009/src/diagnose.py'
    audit_source=audit_origin.read_text(encoding='utf-8')
    audit_pure='import numpy as np\nimport pandas as pd\n\n'+audit_source[
        audit_source.index('def verify_account('):audit_source.index('\ndef main():')]
    audit_path=SRC/'account_reference.py'
    audit_path.write_text(audit_pure,encoding='utf-8',newline='\n')
    audit_spec=importlib.util.spec_from_file_location('s013_ex012_account_reference',audit_path)
    audit_module=importlib.util.module_from_spec(audit_spec)
    audit_spec.loader.exec_module(audit_module)
    module.verify_account=audit_module.verify_account
    return module,{'origin':original.relative_to(ROOT).as_posix(),
                   'origin_sha256':sha256(original.read_bytes()).hexdigest(),
                   'copied_pure_functions_sha256':sha256(path.read_bytes()).hexdigest()}

def annual(account):
    dates=pd.DatetimeIndex(pd.to_datetime(account.date)).normalize()
    equity=account.equity.to_numpy(dtype=float)
    assert len(equity)==1636 and dates[0]==pd.Timestamp('2020-01-02') and dates[-1]==pd.Timestamp('2026-09-30')
    rows={}
    anchor=1_000_000.
    for year in sorted(set(dates.year)):
        segment=equity[dates.year==year]
        wealth=np.r_[anchor,segment]
        rows[str(year)]={'return':float(segment[-1]/anchor-1),
            'drawdown':float(np.max(1-wealth/np.maximum.accumulate(wealth))),
            'opening_equity':anchor,'closing_equity':float(segment[-1])}
        anchor=float(segment[-1])
    return rows

def summarize(bound,result,config,ledger):
    run=result.runs[0]
    own,bh=run.execution.account_daily,run.buyhold.account_daily
    pd.testing.assert_series_equal(pd.to_datetime(own.date),pd.to_datetime(bh.date))
    years,benchmark_years=annual(own),annual(bh)
    cagr=float((own.equity.iloc[-1]/1_000_000)**(252/1636)-1)
    bcagr=float((bh.equity.iloc[-1]/1_000_000)**(252/1636)-1)
    assert abs(cagr-run.observation.net_cagr)<1e-12
    closed=int(run.execution.trades.status.eq('CLOSED').sum())
    negative=[y for y in years if benchmark_years[y]['return']<0]
    gates={'return':cagr>=1.5*bcagr if bcagr>0 else cagr>0,
           'annual_drawdown':all(years[y]['drawdown']<benchmark_years[y]['drawdown'] for y in years),
           'frequency':closed*60/1636>=4,
           'negative_buyhold_year_profit':all(years[y]['return']>0 for y in negative)}
    paths=ledger.inspect_run(run)
    audit=ledger.verify_account(bound,result)
    benchmark_paths=ledger.annual_account(run.buyhold.execution)[0]
    assert len(paths['cycles'])==len(run.execution.trades)
    for row in paths['annual_account']:
        assert abs(row['account_return']-years[str(row['year'])]['return'])<1e-12
    for row in benchmark_paths:
        assert abs(row['account_return']-benchmark_years[str(row['year'])]['return'])<1e-12
    frame=run.execution.decisions.copy()
    if config['mode']=='M0':
        masks=None
    else:
        opportunity=frame.confirmation_opportunity.astype(bool)
        if config['mode']=='M1':
            expected=frame.confirmation_score.ge(-.2)
        else:
            direction=1 if config['mode']=='M2' else -1
            expected=(direction*frame.confirmation_delta).ge(0)
        assert np.array_equal(expected,frame.confirmation_pass)
        assert np.array_equal(opportunity & expected,frame.signal_reason.eq('entry'))
        assert np.array_equal(opportunity & ~expected,frame.signal_reason.eq('confirmation_rejected'))
        masks={'base_opportunities':int(opportunity.sum()),
            'rejected_opportunities':int((opportunity & ~expected).sum()),
            'zero_delta_opportunities':int((opportunity & frame.confirmation_delta.eq(0)).sum())
                 if config['mode'] in ('M2','M3') else None,
            'groups':frame.assign(year=pd.to_datetime(frame.signal_date).dt.year,
                                 opportunity=opportunity.astype(int),rejected=(opportunity & ~expected).astype(int))
                .groupby(['year','regime'])[['opportunity','rejected']].sum().reset_index().to_dict('records')}
    actual_buys=run.execution.fills.side.eq('BUY')
    full_wealth=np.r_[1_000_000.,own.equity.to_numpy()]
    drawdown=float(np.max(1-full_wealth/np.maximum.accumulate(full_wealth)))
    row={key:config[key] for key in ('index','background','mode','candidate_id','content_sha256','existing_identity')}
    row.update(net_cagr=cagr,drawdown=drawdown,closed_trades=closed,frequency60=closed*60/1636,
        annual=years,benchmark_cagr=bcagr,benchmark_annual=benchmark_years,
        negative_benchmark_years=negative,gates=gates,qualified=all(gates.values()),
        total_fees=float(run.execution.fills.fees.sum()),
        signal_entries=int(frame.signal_reason.eq('entry').sum()),buy_fills=int(actual_buys.sum()),
        final_quantity=int(own.quantity.iloc[-1]),gate_counts=masks,paths=paths,account_audit=audit,
        request_hash=result.request_hash,result_hash=result.result_hash,
        raw_input_bindings={key:value.to_dict() for key,value in bound.input_bindings.items()},
        order_statuses={str(k):int(v) for k,v in run.execution.orders.status.value_counts().items()})
    return row,frame

def paired(first,second,label):
    # Difference is full policy outcome, not a sum of rejected predecessor trades.
    result={'comparison':label,'first':first['background']+'/'+first['mode'],
        'second':second['background']+'/'+second['mode'],
        'cagr_difference':second['net_cagr']-first['net_cagr'],
        'drawdown_difference':second['drawdown']-first['drawdown'],
        'closed_trade_difference':second['closed_trades']-first['closed_trades'],
        'annual_differences':{}}
    a={str(x['year']):x for x in first['paths']['annual_account']}
    b={str(x['year']):x for x in second['paths']['annual_account']}
    for year in a:
        result['annual_differences'][year]={'net_return':b[year]['account_return']-a[year]['account_return'],
            'price_contribution':b[year]['price_contribution']-a[year]['price_contribution'],
            'fee_contribution':b[year]['fee_contribution']-a[year]['fee_contribution']}
    def key(cycle):
        return (cycle['entry_fill_time'],cycle.get('exit_fill_time'),cycle['entry_route'])
    old={key(c):c for c in first['paths']['cycles']}
    new={key(c):c for c in second['paths']['cycles']}
    removed=[c for k,c in old.items() if k not in new]
    added=[c for k,c in new.items() if k not in old]
    result['cycle_changes']={'same_entry_exit_route':len(set(old)&set(new)),
        'removed_or_retimed':removed,'added_or_retimed':added,
        'warning':'different paths inherit different cash; old-cycle pnl is descriptive, not additive policy contribution'}
    return result

def rolling_effect(bound,history,ctx):
    binding=next(iter(bound.input_bindings.values()))
    # Explicit public DFLS fetch using the exact strategy input binding.
    request=binding.plan.requests['daily']
    fetched=ctx.data.fetch(request,prepared=binding.prepared)
    assert fetched.ready,fetched.error
    bars=fetched.dataframe.copy()
    dates=pd.DatetimeIndex(pd.to_datetime(bars.Date)).normalize()
    close=pd.Series(bars.Close.to_numpy(dtype=float),index=dates)
    amount=pd.Series(bars.Amount.to_numpy(dtype=float),index=dates)
    volume=pd.Series(bars.Volume.to_numpy(dtype=float),index=dates)
    def acf(values):
        centered=values-values.mean()
        variance=np.mean(centered**2)
        return np.nan if np.isclose(variance,0) else float(np.dot(centered[1:],centered[:-1])/19/variance)
    raw=pd.DataFrame({'acf':close.pct_change(fill_method=None).rolling(20).apply(acf,raw=True),
        'turnover':amount/amount.rolling(20).mean(),'volume':np.log(volume).diff().rolling(20).mean()})
    ranks=pd.DataFrame(index=dates)
    fixed_changes=pd.DataFrame(index=dates)
    for key in raw:
        values=raw[key].to_numpy()
        rank=np.full(len(values),np.nan)
        fixed=np.full(len(values),np.nan)
        for i in range(120,len(values)):
            current=values[i-119:i+1]
            previous=values[i-120:i]
            if np.isfinite(current).all():
                rank[i]=(np.count_nonzero(current<values[i])+.5*np.count_nonzero(current==values[i]))/120-.5
            if np.isfinite(previous).all():
                def on_old(value):
                    return (np.count_nonzero(previous<value)+.5*np.count_nonzero(previous==value))/120-.5
                fixed[i]=on_old(values[i])-on_old(values[i-1])
        ranks[key]=rank
        fixed_changes[key]=fixed
    weights=pd.Series({'acf':.5,'turnover':.25,'volume':.25})
    score=(ranks*weights).sum(axis=1,min_count=3)
    fixed=(fixed_changes*weights).sum(axis=1,min_count=3)
    observed=np.rint(score*960).diff()/960
    selected=pd.DatetimeIndex(pd.to_datetime(history.signal_date)).normalize()
    actual=history.confirmation_delta.to_numpy(dtype=float)
    expected=observed.reindex(selected).to_numpy()
    assert np.allclose(actual,expected,rtol=0,atol=1e-12)
    fixed=np.rint(fixed.reindex(selected).to_numpy()*960)/960
    rolling=actual-fixed
    rows=pd.DataFrame({'signal_date':selected,'observed_delta':actual,
                       'fixed_reference_delta':fixed,'rolling_reference_effect':rolling})
    rows['sign_disagrees']=np.sign(actual)!=np.sign(fixed)
    return {'definition':'Observed current-vs-prior score change decomposed into raw value movement ranked against previous complete 120-day window, plus change in the reference window. No future data.',
        'rows':rows.to_dict('records'),'checked_signal_dates':len(rows),
        'sign_disagreements':int(rows.sign_disagrees.sum()),
        'max_score_delta_recompute_error':float(np.max(np.abs(actual-expected))),
        'mean_absolute_rolling_reference_effect':float(np.mean(np.abs(rolling)))}

def main():
    matrix=read(RUNS/'matrix.json')
    assert matrix['status']=='COMPLETE' and all(r['status']=='SUCCEEDED' for r in matrix['rows'])
    ledger,helper_provenance=helpers()
    assert read(RUNS/'numeric_correction.json')['status']=='PASS'
    plan=read(PROTOCOLS/'plan_r2.json')
    rows=[]
    histories={}
    for config in plan['configurations']:
        label=config['background']+'-'+config['mode']
        bound,result=cache_read(CACHE/(label+'.pkl.gz'))
        row,history=summarize(bound,result,config,ledger)
        rows.append(row)
        histories[label]=history
    lookup={r['background']+'-'+r['mode']:r for r in rows}
    comparisons=[]
    for b in ('B0','B1','B2'):
        for mode in ('M1','M2','M3'):
            comparisons.append(paired(lookup[b+'-M0'],lookup[b+'-'+mode],'gate versus off'))
        comparisons.append(paired(lookup[b+'-M1'],lookup[b+'-M2'],'change versus level'))
        comparisons.append(paired(lookup[b+'-M3'],lookup[b+'-M2'],'improving versus declining'))
    for mode in ('M0','M1','M2','M3'):
        for b in ('B1','B2'):
            comparisons.append(paired(lookup['B0-'+mode],lookup[b+'-'+mode],'known weak-direction response'))
    bound,_=cache_read(CACHE/'B0-M2.pkl.gz')
    effect=rolling_effect(bound,histories['B0-M2'],context(1))
    for label,history in histories.items():
        if label.endswith(('M2','M3')):
            pd.testing.assert_series_equal(history.confirmation_delta,
                histories['B0-M2'].confirmation_delta,check_exact=True)
    output={'status':'PASS','rows':rows,'paired_comparisons':comparisons,
        'rolling_reference_diagnostic':effect,'helper_provenance':helper_provenance,
        'scope':'all 12 full standard accounts; benchmark reconciled; raw change diagnostic is not an independent performance test',
        'account_evaluations':21,'business_configurations':12,'technical_content_identities':18,
        'numeric_correction':read(RUNS/'numeric_correction.json'),'provider_calls':matrix['provider_calls'],
        'qualification_policy':'four user gates only; annual account continuous; negative years derived from actual new benchmark'}
    write(RUNS/'analysis.json',ledger.plain(output))
    print({'analysis':'PASS','qualified':[(r['background'],r['mode']) for r in rows if r['qualified']],
           'matrix':[{k:r[k] for k in ('background','mode','net_cagr','drawdown','closed_trades','gates')} for r in rows],
           'rolling_sign_disagreements':effect['sign_disagreements']},flush=True)

if __name__=='__main__':
    main()
