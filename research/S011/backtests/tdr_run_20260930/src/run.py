"""Public TDR research-snapshot backtest with an explicit owned chart binding."""
from pathlib import Path
from datetime import date
from hashlib import sha256
import json
import argparse
import pandas as pd
from dotenv import load_dotenv
from strategy_runtime import ChartRuntime,implementation_sha256
from strategy_manager import canonical_sha256
from czsc_trader.application.context import RepositoryContext
from czsc_trader.backtesting import resolve_candidate_snapshot,BacktestRequestV2,BacktestExecutionData,run_backtest_v2

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'pyproject.toml').is_file())
BUNDLE=Path(__file__).resolve().parents[1]

def main(cid,receipt_path):
    if receipt_path.exists() or not receipt_path.is_relative_to(ROOT/'.tmp'):raise ValueError('fresh .tmp receipt required')
    ref={'S011-CFG-000618':'EX24T003','S011-CFG-000621':'EX24T007'}[cid]
    registry=json.loads((ROOT/'research/S011/stage4/iteration_04/configurations.json').read_text())
    config=next(c for c in registry['configurations'] if c['config_id']==cid)
    runtime=BUNDLE/'runtime/strategy_runtime';original=ROOT/config['source_root']
    for name in config['definition']['runtime']['source_files']:
        assert (runtime/name).read_bytes()==(original/name).read_bytes()
    binding=json.loads((BUNDLE/'chart_binding.json').read_text())
    ChartRuntime().validate_descriptor(binding,source_root=runtime,install_files=tuple(binding['source_files']))
    assert implementation_sha256(config['definition']['runtime']['source_files'],source_root=runtime)==config['definition']['runtime']['source_sha256']
    context=RepositoryContext.discover(ROOT,explicit_root=ROOT)
    snapshot=resolve_candidate_snapshot(context,'S011-'+ref,config['definition'],canonical_sha256(config['definition']),
        'research/S011/stage4/iteration_04/configurations.json',runtime_root=runtime,chart_descriptor=binding)
    prior=ROOT/'experiments/S011/20260930_S011_EX15/artifacts'
    frames={k:pd.read_csv(prior/(k+'.csv.gz'),parse_dates=['dt']) for k in ('execution_daily','execution_intraday','adjusted_daily')}
    gate=json.loads((prior/'execution_data_gate.json').read_text());assert gate['constant_factor'] and gate['factor_min']==gate['factor_max']==1.
    sessions=pd.DatetimeIndex(frames['execution_daily'].loc[frames['execution_daily'].dt.between('2025-02-06','2026-09-28'),'dt'])
    data=BacktestExecutionData(root=ROOT/'.tmp/s011-ex24-execution',symbol='159326.SZ',asset_type='etf',
        fingerprint=gate['fingerprint'],cutoff=date(2026,9,28),evaluation_sessions=sessions,**frames)
    load_dotenv(ROOT/'.env',override=False)
    result=run_backtest_v2(snapshot=snapshot,request=BacktestRequestV2('159326.SZ','etf',date(2025,2,6),date(2026,9,28),1e6),
        srt_data_root=ROOT/'.tmp/s011-ex24-execution',outputs_root=context.outputs_root,run_date=date(2026,9,30),
        repository_root=ROOT,execution_data=data)
    assert result.manifest['engine']=='TDR_BACKTEST_V2' and result.manifest['audit']['status']=='PASS'
    assert all(a['status']=='PASS' for a in result.manifest['audit']['benchmarks'].values())
    # TDR adds explanatory decision fields; compare shared economic columns explicitly.
    checked={}
    for name in ('decisions','orders','fills','account_daily','trades'):
        actual=pd.read_csv(result.output_dir/(name+'.csv'))
        expected=pd.read_parquet(ROOT/f'research/S011/backtests/devpool_20260930_618_621/CFG{cid[-6:]}/{name}.parquet')
        common=[c for c in expected if c in actual]
        pd.testing.assert_frame_equal(actual[common],expected[common],check_exact=False,rtol=1e-12,atol=1e-8)
        checked[name]={'rows':len(actual),'compared_columns':common,
            'tdr_only_columns':sorted(set(actual)-set(expected)),'direct_only_columns':sorted(set(expected)-set(actual))}
    receipt={'status':'COMPLETE','config_id':cid,'reference_id':snapshot.identity.reference,'engine':'TDR_BACKTEST_V2',
        'entrypoint':'czsc_trader.backtesting.run_backtest_v2','cli_used':False,'output_dir':result.output_dir.relative_to(ROOT).as_posix(),
        'audit':result.manifest['audit'],'strategy_metrics':result.metrics['strategy']['metrics'],'ledger_comparison':checked,
        'strategy_source_unchanged':True,'config_fingerprint':config['config_fingerprint'],'chart_binding':binding,
        'platform_modified':False,'candidate_registered':False,'candidate_promoted':False,
        'files':{p.name:sha256(p.read_bytes()).hexdigest() for p in result.output_dir.iterdir() if p.is_file()}}
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'COMPLETE','config_id':cid,'output_dir':receipt['output_dir'],'metrics':receipt['strategy_metrics']},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config-id',required=True,choices=['S011-CFG-000618','S011-CFG-000621']);p.add_argument('--receipt',required=True,type=Path)
    a=p.parse_args();main(a.config_id,a.receipt.resolve())
