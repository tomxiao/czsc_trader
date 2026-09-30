"""2026 YTD TDR backtest, independently funded and empty at the left edge."""
from pathlib import Path
from datetime import date
from dataclasses import replace
from hashlib import sha256
import argparse
import json
import traceback
import pandas as pd
import numpy as np
from dotenv import load_dotenv
from strategy_runtime import ChartRuntime,implementation_sha256
from strategy_manager import canonical_sha256
from czsc_trader.application.context import RepositoryContext
from czsc_trader.backtesting import resolve_candidate_snapshot,BacktestRequestV2,BacktestExecutionData,run_backtest_v2

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
BUNDLE=ROOT/'research/S011/backtests/tdr_run_20260930'
START=date(2026,1,1)
END=date(2026,9,28)
INITIAL=1_000_000.

def main(cid,receipt_path):
    if receipt_path.exists() or not receipt_path.is_relative_to(ROOT/'.tmp'):raise ValueError('fresh .tmp receipt required')
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    ref={'S011-CFG-000618':'EX24T003','S011-CFG-000621':'EX24T007'}[cid]
    registry=json.loads((ROOT/'research/S011/stage4/iteration_04/configurations.json').read_text())
    config=next(c for c in registry['configurations'] if c['config_id']==cid)
    runtime=BUNDLE/'runtime/strategy_runtime'
    for name in config['definition']['runtime']['source_files']:
        assert (runtime/name).read_bytes()==(ROOT/config['source_root']/name).read_bytes()
    binding=json.loads((BUNDLE/'chart_binding.json').read_text())
    ChartRuntime().validate_descriptor(binding,source_root=runtime,install_files=tuple(binding['source_files']))
    assert implementation_sha256(config['definition']['runtime']['source_files'],source_root=runtime)==config['definition']['runtime']['source_sha256']
    context=RepositoryContext.discover(ROOT,explicit_root=ROOT)
    snapshot=resolve_candidate_snapshot(context,'S011-'+ref,config['definition'],canonical_sha256(config['definition']),
        'research/S011/stage4/iteration_04/configurations.json',runtime_root=runtime,chart_descriptor=binding)
    snapshot=replace(snapshot,research_start=date(2025,2,6),research_end=END)
    prior=ROOT/'experiments/S011/20260930_S011_EX15/artifacts'
    frames={k:pd.read_csv(prior/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
    gate=json.loads((prior/'execution_data_gate.json').read_text())
    assert gate['constant_factor'] and gate['factor_min']==gate['factor_max']==1.
    sessions=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between(str(START),str(END)),'dt'])
    assert len(sessions)==179 and sessions[0].date()==date(2026,1,5) and sessions[-1].date()==END
    data=BacktestExecutionData(root=ROOT/'.tmp/s011-ex24-execution',symbol='159326.SZ',asset_type='etf',
        fingerprint=gate['fingerprint'],cutoff=END,evaluation_sessions=sessions,**frames)
    load_dotenv(ROOT/'.env',override=False)
    receipt={'config_id':cid,'config_fingerprint':config['config_fingerprint'],'reference_id':snapshot.identity.reference,
        'entrypoint':'czsc_trader.backtesting.run_backtest_v2','requested_window':[str(START),str(END)],
        'initial_cash':INITIAL,'initial_quantity':0,'one_way_cost':.001,'strategy_source_unchanged':True,
        'original_full_window_preserved':True,'platform_modified':False,'candidate_promoted':False,
        'source_hashes':{p.relative_to(ROOT).as_posix():sha256(p.read_bytes()).hexdigest() for p in [
            BUNDLE/'chart_binding.json',runtime/'charts/common.py',runtime/'charts/s011_development.py',
            runtime/'strategies/s011_reversal.py',prior/'execution_data_gate.json',
            *(prior/(k+'.csv.gz') for k in frames)]}}
    try:
        result=run_backtest_v2(snapshot=snapshot,request=BacktestRequestV2('159326.SZ','etf',START,END,INITIAL),
            srt_data_root=ROOT/'.tmp/s011-ex24-execution',outputs_root=context.outputs_root,run_date=date(2026,9,30),
            repository_root=ROOT,execution_data=data)
        assert result.manifest['engine']=='TDR_BACKTEST_V2' and result.manifest['audit']['status']=='PASS'
        assert all(a['status']=='PASS' for a in result.manifest['audit']['benchmarks'].values())
        a=pd.read_csv(result.output_dir/'account_daily.csv');t=pd.read_csv(result.output_dir/'trades.csv');f=pd.read_csv(result.output_dir/'fills.csv')
        assert pd.DatetimeIndex(pd.to_datetime(a.date)).equals(sessions)
        assert a.cash_before.iloc[0]==INITIAL and a.quantity_before.iloc[0]==0
        assert a.quantity.mod(100).eq(0).all() and a.cash.ge(-1e-8).all()
        np.testing.assert_allclose(a.cash+a.quantity*a.close,a.equity,atol=1e-7,rtol=0)
        np.testing.assert_allclose(f.fees,f.quantity*f.price*.001,atol=1e-7,rtol=0)
        equity=a.equity.to_numpy(float);closed=t[t.status.eq('CLOSED')]
        dd=float(-(equity/np.maximum.accumulate(np.r_[INITIAL,equity])[1:]-1).min())
        metrics={'total_return':float(equity[-1]/INITIAL-1),'annualized_return_252':float((equity[-1]/INITIAL)**(252/len(a))-1),
            'max_drawdown_magnitude':dd,'ending_equity':float(equity[-1]),'closed_trades':len(closed),
            'trades_per_60_sessions':60*len(closed)/len(a),'closed_trade_win_rate':float(closed.net_return.gt(0).mean()),
            'total_fees':float(f.fees.sum()),'ending_quantity':int(a.quantity.iloc[-1]),'sessions':len(a)}
        assert np.isclose(metrics['total_return'],result.metrics['strategy']['metrics']['return'],atol=1e-12)
        assert np.isclose(dd,-result.metrics['strategy']['metrics']['max_drawdown'],atol=1e-12)
        receipt.update(status='COMPLETE',engine='TDR_BACKTEST_V2',output_dir=result.output_dir.relative_to(ROOT).as_posix(),
            evaluation_window=[str(sessions[0].date()),str(sessions[-1].date())],audit=result.manifest['audit'],
            metrics=metrics,tdr_metrics=result.metrics,initial_state_check='PASS',cash_inventory_check='PASS',
            cost_check='PASS',files={p.name:sha256(p.read_bytes()).hexdigest() for p in result.output_dir.iterdir() if p.is_file()})
    except Exception as exc:
        receipt.update(status='FAILED',error_type=type(exc).__name__,error=str(exc))
        receipt_path.with_suffix('.traceback.txt').write_text(traceback.format_exc(),encoding='utf-8',newline='\n')
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(receipt,ensure_ascii=False))
    if receipt['status']!='COMPLETE':raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config-id',required=True,choices=['S011-CFG-000618','S011-CFG-000621']);p.add_argument('--receipt',required=True,type=Path)
    a=p.parse_args();main(a.config_id,a.receipt.resolve())
