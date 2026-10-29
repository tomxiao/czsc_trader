"""Causal M30 pullback-resumption entry; the C0013 held-position rule is unchanged."""
from strategy_runtime.equity_definition import EquityDecision


def pat_entry(history):
    """Rebuild confirmed pivots within 261 observed bars; never amend old decisions."""
    h = history.iloc[-261:]
    highs, lows = h.High.to_numpy(), h.Low.to_numpy()
    pivots = []
    ambiguous = 0
    for i in range(1, len(h) - 1):
        high = highs[i] > highs[i - 1] and highs[i] > highs[i + 1]
        low = lows[i] < lows[i - 1] and lows[i] < lows[i + 1]
        if high and low:
            ambiguous += 1
            continue
        if not high and not low:
            continue
        kind, price = ('H', float(highs[i])) if high else ('L', float(lows[i]))
        point = (kind, i, price)
        if pivots and pivots[-1][0] == kind:
            if (kind == 'H' and price > pivots[-1][2]) or (kind == 'L' and price < pivots[-1][2]):
                pivots[-1] = point
        else:
            pivots.append(point)
    facts = {'pat_window_bars': len(h), 'pat_pivot_count': len(pivots),
             'pat_ambiguous_bars': ambiguous, 'pat_structure': False,
             'pat_intact': False, 'pat_trigger': False}
    selected = pivots[-4:]
    if len(selected) != 4 or [p[0] for p in selected] != ['H', 'L', 'H', 'L']:
        return False, facts
    h1, l1, h2, l2 = selected
    structure = h2[2] > h1[2] and l2[2] > l1[2]
    # Include discarded outside bars: ambiguous intrabar order cannot erase a breach.
    intact = min(lows[h2[1] + 1:]) > l1[2]
    trigger = float(h.Close.iloc[-1]) > float(highs[-2])
    facts.update(pat_structure=bool(structure), pat_intact=bool(intact), pat_trigger=bool(trigger),
        pat_h1=h1[2], pat_l1=l1[2], pat_h2=h2[2], pat_l2=l2[2],
        pat_l2_at=h.Date.iloc[l2[1]].isoformat(),
        pat_l2_confirmed_at=h.Date.iloc[l2[1] + 1].isoformat(),
        pat_trigger_level=float(highs[-2]))
    return bool(structure and intact and trigger), facts


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
    if held:
        target = int(close > exit_price)
        reason = '持仓仍在缓冲下沿之上' if target else '跌至缓冲下沿，退出'
        pat = {}
    else:
        trigger, pat = pat_entry(h)
        target = int(trigger)
        reason = '30m抬高结构回调后恢复，尝试买入' if target else '未形成30m回调恢复入场条件'
    return EquityDecision.from_facts(target, reason,
        facts={'close':close,'held':held,'mean':mean,'atr':atr,'entry_threshold':entry,'exit_threshold':exit_price,
               'trend_bars':p['trend_bars'],'vol_bars':p['vol_bars'],'entry_atr':p['entry_atr'],'exit_atr':p['exit_atr'],
               **pat},
        next_watch='下一根完成K线复核；持仓按原C13动态缓冲退出，空仓按30m PAT重新判断')
