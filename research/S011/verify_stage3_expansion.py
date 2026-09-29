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
from hashlib import sha256
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from strategy_runtime import StrategyCandidate,StrategyRuntime,StrategyInit,TradableWindow
from trading_execution_engine import HistoricalExecutor
from research_experiment import load_experiment,load_experiment_input
from czsc_trader.experiment_archive import validate_experiment_archive

REPO=Path(__file__).resolve().parents[2]
EXPERIMENT=sys.argv[1] if len(sys.argv)>1 else '20260930_S011_EX21'
if EXPERIMENT not in {'20260930_S011_EX21'}:
    raise ValueError('unsupported audit experiment')
ARCHIVE=REPO/'experiments/S011'/EXPERIMENT
OUTPUT=REPO/'.tmp'/('s011-stage3-verification-'+EXPERIMENT.rsplit('_',1)[1])


def audit():
    validate_experiment_archive(ARCHIVE)
    loaded=load_experiment(ARCHIVE)
    receipt=None
    manifest_sha256=sha256((ARCHIVE/'experiment_manifest.json').read_bytes()).hexdigest()
    assert json.loads((ARCHIVE/'experiment_manifest.json').read_text())['status']=='TECHNICAL_FAILURE'
    artifacts=ARCHIVE/'artifacts'
    rows=pd.DataFrame([json.loads((artifacts/f'trials/T{i:03}/metrics.json').read_text()) for i in range(380)])
    assert rows.trial.tolist()==list(range(380))
    parameters=[json.loads((artifacts/f'trials/T{i:03}/payload.json').read_text())['parameters'] for i in range(380)]
    eligible=rows.loc[rows.qualified]
    frontier=[int(r.trial) for r in eligible.itertuples() if not ((eligible.cagr>=r.cagr)&(eligible.drawdown>=r.drawdown)&((eligible.cagr>r.cagr)|(eligible.drawdown>r.drawdown))).any()]
    summary={'evaluated':380,'qualified':len(eligible),'pareto_trials':frontier,'highest_return_trial':int(eligible.sort_values(['cagr','drawdown'],ascending=False).iloc[0].trial)}
    bh=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX16/artifacts/benchmark_account_daily.csv.gz');be=bh.equity
    b_cagr=float((be.iloc[-1]/1e6)**(252/len(be))-1)
    b_dd=float((be/be.cummax().clip(lower=1e6)-1).min())
    prices=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX15/artifacts/execution_daily.csv.gz').set_index('dt')
    intraday=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX15/artifacts/execution_intraday.csv.gz')
    intraday['dt']=pd.to_datetime(intraday.dt)
    intraday['day']=intraday.dt.dt.strftime('%Y-%m-%d')
    components=pd.read_csv(REPO/'experiments/S011/20260929_S011_EX12/artifacts/review_component_values.csv.gz').set_index('Date')
    component_columns={'tail':'EX01__tail_return_90','market':'market__large_return_1',
                       'spx':'external__spx_1','risk5':'daily__range_mean_5'}
    rebuilt=[]
    for row in rows.itertuples():
        path=artifacts/f'trials/T{row.trial:03}'
        frames={k:pd.read_csv(path/(k+'.csv.gz')) for k in ('decisions','orders','fills','account_daily','trades')}
        for frame in frames.values():
            for column in ('quantity','price','fees','limit_price','equity','cash','close','cash_before','quantity_before'):
                if column in frame:
                    frame[column]=pd.to_numeric(frame[column],errors='raise')
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
    assert summary['qualified']==sum(r['qualified'] for r in rebuilt)
    import importlib.util
    spec=importlib.util.spec_from_file_location('verified_search',ARCHIVE/'experiment.py')
    algorithm=importlib.util.module_from_spec(spec);spec.loader.exec_module(algorithm)
    correction=REPO/'experiments/S011/20260930_S011_EX20'
    validate_experiment_archive(correction)
    load_experiment(correction)
    correction_receipt=json.loads((correction/'artifacts/execution_receipt.json').read_text())['receipt_sha256']
    load_experiment_input(correction/'artifacts',expected_receipt_sha256=correction_receipt)
    corrected=json.loads((correction/'artifacts/corrected_trials.json').read_text())
    correction_report=json.loads((correction/'artifacts/summary.json').read_text())
    assert correction_report['proposals_reproduced']==368
    assert correction_report['export_discrepancy_trials']==list(range(11))
    failed=REPO/'experiments/S011/20260930_S011_EX19'
    validate_experiment_archive(failed)
    assert correction_report['source_manifest_sha256']==sha256((failed/'experiment_manifest.json').read_bytes()).hexdigest()
    if EXPERIMENT.endswith('EX21'):
        assert len(rows)==380
        provenance=[{'candidate_id':f'EX19T{i:03}' if i<368 else f'EX21T{i:03}','new_evaluation':i>=368} for i in range(380)]
        assert sum(r['new_evaluation'] for r in provenance)==12
        study=algorithm.make_study()
        for point in algorithm.seed_configurations():study.enqueue_trial(point)
        for row in rows.itertuples():
            trial=study.ask();observed=algorithm.suggest(trial)
            assert observed==parameters[row.trial],('adaptive proposal differs',row.trial)
            record=json.loads((artifacts/f'trials/T{row.trial:03}/optuna_trial.json').read_text())
            if row.trial<368:
                assert record==corrected[row.trial]
                assert provenance[row.trial]['candidate_id']==f'EX19T{row.trial:03}'
                for file in ('payload.json','identity.json','metrics.json','decisions.csv.gz','orders.csv.gz','fills.csv.gz','account_daily.csv.gz','trades.csv.gz'):
                    assert (artifacts/f'trials/T{row.trial:03}'/file).read_bytes()==(failed/f'artifacts/trials/T{row.trial:03}'/file).read_bytes()
            else:
                assert provenance[row.trial]['candidate_id']==f'EX21T{row.trial:03}'
            assert record['state']=='COMPLETE' and record['number']==trial.number
            expected_constraints=[float(1.5*b_cagr-row.cagr),float(np.nextafter(b_dd,np.inf)-row.drawdown),
                                  float(4-row.frequency),float(row.frequency-6)]
            assert np.allclose(record['user_attrs']['constraints'],expected_constraints,rtol=0,atol=1e-12)
            trial.set_user_attr('constraints',record['user_attrs']['constraints'])
            study.tell(trial,values=record['values'])
            assert np.allclose(record['values'],[row.cagr,row.drawdown],rtol=0,atol=1e-12)
        pending=study.ask();pending_parameters=algorithm.suggest(pending)
        assert pending.number==380
        assert pending_parameters==json.loads((artifacts/'trials/T380/payload.json').read_text())['parameters']
        assert pending_parameters==json.loads((artifacts/'trials/T380/failure.json').read_text())['parameters']
    assert set(algorithm.frontier(rows))==set(summary['pareto_trials'])
    anchor=int(sys.argv[2]) if len(sys.argv)>2 else int(summary['highest_return_trial'])
    path=artifacts/f'trials/T{anchor:03}'
    candidate_id=(provenance[anchor]['candidate_id'] if EXPERIMENT.endswith('EX21') else f'EX22T{anchor:03}')
    candidate=StrategyCandidate('S011',candidate_id,json.loads((path/'payload.json').read_text()),
                                 ARCHIVE/'runtime/strategy_runtime')
    load_dotenv(REPO/'.env',override=False)
    if not os.environ.get('TUSHARE_TOKEN'):raise RuntimeError('project credential unavailable')
    output=OUTPUT/f'T{anchor:03}'
    output.mkdir(parents=True,exist_ok=True)
    data_dir=(REPO/Path(sys.argv[3]) if len(sys.argv)>3 else output/'fresh-runtime')
    if len(sys.argv)>3:
        assert (data_dir/'strategy-space.json').is_file()
        assert (data_dir/'preparations/20250206_20260928/prepared-data.json').is_file()
    instance=StrategyRuntime().create(StrategyInit(candidate,TradableWindow(date(2025,2,6),date(2026,9,28)),data_dir))
    prepared=instance.prepare_data()
    definition=instance.definition
    executor=HistoricalExecutor(strategy_reference=candidate.reference_id,symbol='159326.SZ',
        execution_daily=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX15/artifacts/execution_daily.csv.gz'),
        execution_intraday=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX15/artifacts/execution_intraday.csv.gz'),
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
    decomposition.to_csv(output/'anchor_pnl_attribution.csv',index=False)
    closed.to_csv(output/'anchor_closed_trades.csv',index=False)
    pd.DataFrame(years).to_csv(output/'anchor_years.csv',index=False)
    report={'status':'PASS_COMPLETED_PREFIX','search_budget_complete':False,'completed_prefix':380,'planned_trials':384,'remaining_trials':4,'archive_receipt':receipt,'archive_manifest_sha256':manifest_sha256,'source_sha256':loaded.binding.source_sha256,
            'audited_accounts':len(rebuilt),'qualified':summary['qualified'],'fresh_replay_trial':anchor,
            'fresh_data_identity':prepared.data_identity,'input_source':'EXISTING_SAME_CANDIDATE_MANAGED_STORE' if len(sys.argv)>3 else 'NEW_DATA_PREPARATION','full_ledger_equivalence':True,
            'all_order_fills_and_misses_reconstructed':True,
            'pnl_attribution_reconciled':True,'anchor_attribution':{
                'overnight_pnl':float(decomposition.overnight_pnl.sum()),'daytime_pnl':float(decomposition.daytime_pnl.sum()),
                'execution_effect':float(decomposition.execution_effect.sum()),'fees':float(decomposition.fees.sum()),
                'net_pnl':float(decomposition.actual_pnl.sum()),'closed_wins':int(closed.net_cash_pnl.gt(0).sum()),
                'closed_trades':len(closed),'top3_positive_pnl_share':float(positive.head(3).sum()/positive.sum()) if len(positive) else None},
            'stage_four_completed':False,'development_only':True,
            'contract_warning':'Upstream EX19 first 11 state exports require EX20 supplemental correction',
            'correction_receipt':correction_receipt,'adaptive_sampling_reproduced':EXPERIMENT.endswith('EX21'),'fixed_grid_reproduced':EXPERIMENT.endswith('EX22'),'pareto_recomputed':True}
    pd.DataFrame(rebuilt).to_csv(output/'account_audit.csv',index=False)
    (output/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':audit()
