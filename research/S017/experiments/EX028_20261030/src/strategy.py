"""Three frozen short-horizon entry hypotheses and actual-fill timed exits."""

import math

import numpy as np
import pandas as pd
from strategy_runtime.equity_definition import EquityDecision

NAMES = ('S017-M012', 'S017-M013', 'S017-M014')


def compute(bars):
    """Vector expressions and prior-only diagnostic regimes; no future fills."""
    o, h, low, c = (bars[name].astype(float) for name in ('Open', 'High', 'Low', 'Close'))
    tr = pd.concat((h-low, (h-c.shift()).abs(), (low-c.shift()).abs()), axis=1).max(axis=1)
    tr.iloc[0] = np.nan
    atr = tr.rolling(13, min_periods=13).mean()
    previous_high = h.shift().rolling(6, min_periods=6).max()
    previous_low = low.shift().rolling(6, min_periods=6).min()
    pullback = ((c.shift(3)-c.shift(9) >= atr.shift(4))
                & (c.shift(2) < c.shift(3)) & (c.shift() <= c.shift(2)))
    flags = pd.DataFrame({NAMES[0]: c > previous_high,
                          NAMES[1]: pullback & (c > h.shift()),
                          NAMES[2]: (low < previous_low) & (c > previous_low) & (c > o)}, index=bars.index)
    parents = pd.DataFrame({NAMES[0]: c > c.shift(), NAMES[1]: pullback,
                            NAMES[2]: low < previous_low}, index=bars.index)
    ratio = atr / c
    prior_ratio = ratio.shift()
    median_ratio = ratio.rolling(260, min_periods=260).median().shift()
    mean = c.rolling(65, min_periods=65).mean().shift()
    trend = np.where(c.shift() > mean, 'up', np.where(c.shift() < mean, 'down', 'flat'))
    volatility = np.where(prior_ratio > median_ratio, 'high', 'low')
    ready = mean.notna() & median_ratio.notna()
    regimes = pd.Series([f'{a}|{b}' if valid else 'UNREADY'
                         for a, b, valid in zip(trend, volatility, ready, strict=True)], index=bars.index)
    return flags, parents, regimes


def entry_facts(history, mechanism):
    """Independent bounded scalar expression; M013 requires 18 completed bars."""
    if mechanism not in NAMES:
        raise ValueError('Unknown entry mechanism')
    if len(history) < 18:
        return {'entry_signal': False, 'entry_ready': False, 'entry_mechanism': mechanism}
    p = history.iloc[-18:][['Open', 'High', 'Low', 'Close']].to_numpy(dtype=float)
    for opening, high, low, close in p:
        if (not all(math.isfinite(float(v)) for v in (opening, high, low, close))
                or min(opening, high, low, close) <= 0
                or low > min(opening, close) or high < max(opening, close)):
            raise ValueError('Require finite consistent positive raw OHLC')
    close = float(p[-1, 3])
    high6, low6 = float(max(p[-7:-1, 1])), float(min(p[-7:-1, 2]))
    # j=1..13 is t-16..t-4, each compared with its preceding close.
    atr_before = sum(max(float(p[j, 1]-p[j, 2]), abs(float(p[j, 1]-p[j-1, 3])),
                         abs(float(p[j, 2]-p[j-1, 3]))) for j in range(1, 14))/13
    pullback = (p[-4, 3]-p[-10, 3] >= atr_before
                and p[-3, 3] < p[-4, 3] and p[-2, 3] <= p[-3, 3])
    values = {NAMES[0]: close > high6,
              NAMES[1]: pullback and close > p[-2, 1],
              NAMES[2]: p[-1, 2] < low6 and close > low6 and close > p[-1, 0]}
    return {'entry_signal': bool(values[mechanism]), 'entry_ready': True,
            'entry_mechanism': mechanism, 'close': close,
            'previous_six_high': high6, 'previous_six_low': low6,
            'upward_atr13_before_pullback': atr_before, 'pullback_parent': bool(pullback)}


def decide(ctx):
    parameters, history, portfolio = ctx.parameters, ctx.history, ctx.portfolio
    mechanism, horizon = parameters.get('entry_mechanism'), parameters.get('max_holding_bars')
    if (set(parameters) != {'entry_mechanism', 'max_holding_bars'}
            or mechanism not in NAMES or type(horizon) is not int or horizon not in (6, 13)):
        raise ValueError('Require fixed entry mechanism and 6/13-bar holding period')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('RAW prototype requires reference price scale == 1')
    if history.empty or not history.Date.is_monotonic_increasing or history.Date.duplicated().any():
        raise ValueError('Require unique chronological completed history')
    if (history.Date.iloc[-1] > ctx.point.observed_through
            or history.AvailableDate.iloc[-1] > ctx.point.decision_at):
        raise ValueError('Future or unavailable observation')
    facts = entry_facts(history, mechanism)
    held = portfolio.quantity > 0
    facts.update(held=held, holding_bars=0, max_holding_bars=horizon, exit_trigger=None)
    if held:
        entry = portfolio.cycle_entry
        if entry is None or portfolio.cycle_cost <= 0:
            raise ValueError('Held quantity requires confirmed actual cycle entry and cost')
        first = int(history.Date.searchsorted(entry, side='right'))
        if first >= len(history) or history.BarStart.iloc[first] != entry:
            raise ValueError('Actual entry must align with its complete first holding interval')
        count = len(history)-first
        exit_due = count >= horizon
        facts.update(holding_bars=count, actual_entry=entry.isoformat(),
                     exit_trigger='FIXED_HOLD' if exit_due else None)
        target = int(not exit_due)
        reason = f'{mechanism}固定{horizon}柱退出' if exit_due else f'{mechanism}继续持有'
    else:
        target = int(facts['entry_signal'])
        reason = f'{mechanism}入场' if target else f'{mechanism}未触发'
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完整30分钟柱复核；以实际买入计时，退出持续至实际清仓')
