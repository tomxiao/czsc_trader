"""Selected short-cycle public accounts and independent synthetic preflight.

Selection is derived after event analysis, not an entry rule optimization or an
independent validation. This module never runs accounts merely by importing it.
"""

import argparse
from dataclasses import asdict
from datetime import date, datetime, time, timedelta
import json
import multiprocessing as mp
import pickle
from time import perf_counter
from zoneinfo import ZoneInfo

from common import (EXPERIMENT, NAMES, PREP, ROOT, SPEC, WORK, candidate, context,
                    digest, material, read, request, save)
from czsc_trader.application import publish_evidence_many
from czsc_trader.research_tools import (CheckpointMode, EvaluationEvidenceWrite,
                                      EvidenceRef, ExecutionCheckpointRequest,
                                      ResearchExecutionSession)
from dataflows import BarFrequency, TimeInterval, TradingSession
from strategy_runtime import StrategyRuntime
from trading_execution_engine.equity import EquityHistoricalExecutor


RESULT_TABLES = ('decisions', 'orders', 'fills', 'corporate_action_entries',
                 'account_points', 'account_daily', 'trades')
SOURCE = WORK / 'src'


def configurations():
    selection = read(WORK / 'others/selection.json')
    selected = selection['selected_mechanisms']
    if (not isinstance(selected, list) or len(selected) > 2
            or len(set(selected)) != len(selected) or not set(selected) <= set(NAMES)):
        raise ValueError('Selection must contain at most two unique new mechanisms')
    result = {}
    for mechanism in selected:
        for horizon in (6, 13):
            key = f'C{51 + len(result):04d}'
            result[key] = {'entry_mechanism': mechanism, 'max_holding_bars': horizon}
    return result


def initialize():
    values = configurations()
    candidates = {key: candidate(key, parameters) for key, parameters in values.items()}
    definitions = {'schema': 's017-event-selected-prototypes/v1',
        'selected_after_event_results': True,
        'selection_sha256': digest(WORK / 'others/selection.json'),
        'interpretation': 'Resource allocation after same-development-pool event analysis; not independent validation.',
        'candidates': {key: value.definition.to_dict() for key, value in candidates.items()}}
    for name, value in (('configurations', values), ('definitions', definitions)):
        path = WORK / f'protocols/{name}.json'
        canonical = json.loads(json.dumps(value, default=str))
        if path.exists() and read(path) != canonical:
            raise ValueError(f'Frozen {name} changed after initialization')
        if not path.exists():
            save(path, value)
    return candidates


def _fixture():
    """Wholly synthetic session grid and repeated three-mechanism prices."""
    import pandas as pd

    zone = ZoneInfo('America/New_York')
    days, day = [], date(2018, 10, 1)
    while len(days) < 52:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    calendars = tuple(TradingSession(day, str(zone), (TimeInterval(
        datetime.combine(day, time(9, 30), zone),
        datetime.combine(day, time(16), zone)),)) for day in days)
    rows, previous = [], 100.
    for session in calendars:
        for bar in session.bars(BarFrequency.M30):
            phase = len(rows) % 30
            if phase <= 11:
                close = 100. + phase * .4
            elif phase == 12:
                close = 104.1
            elif phase == 13:
                close = 103.8
            elif phase == 14:
                close = 104.7
            else:
                close = 104.7 - (phase - 14) * .3
            opening, low = previous, min(previous, close) - .12
            if phase == 22:
                close = opening + .4
                low = min(row['Low'] for row in rows[-6:]) - .5
            rows.append(dict(BarStart=bar.start, Date=bar.end, AvailableDate=bar.end,
                Open=opening, High=max(opening, close) + .12, Low=low, Close=close,
                Volume=100000., Amount=close * 100000.))
            previous = close
    bars = pd.DataFrame(rows)
    for field in ('BarStart', 'Date', 'AvailableDate'):
        bars[field] = pd.to_datetime(bars[field], utc=True)
    constraints = pd.DataFrame(dict(Date=bars.BarStart, AvailableDate=bars.BarStart,
        QuantityStep=1, PriceTick=.01, Tradable=True))
    sessions = pd.DataFrame(dict(Date=[session.segments[0].start for session in calendars],
        AvailableDate=[session.segments[0].start for session in calendars],
        SessionDate=[session.session_date.isoformat() for session in calendars]))
    for field in ('Date', 'AvailableDate'):
        sessions[field] = pd.to_datetime(sessions[field], utc=True)
    stamp = bars.BarStart.iloc[0]
    actions = pd.DataFrame([dict(Date=stamp, AvailableDate=stamp, EventId='EX028-synthetic-none',
        Kind='NONE', Ratio=1., CashPerShare=0., PayAt=None)])
    start = calendars[22].segments[0].start
    end = calendars[44].segments[-1].end
    return bars, constraints, sessions, calendars, actions, start, end


