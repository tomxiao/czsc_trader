"""C13 stock buffer with C43 entry gate plus a fixed relative-price exception.

Twenty completed daily closes define nineteen close-to-close intervals. All
twenty SPY completion timestamps must match unique completed LITE M30 closes.
The exception is price evidence, not industry causality or total-shareholder
return. Holdings and exits retain the original C13 buffer without a market exit.
"""
from math import isfinite
from strategy_runtime import EquityDecision


def base_signal(history, held, parameters):
    close = float(history.Close.iloc[-1])
    mean = float(history.Close.iloc[-parameters['trend_bars']:].mean())
    tail = history.iloc[-parameters['vol_bars']:]
    previous = history.Close.shift(1).iloc[-parameters['vol_bars']:]
    ranges = [max(float(hi-lo), abs(float(hi-prev)), abs(float(lo-prev)))
              for hi, lo, prev in zip(tail.High, tail.Low, previous)]
    atr = sum(ranges)/len(ranges)
    entry = mean + parameters['entry_atr']*atr
    exit_price = mean - parameters['exit_atr']*atr
    return close > (exit_price if held else entry), dict(close=close, mean=mean,
        atr=atr, entry_threshold=entry, exit_threshold=exit_price, held=held)


def visible_times(frame, point, name):
    """Reject non-causal direct calls; the public context supplies visible frames."""
    if frame.empty or not {'Date', 'BarStart', 'AvailableDate', 'Close'} <= set(frame):
        raise ValueError(name + ': missing completed observation fields')
    if (point.observed_through.tzinfo is None or point.decision_at.tzinfo is None
            or point.observed_through > point.decision_at):
        raise ValueError(name + ': invalid causal decision point')
    for field in ('Date', 'BarStart', 'AvailableDate'):
        values = frame[field]
        if values.isna().any() or values.dt.tz is None:
            raise ValueError(name + ': missing or naive observation time')
    if not frame.Date.is_monotonic_increasing or frame.Date.duplicated().any():
        raise ValueError(name + ': unordered or duplicate completion time')
    if (frame.Date.iloc[-1] > point.observed_through
            or frame.AvailableDate.max() > point.decision_at
            or (frame.AvailableDate < frame.Date).any()
            or (frame.BarStart >= frame.Date).any()):
        raise ValueError(name + ': future, unavailable or incomplete observation')


def relative_context(history, market, point, n):
    visible_times(history, point, 'LITE')
    visible_times(market, point, 'SPY')
    market = market.iloc[-n:]
    if len(market) != n:
        raise ValueError('SPY requires twenty complete daily closes')
    matched = history.loc[history.Date.isin(market.Date)]
    if len(matched) != n or tuple(matched.Date) != tuple(market.Date):
        raise ValueError('LITE requires a unique exact close at every SPY daily Date')
    if any((end-start).total_seconds() != 1800 for start, end in zip(matched.BarStart, matched.Date)):
        raise ValueError('LITE matched daily endpoint is not a completed M30 bar')
    lite_closes, spy_closes = ([float(value) for value in frame.Close] for frame in (matched, market))
    if any(not isfinite(value) or value <= 0 for value in (*lite_closes, *spy_closes)):
        raise ValueError('relative price requires finite positive values at all twenty closes')
    lite_ratio, market_ratio = lite_closes[-1]/lite_closes[0], spy_closes[-1]/spy_closes[0]
    last, mean = float(market.Close.iloc[-1]), float(market.Close.mean())
    if any(not isfinite(value) or value <= 0 for value in (lite_ratio, market_ratio, mean)):
        raise ValueError('relative price ratios and market mean must remain finite and positive')
    market_allowed, relative_allowed = last > mean, lite_ratio > market_ratio
    return market_allowed, relative_allowed, dict(
        market_last=last, market_mean=mean, market_allowed=market_allowed,
        market_observed=market.Date.iloc[-1].isoformat(),
        relative_lite_ratio=lite_ratio, relative_market_ratio=market_ratio,
        relative_allowed=relative_allowed, relative_first_observed=market.Date.iloc[0].isoformat(),
        relative_last_observed=market.Date.iloc[-1].isoformat(),
        relative_matched_closes=n, relative_close_intervals=n-1,
        weak_market_exception=not market_allowed and relative_allowed,
        relative_basis='RAW_PRICE_SAME_COMPLETED_DATES_NOT_INDUSTRY_CAUSALITY')


def decide(ctx):
    p = ctx.parameters
    if p['context_mode'] != 'MARKET' or p['context_sessions'] != 20:
        raise ValueError('this fixed design requires MARKET and twenty complete daily closes')
    market_allowed, relative_allowed, context_facts = relative_context(
        ctx.history, ctx.auxiliary_histories['market'], ctx.point, p['context_sessions'])
    held = ctx.portfolio.quantity > 0
    base, facts = base_signal(ctx.history, held, p)
    allowed = market_allowed or relative_allowed
    target = int(base if held else base and allowed)
    facts.update(context_facts)
    facts.update(base_target=base, entry_context_allowed=allowed, gate_role='ENTRY_ONLY',
        context_mode=p['context_mode'], context_sessions=p['context_sessions'],
        trend_bars=p['trend_bars'], vol_bars=p['vol_bars'], entry_atr=p['entry_atr'], exit_atr=p['exit_atr'])
    if held:
        reason = '持仓仍在缓冲下沿之上' if target else '跌至缓冲下沿，退出'
    elif not base:
        reason = 'LITE尚未越过自身入场缓冲，相对更强也不触发买入'
    elif market_allowed:
        reason = 'LITE入场缓冲与SPY完整日收盘条件成立，尝试买入'
    elif relative_allowed:
        reason = 'SPY条件偏弱，但LITE同期价格比值严格更高且自身突破成立，按弱市例外尝试买入'
    else:
        reason = 'SPY条件与LITE同期相对价格条件均不允许新入场'
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完成30分钟复核LITE缓冲；完整日价格背景仅约束空仓入场，不触发持仓退出')
