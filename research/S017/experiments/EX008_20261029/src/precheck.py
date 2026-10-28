"""EX008 mechanism preflight; synthetic comparisons and bounded prepared-data read."""
from dataclasses import replace
from datetime import date
from hashlib import sha256
import importlib.util
import json
from math import fsum
import os
from pathlib import Path
import pickle
import sys
from uuid import UUID

from dataflows import PreparedDataRef, EquityDataRequest, EquityQuery, EquityProduct
from strategy_runtime import EquityStrategyDefinition, StrategyRuntime

WORK = Path(__file__).resolve().parents[1]
ROOT = WORK.parents[3]
SOURCES = {}


def load(name, path):
    SOURCES[str(path.relative_to(ROOT))] = sha256(path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


RUN = load('_s017_ex008_runner', WORK/'src/run.py')
NEW = load('_s017_ex008_strategy', WORK/'src/strategy.py')
PRIOR = load('_s017_ex008_prior_check', ROOT/'research/S017/experiments/EX007_20261029/src/precheck.py')
SOURCES.update(PRIOR.SOURCES)
CHECK, OLD = PRIOR.CHECK, PRIOR.NEW
CONFIGS = RUN.configurations()
NONE = {**CONFIGS['C0031'], 'recovery_gate':'NONE'}


def context(frame, account, parameters):
    return replace(PRIOR.context(frame, account), parameters=parameters)


def arithmetic(frame, parameters):
    values = [float(x) for x in frame.Close]
    count, lag = parameters['background_bars'], parameters['background_slope_bars']
    position = len(values)-1
    current = fsum(values[i] for i in range(position-count, position))/count
    previous = fsum(values[i] for i in range(position-lag-count, position-lag))/count
    return current, previous


def background_boundaries():
    frame = CHECK.synthetic().iloc[:326].copy()
    frame[['Open', 'Close']] = 100.
    frame['High'], frame['Low'] = 101., 99.
    checks = 0
    for mark in (99.999, 100., 100.001):
        frame.loc[frame.index[-1], 'Close'] = mark
        for key, parameters in CONFIGS.items():
            state = NEW.recovery_background(frame, parameters)
            expected = mark > 100. and key == 'C0031'
            CHECK.require(state['background_allowed'] == expected, 'strict mean equality or flat slope differs')
            CHECK.close(state['prior_mean'], 100., 'current close leaked into prior mean')
            CHECK.close(state['lagged_prior_mean'], 100., 'flat lagged mean differs')
            checks += 1
    frame.loc[frame.index[:65], 'Close'] = 200.
    frame.loc[frame.index[-1], 'Close'] = 101.
    positive = NEW.recovery_background(frame, CONFIGS['C0031'])
    negative = NEW.recovery_background(frame, CONFIGS['C0032'])
    CHECK.require(positive['background_allowed'] and not negative['background_allowed'],
                  'negative slope must distinguish C0031 from C0032')
    CHECK.close(positive['prior_mean'], 100., 'position boundary')
    CHECK.close(positive['lagged_prior_mean'], 125., 'negative slope arithmetic')
    frame.loc[frame.index[:65], 'Close'] = 50.
    CHECK.require(NEW.recovery_background(frame, CONFIGS['C0032'])['background_allowed'],
                  'positive slope incorrectly rejected')
    for parameters in CONFIGS.values():
        PRIOR.rejected(lambda p=parameters: NEW.recovery_background(frame.iloc[-325:], p), 'insufficient completed history')
        NEW.recovery_background(frame, parameters)
    PRIOR.rejected(lambda: NEW.recovery_background(frame, {**NONE, 'recovery_gate':'INVALID'}), 'unsupported recovery background')
    return {'strict_equality_cases':checks, 'negative_slope_C0031':True, 'negative_slope_C0032':False,
            'positive_slope_C0032':True, 'minimum_history':326, '325_rejected':True,
            'independent_lagged_mean':125.}


def prefix_arithmetic_and_control():
    frame = CHECK.synthetic().iloc[:455].copy()
    first = 390
    held = PRIOR.account(frame.BarStart.iloc[first].to_pydatetime(), float(frame.Close.iloc[first]), 10)
    frame.loc[frame.index[first+10:first+14], 'Close'] *= 1.2
    frame.loc[frame.index[first+20:first+23], 'Close'] *= .6
    frame['High'] = frame[['High','Close']].max(axis=1)
    frame['Low'] = frame[['Low','Close']].min(axis=1)
    mean_count = decisions = 0
    for stop in range(326, len(frame)+1):
        prefix = frame.iloc[:stop]
        expected, earlier = arithmetic(prefix, CONFIGS['C0031'])
        for parameters in CONFIGS.values():
            actual = NEW.recovery_background(prefix, parameters)
            CHECK.close(actual['prior_mean'], expected, 'independent current mean')
            CHECK.close(actual['lagged_prior_mean'], earlier, 'independent lagged mean')
            altered = prefix.copy()
            altered.loc[altered.index[-1], 'Close'] = 100000.
            other = NEW.recovery_background(altered, parameters)
            CHECK.close(actual['prior_mean'], other['prior_mean'], 'current observation moved historical mean')
            CHECK.close(actual['lagged_prior_mean'], other['lagged_prior_mean'], 'current observation moved lagged mean')
            mean_count += 1
        portfolios = [PRIOR.account()]
        if stop > first:
            portfolios.append(held)
            CHECK.same_state(NEW.cycle_levels(prefix, held, NONE), PRIOR.ORACLE.oracle(prefix, held, PRIOR.PARAMETERS))
        for portfolio in portfolios:
            previous = OLD.decide(PRIOR.context(prefix, portfolio))
            current = NEW.decide(context(prefix, portfolio, NONE))
            CHECK.require(current.target == previous.target, 'NONE changed C0030 prefix target')
            for parameters in CONFIGS.values():
                restricted = NEW.decide(context(prefix, portfolio, parameters))
                CHECK.require(restricted.target == previous.target, 'held or no-history initial entry changed')
                if portfolio.quantity:
                    CHECK.require(restricted == previous, 'held explanation changed')
            decisions += 1
    retained, closed = PRIOR.fixture()
    for stop in range(395, len(retained)+1):
        prefix, portfolio = retained.iloc[:stop], PRIOR.account(latest=closed)
        CHECK.require(NEW.decide(context(prefix, portfolio, NONE)).target == OLD.decide(PRIOR.context(prefix, portfolio)).target,
                      'NONE changed C0030 recovery branch')
        CHECK.require(NEW.recovery_level(prefix, portfolio, NONE) == OLD.recovery_level(prefix, portfolio, PRIOR.PARAMETERS),
                      'background modification moved frozen recovery line')
        decisions += 1
    return {'independent_mean_prefixes':mean_count, 'NONE_branch_prefix_comparisons':decisions,
            'held_oracle_prefixes':len(frame)-first, 'recovery_prefixes':len(retained)-394}


def unfiltered_breakout_and_gate_wiring():
    # Earliest 65 observations make the lagged mean higher, but they are outside
    # the unchanged 260-bar breakout. The initial breakout must still buy.
    frame = CHECK.synthetic().iloc[:326].copy()
    frame[['Open','High','Low','Close']] = 100.
    frame.loc[frame.index[:65], ['Open','High','Low','Close']] = 200.
    frame.loc[frame.index[-1], ['Open','High','Low','Close']] = 101.
    CHECK.require(not NEW.recovery_background(frame, CONFIGS['C0032'])['background_allowed'], 'fixture must block slope gate')
    CHECK.require(NEW.decide(context(frame, PRIOR.account(), CONFIGS['C0032'])).target == 1,
                  'background gate incorrectly suppressed original breakout')
    # Keep a genuine closed-cycle fixture, change only earlier closes outside its
    # entry ATR prefix. This changes background direction without changing the
    # first stop or creating an original breakout.
    history, closed = PRIOR.fixture()
    history = history.iloc[:396].copy()
    history.loc[history.index[70:135], 'Close'] = 200.
    history['High'] = history[['High','Close']].max(axis=1)
    flat = PRIOR.account(latest=closed)
    states = {key: NEW.recovery_background(history, p) for key,p in CONFIGS.items()}
    CHECK.require(states['C0031']['background_allowed'] and not states['C0032']['background_allowed'],
                  'closed-cycle fixture must isolate direction condition')
    CHECK.require(NEW.decide(context(history, flat, CONFIGS['C0031'])).target == 1, 'C0031 recovery entry wiring failed')
    CHECK.require(NEW.decide(context(history, flat, CONFIGS['C0032'])).target == 0, 'C0032 direction gate wiring failed')
    held = PRIOR.account(history.BarStart.iloc[-1].to_pydatetime(), 101., 10, closed)
    CHECK.require(NEW.decide(context(history, held, CONFIGS['C0032'])) == OLD.decide(PRIOR.context(history, held)),
                  'blocked background must not alter current holding')
    return {'negative_slope_initial_breakout_target':1, 'recovery_targets':{'C0031':1,'C0032':0},
            'blocked_background_does_not_exit_held':True}


def typed_loading_and_serialization():
    frame, closed = PRIOR.fixture()
    frame = frame.iloc[:396]
    portfolio = PRIOR.account(latest=closed)
    identities = []
    for key, parameters in CONFIGS.items():
        value = RUN.candidate(key, parameters)
        definition = EquityStrategyDefinition.from_dict(json.loads(json.dumps(value.definition.to_dict())))
        CHECK.require(definition == value.definition and definition.warmup_bars == 326, 'definition/history roundtrip differs')
        restored = pickle.loads(pickle.dumps(value))
        CHECK.require(restored == value, 'candidate pickle differs')
        ctx = context(frame, portfolio, parameters)
        direct = NEW.decide(ctx)
        CHECK.require(restored.decide(ctx) == direct, 'isolated actual loader differs')
        plan = StrategyRuntime(execution_spec=RUN.SPEC).create(restored).plan(frame, ctx.point.execution_interval, portfolio, fee_rate=.001)
        CHECK.require(plan.target == direct.target and plan.explanation == direct.explanation.to_dict(), 'plan changed decision')
        short = frame.iloc[-325:]
        PRIOR.rejected(lambda: StrategyRuntime(execution_spec=RUN.SPEC).create(restored).plan(
            short, ctx.point.execution_interval, portfolio, fee_rate=.001), 'insufficient candidate warmup')
        PRIOR.rejected(lambda: restored.decide(replace(ctx, portfolio=replace(portfolio, closed_cycle_feedback=None))),
                       'CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
        identities.append(value.content_identity.content_sha256)
    CHECK.require(len(set(identities)) == 2, 'nested configurations share identity')
    return {'definitions':2, 'candidate_pickle_roundtrips':2, 'actual_isolated_loads':2,
            'runtime_plans_without_execution':2, 'candidate_content_sha256':identities}


def actual_prepared_warmup():
    saved = RUN.read(ROOT/'research/S017/experiments/EX001_20261028/others/data_preparation_v2.json')
    identity = saved['reference']
    prepared = PreparedDataRef(UUID(identity['space_id']), UUID(identity['preparation_id']), identity['manifest_sha256'])
    query = EquityDataRequest(RUN.INSTRUMENT, RUN.SOURCE,
        EquityQuery(EquityProduct.BARS, date(2018,11,1), date(2025,12,31)))
    fetched = RUN.context().data.fetch(query, prepared=prepared)
    CHECK.require(fetched.ready, str(fetched.error))
    frame = fetched.dataframe
    local = frame.Date.dt.tz_convert('America/New_York')
    CHECK.require(local.min().date() == date(2018,11,1) and local.max().date() == date(2025,12,31), 'authorized dates differ')
    original = next(item for item in saved['items'] if item['product'] == EquityProduct.BARS.value)
    CHECK.require(fetched.identity.content_sha256 == original['sha256'], 'prepared bar hash differs')
    start = RUN.request(RUN.candidate('C0031', CONFIGS['C0031'])).window.start
    warmup = frame.loc[(frame.Date <= start) & (frame.AvailableDate <= start) & frame.BarStatus.eq('OBSERVED')]
    CHECK.require(len(warmup) == 508 and len(warmup) >= 326, 'actual 508-bar warmup changed or insufficient')
    CHECK.require(frame.BarStatus.eq('OBSERVED').all() and (frame.Volume > 0).all(), 'unexpected unavailable bar')
    CHECK.require(int(frame.ExecutionBlocked.sum()) == 5, 'known blocked bar count changed')
    for parameters in CONFIGS.values():
        actual = NEW.recovery_background(warmup, parameters)
        expected, earlier = arithmetic(warmup, parameters)
        CHECK.close(actual['prior_mean'], expected, 'prepared warmup current mean')
        CHECK.close(actual['lagged_prior_mean'], earlier, 'prepared warmup lagged mean')
    return {'reference':identity, 'public_fetch_calls':1, 'authorized_range':['2018-11-01','2025-12-31'],
            'content_sha256':fetched.identity.content_sha256, 'bars':len(frame), 'actual_pre_evaluation_bars':len(warmup),
            'old_declared_warmup':261, 'new_declared_warmup':326, 'actual_input_history_unchanged':True}


def check():
    scratch = ROOT/'.tmp/s017-ex008-precheck'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    cases = {}
    for name, function in (('arithmetic_and_strict_boundaries', background_boundaries),
                           ('prefix_causality_and_C0030_NONE', prefix_arithmetic_and_control),
                           ('breakout_holding_and_nested_gate_wiring', unfiltered_breakout_and_gate_wiring),
                           ('typed_contracts_and_actual_loader', typed_loading_and_serialization),
                           ('prepared_input_and_actual_warmup', actual_prepared_warmup)):
        try:
            cases[name] = {'status':'PASS', **function()}
        except Exception as exc:
            cases[name] = {'status':'FAIL', 'error_type':type(exc).__name__, 'error':str(exc)}
        print(cases[name]['status'], name, flush=True)
    unchanged = all(sha256((ROOT/path).read_bytes()).hexdigest() == digest for path,digest in SOURCES.items())
    cases['source_immutability'] = {'status':'PASS' if unchanged else 'FAIL', 'source_sha256':SOURCES}
    passed = sum(case['status'] == 'PASS' for case in cases.values())
    output = {'status':'PASS' if passed == len(cases) else 'FAIL', 'passed_groups':passed, 'total_groups':len(cases),
        'strategy_source_sha256':SOURCES[str((WORK/'src/strategy.py').relative_to(ROOT))],
        'precheck_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(), 'cases':cases,
        'scope':'Synthetic 2020 decision fixtures and one public fetch of pinned 2018-2025 development bars; no fills, account replay or 2026 market data.',
        'oracle':'Python fsum over explicit index ranges for means; retained EX005 sequential stop oracle and EX007 cycle fixtures loaded by exact importlib paths with source hashes.'}
    RUN.save(WORK/'others/precheck.json', output)
    if output['status'] != 'PASS':
        raise RuntimeError('EX008 precheck failed; see others/precheck.json')
    print('EX008 PRECHECK PASS', passed, 'groups', flush=True)


if __name__ == '__main__':
    check()
