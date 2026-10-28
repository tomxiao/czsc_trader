"""Independent causal EX007 checks using synthetic prices; no account replay."""
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import pickle
import sys

from dataflows import TimeInterval
from strategy_runtime import (DecisionPoint, EquityClosedCycle, EquityClosedCycleFeedback,
    EquityDecisionContext, EquityPortfolio, EquityStrategyDefinition, StrategyRuntime)


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


RUN = load('_s017_ex007_runner', WORK/'src/run.py')
NEW = load('_s017_ex007_strategy', WORK/'src/strategy.py')
PRIOR = ROOT/'research/S017/experiments/EX005_20261028/src'
OLD = load('_s017_ex007_control', PRIOR/'strategy.py')
old_run = load('_s017_ex007_control_runner', PRIOR/'run.py')
saved = {name: sys.modules.get(name) for name in ('run', 'strategy')}
try:
    sys.modules['run'], sys.modules['strategy'] = old_run, OLD
    ORACLE = load('_s017_ex007_control_check', PRIOR/'precheck.py')
finally:
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
CHECK = ORACLE.CHECK
for name in ('strategy.py', 'run.py', 'precheck.py'):
    path = ROOT/'research/S017/experiments/EX004_20261028/src'/name
    SOURCES[str(path.relative_to(ROOT))] = sha256(path.read_bytes()).hexdigest()
PARAMETERS = RUN.configurations()['C0030']


def account(entry=None, basis=100., quantity=0, latest=None):
    return EquityPortfolio(100000., quantity, 0., 1, entry, basis*quantity,
                           closed_cycle_feedback=EquityClosedCycleFeedback(latest))


def context(frame, portfolio):
    observed = frame.Date.iloc[-1].to_pydatetime()
    point = DecisionPoint(observed, observed, TimeInterval(observed, observed+timedelta(minutes=30)))
    return EquityDecisionContext(frame, portfolio, point, PARAMETERS)


def rejected(function, message):
    try:
        function()
    except ValueError as exc:
        CHECK.require(message in str(exc), 'wrong rejection: '+str(exc))
        return
    raise AssertionError('invalid state was accepted: '+message)


def prefix_equivalence():
    frame = CHECK.synthetic().iloc[:455].copy()
    first = 390
    held = account(frame.BarStart.iloc[first].to_pydatetime(), float(frame.Close.iloc[first]), 10)
    frame.loc[frame.index[first+10:first+14], 'Close'] *= 1.2
    frame.loc[frame.index[first+20:first+23], 'Close'] *= .6
    frame['High'] = frame[['High', 'Close']].max(axis=1)
    frame['Low'] = frame[['Low', 'Close']].min(axis=1)
    CHECK.require(PARAMETERS == old_run.configurations()['C0029'], 'fixed C0029 parameters drifted')
    full = NEW.cycle_levels(frame, held, PARAMETERS)
    count = 0
    for stop in range(first+1, len(frame)+1):
        prefix = frame.iloc[:stop]
        state = NEW.cycle_levels(prefix, held, PARAMETERS)
        CHECK.same_state(state, ORACLE.oracle(prefix, held, PARAMETERS))
        CHECK.same_state(state, OLD.cycle_levels(prefix, held, PARAMETERS))
        for actual, expected in zip(state['levels'], full['levels'][:stop-first]):
            CHECK.close(actual, expected, 'future data changed earlier stop')
        for portfolio in (held, account()):
            current, prior = NEW.decide(context(prefix, portfolio)), OLD.decide(context(prefix, portfolio))
            CHECK.require(current.target == prior.target, 'C0029 held/first-entry decision differs')
            if portfolio.quantity:
                CHECK.require(current == prior, 'held branch explanation differs from C0029')
        count += 1
    return {'independent_prefix_states':count, 'C0029_held_flat_decisions':count*2,
            'full_sequence_prefix_consistency':True, 'fixture':'synthetic half-days and DST in 2020'}


def fixture():
    frame = CHECK.synthetic().iloc[:400].copy()
    frame[['Open', 'Close']] = 100.
    frame['High'], frame['Low'] = 101., 99.
    marks = [104., 100., 120., 119., 103., 101., 101., 101., 101., 101.]
    frame.loc[frame.index[390:], 'Close'] = marks
    frame['High'] = frame[['High', 'Close']].max(axis=1)
    frame['Low'] = frame[['Low', 'Close']].min(axis=1)
    closed = EquityClosedCycle('synthetic-closed-1',
        TimeInterval(frame.BarStart.iloc[390].to_pydatetime(), frame.Date.iloc[390].to_pydatetime()),
        TimeInterval(frame.BarStart.iloc[394].to_pydatetime(), frame.Date.iloc[394].to_pydatetime()),
        10, 1000., frame.Date.iloc[393].to_pydatetime())
    return frame, closed


