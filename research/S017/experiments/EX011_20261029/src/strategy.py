"""Thirty-minute opening-range continuation, with confirmed-cycle exits."""
from zoneinfo import ZoneInfo

from strategy_runtime.equity_definition import EquityDecision


def opening_facts(history, session, volume_gate):
    """Use completed RTH bars; the fixed 14-session comparison excludes today."""
    tail = history.iloc[-261:]
    start, end = session.segments[0].start, session.segments[-1].end
    current = tail.loc[(tail.BarStart >= start) & (tail.Date <= end)]
    if current.empty:
        return None, current
    if current.BarStart.iloc[0].to_pydatetime() != start:
        raise ValueError('current opening bar is absent from completed observations')
    first = current.iloc[0]
    local_starts = tail.BarStart.dt.tz_convert(session.timezone)
    prior = tail.loc[(tail.Date <= start) & local_starts.dt.hour.eq(9)
                     & local_starts.dt.minute.eq(30)]
    if volume_gate and len(prior) < 14:
        raise ValueError('volume gate requires 14 prior completed session opening bars')
    mean_volume = float(prior.Volume.iloc[-14:].mean()) if len(prior) >= 14 else None
    if mean_volume is not None and mean_volume <= 0:
        raise ValueError('opening-volume comparison requires a positive prior mean')
    opening_volume = float(first.Volume)
    facts = dict(opening_open=float(first.Open), opening_high=float(first.High),
        opening_low=float(first.Low), opening_close=float(first.Close),
        opening_range=float(first.High-first.Low), opening_volume=opening_volume,
        prior_opening_mean_volume=mean_volume,
        opening_relative_volume=None if mean_volume is None else opening_volume/mean_volume,
        relative_volume_sessions=14, volume_gate=volume_gate,
        opening_bullish=bool(first.Close > first.Open))
    return facts, current


def cycle_stop(current, portfolio, opening):
    """Reconstruct a ratchet and latch from this actual, single-fill cycle only."""
    if portfolio.cycle_entry is None or portfolio.quantity <= 0 or portfolio.cycle_cost <= 0:
        raise ValueError('a confirmed filled cycle with positive cost is required')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('this RAW prototype does not support split rebasing')
    width = opening['opening_range']
    if width <= 0:
        raise ValueError('an entered opening-range cycle requires a positive range')
    # BAR_RANGE_V1 uses a single entry fill and a complete exit. This is not a
    # partial-liquidation or PTE implementation.
    cost_reference = float(portfolio.cycle_cost/portfolio.quantity)
    cycle = current.loc[current.Date > portfolio.cycle_entry]
    if cycle.empty:
        raise ValueError('actual entry has no completed holding observation')
    peak = cost_reference
    stop = opening['opening_low']
    stop_hit = False
    first_trigger = None
    levels = []
    for row in cycle.itertuples():
        peak = max(peak, float(row.Close))
        stop = max(stop, peak-width)
        levels.append(stop)
        if float(row.Close) <= stop:
            stop_hit = True
            if first_trigger is None:
                first_trigger = row.Date.isoformat()
    return dict(stop=stop, initial_stop=opening['opening_low'], peak_close=peak,
        cost_reference_per_share=cost_reference, stop_hit=stop_hit,
        first_trigger_at=first_trigger, cycle_observations=len(cycle), levels=levels)


def decide(ctx):
    h, portfolio, session = ctx.history, ctx.portfolio, ctx.session
    if session is None or portfolio.closed_cycle_feedback is None:
        raise ValueError('session and confirmed closed-cycle feedback are required')
    if set(ctx.parameters) != {'volume_gate'} or type(ctx.parameters['volume_gate']) is not bool:
        raise ValueError('the sole experimental parameter is boolean volume_gate')
    volume_gate = ctx.parameters['volume_gate']
    if h.empty:
        raise ValueError('completed history is required')
    held = portfolio.quantity > 0
    zone = ZoneInfo(session.timezone)
    entry_day = (None if portfolio.cycle_entry is None else portfolio.cycle_entry.astimezone(zone).date())
    last_interval = ctx.point.execution_interval.end == session.segments[-1].end
    latest_closed = portfolio.closed_cycle_feedback.latest
    entered_today = (latest_closed is not None
        and latest_closed.entry_interval.start.astimezone(zone).date() == session.session_date)
    facts = dict(close=float(h.Close.iloc[-1]), held=held, session_date=session.session_date.isoformat(),
        session_end=session.segments[-1].end.isoformat(), last_execution_interval=last_interval,
        volume_gate=volume_gate, completed_entry_cycle_today=entered_today,
        actual_entry=None if portfolio.cycle_entry is None else portfolio.cycle_entry.isoformat(),
        stop_width_multiple=1., closed_cycle_id=None if latest_closed is None else latest_closed.cycle_id)

    if held and entry_day is None:
        raise ValueError('held quantity requires actual cycle entry')
    if held and entry_day > session.session_date:
        raise ValueError('actual entry cannot lie after the current session')
    if held and entry_day < session.session_date:
        target, reason = 0, '上一交易日退出未完成，继续卖出隔夜残留仓位'
        facts['overnight_residual'] = True
    elif last_interval:
        target, reason = 0, '进入当日最后可执行区间，退出持仓并禁止新买入'
    elif not held and entered_today:
        target, reason = 0, '本会话已有实际完成的入场周期，保持空仓避免重复试错'
    else:
        opening, current = opening_facts(h, session, volume_gate)
        if opening is None:
            target, reason = 0, '首根30分钟区间尚未完成，等待开盘价格发现'
            facts['opening_observed'] = False
        else:
            facts.update(opening, opening_observed=True)
            if held:
                state = cycle_stop(current, portfolio, opening)
                facts.update({name: value for name, value in state.items() if name != 'levels'})
                target = int(not state['stop_hit'])
                reason = ('完成收盘已触发只上移止损，持续退出直至成交' if not target
                          else '本次实际持仓的移动止损未触发，保留日内上涨延续')
            else:
                breakout = facts['close'] > opening['opening_high']
                active_volume = (not volume_gate or opening['opening_volume'] > opening['prior_opening_mean_volume'])
                target = int(opening['opening_range'] > 0 and opening['opening_bullish']
                             and breakout and active_volume)
                facts.update(breakout=breakout, volume_allowed=active_volume)
                reason = ('上涨开盘区间已被完成收盘突破，下一执行区间尝试参与' if target
                          else '开盘方向、完成突破或相对成交量条件尚未同时成立')
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='仅用下一根已完成K线与真实账户反馈；移动止损只上移，触发或日终退出持续至成交')