def _replay(job):
    from hashlib import sha256
    from strategy import entry_facts

    cand, parameters, changed = job
    bars, constraints, sessions, calendars, actions, start, end = _fixture()
    if changed:
        suffix = bars.Date > end
        if not suffix.any():
            raise ValueError('Synthetic future perturbation requires a suffix')
        bars.loc[suffix, ['Open', 'High', 'Low', 'Close']] *= 7
        bars.loc[suffix, 'Volume'] *= 11
        bars.loc[suffix, 'Amount'] *= 77
    executor = EquityHistoricalExecutor(specification=SPEC, initial_cash=100000., fee_rate=.001, actions=actions)
    result = StrategyRuntime(execution_spec=SPEC).create(cand).run_window(
        bars, constraints, executor, start=start, end=end, fee_rate=.001,
        sessions=sessions, trading_sessions=calendars)
    hashes = {name: sha256(getattr(result, name).to_json(
        date_format='iso', double_precision=15).encode()).hexdigest() for name in RESULT_TABLES}
    buys = result.fills.loc[result.fills.side.eq('BUY')]
    if buys.empty or result.trades.empty:
        raise ValueError('Synthetic replay did not exercise actual filled and closed cycles')
    for fill in buys.itertuples():
        visible = bars.loc[(bars.Date <= fill.interval_start) & (bars.AvailableDate <= fill.interval_start)]
        if not entry_facts(visible, parameters['entry_mechanism'])['entry_signal']:
            raise ValueError('Actual synthetic fill is not anchored to its entry mechanism')
    exits = []
    intervals = {bar for session in calendars for bar in session.bars(BarFrequency.M30)}
    for row in result.decisions.itertuples():
        if TimeInterval(row.execution_start, row.execution_end) not in intervals:
            raise ValueError('Synthetic decision escaped its session grid')
        if not isinstance(row.explanation, dict):
            raise ValueError('Synthetic decision lacks structured explanation')
        facts = {item['key']: item['text'] for item in row.explanation['basis']}
        if facts.get('held') == 'True' and float(row.target) == 0:
            count = int(facts['holding_bars'])
            if count != parameters['max_holding_bars']:
                raise ValueError('Actual-fill holding counter differs from frozen horizon')
            exits.append(count)
    if not exits:
        raise ValueError('Synthetic timed exit was not exercised')
    return {'economic_hashes': hashes, 'decisions': len(result.decisions), 'fills': len(result.fills),
        'actual_entries': len(buys), 'closed_cycles': len(result.trades),
        'timed_exit_counts': exits, 'all_actual_buys_signal_anchored': True,
        'all_decisions_on_session_grid': True}


