"""Replay one registered configuration through public SRT/TXE; original evidence is read-only."""
from pathlib import Path
from datetime import date
from io import StringIO
import argparse
import json
import pandas as pd
from dotenv import load_dotenv
from strategy_runtime import StrategyCandidate,StrategyRuntime,StrategyInit,TradableWindow
from trading_execution_engine import HistoricalExecutor
from contracts import Registry
from inputs import REPO,LEDGERS
from build import validate,dump


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--package',type=Path,default=Path(__file__).resolve().parent.parent)
    parser.add_argument('--config-id',required=True)
    parser.add_argument('--data-dir',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();package=args.package.resolve();output=args.output.resolve()
    if output.exists() or not output.is_relative_to(REPO/'.tmp'):raise ValueError('use fresh .tmp output')
    validate(package)
    registry=Registry.model_validate(json.loads((package/'configurations.json').read_text()))
    config=next(c for c in registry.configurations if c['config_id']==args.config_id)
    evaluations=pd.read_parquet(package/'evaluations.parquet')
    row=evaluations.loc[evaluations.config_id.eq(args.config_id)&evaluations.scope.eq('COMPARABLE_DEVELOPMENT')].iloc[0]
    data_dir=args.data_dir.resolve()
    if not (data_dir/'strategy-space.json').is_file() or not (data_dir/'preparations/20250206_20260928/prepared-data.json').is_file():
        raise ValueError('explicit same-candidate managed preparation required; no cache copying or fallback')
    candidate=StrategyCandidate('S011',row.source_candidate_id,config['definition'],REPO/config['source_root'])
    load_dotenv(REPO/'.env',override=False)
    instance=StrategyRuntime().create(StrategyInit(candidate,TradableWindow(date(2025,2,6),date(2026,9,28)),data_dir))
    instance.prepare_data()
    price=REPO/'experiments/S011/20260930_S011_EX15/artifacts'
    executor=HistoricalExecutor(strategy_reference=candidate.reference_id,symbol='159326.SZ',
        execution_daily=pd.read_csv(price/'execution_daily.csv.gz'),execution_intraday=pd.read_csv(price/'execution_intraday.csv.gz'),
        evaluation_start=pd.Timestamp('2025-02-06'),evaluation_end=pd.Timestamp('2026-09-28'),initial_cash=1e6,
        execution_policy=instance.definition.execution,order_types=instance.definition.capabilities.order_types)
    result=instance.run_window(executor=executor);output.mkdir(parents=True)
    for name in LEDGERS:
        actual=pd.read_csv(StringIO(getattr(result,name).to_csv(index=False)))
        expected=pd.read_csv(REPO/row.evidence/(name+'.csv.gz'))
        actual.to_parquet(output/(name+'.parquet'),index=False)
        pd.testing.assert_frame_equal(actual,expected,check_exact=False,rtol=1e-12,atol=1e-8)
    dump(output/'verification.json',{'status':'PASS','config_id':args.config_id,'source_evaluation_id':row.evaluation_id,
        'all_five_ledgers_equal':True,'managed_preparation_reused':True,'independent_data_validation':False})
    print('PASS: same-configuration five-ledger public SRT/TXE replay')


if __name__=='__main__':main()
