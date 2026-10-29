"""Synthetic mechanism checks; no historical account or market result is read."""

from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pandas as pd
from dataflows import AssetClass, BarFrequency, InstrumentId, MarketId, TimeInterval
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, DecisionPoint,
    EquityDecisionContext, EquityPortfolio, EquityStrategyCandidate,
    EquityStrategyDefinition, ResearchExecutionSpec, UsEquitySpec, equity_source_hash)

from strategy import decide, entry_facts

ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT.parents[1] / 'EX024_20261029/src/numbered_entries.py'
REFERENCE_SHA256 = '1c7963dbdbbfbf005f170201eadeb94d5754dba9785e7f3153a9f03b9eba8736'


def bars():
    stamps = [(day + pd.Timedelta(minutes=minute)).tz_localize('America/New_York')
              .tz_convert('UTC') for day in pd.bdate_range('2024-02-01', periods=40)
              for minute in range(570, 960, 30)]
    starts = pd.DatetimeIndex(stamps)
    return pd.DataFrame({'BarStart': starts, 'Date': starts + pd.Timedelta(minutes=30),
        'AvailableDate': starts + pd.Timedelta(minutes=30), 'Open': 100., 'High': 101.,
        'Low': 99., 'Close': 100., 'Volume': 100., 'Amount': 10000.})


def candle(frame, index, opening, high, low, close, volume=100.):
    frame.loc[index, ['Open', 'High', 'Low', 'Close', 'Volume']] = (
        opening, high, low, close, volume)


def inject(frame, signal):
    candle(frame, signal - 1, 100., 100., 98., 99.5, 150.)
    candle(frame, signal, 99.5, 102., 99., 101.5)


def parameters(mechanism):
    result = {'exit_mechanism': mechanism, 'max_holding_bars': 65}
    if mechanism == 'S017-M011':
        result['trailing_atr_multiple'] = 3.
    return result


def candidate(mechanism):
    execution = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH),
        1, .01, .01, 0.)
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'),
        execution, 261, 'strategy:decide', ('strategy.py',),
        equity_source_hash(ROOT, ('strategy.py',)), json.dumps(parameters(mechanism)),
        feedback_mode='CONFIRMED_EXECUTION', session_context=False)
    return EquityStrategyCandidate('S017', {'S017-M009': 'C0048', 'S017-M010': 'C0049',
        'S017-M011': 'C0050'}[mechanism], definition, ROOT)


def context(frame, end, mechanism, *, signal=None):
    history = frame.iloc[:end + 1].copy()
    now = history.Date.iloc[-1].to_pydatetime()
    execution_start = frame.BarStart.iloc[end + 1].to_pydatetime()
    point = DecisionPoint(now, now, TimeInterval(execution_start,
        execution_start + timedelta(minutes=30)))
    portfolio = EquityPortfolio(10000., 0, 0., 0) if signal is None else EquityPortfolio(
        9000., 10, 0., 1, cycle_entry=frame.BarStart.iloc[signal + 1].to_pydatetime(),
        cycle_cost=1000.)
    return EquityDecisionContext(history, portfolio, point, parameters(mechanism))


def facts(decision):
    return {item.key: item.text for item in decision.explanation.basis}


def rejects(call):
    try:
        call()
    except (TypeError, ValueError):
        return
    raise AssertionError('Expected explicit invalid-input rejection')