def recovery_boundaries():
    frame, closed = fixture()
    flat = account(latest=closed)
    prefix = frame.iloc[:396].copy()
    levels = NEW.recovery_level(prefix, flat, PARAMETERS)
    CHECK.close(levels['recovery_stop'], 100., 'first trigger level must freeze at cost floor')
    CHECK.require(levels['recovery_trigger_at'] == frame.Date.iloc[391].isoformat(), 'first trigger time differs')
    original = account(closed.entry_interval.start, 100., 10)
    delayed = ORACLE.oracle(frame.iloc[:394], original, PARAMETERS)
    CHECK.require(delayed['stop'] > 100., 'fixture must ratchet above first trigger during delayed exit')
    CHECK.require(NEW.decide(context(frame.iloc[:394], original)).target == 0,
                  'pending real exit must stay latched during rebound')
    targets = {}
    for mark in (99.999, 100., 100.001):
        changed = prefix.copy()
        changed.loc[changed.index[-1], 'Close'] = mark
        decision = NEW.decide(context(changed, flat))
        expected = int(mark > 100.)
        CHECK.require(decision.target == expected, 'recovery strict equality boundary differs')
        targets[str(mark)] = decision.target
    # Breakout remains independently available even below a separate recovery line.
    fresh = prefix.copy()
    fresh.loc[fresh.index[-1], 'Close'] = 121.
    CHECK.require(NEW.decide(context(fresh, account())).target == 1, 'first breakout entry was removed')
    altered = frame.copy()
    mask = altered.Date > closed.exit_observed_through
    altered.loc[mask, ['Open', 'High', 'Low', 'Close']] *= 100.
    CHECK.require(NEW.recovery_level(altered, flat, PARAMETERS) == levels,
                  'post-exit-observation prices moved frozen line')
    for stop in range(395, len(frame)+1):
        CHECK.require(NEW.recovery_level(frame.iloc[:stop], flat, PARAMETERS) == levels,
                      'flat-period extension moved frozen line')
    return {'first_trigger_stop':100., 'delayed_exit_last_stop':delayed['stop'],
            'strict_boundary_targets':targets, 'post_exit_perturbation_multiplier':100.,
            'flat_prefixes_checked':len(frame)-394, 'pending_exit_latch':True}


def cycle_replacement():
    frame, closed = fixture()
    newer = frame.copy()
    newer.loc[newer.index[395:399], 'Close'] = [205., 1., 210., 210.]
    newer['High'] = newer[['High', 'Close']].max(axis=1)
    newer['Low'] = newer[['Low', 'Close']].min(axis=1)
    held = account(newer.BarStart.iloc[395].to_pydatetime(), 200., 10, closed)
    first = newer.iloc[:396]
    CHECK.require(NEW.decide(context(first, held)).target == 1, 'reentry inherited previous stop latch')
    CHECK.require(NEW.decide(context(first, held)) == OLD.decide(context(first, held)),
                  'reentry must use unchanged C0029 held management')
    second = EquityClosedCycle('synthetic-closed-2',
        TimeInterval(newer.BarStart.iloc[395].to_pydatetime(), newer.Date.iloc[395].to_pydatetime()),
        TimeInterval(newer.BarStart.iloc[398].to_pydatetime(), newer.Date.iloc[398].to_pydatetime()),
        10, 2000., newer.Date.iloc[397].to_pydatetime())
    state = NEW.recovery_level(newer, account(latest=second), PARAMETERS)
    expected = ORACLE.oracle(newer.iloc[:398], held, PARAMETERS)
    cycle = newer.loc[(newer.Date > second.entry_interval.start) & (newer.Date <= second.exit_observed_through)]
    first_hit = next(level for row, level in zip(cycle.itertuples(), expected['levels']) if row.Close <= level)
    CHECK.close(state['recovery_stop'], first_hit, 'second cycle first trigger differs')
    CHECK.require(state['closed_cycle_id'] == second.cycle_id and state['recovery_stop'] != 100.,
                  'second closed cycle reused old recovery facts')
    return {'new_cycle_entry_target':1, 'replaced_cycle_id':second.cycle_id,
            'second_recovery_stop':state['recovery_stop'], 'old_recovery_stop':100.}


