"""Retained real observations and audited RAW facts for S001 correction accounts."""
from copy import deepcopy
from datetime import date, datetime, time
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import (BarFrequency, Dataset, EquityFrequencyFacts, EquitySourceCoverage,
    ProviderBinding, ProviderConfig, SourceRef, TimeInterval, versioned_equity_bindings)
from strategy_runtime import ExecutionResources
from czsc_trader.application import RepositoryContext, create_research_context
from czsc_trader.research_tools import (EquityEvaluationRequest, EquitySources, EquityBuyHold,
    EvaluationBenchmark, ResearchBatchRef)

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))
from research.S001.runtime_upgrade_v4.build import build_candidate

INPUT = ROOT/'.tmp/s001-v4-correction/inputs'
ZONE = ZoneInfo('Asia/Shanghai')
IDENTITY = json.loads((INPUT/'input_identity.json').read_text(encoding='utf-8'))
FRAMES = {key: pd.read_parquet(INPUT/f'{key}.parquet') for key in IDENTITY['inputs']}
SOURCE = SourceRef('s001-audited-retained-raw', '20261106-completed-week-v1')


def at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), ZONE)


def retained_observation(query):
    if query.dataset is Dataset.TRADING_CALENDAR:
        key = 'calendar'
    else:
        if query.symbol != '588080.SH':
            raise ValueError('retained S001 source only covers 588080.SH')
        key = {'daily': 'daily', '30m': 'm30', 'weekly': 'weekly'}[query.frequency]
    first, last = pd.Timestamp(query.start), pd.Timestamp(query.end)
    upper = pd.Timestamp('2026-11-26' if key == 'calendar' else '2026-11-05')
    if first < pd.Timestamp('2020-11-16') or last > upper:
        raise ValueError('request exceeds authenticated retained source coverage')
    source = FRAMES[key]
    days = pd.to_datetime(source.Date).dt.normalize()
    frame = source.loc[days.between(first, last)].copy()
    metadata = deepcopy(IDENTITY['inputs'][key]['identity']['metadata'])
    metadata['retained_parent_content_sha256'] = IDENTITY['inputs'][key]['identity']['content_sha256']
    metadata['retained_parent_preparation'] = IDENTITY['prepared_ref']
    metadata['retained_selection_rule'] = 'Exact row selection; calendar resolves completed weekly cutoff before request'
    return frame, metadata


def build_context(version, *, extra_bindings=None):
    candidate = build_candidate(version)
    helper = ROOT/'.tmp/rsch-frozen-v4-upgrade/run_s003_s007_accounts.py'
    spec = importlib.util.spec_from_file_location('s001_raw_retained_helper', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    raw, rules = module.bars_and_rules('S007', BarFrequency.DAILY)
    raw['AvailableDate'] = [at(day, 17) for day in raw.Date.dt.date]
    first, last = date(2026,8,1), date(2026,11,5)
    stamp = module.sessions[0].segments[0].start
    actions = pd.DataFrame([dict(Date=stamp, AvailableDate=stamp,
        EventId='S001-verified-none-aug-nov2026', Kind='NONE', Ratio=1., CashPerShare=0., PayAt=None)])
    proof = {'corporate_actions': module.evidence, 'symbol': '588080.SH',
        'raw_source': 'same retained S007 588080 RAW tables, independent SSE sessions and dated ETF limits',
        'observation_source_manifest_sha256': sha256((INPUT/'input_identity.json').read_bytes()).hexdigest(),
        'scope': 'RSCH retained history only; no production source enablement'}
    bindings = versioned_equity_bindings(instrument=candidate.instrument, source=SOURCE,
        coverage=EquitySourceCoverage(first,last,json.dumps(proof,sort_keys=True),True,True),
        sessions=module.sessions, frequencies=(EquityFrequencyFacts(BarFrequency.DAILY,raw,rules),), actions=actions)
    tables = {item: ProviderBinding('s001-retained-real-observation', '20261106-v1', retained_observation)
              for item in (Dataset.ETF_OHLCV, Dataset.TRADING_CALENDAR)}
    tables.update(extra_bindings or {})
    context = create_research_context(RepositoryContext.discover(ROOT), ResearchBatchRef('S001'),
        providers=ProviderConfig(bindings=tables,equity_bindings=bindings),
        execution_spec=candidate.definition.execution_spec,resources=ExecutionResources(1,1,17))
    return context, candidate


def build_request(context,candidate,experiment,*,start=date(2026,9,4),end=date(2026,11,5),window_id='CORRECTED_FORWARD'):
    return EquityEvaluationRequest(experiment,candidate,TimeInterval(at(start,9,30),at(end,15)),date(2026,8,1),
        EquitySources(SOURCE,SOURCE,SOURCE,SOURCE),100000.,.0005,
        benchmark=EvaluationBenchmark(EquityBuyHold(candidate.definition.execution_spec)),
        drawdown_basis='SESSION_CLOSE',concentration_basis='TOP_DECILE',window_id=window_id,scenario_id='STANDARD')
