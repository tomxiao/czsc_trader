"""Independent read-only accounting checks for the EX26/EX27 robustness archives."""
from pathlib import Path
from hashlib import sha256
from decimal import Decimal, ROUND_FLOOR
import json
import argparse
import numpy as np
import pandas as pd
from research_experiment import load_experiment, load_experiment_input
from czsc_trader.experiment_archive import validate_experiment_archive

REPO=Path(__file__).resolve().parents[2]
ROOT=REPO/'experiments/S011/20260930_S011_EX26'
OUTPUT=REPO/'.tmp/s011-stage4-verification'


def audit(experiment=26):
    global ROOT, OUTPUT
    ROOT=REPO/f'experiments/S011/20260930_S011_EX{experiment}'
    OUTPUT=REPO/f'.tmp/s011-stage4-ex{experiment}-verification'
    validate_experiment_archive(ROOT); loaded=load_experiment(ROOT)
    receipt=json.loads((ROOT/'artifacts/execution_receipt.json').read_text())['receipt_sha256']
    load_experiment_input(ROOT/'artifacts',expected_receipt_sha256=receipt)
    costs=pd.read_csv(ROOT/'artifacts/cost_sensitivity.csv',float_precision='round_trip')
    benchmark_costs=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX26/artifacts/cost_sensitivity.csv',float_precision='round_trip')
    if experiment==27:
        costs['reference']=costs.trial.map(lambda x:f'EX27T{x:03}')
        costs['one_way_cost']=costs.fee
        costs['is_benchmark']=False
        costs['original_gates_under_scenario']=costs.qualified
        assert len(costs)==120 and costs.reference.nunique()==15
        trial_table=pd.read_csv(ROOT/'artifacts/trials.csv',float_precision='round_trip')
        assert len(trial_table)==15 and trial_table.trial.is_unique
        center={'tail_weight':.575,'spx_weight':.05,'entry':.325,'exit':.025,'max_days':2,'lookback':130,'premium':.0025}
        steps={'tail_weight':.025,'spx_weight':.025,'entry':.005,'exit':.025,'max_days':1,'lookback':10,'premium':.0005}
        seen=set()
        for t in trial_table.itertuples():
            expected=dict(center); expected[t.axis]=round(expected[t.axis]+t.direction*steps[t.axis],10)
            saved=json.loads((ROOT/f'artifacts/trials/T{t.trial:03}/optuna_trial.json').read_text())
            actual=json.loads((ROOT/f'artifacts/trials/T{t.trial:03}/payload.json').read_text())['parameters']
            assert actual==expected==saved['user_attrs']['actual_parameters']
            assert saved['state']=='COMPLETE' and saved['parameters']=={'axis':t.axis,'direction':t.direction}
            assert np.allclose(saved['values'],[t.cagr,t.drawdown],rtol=0,atol=1e-12)
            seen.add((t.axis,t.direction))
        assert seen=={(k,s) for k in steps for s in (-1,1)}|{('entry',0)}
    else:
        assert len(costs)==216 and len(costs.reference.unique())==27
    daily=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX15/artifacts/execution_daily.csv.gz').set_index('dt')
    bars=pd.read_csv(REPO/'experiments/S011/20260930_S011_EX15/artifacts/execution_intraday.csv.gz')
    bars['day']=pd.to_datetime(bars.dt).dt.strftime('%Y-%m-%d')
    records=[]
    for row in costs.itertuples():
        path=ROOT/(f'artifacts/trials/T{row.trial:03}/{row.scenario}' if experiment==27 else f'artifacts/accounts/{row.reference}/{row.scenario}')
        frames={k:pd.read_csv(path/f'{k}.csv.gz') for k in ('account_daily','orders','fills','trades','decisions')}
        acc,orders,fills,trades,decisions=(frames[k] for k in frames)
        payload=json.loads((path.parent/'payload.json').read_text()) if experiment==27 else json.loads((path.parent/'identity.json').read_text())['payload']
        premium=payload['parameters']['premium']; fee=row.one_way_cost
        assert len(acc)==403 and acc.date.is_unique and acc.date.is_monotonic_increasing
        assert (pd.to_datetime(acc.signal_date)<pd.to_datetime(acc.date)).all()
        assert orders.loc[orders.side.eq('BUY'),'order_type'].eq('LIMIT').all()
        assert orders.loc[orders.side.eq('SELL'),'order_type'].eq('MARKET').all()
        assert orders.order_id.is_unique and fills.order_id.is_unique
        assert fills.order_id.isin(orders.order_id).all()
        assert decisions.decision_id.is_unique and orders.decision_id.isin(decisions.decision_id).all()
        assert fills.decision_id.isin(decisions.decision_id).all()
        joined=orders[['order_id','decision_id','cycle_id']].merge(fills[['order_id','decision_id','cycle_id']],on='order_id',suffixes=('_order','_fill'))
        assert joined.decision_id_order.equals(joined.decision_id_fill)
        assert joined.cycle_id_order.equals(joined.cycle_id_fill)
        assert np.allclose(fills.fees,fills.quantity*fills.price*fee,rtol=0,atol=1e-6)
        assert acc.cash.ge(-1e-6).all() and acc.quantity.ge(0).all() and acc.quantity.mod(100).eq(0).all()
        f=fills.copy(); f['day']=pd.to_datetime(f.fill_time).dt.strftime('%Y-%m-%d')
        f['dq']=np.where(f.side.eq('BUY'),f.quantity,-f.quantity)
        f['dc']=-f.dq*f.price-f.fees
        changes=f.groupby('day')[['dq','dc']].sum().reindex(acc.date,fill_value=0)
        assert np.allclose(acc.quantity.to_numpy(),changes.dq.cumsum().to_numpy(),rtol=0,atol=0)
        assert np.allclose(acc.cash.to_numpy(),1e6+changes.dc.cumsum().to_numpy(),rtol=0,atol=1e-6)
        assert np.allclose(acc.equity,acc.cash+acc.quantity*acc.close,rtol=0,atol=1e-6)
        assert np.allclose(acc.cash_before,acc.cash.shift(1,fill_value=1e6),rtol=0,atol=1e-6)
        balances=acc.set_index('date').cash_before.to_dict(); filled=set(fills.order_id)
        by_order=fills.set_index('order_id')
        for order in orders.itertuples():
            opening=float(daily.loc[order.execution_date,'open'])
            if order.side=='BUY':
                previous=float(daily.loc[order.signal_date,'close'])
                limit=float((Decimal(str(previous*(1+premium)))/Decimal('.001')).to_integral_value(rounding=ROUND_FLOOR)*Decimal('.001'))
                assert abs(order.limit_price-limit)<1e-12
                touches=bars.loc[bars.day.eq(order.execution_date)&bars.low.lt(limit)]
                price=opening if opening<=limit else limit
                possible=(opening<=limit or not touches.empty) and order.quantity*price*(1+fee)<=balances[order.execution_date]+1e-8
                if possible:balances[order.execution_date]-=order.quantity*price*(1+fee)
                fill_time=pd.Timestamp(order.execution_date) if opening<=limit else (pd.Timestamp(touches.dt.iloc[0]) if not touches.empty else None)
            else:
                possible=True; price=opening; fill_time=pd.Timestamp(order.execution_date)
                balances[order.execution_date]+=order.quantity*price*(1-fee)
            assert possible==(order.order_id in filled)
            assert order.status==('FILLED' if possible else 'UNFILLED')
            if possible:
                observed=by_order.loc[order.order_id]
                assert abs(observed.price-price)<1e-12 and pd.Timestamp(observed.fill_time)==fill_time
                assert observed.quantity==order.quantity and observed.side==order.side
        eq=acc.equity; cagr=float((eq.iloc[-1]/1e6)**(252/403)-1)
        dd=float((eq/eq.cummax().clip(lower=1e6)-1).min()); closed=int(trades.status.eq('CLOSED').sum()); frequency=60*closed/403
        assert np.allclose([cagr,dd,frequency],[row.cagr,row.drawdown,row.frequency],rtol=0,atol=1e-12)
        benchmark=benchmark_costs.loc[benchmark_costs.is_benchmark & benchmark_costs.scenario.eq(row.scenario)].iloc[0]
        assert np.allclose([row.buyhold_cagr,row.buyhold_drawdown],[benchmark.cagr,benchmark.drawdown],rtol=0,atol=1e-12)
        if not row.is_benchmark:
            qualified=bool(cagr>=1.5*benchmark.cagr and (benchmark.cagr>0 or(cagr>0 and cagr>benchmark.cagr)) and dd>benchmark.drawdown and 4<=frequency<=6)
            assert qualified==row.original_gates_under_scenario
            baseline=pd.read_csv(path.parent/'standard/decisions.csv.gz')
            # Fee overrides alter identity hashes through executable quantities.
            # Match IDs bijectively by signal date; every in-scenario join is checked above.
            assert baseline.decision_id.is_unique and baseline.signal_date.equals(decisions.signal_date)
            normalized=decisions.copy(); normalized['decision_id']=baseline.decision_id
            pd.testing.assert_frame_equal(baseline,normalized)
        records.append({'reference':row.reference,'scenario':row.scenario,'accounting':'PASS','all_order_outcomes':'PASS','metrics_and_gates':'PASS'})
    report={'status':'PASS','audited_accounts':len(records),'source_sha256':loaded.binding.source_sha256,
        'archive_receipt':receipt,'manifest_sha256':sha256((ROOT/'experiment_manifest.json').read_bytes()).hexdigest(),
        'same_cost_integer_lot_benchmark':True,'all_fills_and_misses_reconstructed':True,
        'standard_signals_equal_under_fee_overrides':True,'new_hard_gates':False,'independent_data_validation':False}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    pd.DataFrame(records).to_csv(OUTPUT/'account_audit.csv',index=False)
    (OUTPUT/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--experiment',type=int,choices=(26,27),default=26)
    audit(parser.parse_args().experiment)
