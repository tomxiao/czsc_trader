"""Synthetic-only EX012 checks; no account replay, downloads or market samples."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import pickle

import pandas as pd
from dataflows import (AssetClass, BarFrequency, InstrumentId, MarketId, SourceRef,
                       TimeInterval, TradingSession)
from strategy_runtime import (AccountPolicy, CashAvailabilityPolicy, DecisionPoint,
    EquityAuxiliaryInput, EquityClosedCycle, EquityClosedCycleFeedback, EquityDecisionContext,
    EquityPortfolio, EquityStrategyCandidate, EquityStrategyDefinition, ResearchExecutionSpec,
    UsEquitySpec, equity_source_hash)


ROOT = Path(__file__).resolve().parent
OPEN = datetime(2025, 11, 28, 14, 30, tzinfo=timezone.utc)
SESSION = TradingSession(date(2025, 11, 28), 'America/New_York',
                         (TimeInterval(OPEN, OPEN + timedelta(hours=3, minutes=30)),))


def candidate(antidip=False):
    spec = ResearchExecutionSpec(UsEquitySpec(), BarFrequency.M30,
        AccountPolicy('USD', CashAvailabilityPolicy.IMMEDIATE_RESEARCH), 1, .01, .01, 0.)
    definition = EquityStrategyDefinition(InstrumentId(MarketId.US, AssetClass.STOCK, 'LITE'),
        spec, 261, 'strategy:decide', ('strategy.py',), equity_source_hash(ROOT, ('strategy.py',)),
        json.dumps({'antidip': antidip}), feedback_mode='CONFIRMED_CLOSED_CYCLE_V1',
        auxiliary_inputs=(EquityAuxiliaryInput('market', InstrumentId(MarketId.US, AssetClass.ETF, 'SPY'),
            SourceRef('futu', 's017-auxiliary-rth-raw-v1-20261029'), BarFrequency.M30, 2, 345600),),
        session_context=True)
    return EquityStrategyCandidate('S017', 'C0039' if antidip else 'C0038', definition, ROOT)


def bars(opens, closes, lows=None):
    starts = [OPEN + timedelta(minutes=30 * i) for i in range(len(opens))]
    return pd.DataFrame({'BarStart': starts, 'Date': [x + timedelta(minutes=30) for x in starts],
        'AvailableDate': [x + timedelta(minutes=30) for x in starts], 'Open': opens,
        'High': [max(a, b) + 1 for a, b in zip(opens, closes)],
        'Low': [min(a, b) - 1 for a, b in zip(opens, closes)] if lows is None else lows,
        'Close': closes, 'Volume': 1000., 'Amount': 100000.})


def context(value, index=2, *, stock=None, market=None, portfolio=None):
    stock = bars([100.] * index, [100., 102., 105., 102., 108., 109.][:index],
                 [99.] * index) if stock is None else stock
    market = bars([100.] * index, [99., 101., 102., 103., 104., 105.][:index]) if market is None else market
    if index < 2:
        previous = market.iloc[:1].copy()
        for field in ('BarStart', 'Date', 'AvailableDate'):
            previous[field] -= timedelta(days=2)
        market = pd.concat([previous, market], ignore_index=True)
    now = OPEN + timedelta(minutes=30 * index)
    point = DecisionPoint(stock.Date.iloc[-1].to_pydatetime(), now, TimeInterval(now, now + timedelta(minutes=30)))
    portfolio = portfolio or EquityPortfolio(10000., 0, 0., 0,
                                             closed_cycle_feedback=EquityClosedCycleFeedback())
    return EquityDecisionContext(stock, portfolio, point, value.definition.parameters,
                                 {'market': market}, SESSION, OPEN)


def rejects(call, fragment):
    try:
        call()
    except (ValueError, TypeError) as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError('expected rejection: ' + fragment)


def run():
    control, antidip = candidate(), candidate(True)
    groups = []
    base = context(control)
    assert control.decide(base).target == 1
    assert antidip.decide(replace(base, parameters=antidip.definition.parameters)).target == 1
    weak = bars([100., 100.], [99., 102.], [98., 99.])
    assert control.decide(context(control, stock=weak)).target == 1
    assert antidip.decide(context(antidip, stock=weak)).target == 0
    for previous, current in ((100., 101.), (99., 100.)):
        assert control.decide(context(control, market=bars([100., 100.], [previous, current]))).target == 0
    equal = bars([100., 100.], [100., 101.])
    assert control.decide(context(control, stock=equal)).target == 0
    assert control.decide(context(control, index=1)).target == 0
    groups.append('two_bar_directions_antidip_and_strict_return_boundary')

    incomplete = base.auxiliary_histories['market'].iloc[1:].copy()
    rejects(lambda: control.decide(replace(base, auxiliary_histories={'market': incomplete})), 'WARMUP')
    misaligned = base.auxiliary_histories['market'].copy()
    misaligned.loc[0, 'BarStart'] -= timedelta(seconds=1)
    rejects(lambda: control.decide(replace(base, auxiliary_histories={'market': misaligned})), 'EXACT_TWO_BAR_ALIGNMENT')
    missing_timestamp = base.auxiliary_histories['market'].copy()
    missing_timestamp.loc[0, 'Date'] -= timedelta(seconds=1)
    rejects(lambda: control.decide(replace(base, auxiliary_histories={'market': missing_timestamp})),
            'EXACT_TWO_BAR_ALIGNMENT')
    future = bars([100., 100., 100.], [99., 101., 102.])
    rejects(lambda: control.decide(replace(base, auxiliary_histories={'market': future})), 'future auxiliary')
    rejects(lambda: control.decide(replace(base, history=future)), 'future primary')
    assert control.decide(base) == control.decide(base)
    groups.append('precise_timestamp_alignment_future_rejection_and_stateless_retry')

    recovery_stock = bars([100.] * 4, [100., 102., 100., 102.], [99.] * 4)
    recovery_market = bars([100.] * 4, [99., 101., 99., 101.])
    gap_history = recovery_stock.drop(index=1).copy()
    first_restored = context(control, 3, stock=gap_history.iloc[:2].copy(),
                             market=recovery_market.iloc[:3].copy())
    waiting = control.decide(first_restored)
    assert waiting.target == 0 and 'TWO_BAR_SIGNAL_INELIGIBLE' in waiting.reason
    eligible = context(control, 4, stock=gap_history, market=recovery_market)
    assert control.decide(eligible).target == 1
    malformed = first_restored.history.copy()
    malformed.loc[malformed.index[-1], 'BarStart'] -= timedelta(seconds=1)
    rejects(lambda: control.decide(replace(first_restored, history=malformed)), 'TIMESTAMP_MISALIGNED')
    missing_market = first_restored.auxiliary_histories['market'].drop(index=1).copy()
    rejects(lambda: control.decide(replace(first_restored, auxiliary_histories={'market': missing_market})),
            'EXACT_TWO_BAR_ALIGNMENT')
    duplicate = pd.concat([base.history.iloc[:1], base.history], ignore_index=True)
    rejects(lambda: control.decide(replace(base, history=duplicate)), 'UNIQUE_ORDERED')
    groups.append('known_stock_gap_waits_until_two_adjacent_bars_restore_without_error_fallback')

    entry = OPEN + timedelta(hours=1)
    actual = EquityPortfolio(8990., 10, 0., 1, cycle_entry=entry, cycle_cost=1010.,
                             closed_cycle_feedback=EquityClosedCycleFeedback())
    holding = context(control, 3, portfolio=actual)
    assert control.decide(holding).target == 1
    assert antidip.decide(replace(holding, parameters=antidip.definition.parameters)) == control.decide(holding)
    stopped = context(control, 4, portfolio=actual)
    rebounded = context(control, 5, portfolio=actual)
    assert control.decide(stopped).target == 0
    assert control.decide(rebounded).target == 0
    assert antidip.decide(replace(stopped, parameters=antidip.definition.parameters)) == control.decide(stopped)
    equality = bars([100., 100., 100., 100.], [100., 102., 105., 103.], [99.] * 4)
    assert control.decide(context(control, 4, stock=equality, portfolio=actual)).target == 0
    assert control.decide(context(control, 3, portfolio=replace(actual, cycle_cost=990.))).target == 0
    invalid = replace(actual, cycle_entry=entry - timedelta(seconds=1))
    rejects(lambda: control.decide(context(control, 3, portfolio=invalid)), 'SIGNAL_BAR_UNAVAILABLE')
    groups.append('actual_cost_frozen_entry_low_ratcheting_stop_and_sticky_exit')

    closed = EquityClosedCycle('synthetic-cycle', TimeInterval(entry, entry + timedelta(minutes=30)),
        TimeInterval(entry + timedelta(minutes=30), entry + timedelta(minutes=60)), 10, 1010.,
        entry + timedelta(minutes=30))
    flat = EquityPortfolio(10000., 0, 0., 2, closed_cycle_feedback=EquityClosedCycleFeedback(closed))
    assert control.decide(context(control, 5, portfolio=flat)).target == 0
    old_closed = replace(closed, entry_interval=TimeInterval(entry - timedelta(days=1),
        entry - timedelta(days=1) + timedelta(minutes=30)), exit_interval=TimeInterval(
        entry - timedelta(days=1) + timedelta(minutes=30), entry - timedelta(days=1) + timedelta(minutes=60)),
        exit_observed_through=entry - timedelta(days=1) + timedelta(minutes=30))
    prior = replace(flat, closed_cycle_feedback=EquityClosedCycleFeedback(old_closed))
    assert control.decide(context(control, portfolio=prior)).target == 1
    rejects(lambda: control.decide(replace(base, portfolio=replace(base.portfolio, closed_cycle_feedback=None))),
            'CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
    assert control.decide(context(control, 6)).target == 0
    assert control.decide(context(control, 6, portfolio=actual)).target == 0
    overnight = replace(actual, cycle_entry=entry - timedelta(days=1))
    assert control.decide(context(control, 2, portfolio=overnight)).target == 0
    groups.append('actual_cycle_once_per_session_last_halfday_interval_and_overnight_exit')

    for value in (control, antidip):
        assert EquityStrategyDefinition.from_dict(json.loads(json.dumps(value.definition.to_dict()))) == value.definition
        assert pickle.loads(pickle.dumps(value)) == value
    assert control.content_identity != antidip.content_identity
    groups.append('typed_candidate_source_loading_pickle_and_definition_identity')
    return {'status': 'PASS', 'synthetic_only': True, 'checks': groups,
            'strategy_source_sha256': sha256((ROOT / 'strategy.py').read_bytes()).hexdigest(),
            'source_closure_sha256': control.definition.source_sha256}


if __name__ == '__main__':
    print(json.dumps(run(), ensure_ascii=False, indent=2))
