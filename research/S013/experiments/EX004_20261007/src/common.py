from datetime import date
from pathlib import Path
import json
import copyreg
import gzip
import pickle
from importlib.metadata import version
from types import MappingProxyType
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import ResearchBatchRef, EvaluationResources, EvaluationRequest, EvaluationWindow, EvaluationCost
from czsc_trader.research_tools import EvaluationBenchmark, NextOpenBuyHold, ExecutionPriceBasis
from strategy_runtime import StrategyCandidate, implementation_sha256, ImplementationDependency

SRC = Path(__file__).resolve().parent
ROOT = SRC.parents[4]
RUNS = ROOT / 'research/S013/assets/runs/EX004_20261007/historical'
PROTOCOLS = SRC.parent / 'protocols'
OTHERS = SRC.parent / 'others'
SOURCE=SRC/'strategy_runtime'
EXTENDED_SOURCE=SRC/'extended_window/strategy_runtime'
FILES=('strategies/range_reversion.py',)
DEPENDENCIES=tuple(ImplementationDependency(name,version(name)) for name in ('numpy','pandas','czsc-strategy-runtime'))
BASE={'range_window':60,'entry':.35,'exit':.75,'max_hold':8,'acf_min':None,
      'stop_loss':None,'trailing_stop':None,'cooldown':0,'momentum_min':None,'limit_premium':.002}

def save(name, value, *, directory=RUNS):
    (directory / name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')

def _mapping(value):
    return MappingProxyType(value)

def _reduce_mapping(value):
    return _mapping,(dict(value),)

def cache_write(path,value):
    with gzip.open(path,'wb') as handle:
        writer=pickle.Pickler(handle,protocol=pickle.HIGHEST_PROTOCOL)
        writer.dispatch_table={**copyreg.dispatch_table,MappingProxyType:_reduce_mapping}
        writer.dump(value)

def cache_read(path):
    with gzip.open(path,'rb') as handle:
        return pickle.load(handle)

def context(max_workers=8):
    return create_research_context(RepositoryContext.discover(ROOT),ResearchBatchRef('S013'),
        resources=EvaluationResources(max_workers,1,13))

def candidate(number,parameters):
    source = EXTENDED_SOURCE if parameters['range_window'] > 180 else SOURCE
    return StrategyCandidate('S013',f'C{number:04}',{
        'runtime':{'module':'strategy_runtime.strategies.range_reversion','qualname':'RangeReversion',
                   'contract_version':1,'source_files':list(FILES),
                   'source_sha256':implementation_sha256(FILES,source_root=source)},
        'parameters':parameters},source_root=source)

def request(number,parameters,execution_data=None,dependencies=DEPENDENCIES):
    c=candidate(number,parameters)
    return EvaluationRequest(ROOT,'EX004_20261007',c,
        {'candidate_id':c.reference_id,'source_files':list(FILES),
         'implementation_sha256':c.payload['runtime']['source_sha256']},'510500.SH','etf',
        (EvaluationWindow('full',date(2020,1,2),date(2026,9,30)),),date(2026,9,30),1_000_000,
        (EvaluationCost('baseline',.001,'FORMAL'),),execution_data=execution_data,
        benchmark=EvaluationBenchmark(NextOpenBuyHold(100)),workers=1,frequency_window_days=60,execution_mode='FULL',
        dependencies=dependencies, price_basis=ExecutionPriceBasis.HFQ_RESEARCH)
