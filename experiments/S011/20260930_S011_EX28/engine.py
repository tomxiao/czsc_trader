"""Research-only spawn dispatch of the unchanged public evaluation API."""
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from types import MappingProxyType
from threading import Lock
import copyreg
import os
import pickle
import time
from strategy_runtime import StrategyRuntime
from czsc_trader.research_tools import evaluate_strategy
from dotenv import load_dotenv

def restore_mapping(value):
    return MappingProxyType(value)

def reduce_mapping(value):
    return restore_mapping,(dict(value),)

# Lossless transport of immutable public contract fields, without changing APIs.
copyreg.pickle(type(MappingProxyType({})),reduce_mapping)

def describe(candidate):
    roundtrip=pickle.loads(pickle.dumps(candidate))
    assert dict(roundtrip.payload)==dict(candidate.payload)
    definition=StrategyRuntime().describe(roundtrip)
    try:roundtrip.payload['illegal']=True
    except TypeError:pass
    else:raise AssertionError('immutable transport lost')
    time.sleep(.1)
    return os.getpid(),definition.tradable_symbol

def compute(request):
    load_dotenv(request.repository_root/'.env',override=False)
    started=time.time(); result=evaluate_strategy(request)
    return result,{'pid':os.getpid(),'started':started,'finished':time.time()}

class Dispatcher:
    def __init__(self,workers):
        self.pool=ProcessPoolExecutor(max_workers=workers,mp_context=get_context('spawn'))
        self.lock=Lock();self.last_start=0.;self.records={}
    def precheck(self,candidate):
        values=list(self.pool.map(describe,[candidate]*32))
        assert all(symbol=='159326.SZ' for _,symbol in values)
        return {'transport':'PICKLE_IMMUTABLE_MAPPING_ROUNDTRIP','worker_pids':sorted({pid for pid,_ in values})}
    def __call__(self,request):
        with self.lock:
            delay=max(0.,10-(time.monotonic()-self.last_start))
            if delay:time.sleep(delay)
            self.last_start=time.monotonic()
            future=self.pool.submit(compute,request)
        result,record=future.result()
        with self.lock:self.records[request.strategy.candidate_id]=record
        return result
    def close(self):
        self.pool.shutdown(wait=True,cancel_futures=True)
