"""Causal fixed-structure prototypes; all decisions use completed visible bars."""
from strategy_runtime.equity_definition import EquityDecision


def decide(ctx):
    p = ctx.parameters
    h = ctx.history
    held = ctx.portfolio.quantity > 0
    close = float(h.Close.iloc[-1])
    mode = p['mode']
    facts = {'mode': mode, 'close': close, 'held': held}
    if mode == 'hold':
        target, reason = 1, '持续持有基线；空仓时尝试买入'
    else:
        slow = float(h.Close.iloc[-p['trend_bars']:].mean())
        trend = close > slow
        facts.update(slow_mean=slow, trend=trend, trend_bars=p['trend_bars'])
        if mode == 'trend':
            target = int(trend)
            reason = '价格高于慢均价，维持多头' if target else '价格不高于慢均价，保持空仓或退出'
        elif mode == 'breakout':
            upper = float(h.High.iloc[-p['entry_bars']-1:-1].max())
            lower = float(h.Low.iloc[-p['exit_bars']-1:-1].min())
            enter = close > upper and (trend or not p['trend_filter'])
            target = int(close >= lower) if held else int(enter)
            facts.update(prior_upper=upper, prior_lower=lower, enter=enter,
                         entry_bars=p['entry_bars'], exit_bars=p['exit_bars'], trend_filter=p['trend_filter'])
            reason = ('持仓支持未破坏' if target else '价格跌破支持，退出') if held else ('突破且入场条件满足' if target else '未满足突破入场条件')
        elif mode == 'dip':
            tail = h.iloc[-p['mean_bars']:]
            mean = float(tail.Close.mean())
            previous = h.Close.shift(1).iloc[-p['mean_bars']:]
            ranges = [max(float(hi-lo), abs(float(hi-prev)), abs(float(lo-prev)))
                      for hi, lo, prev in zip(tail.High, tail.Low, previous)]
            atr = sum(ranges) / len(ranges)
            threshold = mean - p['dip_atr'] * atr
            enter = close < threshold and (trend or not p['trend_filter'])
            recovered = close >= mean
            invalidated = p['trend_exit'] and not trend
            target = int(not (recovered or invalidated)) if held else int(enter)
            facts.update(local_mean=mean, atr=atr, entry_threshold=threshold,
                         mean_bars=p['mean_bars'], dip_atr=p['dip_atr'], trend_filter=p['trend_filter'],
                         trend_exit=p['trend_exit'], recovered=recovered, invalidated=invalidated, enter=enter)
            reason = ('背景失效，退出' if invalidated else '恢复局部均价，退出') if held and not target else ('等待价格恢复' if held else ('回落条件满足，尝试买入' if target else '未满足回落入场条件'))
        else:
            raise ValueError('unsupported prototype mode')
    return EquityDecision.from_facts(target, reason, facts=facts, next_watch='下一根完成K线复核同一规则及实际持仓')
