"""Market reversal with a controlled test of stock resistance to the prior dip."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from strategy_runtime import EquityDecision


def _decision(target, reason, facts):
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一已完成30分钟柱、实际成交反馈或会话最后可执行区间')


def _calendar(ctx):
    if ctx.session is None:
        raise ValueError('CURRENT_SESSION_UNAVAILABLE')
    intervals = []
    for segment in ctx.session.segments:
        start = segment.start
        while start < segment.end:
            end = start + timedelta(minutes=30)
            if end > segment.end:
                raise ValueError('SESSION_NOT_ALIGNED_TO_30M')
            intervals.append((start, end))
            start = end
    current = (ctx.point.execution_interval.start, ctx.point.execution_interval.end)
    if current not in intervals:
        raise ValueError('EXECUTION_INTERVAL_OUTSIDE_SESSION')
    return intervals, intervals.index(current)


def _require_visible(frame, ctx):
    if frame.empty or 'Date' not in frame or 'AvailableDate' not in frame:
        raise ValueError('VISIBLE_HISTORY_UNAVAILABLE')
    if (frame.Date > ctx.point.decision_at).any() or (frame.AvailableDate > ctx.point.decision_at).any():
        raise ValueError('FUTURE_OBSERVATION_FORBIDDEN')
    if frame.Date.duplicated().any() or not frame.Date.is_monotonic_increasing:
        raise ValueError('HISTORY_REQUIRES_UNIQUE_ORDERED_TIMESTAMPS')


def _exact(frame, interval, label):
    rows = frame.loc[frame.Date == interval[1]]
    if len(rows) != 1 or 'BarStart' not in rows or rows.BarStart.iloc[0] != interval[0]:
        raise ValueError('EXACT_TWO_BAR_ALIGNMENT_UNAVAILABLE:' + label)
    return rows.iloc[0]


def _held(ctx):
    portfolio = ctx.portfolio
    if portfolio.cycle_entry is None or portfolio.cycle_cost <= 0:
        raise ValueError('ACTUAL_ENTRY_FACTS_UNAVAILABLE')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('RAW_SPLIT_REBASING_UNSUPPORTED')
    before = ctx.history.loc[(ctx.history.Date <= portfolio.cycle_entry)
                             & (ctx.history.AvailableDate <= portfolio.cycle_entry)]
    if before.empty or before.Date.iloc[-1] != portfolio.cycle_entry:
        raise ValueError('ACTUAL_ENTRY_SIGNAL_BAR_UNAVAILABLE')
    initial = float(before.Low.iloc[-1])
    basis = float(portfolio.cycle_cost / portfolio.quantity)
    risk = basis - initial
    facts = {'actual_entry': portfolio.cycle_entry.isoformat(), 'cost_per_share': basis,
             'initial_signal_low': initial, 'risk_width': risk}
    if risk <= 0:
        return _decision(0, '实际每股成本不高于入场反转柱低点，风险宽度无效，退出', facts)
    completed = ctx.history.loc[ctx.history.Date > portfolio.cycle_entry]
    if completed.empty:
        raise ValueError('FILLED_CYCLE_COMPLETED_BAR_UNAVAILABLE')
    peak = None
    first_hit = None
    line = initial
    for row in completed.itertuples():
        close = float(row.Close)
        peak = close if peak is None else max(peak, close)
        line = max(initial, peak - risk)
        if first_hit is None and close <= line:
            first_hit = row.Date
    facts.update(peak_close=peak, trailing_stop=line,
                 first_stop_observation=None if first_hit is None else first_hit.isoformat())
    if first_hit is not None:
        return _decision(0, '已完成收盘曾触及移动止损，持续退出直到实际成交', facts)
    return _decision(1, '实际持仓未触及初始低点或只上移的收盘移动止损', facts)


def decide(ctx):
    if set(ctx.parameters) != {'antidip'} or type(ctx.parameters['antidip']) is not bool:
        raise ValueError('EX012_REQUIRES_BOOLEAN_ANTIDIP_PARAMETER')
    if ctx.portfolio is None or ctx.portfolio.closed_cycle_feedback is None:
        raise ValueError('CONFIRMED_CLOSED_CYCLE_FEEDBACK_REQUIRED')
    if 'market' not in ctx.auxiliary_histories:
        raise ValueError('MARKET_AUXILIARY_UNAVAILABLE')
    _require_visible(ctx.history, ctx)
    _require_visible(ctx.auxiliary_histories['market'], ctx)
    intervals, index = _calendar(ctx)
    day = ctx.session.session_date
    if ctx.portfolio.quantity:
        if ctx.portfolio.cycle_entry is None:
            raise ValueError('ACTUAL_ENTRY_FACTS_UNAVAILABLE')
        entry_day = ctx.portfolio.cycle_entry.astimezone(ZoneInfo(ctx.session.timezone)).date()
        if entry_day != day:
            return _decision(0, '隔夜残留持仓继续退出', {'entry_day': str(entry_day), 'session_day': str(day)})
        if index == len(intervals) - 1:
            return _decision(0, '进入会话最后可执行区间，退出持仓', {'session_day': str(day)})
        return _held(ctx)
    if index == len(intervals) - 1:
        return _decision(0, '会话最后可执行区间禁止新买入', {'session_day': str(day)})
    closed = ctx.portfolio.closed_cycle_feedback.latest
    if closed is not None:
        entry_day = closed.entry_interval.start.astimezone(ZoneInfo(ctx.session.timezone)).date()
        if entry_day == day:
            return _decision(0, '本会话已有实际入场且完成退出，不重复入场', {'closed_cycle_id': closed.cycle_id})
    if index < 2:
        return _decision(0, '等待当前会话内两根完整30分钟柱', {'completed_session_bars': index})
    previous, current = intervals[index - 2], intervals[index - 1]
    market = ctx.auxiliary_histories['market']
    market_previous = _exact(market, previous, 'SPY_previous')
    market_current = _exact(market, current, 'SPY_current')
    # A known absent stock observation removes signal eligibility. Malformed
    # observations and missing auxiliary evidence remain explicit errors.
    session_stock = ctx.history.loc[(ctx.history.Date > intervals[0][0])
                                    & (ctx.history.Date <= intervals[-1][1])]
    if 'BarStart' not in session_stock or any((row.BarStart, row.Date) not in intervals
                                             for row in session_stock.itertuples()):
        raise ValueError('PRIMARY_SESSION_TIMESTAMP_MISALIGNED')
    missing = [interval[1].isoformat() for interval in (previous, current)
               if not (ctx.history.Date == interval[1]).any()]
    if missing:
        return _decision(0, 'TWO_BAR_SIGNAL_INELIGIBLE：相邻两根个股完成柱不齐全，等待完整观察',
            {'signal_status': 'TWO_BAR_SIGNAL_INELIGIBLE', 'missing_stock_bar_ends': str(missing)})
    lite_previous = _exact(ctx.history, previous, 'LITE_previous')
    lite_current = _exact(ctx.history, current, 'LITE_current')
    market_down = float(market_previous.Close) < float(market_previous.Open)
    market_up = float(market_current.Close) > float(market_current.Open)
    lite_return = float(lite_current.Close / lite_current.Open - 1.)
    market_return = float(market_current.Close / market_current.Open - 1.)
    stronger = lite_return > market_return
    held_up = float(lite_previous.Close) >= float(lite_previous.Open)
    target = int(market_down and market_up and stronger and (held_up or not ctx.parameters['antidip']))
    facts = {'spy_previous_down': market_down, 'spy_current_up': market_up,
             'lite_current_return': lite_return, 'spy_current_return': market_return,
             'lite_stronger_than_spy': stronger, 'lite_previous_nonnegative': held_up,
             'antidip_required': ctx.parameters['antidip'], 'signal_low': float(lite_current.Low),
             'signal_observed_at': current[1].isoformat()}
    return _decision(target, '大盘先跌后涨且个股当前上涨更强，抗跌要求按配置判断' if target
                     else '同会话两柱的市场反转、相对涨幅或抗跌条件未同时满足', facts)
