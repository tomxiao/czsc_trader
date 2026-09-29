"""Audit the investable comparator and final stage-three qualification from raw ledgers."""
from pathlib import Path
from datetime import date
from decimal import Decimal, ROUND_FLOOR
from io import StringIO
import json
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from research_experiment import load_experiment,load_experiment_input
from strategy_runtime import StrategyCandidate,StrategyRuntime,StrategyInit,TradableWindow
from trading_execution_engine import HistoricalExecutor
from czsc_trader.experiment_archive import validate_experiment_archive

REPO=Path(__file__).resolve().parents[2]
P15=REPO/'experiments/S011/20260930_S011_EX15'
P16=REPO/'experiments/S011/20260930_S011_EX16'
OUT=REPO/'.tmp/s011-stage3-final-audit'


def main():
    receipts={}
    for path in (P15,P16):
        validate_experiment_archive(path);load_experiment(path)
        sha=json.loads((path/'artifacts/execution_receipt.json').read_text())['receipt_sha256']
        load_experiment_input(path/'artifacts',expected_receipt_sha256=sha);receipts[path.name]=sha
    previous=json.loads((REPO/'.tmp/s011-stage3-verification-EX15/verification.json').read_text())
    assert previous['status']=='PASS' and previous['audited_accounts']==96 and previous['contract_warning'] is None
    assert previous['archive_receipt']==receipts[P15.name]
    p=P16/'artifacts';acc=pd.read_csv(p/'benchmark_account_daily.csv.gz')
    orders=pd.read_csv(p/'benchmark_orders.csv.gz');fills=pd.read_csv(p/'benchmark_fills.csv.gz')
    prices=pd.read_csv(P15/'artifacts/execution_daily.csv.gz').set_index('dt')
    assert len(acc)==403 and len(orders)==len(fills)==1
    order=orders.iloc[0];fill=fills.iloc[0]
    assert order.side=='BUY' and order.order_type=='LIMIT' and order.status=='FILLED'
    assert order.signal_date=='2025-02-05' and order.execution_date=='2025-02-06'
    prior=float(prices.loc[order.signal_date,'close'])
    limit=float((Decimal(str(prior*1.003))/Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.001'))
    assert abs(order.limit_price-limit)<1e-12
    size=int((Decimal('1000000')/(Decimal(str(limit))*Decimal('1.001')*100)).to_integral_value(rounding=ROUND_FLOOR))*100
    actual_open=float(prices.loc['2025-02-06','open'])
    assert actual_open<=limit and size==int(fill.quantity) and size==int(order.quantity)
    assert fill.trigger=='OPEN' and pd.Timestamp(fill.fill_time)==pd.Timestamp('2025-02-06')
    assert abs(fill.price-actual_open)<1e-12
    fee=size*actual_open*.001;cash=1e6-size*actual_open-fee
    assert abs(fill.fees-fee)<1e-8 and cash>=0
    assert acc.quantity.eq(size).all() and np.allclose(acc.cash,cash,rtol=0,atol=1e-8)
    expected=cash+size*prices.close.reindex(acc.date).to_numpy()
    assert np.allclose(acc.equity,expected,rtol=0,atol=1e-8)
    bc=float((expected[-1]/1e6)**(252/403)-1)
    bd=float((expected/np.maximum.accumulate(np.maximum(expected,1e6))-1).min())
    q=pd.read_csv(p/'qualification.csv');assert len(q)==96 and q.trial.nunique()==96
    qualified=[]
    for row in q.itertuples():
        path=P15/f'artifacts/trials/T{row.trial:03}'
        account=pd.read_csv(path/'account_daily.csv.gz');trades=pd.read_csv(path/'trades.csv.gz')
        assert account.date.equals(acc.date)
        c=float((account.equity.iloc[-1]/1e6)**(252/403)-1)
        dd=float((account.equity/account.equity.cummax().clip(lower=1e6)-1).min())
        n=int(trades.status.eq('CLOSED').sum());frequency=60*n/403
        passed=c>=1.5*bc and (bc>0 or (c>0 and c>bc)) and dd>bd and 4<=frequency<=6
        assert np.allclose([row.cagr,row.drawdown,row.frequency,row.buyhold_cagr,row.buyhold_drawdown],[c,dd,frequency,bc,bd],rtol=0,atol=1e-10)
        assert row.qualified==passed
        if passed:qualified.append(row.trial)
    summary=json.loads((p/'summary.json').read_text())
    assert sorted(summary['qualified_trials'])==qualified
    # Fresh execution confirms the benchmark artifact is an SRT/TXE result.
    load_dotenv(REPO/'.env',override=False);OUT.mkdir(parents=True,exist_ok=True)
    candidate=StrategyCandidate('S011','EX16BH',json.loads((p/'benchmark_payload.json').read_text()),P16/'runtime/strategy_runtime')
    runtime=StrategyRuntime().create(StrategyInit(candidate,TradableWindow(date(2025,2,6),date(2026,9,28)),OUT/'fresh-runtime'))
    prepared=runtime.prepare_data()
    replay=runtime.run_window(executor=HistoricalExecutor(strategy_reference=candidate.reference_id,symbol='159326.SZ',
        execution_daily=pd.read_csv(P15/'artifacts/execution_daily.csv.gz'),
        execution_intraday=pd.read_csv(P15/'artifacts/execution_intraday.csv.gz'),
        evaluation_start=pd.Timestamp('2025-02-06'),evaluation_end=pd.Timestamp('2026-09-28'),
        initial_cash=1e6,execution_policy=runtime.definition.execution,order_types=runtime.definition.capabilities.order_types))
    for name in ('decisions','orders','fills','account_daily','trades'):
        expected=pd.read_csv(p/('benchmark_'+name+'.csv.gz'))
        observed=pd.read_csv(StringIO(getattr(replay,name).to_csv(index=False)))
        pd.testing.assert_frame_equal(expected,observed,check_exact=False,rtol=1e-12,atol=1e-8)
    report={'status':'PASS','strategy_receipt':receipts[P15.name],'benchmark_receipt':receipts[P16.name],
        'audited_strategy_accounts':96,'qualified_trials':qualified,'benchmark_shares':size,'benchmark_cash':cash,
        'benchmark_fee':fee,'benchmark_cagr':bc,'benchmark_drawdown':bd,'all_integer_lots':True,
        'benchmark_fresh_replay_equal':True,'benchmark_data_identity':prepared.data_identity,
        'all_original_hard_gates_recomputed':True,'development_only':True,'stage_four_complete':False}
    (OUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
