"""S013 EX101 public research capabilities with explicit zero provider budget."""
from datetime import date
from importlib.metadata import version
from pathlib import Path
from types import MappingProxyType
from hashlib import sha256
import copyreg
import gzip
import json
import pickle
from dataflows import Dataset, ProviderBinding, ProviderConfig
from strategy_runtime import StrategyCandidate, ImplementationDependency
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import (ResearchBatchRef, EvaluationResources, EvaluationRequest,
    EvaluationWindow, EvaluationCost, EvaluationBenchmark, LimitBuyHold, ExecutionPriceBasis)
from czsc_trader.research_tools.context import ExperimentRef

SRC=Path(__file__).resolve().parent
ROOT=SRC.parents[4]
EXPERIMENT=ExperimentRef('S013',SRC.parent.name)
PROTOCOLS=SRC.parent/'protocols'
SOURCE=SRC/'strategy_runtime'
RUNS=ROOT/'research/S013/assets/runs'/EXPERIMENT.experiment_id
CACHE=ROOT/'.tmp/s013-trend-fixed-20261015/cache'
DEPENDENCIES=tuple(ImplementationDependency(x,version(x)) for x in ('numpy','pandas','czsc-strategy-runtime'))
SOURCE_CALLS=[]
def read(p): return json.loads(Path(p).read_text('utf-8-sig'))
def write(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
def file_hash(p): return sha256(Path(p).read_bytes()).hexdigest()
def deny(request):
    SOURCE_CALLS.append(str(request))
    raise RuntimeError('S013 existing assets only; provider requests forbidden: '+str(request))
def context(workers=2):
    bindings={x:ProviderBinding(str(x),'S013-EX101-existing-only',deny) for x in
        (Dataset.TRADING_CALENDAR,Dataset.ETF_OHLCV,Dataset.ETF_UNADJUSTED_DAILY,Dataset.ETF_UNADJUSTED_INTRADAY)}
    return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S013'),
        providers=ProviderConfig(bindings=bindings),resources=EvaluationResources(workers,1,13))
def benchmark():
    return EvaluationBenchmark(LimitBuyHold(lot_size=100,premium=.01,price_tick=.001,
        price_limit_ratio=.1,maximum_order_quantity=1_000_000))
def candidate(config): return StrategyCandidate('S013',config['candidate_id'],config['payload'],SOURCE)
def request(config):
    strategy=candidate(config)
    return EvaluationRequest(ROOT,EXPERIMENT.experiment_id,strategy,
        dict(candidate_id=strategy.reference_id,source_files=list(strategy.payload['runtime']['source_files']),
            implementation_sha256=strategy.payload['runtime']['source_sha256']),
        '510500.SH','etf',(EvaluationWindow('full',date(2020,1,2),date(2026,9,30)),),
        date(2026,9,30),1_000_000,(EvaluationCost('baseline',.001,'FORMAL'),),
        benchmark=benchmark(),workers=1,frequency_window_days=60,execution_mode='FULL',
        dependencies=DEPENDENCIES,price_basis=ExecutionPriceBasis.HFQ_RESEARCH)
def restore_mapping(v): return MappingProxyType(v)
def reduce_mapping(v): return restore_mapping,(dict(v),)
def cache_write(p,v):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True)
    with gzip.open(p,'wb') as stream:
        writer=pickle.Pickler(stream,protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table={**copyreg.dispatch_table,MappingProxyType:reduce_mapping}
        writer.dump(v)
def cache_read(p):
    with gzip.open(p,'rb') as stream: return pickle.load(stream)