def precheck():
    started = perf_counter()
    candidates = initialize()
    values = configurations()
    if not candidates:
        result = {'status': 'NOT_RUN', 'reason': 'No event-qualified mechanisms selected',
            'real_account_evaluations': 0, 'strategy_source_sha256': digest(SOURCE / 'strategy.py'),
            'accounts_source_sha256': digest(SOURCE / 'accounts.py'),
            'selection_sha256': digest(WORK / 'others/selection.json')}
        save(WORK / 'others/precheck_accounts.json', result)
        return result
    jobs = [(cand, values[key], False) for key, cand in candidates.items()]
    for cand in candidates.values():
        definition = cand.definition
        if (definition.warmup_bars != 261 or definition.feedback_mode != 'CONFIRMED_EXECUTION'
                or definition.session_context or definition.auxiliary_inputs):
            raise ValueError('Synthetic candidate contract changed')
        if pickle.loads(pickle.dumps(cand)) != cand:
            raise ValueError('Candidate serialization changed')
    serial = [_replay(job) for job in jobs]
    altered = [_replay((cand, parameters, True)) for cand, parameters, _ in jobs]
    if serial != altered:
        raise ValueError('Future suffix changed an earlier public economic table')
    with mp.get_context('spawn').Pool(2) as pool:
        parallel = pool.map(_replay, jobs)
    if parallel != serial:
        raise ValueError('Spawn and serial public economic tables differ')
    result = {'status': 'PASS', 'scope': 'SYNTHETIC_PUBLIC_SRT_TXE_ONLY',
        'strategy_source_sha256': digest(SOURCE / 'strategy.py'),
        'accounts_source_sha256': digest(SOURCE / 'accounts.py'),
        'common_source_sha256': digest(SOURCE / 'common.py'),
        'selection_sha256': digest(WORK / 'others/selection.json'),
        'configurations_sha256': digest(WORK / 'protocols/configurations.json'),
        'definitions_sha256': digest(WORK / 'protocols/definitions.json'),
        'public_serial_equals_spawn': True, 'future_suffix_invariance': True,
        'candidate_pickle': True, 'max_spawn_workers': 2, 'native_threads': 1,
        'compared_result_tables': list(RESULT_TABLES), 'real_account_evaluations': 0,
        'candidates': dict(zip(candidates, serial, strict=True)), 'seconds': perf_counter() - started}
    save(WORK / 'others/precheck_accounts.json', result)
    print('SYNTHETIC_PRECHECK_PASS', sorted(candidates), flush=True)
    return result


def _checked_precheck():
    checked = read(WORK / 'others/precheck_accounts.json')
    files = {'strategy_source_sha256': SOURCE / 'strategy.py',
        'accounts_source_sha256': SOURCE / 'accounts.py',
        'common_source_sha256': SOURCE / 'common.py',
        'selection_sha256': WORK / 'others/selection.json',
        'configurations_sha256': WORK / 'protocols/configurations.json',
        'definitions_sha256': WORK / 'protocols/definitions.json'}
    if checked['status'] != 'PASS' or any(checked[key] != digest(path) for key, path in files.items()):
        raise ValueError('Source-bound synthetic public precheck must pass before real accounts')
    return checked


