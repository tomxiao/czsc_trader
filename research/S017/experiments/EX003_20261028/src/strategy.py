"""A causal slow-trend buffer using actual positions, not hidden signal state."""
from strategy_runtime.equity_definition import EquityDecision


def decide(ctx):
    p, h = ctx.parameters, ctx.history
    held = ctx.portfolio.quantity > 0
    close = float(h.Close.iloc[-1])
    mean = float(h.Close.iloc[-p['trend_bars']:].mean())
    tail = h.iloc[-p['vol_bars']:]
    previous = h.Close.shift(1).iloc[-p['vol_bars']:]
    ranges = [max(float(hi-lo),abs(float(hi-prev)),abs(float(lo-prev)))
              for hi,lo,prev in zip(tail.High,tail.Low,previous)]
    atr = sum(ranges)/len(ranges)
    entry = mean + p['entry_atr']*atr
    exit_price = mean - p['exit_atr']*atr
    target = int(close > (exit_price if held else entry))
    reason = ('持仓仍在缓冲下沿之上' if target else '跌至缓冲下沿，退出') if held else ('越过入场缓冲，尝试买入' if target else '尚未越过入场缓冲')
    return EquityDecision.from_facts(target, reason,
        facts={'close':close,'held':held,'mean':mean,'atr':atr,'entry_threshold':entry,'exit_threshold':exit_price,
               'trend_bars':p['trend_bars'],'vol_bars':p['vol_bars'],'entry_atr':p['entry_atr'],'exit_atr':p['exit_atr']},
        next_watch='下一根完成K线复核动态缓冲边界与实际持仓')
