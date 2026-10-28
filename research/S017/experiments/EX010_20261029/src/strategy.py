"""The retained C0013 buffer plus explicit completed-day market/industry gates."""
from math import log
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


def decide(ctx):
    p = ctx.parameters
    base, facts = base_signal(ctx.history, ctx.portfolio.quantity > 0, p)
    mode, n = p['context_mode'], p['context_sessions']
    if mode not in ('MARKET', 'INDUSTRY_DAY', 'BOTH'):
        raise ValueError('unknown explicit context mode')
    allowed = []
    if mode in ('MARKET', 'BOTH'):
        market = ctx.auxiliary_histories['market'].iloc[-n:]
        if len(market) != n:
            raise ValueError('market requires complete declared daily lookback')
        last, mean = float(market.Close.iloc[-1]), float(market.Close.mean())
        market_allowed = last > mean
        allowed.append(market_allowed)
        facts.update(market_last=last, market_mean=mean, market_allowed=market_allowed,
                     market_observed=market.Date.iloc[-1].isoformat())
    if mode in ('INDUSTRY_DAY', 'BOTH'):
        industry = ctx.auxiliary_histories['industry'].iloc[-n:]
        if len(industry) != n:
            raise ValueError('industry requires complete declared daily lookback')
        daytime = sum(log(float(close)/float(open_)) for close, open_ in zip(industry.Close, industry.Open))
        industry_allowed = daytime > 0
        allowed.append(industry_allowed)
        facts.update(industry_day_log_change=daytime, industry_allowed=industry_allowed,
                     industry_observed=industry.Date.iloc[-1].isoformat())
    target = int(base and all(allowed))
    facts.update(base_target=base, context_mode=mode, context_sessions=n,
        trend_bars=p['trend_bars'], vol_bars=p['vol_bars'], entry_atr=p['entry_atr'], exit_atr=p['exit_atr'])
    reason = ('个股慢趋势与已完成日线背景共同支持持仓' if target else
              '个股缓冲或外部背景条件不成立，保持或转为空仓')
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一完成30分钟观察复核个股；外部条件只在新的完整日线可得后变化')