def run(mode='CREATE'):
    mode = CheckpointMode(mode)
    candidates = initialize()
    if not candidates:
        save(WORK / 'others/accounts.json', {})
        save(WORK / 'others/execution_status.json', [])
        save(WORK / 'others/publication_status.json', [])
        result = {'status': 'NOT_RUN', 'reason': 'No event-qualified mechanisms selected',
            'new_strategy_accounts': 0, 'new_benchmark_accounts': 0}
        save(WORK / 'others/account_run_status.json', result)
        print('ACCOUNTS_NOT_RUN_NO_SELECTED_MECHANISMS', flush=True)
        return result
    _checked_precheck()
    research = context(2)
    files = [(name, path) for name, path in (
        ('account-source', SOURCE / 'accounts.py'), ('strategy-source', SOURCE / 'strategy.py'),
        ('common-source', SOURCE / 'common.py'), ('event-selection', WORK / 'others/selection.json'),
        ('account-configurations', WORK / 'protocols/configurations.json'),
        ('account-definitions', WORK / 'protocols/definitions.json'),
        ('account-precheck', WORK / 'others/precheck_accounts.json'),
        ('prepared-reference', PREP), ('design', WORK / 'protocols/design.md'),
        ('authorization', WORK / 'protocols/authorization.md'))]
    frozen = WORK / 'others/pre_account_evidence.json'
    if frozen.exists():
        if mode is not CheckpointMode.RESUME:
            raise ValueError('Frozen account run exists; explicit RESUME required')
        before = read(frozen)
        if set(before) != {name for name, _ in files}:
            raise ValueError('Frozen account input set changed')
        for name, path in files:
            reference = EvidenceRef.from_dict(before[name])
            if digest(reference.resolve(ROOT)) != digest(path):
                raise ValueError('Frozen account input changed: ' + name)
    else:
        if mode is not CheckpointMode.CREATE:
            raise ValueError('No frozen account run to resume')
        save(frozen, {name: material(research, name, path).to_dict() for name, path in files})
    requests = []
    for key, cand in candidates.items():
        requests.append(research.evaluation.prepare(request(cand)))
        print('ACCOUNT_PREPARED', key, flush=True)

    def progress(event):
        print(json.dumps(asdict(event), default=str), flush=True)

    with ResearchExecutionSession(research, experiment=EXPERIMENT,
            checkpoint=ExecutionCheckpointRequest(EXPERIMENT.experiment_id, mode), on_progress=progress) as execution:
        outcomes = research.evaluation.evaluate_many(tuple(requests), execution=execution)
        statuses = [{'candidate': req.candidate.candidate_id, 'status': outcome.status.value,
            'error': None if outcome.error is None else asdict(outcome.error)}
            for req, outcome in zip(requests, outcomes, strict=True)]
        save(WORK / 'others/execution_status.json', statuses)
        save(WORK / 'others/execution_stats.json', asdict(execution.stats))
        if any(outcome.status.value != 'SUCCEEDED' for outcome in outcomes):
            raise RuntimeError(statuses)
        writes = tuple(EvaluationEvidenceWrite(EXPERIMENT, 'account-' + req.candidate.candidate_id,
            req, outcome.result) for req, outcome in zip(requests, outcomes, strict=True))
        published = publish_evidence_many(research, writes, execution=execution)
        save(WORK / 'others/publication_status.json', [asdict(item) for item in published])
        save(WORK / 'others/execution_stats.json', asdict(execution.stats))
        if any(item.status.value != 'PUBLISHED' for item in published):
            raise RuntimeError('Account evidence publication failed')
        rows = {}
        for req, outcome, publication in zip(requests, outcomes, published, strict=True):
            value = outcome.result.payload
            rows[req.candidate.candidate_id] = {'evidence': publication.reference.to_dict(),
                'evaluation_identity': value['evaluation_identity'], 'evaluation_id': value['evaluation_id'],
                'request_hash': outcome.result.request_hash, 'execution_status': outcome.status.value,
                'publication_status': publication.status.value, 'candidate': value['runs']['candidate']['metrics'],
                'buy_hold': value['runs']['buy_hold']['metrics']}
        save(WORK / 'others/accounts.json', rows)
        save(WORK / 'others/account_run_status.json', {'status': 'PUBLISHED',
            'new_strategy_accounts': len(rows), 'new_benchmark_accounts': len(rows),
            'selection_after_event_results': True, 'independent_validation': False})
        print('ACCOUNTS_PUBLISHED', sorted(rows), flush=True)
        return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('init', 'precheck', 'run'))
    parser.add_argument('--mode', choices=('CREATE', 'RESUME'), default='CREATE')
    args = parser.parse_args()
    if args.action == 'init':
        initialize()
    elif args.action == 'precheck':
        precheck()
    else:
        run(args.mode)
