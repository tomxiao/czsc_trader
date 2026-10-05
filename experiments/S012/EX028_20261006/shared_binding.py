"""Bind a new public runtime plan to identical, already-prepared requests."""
from dataclasses import replace
from pathlib import Path
from hashlib import sha256
import json
from datetime import date
from strategy_runtime import StrategyInputBinding, StrategyRuntime, StrategyInit, TradableWindow

def baseline(root):
    exp=Path(root)/'experiments/S012/EX023_20261005'
    workspace=exp/'artifacts/rex'
    if not (workspace/'trials.json').is_file():workspace=Path(root)/'.tmp/s012-stage3-20261005/EX023_20261005/execution'
    trial=json.loads((workspace/'trials.json').read_text(encoding='utf-8'))[0]
    artifact=trial['record']['result_artifact']
    path=workspace/artifact['path'];assert sha256(path.read_bytes()).hexdigest()==artifact['sha256']
    result=json.loads(path.read_text(encoding='utf-8'))
    support=result['runs'][0]['signal_support']
    binding=StrategyInputBinding.from_mapping(support['input_binding'])
    return binding,{'result_path':path.relative_to(root).as_posix(),'result_sha256':artifact['sha256'],'candidate':trial['candidate_id']}

def for_candidate(context,candidate,prior,calendar):
    # New typed identity is derived by the public runtime. Reusing preparation
    # is permitted only when every public planned DataRequest is identical.
    instance=StrategyRuntime().create(StrategyInit(candidate,TradableWindow(date(2020,6,8),date(2026,9,30)),context.workspace.path('calculation_contexts/'+candidate.candidate_id)))
    plan=instance.plan_inputs(calendar)
    if (dict(plan.requests)!=dict(prior.plan.requests) or plan.calendar_sha256!=prior.plan.calendar_sha256
            or plan.calendar_dates!=prior.plan.calendar_dates or dict(plan.signal_dates)!=dict(prior.plan.signal_dates)
            or plan.calculation_dates!=prior.plan.calculation_dates):
        raise ValueError('public input requests changed; shared preparation cannot be reused')
    return StrategyInputBinding(plan,prior.prepared)
