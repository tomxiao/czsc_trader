"""Attempt the public TDR backtest service on existing research identities."""
from pathlib import Path
from datetime import date
from hashlib import sha256
import json
import traceback
import argparse
import pandas as pd
from dotenv import load_dotenv
from strategy_manager import canonical_sha256
from czsc_trader.application.context import RepositoryContext
from czsc_trader.backtesting import resolve_candidate_snapshot,BacktestRequestV2,BacktestExecutionData,run_backtest_v2

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())

def main(config_id,output):
    if output.exists() or not output.is_relative_to(ROOT/'.tmp'):raise ValueError('fresh .tmp output required')
    output.mkdir(parents=True)
    registry=json.loads((ROOT/'research/S011/stage4/iteration_04/configurations.json').read_text())
    config=next(c for c in registry['configurations'] if c['config_id']==config_id)
    ref={'S011-CFG-000618':'EX24T003','S011-CFG-000621':'EX24T007'}[config_id]
    context=RepositoryContext.discover(ROOT,explicit_root=ROOT)
    snapshot=resolve_candidate_snapshot(context,'S011-'+ref,config['definition'],canonical_sha256(config['definition']),
        'research/S011/stage4/iteration_04/configurations.json',runtime_root=ROOT/config['source_root'])
    prior=ROOT/'experiments/S011/20260930_S011_EX15/artifacts'
    frames={k:pd.read_csv(prior/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
    gate=json.loads((prior/'execution_data_gate.json').read_text())
    assert gate['constant_factor'] and gate['factor_min']==gate['factor_max']==1.
    sessions=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between('2025-02-06','2026-09-28'),'dt'])
    data=BacktestExecutionData(root=ROOT/'.tmp/s011-ex24-execution',symbol='159326.SZ',asset_type='etf',
        fingerprint=gate['fingerprint'],cutoff=date(2026,9,28),evaluation_sessions=sessions,**frames)
    load_dotenv(ROOT/'.env',override=False)
    receipt={'config_id':config_id,'reference_id':snapshot.identity.reference,'entrypoint':'czsc_trader.backtesting.run_backtest_v2',
        'strategy_snapshot_kind':snapshot.identity.kind,'window':['2025-02-06','2026-09-28'],'initial_cash':1e6,
        'config_fingerprint':config['config_fingerprint'],'new_candidate_registration':False,'platform_modified':False,
        'chart_descriptor_present':snapshot.chart_descriptor is not None,
        'source_hashes':{str(p.relative_to(ROOT)).replace('\\','/'):sha256(p.read_bytes()).hexdigest() for p in
            [ROOT/'src/czsc_trader/backtesting/service.py',ROOT/'src/czsc_trader/backtesting/strategy_source.py',
             ROOT/'packages/strategy_runtime/src/strategy_runtime/charting.py',prior/'execution_data_gate.json']}}
    try:
        result=run_backtest_v2(snapshot=snapshot,request=BacktestRequestV2('159326.SZ','etf',date(2025,2,6),date(2026,9,28),1e6),
            srt_data_root=ROOT/'.tmp/s011-ex24-execution',outputs_root=output/'outputs',run_date=date(2026,9,30),
            repository_root=ROOT,execution_data=data)
        receipt.update(status='COMPLETE',output_dir=result.output_dir.relative_to(ROOT).as_posix(),metrics=result.metrics)
    except Exception as exc:
        receipt.update(status='FAILED',error_type=type(exc).__name__,error=str(exc),standard_report_published=False)
        (output/'traceback.txt').write_text(traceback.format_exc(),encoding='utf-8',newline='\n')
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(receipt,ensure_ascii=False))
    if receipt['status']!='COMPLETE':raise SystemExit(1)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config-id',choices=['S011-CFG-000618','S011-CFG-000621'],required=True)
    p.add_argument('--output',required=True,type=Path);a=p.parse_args();main(a.config_id,a.output.resolve())