def contracts_and_real_loader():
    value = RUN.candidate('C0030', PARAMETERS)
    definition = EquityStrategyDefinition.from_dict(json.loads(json.dumps(value.definition.to_dict())))
    CHECK.require(definition == value.definition and definition.feedback_mode == 'CONFIRMED_CLOSED_CYCLE_V1',
                  'definition capability serialization differs')
    restored = pickle.loads(pickle.dumps(value))
    CHECK.require(restored.content_identity == value.content_identity, 'candidate pickle identity differs')
    frame, closed = fixture()
    flat = account(latest=closed)
    ctx = context(frame.iloc[:396], flat)
    CHECK.require(pickle.loads(pickle.dumps(flat)) == flat, 'typed portfolio serialization differs')
    direct = NEW.decide(ctx)
    CHECK.require(value.decide(ctx) == restored.decide(ctx) == direct, 'isolated actual loading differs')
    plan = StrategyRuntime(execution_spec=RUN.SPEC).create(restored).plan(
        ctx.history, ctx.point.execution_interval, flat, fee_rate=.001)
    CHECK.require(plan.target == direct.target and plan.explanation == direct.explanation.to_dict(),
                  'runtime plan changed verified decision or explanation')
    CHECK.require(value.decide(ctx) == value.decide(ctx), 'isolated repeated loading is not stateless')
    unavailable = replace(flat, closed_cycle_feedback=None)
    rejected(lambda: value.decide(replace(ctx, portfolio=unavailable)), 'CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
    rejected(lambda: NEW.recovery_level(ctx.history, unavailable, PARAMETERS), 'CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
    no_trigger = frame.copy()
    no_trigger[['Open', 'Close']] = 100.
    no_trigger['High'], no_trigger['Low'] = 101., 99.
    rejected(lambda: NEW.recovery_level(no_trigger, flat, PARAMETERS), 'no causal stop trigger')
    future = replace(closed, exit_interval=ctx.point.execution_interval)
    rejected(lambda: value.decide(replace(ctx, portfolio=account(latest=future))), 'CAUSAL_TIME_VIOLATION')
    return {'definition_roundtrip':True, 'candidate_and_feedback_pickle':True,
            'actual_isolated_loader':True, 'runtime_plan_without_execution':True,
            'unsupported_no_trigger_future_rejections':4,
            'candidate_content_sha256':value.content_identity.content_sha256}


def check():
    scratch = ROOT/'.tmp/s017-ex007-precheck'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['TEMP'] = os.environ['TMP'] = str(scratch)
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    cases = {}
    for name, function in (('C0029_equivalence_and_sequential_oracle', prefix_equivalence),
                           ('frozen_recovery_boundaries', recovery_boundaries),
                           ('real_cycle_replacement', cycle_replacement),
                           ('typed_contracts_and_actual_loader', contracts_and_real_loader)):
        try:
            cases[name] = {'status':'PASS', **function()}
        except Exception as exc:
            cases[name] = {'status':'FAIL', 'error_type':type(exc).__name__, 'error':str(exc)}
        print(cases[name]['status'], name, flush=True)
    unchanged = all(sha256((ROOT/path).read_bytes()).hexdigest() == digest for path, digest in SOURCES.items())
    cases['source_immutability'] = {'status':'PASS' if unchanged else 'FAIL', 'source_sha256':SOURCES}
    passed = sum(item['status'] == 'PASS' for item in cases.values())
    output = {'status':'PASS' if passed == len(cases) else 'FAIL',
        'strategy_source_sha256':SOURCES[str((WORK/'src/strategy.py').relative_to(ROOT))],
        'precheck_source_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'passed_groups':passed, 'total_groups':len(cases), 'cases':cases,
        'scope':'Synthetic 2020 data and typed fabricated portfolio facts only; no market data reads, fills, account replay or return claims.',
        'oracle':'EX004 independent chronological daily true-range fold plus EX005 independent sequential stop fold; exact importlib isolation and source hashes retained.'}
    RUN.save(WORK/'others/precheck.json', output)
    if output['status'] != 'PASS':
        raise RuntimeError('EX007 precheck failed; see others/precheck.json')
    print('EX007 PRECHECK PASS', passed, 'groups', flush=True)


if __name__ == '__main__':
    check()
