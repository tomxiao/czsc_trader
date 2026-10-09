from datetime import date
import json
import time
from uuid import UUID
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, PreparedDataRef, DataCoverageRequirement
from czsc_trader.application import publish_evidence
from czsc_trader.research_tools import MaterialEvidenceWrite, EvaluationEvidenceWrite
from czsc_trader.research_tools.context import ExperimentRef
from common import ROOT,BASE,context,request,save,candidate,cache_write, PROTOCOLS, SRC
import importlib.util
from strategy_runtime import ParameterSet, StrategyRuntime
spec=importlib.util.spec_from_file_location('s013_precheck_author',SRC/'strategy_runtime/strategies/range_reversion.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
RangeReversion,components=module.RangeReversion,module.components

def main():
    research=context()
    exp=ExperimentRef('S013','EX003_20261007')
    protocol=publish_evidence(research,MaterialEvidenceWrite(exp,'stage3-protocol',
        (PROTOCOLS/'protocol.md').read_bytes(),'text/markdown','md'))
    save('protocol_reference.json',protocol.to_dict(), directory=PROTOCOLS)
    rec=json.loads((ROOT/'research/S013/assets/runs/EX002_20261007/historical/data_preparation.json').read_text(encoding='utf-8'))
    raw=rec['daily']['reference']
    prepared=PreparedDataRef(UUID(raw['space_id']),UUID(raw['preparation_id']),raw['manifest_sha256'])
    req=DataRequest(Dataset.ETF_OHLCV,'510500.SH',rec['warmup_start'],'2026-09-30','2026-09-30',
        coverage=DataCoverageRequirement(maximum_start_lag_days=None,minimum_sessions=60,observations_through='2019-12-31'))
    fetched=research.data.fetch(req,prepared=prepared)
    assert fetched.ready
    frame=fetched.dataframe
    feat=components(frame)
    prior=pd.read_csv(ROOT/'research/S013/assets/runs/EX002_20261007/historical/component_observations.csv',float_precision='round_trip')
    prior.index=pd.DatetimeIndex(pd.to_datetime(prior.Date))
    errors={}
    for own,old in [('range_position','range_position_60'),('acf1','tsfresh20_autocorrelation__lag_1')]:
        aligned=feat[own].reindex(prior.index).to_numpy()
        reference=prior[old].to_numpy()
        assert np.allclose(aligned,reference,rtol=1e-12,atol=1e-12,equal_nan=True)
        errors[own]=float(np.nanmax(np.abs(aligned-reference)))
    algorithm=RangeReversion.from_parameters(ParameterSet(BASE))
    sessions=pd.DatetimeIndex(pd.to_datetime(frame.Date))[-1637:-1]
    full=algorithm.calculate_history({'daily':frame},sessions)
    for end in [sessions[120],sessions[470],sessions[1000]]:
        prefix=frame.loc[pd.to_datetime(frame.Date)<=end]
        actual=algorithm.calculate_history({'daily':prefix},sessions[sessions<=end])
        pd.testing.assert_frame_equal(full.loc[:end],actual)
    StrategyRuntime().describe(candidate(1,BASE))
    save('implementation_precheck.json',{'status':'PASS','component_max_errors':errors,
        'causal_prefix_checks':3,'sessions':len(sessions),'terminal_signal':str(sessions[-1].date())})
    print(json.dumps({'component_checks':'PASS','max_errors':errors}),flush=True)
    start=time.perf_counter()
    bound=research.evaluation.prepare(request(1,BASE))
    print(json.dumps({'preparation_seconds':time.perf_counter()-start,'execution_data':bound.execution_data.fingerprint}),flush=True)
    start=time.perf_counter()
    result=research.evaluation.evaluate(bound)
    elapsed=time.perf_counter()-start
    run=result.runs[0]
    print(json.dumps({'evaluation_seconds':elapsed,'observation':run.observation.to_dict(),
        'account_columns':list(run.execution.account_daily.columns),'trade_columns':list(run.execution.trades.columns),
        'order_columns':list(run.execution.orders.columns),'fill_columns':list(run.execution.fills.columns),
        'account_n':len(run.execution.account_daily),'buyhold_metrics':run.buyhold.metrics},default=str),flush=True)
    evidence=publish_evidence(research,EvaluationEvidenceWrite(exp,'initial-range-account',bound,result))
    save('initial_account_reference.json',evidence.to_dict())
    # Private, ephemeral transport for independently checking public API parallel replay.
    cache_write(ROOT/'.tmp/s013-stage3/precheck.pkl.gz',(bound,result))
    save('initial_timing.json',{'formal_evaluation_seconds':elapsed,'result_hash':result.result_hash})

if __name__=='__main__':
    main()
