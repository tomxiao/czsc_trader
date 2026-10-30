"""Prior-mean background, unchanged breakout and confirmed-fill timed exits."""
import math
from statistics import fmean

import numpy as np
import pandas as pd
from strategy_runtime.equity_definition import EquityDecision

NAMES = ('S017-M012', 'S017-M017', 'S017-M018')


def compute(bars):
    """Current breakout uses only the six prior highs; background excludes t."""
    close, high = bars.Close.astype(float), bars.High.astype(float)
    prior_mean = close.shift().rolling(65, min_periods=65).mean()
    previous = close.shift()
    ready = prior_mean.notna()
    low_background = ready & (previous < prior_mean)
    breakout = close > high.shift().rolling(6, min_periods=6).max()
    flags = pd.DataFrame({NAMES[0]: breakout, NAMES[1]: low_background & breakout,
                          NAMES[2]: low_background}, index=bars.index)
    parents = pd.DataFrame({NAMES[0]: close > previous, NAMES[1]: low_background,
                            NAMES[2]: ready}, index=bars.index)
    regimes = pd.Series(np.where(~ready, 'UNREADY', np.where(previous < prior_mean, 'below65',
        np.where(previous > prior_mean, 'above65', 'equal65'))), index=bars.index)
    return flags, parents, regimes


def entry_facts(history, mechanism):
    """Bounded scalar equivalent; no all-history scan or replay-local cache."""
    if mechanism not in NAMES:
        raise ValueError('Unknown entry mechanism')
    if len(history) < 66:
        return {'entry_signal': False, 'entry_ready': False, 'entry_mechanism': mechanism}
    prices = history.iloc[-66:][['Open', 'High', 'Low', 'Close']].to_numpy(dtype=float)
    for opening, high, low, close in prices:
        if (not all(math.isfinite(float(value)) for value in (opening, high, low, close))
                or min(opening, high, low, close) <= 0
                or high < max(opening, close) or low > min(opening, close)):
            raise ValueError('Require finite consistent positive raw OHLC')
    close, previous = float(prices[-1, 3]), float(prices[-2, 3])
    prior_mean = fmean(float(value) for value in prices[:-1, 3])
    high6 = float(max(prices[-7:-1, 1]))
    background, breakout = previous < prior_mean, close > high6
    flags = {NAMES[0]: breakout, NAMES[1]: background and breakout, NAMES[2]: background}
    return {'entry_signal': bool(flags[mechanism]), 'entry_ready': True, 'entry_mechanism': mechanism,
            'close': close, 'previous_close': previous, 'prior_sma65': prior_mean,
            'low_background': bool(background), 'breakout_high6': high6}


def decide(ctx):
    parameters, history, portfolio = ctx.parameters, ctx.history, ctx.portfolio
    mechanism, horizon = parameters.get('entry_mechanism'), parameters.get('max_holding_bars')
    if (set(parameters) != {'entry_mechanism', 'max_holding_bars'} or mechanism not in NAMES
            or type(horizon) is not int or horizon not in (6, 13)):
        raise ValueError('Require frozen mechanism and 6/13 completed holding bars')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('RAW prototype requires reference price scale == 1')
    if history.empty:
        raise ValueError('Completed visible history is required')
    if (history.Date.iloc[-1] > ctx.point.observed_through
            or history.AvailableDate.iloc[-1] > ctx.point.decision_at):
        raise ValueError('Future or unavailable completed observation')
    facts = entry_facts(history, mechanism)
    held = portfolio.quantity > 0
    facts.update(held=held, holding_bars=0, max_holding_bars=horizon, exit_trigger=None)
    if held:
        entry = portfolio.cycle_entry
        if entry is None or portfolio.cycle_cost <= 0:
            raise ValueError('Confirmed held quantity requires actual cycle entry and cost')
        first = int(history.Date.searchsorted(entry, side='right'))
        if first >= len(history) or history.BarStart.iloc[first] != entry:
            raise ValueError('Actual fill must align with its complete first holding interval')
        count = len(history) - first
        due = count >= horizon
        facts.update(holding_bars=count, actual_entry=entry.isoformat(),
                     exit_trigger='FIXED_HOLD' if due else None)
        target = int(not due)
        reason = f'{mechanism}固定{horizon}柱退出' if due else f'{mechanism}继续持有'
    else:
        target = int(facts['entry_signal'])
        reason = f'{mechanism}入场' if target else f'{mechanism}未触发'
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完整30分钟柱复核；以实际成交计时，到期退出持续至清仓')