def run():
    groups = []
    assert sha256(REFERENCE.read_bytes()).hexdigest() == REFERENCE_SHA256
    spec = importlib.util.spec_from_file_location('ex024_reference', REFERENCE)
    reference = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reference)
    frame = bars()
    signal = 25 * 13 + 5
    inject(frame, signal)
    reference_flags, _, _ = reference.compute(frame)
    for end in range(15, len(frame)):
        assert entry_facts(frame.iloc[:end + 1])['entry_signal'] == bool(
            reference_flags['S017-M005'].iloc[end])
    assert entry_facts(frame.iloc[:signal + 1])['entry_signal']
    for field, value in [('Volume', 149.99), ('Open', 99.5), ('Low', 97.99)]:
        altered = frame.copy()
        altered.loc[signal - 1, field] = value
        assert not entry_facts(altered.iloc[:signal + 1])['entry_signal']
    altered = frame.copy()
    altered.loc[signal, 'Close'] = 100.
    assert not entry_facts(altered.iloc[:signal + 1])['entry_signal']
    groups.append('EX024_source_hash_and_all_synthetic_bar_entry_equivalence_boundaries')

    partial = bars()
    local = partial.BarStart.dt.tz_convert('America/New_York')
    last_signal = 38 * 13 + 11
    inject(partial, last_signal)
    missing_day = local.iloc[15 * 13].date()
    partial = partial.loc[~((local.dt.date == missing_day) & (local.dt.hour >= 13))]
    reference_flags, _, _ = reference.compute(partial)
    for end in (260, 300, 400, len(partial) - 1):
        computed = entry_facts(partial.iloc[:end + 1])
        assert computed['entry_signal'] == bool(reference_flags['S017-M005'].iloc[end])
    slot = entry_facts(partial.iloc[:-1])
    assert slot['same_slot_history_count'] == 20
    assert local.dt.tz_convert('UTC').dt.hour.nunique() > local.dt.hour.nunique()
    groups.append('same_local_slot_prior_day_exclusion_half_day_and_DST')

    for mechanism in ('S017-M009', 'S017-M010', 'S017-M011'):
        value = candidate(mechanism)
        value.verify()
        assert value.decide(context(frame, signal, mechanism)).target == 1
        first = value.decide(context(frame, signal + 1, mechanism, signal=signal))
        assert first.target == 1 and facts(first)['holding_bars'] == '1'
        for count in (64, 65, 66):
            decision = value.decide(context(frame, signal + count, mechanism, signal=signal))
            assert decision.target == int(count < 65)
            assert facts(decision)['holding_bars'] == str(count)
        flat = value.decide(context(frame, signal + 65, mechanism))
        assert facts(flat)['holding_bars'] == '0' and facts(flat)['held'] == 'False'
        held_signal = frame.copy()
        inject(held_signal, signal + 5)
        decision = value.decide(context(held_signal, signal + 5, mechanism, signal=signal))
        assert facts(decision)['entry_signal'] == 'True'
    groups.append('three_candidate_source_contract_actual_fill_65_completed_bars_and_flat_no_clock')

    overnight = bars()
    overnight_signal = 25 * 13 + 12
    inject(overnight, overnight_signal)
    ctx = context(overnight, overnight_signal + 1, 'S017-M009', signal=overnight_signal)
    assert ctx.portfolio.cycle_entry > overnight.Date.iloc[overnight_signal]
    result = decide(ctx)
    assert result.target == 1 and facts(result)['anchor'] == overnight.Date.iloc[overnight_signal].isoformat()
    groups.append('overnight_actual_entry_recovers_prior_available_signal')

    structural = frame.copy()
    candle(structural, signal + 1, 100., 101., 98., 98.)
    candle(structural, signal + 2, 98., 99., 97., 97.99)
    candle(structural, signal + 3, 98., 104., 97., 103.)
    for count, expected in ((1, 1), (2, 0), (3, 0)):
        result = decide(context(structural, signal + count, 'S017-M010', signal=signal))
        assert result.target == expected
    groups.append('S017-M010_strict_structural_low_and_latched_exit_after_rebound')

    trailing = frame.copy()
    frozen_atr = entry_facts(frame.iloc[:signal + 1])['atr']
    threshold = 108. - 3. * frozen_atr
    candle(trailing, signal + 1, 101., 109., 100., 108.)
    candle(trailing, signal + 2, 108., 109., threshold - 1., threshold)
    candle(trailing, signal + 3, threshold, 108., threshold - 1., threshold - .01)
    candle(trailing, signal + 4, 108., 111., 107., 110.)
    for count, expected in ((1, 1), (2, 1), (3, 0), (4, 0)):
        result = decide(context(trailing, signal + count, 'S017-M011', signal=signal))
        assert result.target == expected
        assert float(facts(result)['frozen_atr']) == frozen_atr
    no_structure = frame.copy()
    candle(no_structure, signal + 1, 100., 101., 96., 97.)
    assert decide(context(no_structure, signal + 1, 'S017-M011', signal=signal)).target == 1
    seed = frame.copy()
    initial_threshold = frame.Close.iloc[signal] - 3. * frozen_atr
    candle(seed, signal + 1, 100., 101., initial_threshold - 1., initial_threshold - .01)
    assert decide(context(seed, signal + 1, 'S017-M011', signal=signal)).target == 0
    groups.append('S017-M011_frozen_signal_ATR_strict_trailing_peak_latch_no_structural_stop')

    ctx = context(frame, signal + 4, 'S017-M009', signal=signal)
    expected = decide(ctx)
    altered = frame.copy()
    altered.loc[signal + 5:, ['Open', 'High', 'Low', 'Close', 'Volume']] *= 3.
    assert decide(context(altered, signal + 4, 'S017-M009', signal=signal)) == expected
    rejects(lambda: decide(replace(ctx, history=frame.iloc[:signal + 6])))
    rejects(lambda: decide(replace(ctx, portfolio=replace(ctx.portfolio, reference_price_scale=2.))))
    rejects(lambda: decide(replace(ctx, portfolio=replace(ctx.portfolio, cycle_entry=None))))
    rejects(lambda: decide(replace(ctx, parameters={'exit_mechanism': 'S017-M009',
                                                   'max_holding_bars': 64})))
    value = candidate('S017-M009')
    rejects(lambda: replace(value, definition=replace(value.definition, source_sha256='0' * 64)))
    groups.append('future_suffix_invariance_future_input_rejection_scale_params_and_source_hash')

    payload = {'status': 'PASS', 'scope': 'synthetic_only', 'checks': groups,
               'reference_source_sha256': REFERENCE_SHA256,
               'strategy_source_sha256': sha256((ROOT / 'strategy.py').read_bytes()).hexdigest(),
               'check_source_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
               'source_closure_sha256': equity_source_hash(ROOT, ('strategy.py',)),
               'feedback_mode': 'CONFIRMED_EXECUTION', 'session_context': False}
    destination = ROOT.parent / 'others/precheck_mechanism.json'
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return payload


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False), flush=True)
