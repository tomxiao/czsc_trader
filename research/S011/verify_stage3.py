"""Read-only audit of sealed stage-three accounts and fresh public SRT/TXE replay.

Writes only disposable audit output below .tmp; never changes source archives.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_FLOOR
import json
import os
import sys
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from strategy_runtime import StrategyCandidate,StrategyRuntime,StrategyInit,TradableWindow
from trading_execution_engine import HistoricalExecutor
from research_experiment import load_experiment,load_experiment_input
from czsc_trader.experiment_archive import validate_experiment_archive

REPO=Path(__file__).resolve().parents[2]
EXPERIMENT=sys.argv[1] if len(sys.argv)>1 else '20260930_S011_EX15'
if EXPERIMENT not in {'20260930_S011_EX14','20260930_S011_EX15'}:
    raise ValueError('unsupported audit experiment')
ARCHIVE=REPO/'experiments/S011'/EXPERIMENT
OUTPUT=REPO/'.tmp'/('s011-stage3-verification-'+EXPERIMENT.rsplit('_',1)[1])


def audit():
    validate_experiment_archive(ARCHIVE)
    loaded=load_experiment(ARCHIVE)
    receipt=json.loads((ARCHIVE/'artifacts/execution_receipt.json').read_text())['receipt_sha256']
    load_experiment_input(ARCHIVE/'artifacts',expected_receipt_sha256=receipt)
    artifacts=ARCHIVE/'artifacts'
    rows=pd.read_csv(artifacts/'trials.csv')
    assert len(rows)==96 and rows.trial.nunique()==96
    parameters=json.loads((artifacts/'trial_parameters.json').read_text())
    bh=pd.read_csv(artifacts/'buyhold_account.csv.gz');be=bh.equity
    b_cagr=float((be.iloc[-1]/1e6)**(252/len(be))-1)
    b_dd=float((be/be.cummax().clip(lower=1e6)-1).min())
    prices=pd.read_csv(artifacts/'execution_daily.csv.gz').set_index('dt')
    intraday=pd.read_csv(artifacts/'execution_intraday.csv.gz')
    intraday['dt']=pd.to_datetime(intraday.dt)
    intraday['day']=intraday.dt.dt.strftime('%Y-%m-%d')
    components=pd.read_csv(REPO/'experiments/S011/20260929_S011_EX12/artifacts/review_component_values.csv.gz').set_index('Date')
    component_columns={'tail':'EX01__tail_return_90','market':'market__large_return_1',
                       'spx':'external__spx_1','risk5':'daily__range_mean_5'}
    rebuilt=[]
    for row in rows.itertuples():
        path=artifacts/f'trials/T{row.trial:03}'
        frames={k:pd.read_csv(path/(k+'.csv.gz')) for k in ('decisions','orders','fills','account_daily','trades')}
        acc,orders,fills,decisions,trades=(frames[k] for k in ('account_daily','orders','fills','decisions','trades'))
        assert len(acc)==403 and acc.date.is_unique and acc.date.is_monotonic_increasing
        assert (pd.to_datetime(acc.signal_date)<pd.to_datetime(acc.date)).all()
        assert (pd.to_datetime(decisions.spx_source_time)<pd.to_datetime(decisions.signal_date)).all()
        assert decisions.spx_staleness_days.between(1,10).all()
        expected=components.reindex(decisions.signal_date)
        for field,source in component_columns.items():
            assert np.allclose(decisions[field],expected[source],rtol=0,atol=1e-12)
        assert orders.loc[orders.side.eq('BUY'),'order_type'].eq('LIMIT').all()
        assert orders.loc[orders.side.eq('SELL'),'order_type'].eq('MARKET').all()
        assert fills.order_id.isin(orders.order_id).all()
        assert fills.order_id.is_unique and orders.order_id.is_unique
        # Re-resolve every order, including misses, from prices and available cash.
        balances=acc.set_index('date').cash_before.to_dict()
        fill_ids=set(fills.order_id)
        for order in orders.itertuples():
            op=float(prices.loc[order.execution_date,'open'])
            if order.side=='BUY':
                prior=float(prices.loc[order.signal_date,'close'])
                expected_limit=float((Decimal(str(prior*(1+parameters[row.trial]['premium'])))/Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.001'))
                assert abs(order.limit_price-expected_limit)<1e-12
                touch=intraday.loc[intraday.day.eq(order.execution_date),'low']
                possible=op<=order.limit_price or bool(touch.lt(order.limit_price).any())
                price=op if op<=order.limit_price else order.limit_price
                possible=possible and order.quantity*price*1.001<=balances[order.execution_date]+1e-8
                if possible:balances[order.execution_date]-=order.quantity*price*1.001
            else:
                possible=True
                balances[order.execution_date]+=order.quantity*op*.999
            assert (order.order_id in fill_ids)==possible
            assert order.status==('FILLED' if possible else 'UNFILLED')
        assert (pd.to_datetime(fills.signal_date)<pd.to_datetime(fills.fill_time).dt.normalize()).all()
        filled=orders.merge(fills,on='order_id',suffixes=('_order','_fill'))
        for fill in filled.itertuples():
            op=float(prices.loc[fill.execution_date,'open'])
            if fill.side_order=='SELL':
                assert fill.order_type=='MARKET' and abs(fill.price-op)<1e-12
                # TXE represents a daily opening fill with the normalized session date.
                assert pd.Timestamp(fill.fill_time)==pd.Timestamp(fill.execution_date)
            else:
                assert fill.price<=fill.limit_price+1e-12
                if op<=fill.limit_price:
                    assert abs(fill.price-op)<1e-12
                    assert pd.Timestamp(fill.fill_time)==pd.Timestamp(fill.execution_date)
                else:
                    touches=intraday.loc[intraday.day.eq(fill.execution_date)&intraday.low.lt(fill.limit_price)]
                    assert len(touches) and pd.Timestamp(fill.fill_time)==touches.dt.iloc[0]
                    assert abs(fill.price-fill.limit_price)<1e-12
        assert np.allclose(fills.fees,fills.quantity*fills.price*.001,atol=1e-6)
        assert np.allclose(acc.equity,acc.cash+acc.quantity*acc.close,atol=1e-6)
        assert acc.cash.min()>=-1e-6 and acc.quantity.ge(0).all() and acc.quantity.mod(100).eq(0).all()
        ff=fills.copy();ff['day']=pd.to_datetime(ff.fill_time).dt.strftime('%Y-%m-%d')
        ff['dq']=np.where(ff.side.eq('BUY'),ff.quantity,-ff.quantity)
        ff['dc']=-ff.dq*ff.price-ff.fees
        by_day=ff.groupby('day')[['dq','dc']].sum().reindex(acc.date,fill_value=0)
        assert np.allclose(acc.quantity.to_numpy(),by_day.dq.cumsum().to_numpy(),atol=0)
        assert np.allclose(acc.cash.to_numpy(),1e6+by_day.dc.cumsum().to_numpy(),rtol=0,atol=1e-6)
        assert np.allclose(acc.quantity_before,acc.quantity.shift(1,fill_value=0))
        assert np.allclose(acc.cash_before,acc.cash.shift(1,fill_value=1e6),rtol=0,atol=1e-6)
        eq=acc.equity;cagr=float((eq.iloc[-1]/1e6)**(252/len(eq))-1)
        dd=float((eq/eq.cummax().clip(lower=1e6)-1).min())
        closed=trades.loc[trades.status.eq('CLOSED')];freq=60*len(closed)/len(eq)
        qualified=bool(cagr>=1.5*b_cagr and (b_cagr>0 or (cagr>0 and cagr>b_cagr)) and dd>b_dd and 4<=freq<=6)
        assert np.allclose([row.cagr,row.drawdown,row.frequency,row.buyhold_cagr,row.buyhold_drawdown],
                           [cagr,dd,freq,b_cagr,b_dd],rtol=0,atol=1e-10)
        assert qualified==row.qualified and len(closed)==row.closed_trades
        chosen=json.loads((path/'payload.json').read_text())
        assert chosen['parameters']==parameters[row.trial]
        rebuilt.append({'trial':row.trial,'qualified':qualified,'cagr':cagr,'drawdown':dd,'frequency':freq,
                        'unfilled_orders':int(orders.status.ne('FILLED').sum()),'cash_days':int(acc.quantity.eq(0).sum())})
    summary=json.loads((artifacts/'summary.json').read_text())
    assert summary['evaluated']==96 and summary['qualified']==sum(r['qualified'] for r in rebuilt)
    anchor=int(summary['diagnostic_anchor'])
    path=artifacts/f'trials/T{anchor:03}'
    candidate=StrategyCandidate('S011',f'{EXPERIMENT.rsplit("_",1)[1]}T{anchor:03}',json.loads((path/'payload.json').read_text()),
                                 ARCHIVE/'runtime/strategy_runtime')
    load_dotenv(REPO/'.env',override=False)
    if not os.environ.get('TUSHARE_TOKEN'):raise RuntimeError('project credential unavailable')
    OUTPUT.mkdir(parents=True,exist_ok=True)
    instance=StrategyRuntime().create(StrategyInit(candidate,TradableWindow(date(2025,2,6),date(2026,9,28)),OUTPUT/'fresh-runtime'))
    prepared=instance.prepare_data()
    definition=instance.definition
    executor=HistoricalExecutor(strategy_reference=candidate.reference_id,symbol='159326.SZ',
        execution_daily=pd.read_csv(artifacts/'execution_daily.csv.gz'),
        execution_intraday=pd.read_csv(artifacts/'execution_intraday.csv.gz'),
        evaluation_start=pd.Timestamp('2025-02-06'),evaluation_end=pd.Timestamp('2026-09-28'),
        initial_cash=1e6,execution_policy=definition.execution,order_types=definition.capabilities.order_types)
    replay=instance.run_window(executor=executor)
    for name in ('decisions','orders','fills','account_daily','trades'):
        original=pd.read_csv(path/(name+'.csv.gz'))
        actual=getattr(replay,name)
        # Normalize CSV serialization and datetime precision without changing values.
        from io import StringIO
        actual=pd.read_csv(StringIO(actual.to_csv(index=False)))
        pd.testing.assert_frame_equal(original,actual,check_exact=False,rtol=1e-12,atol=1e-8)
    acc=replay.account_daily.copy();market=prices.copy();market.index=pd.to_datetime(market.index)
    index=pd.DatetimeIndex(pd.to_datetime(acc.date))
    opening=market.open.reindex(index).to_numpy()
    previous_close=market.close.shift(1).reindex(index).to_numpy()
    fills=replay.fills.copy();fills['date']=pd.to_datetime(fills.fill_time).dt.normalize()
    fills['open']=fills.date.map(market.open)
    fills['execution_effect']=np.where(fills.side.eq('BUY'),1.,-1.)*fills.quantity*(fills.open-fills.price)
    grouped=fills.groupby('date')[['fees','execution_effect']].sum().reindex(index,fill_value=0)
    pnl=acc.equity.diff();pnl.iloc[0]=acc.equity.iloc[0]-1e6
    decomposition=pd.DataFrame({'date':index,
        'overnight_pnl':acc.quantity_before.to_numpy()*(opening-previous_close),
        'daytime_pnl':acc.quantity.to_numpy()*(acc.close.to_numpy()-opening),
        'execution_effect':grouped.execution_effect.to_numpy(),'fees':grouped.fees.to_numpy(),
        'actual_pnl':pnl.to_numpy()})
    reconstructed=decomposition.overnight_pnl+decomposition.daytime_pnl+decomposition.execution_effect-decomposition.fees
    assert np.allclose(decomposition.actual_pnl,reconstructed,rtol=0,atol=1e-6)
    fills['cashflow']=np.where(fills.side.eq('SELL'),1.,-1.)*fills.quantity*fills.price-fills.fees
    cycle_pnl=fills.groupby('cycle_id').cashflow.sum()
    closed=replay.trades.loc[replay.trades.status.eq('CLOSED')].copy()
    closed['net_cash_pnl']=closed.cycle_id.map(cycle_pnl)
    positive=closed.loc[closed.net_cash_pnl.gt(0),'net_cash_pnl'].sort_values(ascending=False)
    years=[]
    for year in sorted(index.year.unique()):
        positions=np.flatnonzero(index.year==year);first,last=positions[0],positions[-1]
        before=1e6 if first==0 else float(acc.equity.iloc[first-1])
        bbefore=1e6 if first==0 else float(be.iloc[first-1])
        years.append({'year':int(year),'sessions':len(positions),'strategy_return':float(acc.equity.iloc[last]/before-1),
                      'buyhold_return':float(be.iloc[last]/bbefore-1)})
    decomposition.to_csv(OUTPUT/'anchor_pnl_attribution.csv',index=False)
    closed.to_csv(OUTPUT/'anchor_closed_trades.csv',index=False)
    pd.DataFrame(years).to_csv(OUTPUT/'anchor_years.csv',index=False)
    report={'status':'PASS','archive_receipt':receipt,'source_sha256':loaded.binding.source_sha256,
            'audited_accounts':len(rebuilt),'qualified':summary['qualified'],'fresh_replay_trial':anchor,
            'fresh_data_identity':prepared.data_identity,'full_ledger_equivalence':True,
            'all_order_fills_and_misses_reconstructed':True,
            'pnl_attribution_reconciled':True,'anchor_attribution':{
                'overnight_pnl':float(decomposition.overnight_pnl.sum()),'daytime_pnl':float(decomposition.daytime_pnl.sum()),
                'execution_effect':float(decomposition.execution_effect.sum()),'fees':float(decomposition.fees.sum()),
                'net_pnl':float(decomposition.actual_pnl.sum()),'closed_wins':int(closed.net_cash_pnl.gt(0).sum()),
                'closed_trades':len(closed),'top3_positive_pnl_share':float(positive.head(3).sum()/positive.sum()) if len(positive) else None},
            'stage_four_completed':False,'development_only':True,
            'contract_warning':('EX14 warmup begins before preregistered boundary; no admission' if EXPERIMENT.endswith('EX14') else None)}
    pd.DataFrame(rebuilt).to_csv(OUTPUT/'account_audit.csv',index=False)
    (OUTPUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':audit()
