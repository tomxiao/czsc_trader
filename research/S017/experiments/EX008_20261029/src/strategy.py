"""Price-only breakout with actual-cycle, causal, ratcheting close-based stops."""
from dataclasses import replace
from zoneinfo import ZoneInfo
from strategy_runtime.equity_definition import EquityDecision


def cycle_levels(history, portfolio, parameters):
    if portfolio.quantity <= 0 or portfolio.cycle_entry is None or portfolio.cycle_cost <= 0:
        raise ValueError('a filled long cycle with positive cost is required')
    if portfolio.reference_price_scale != 1.:
        raise ValueError('this RAW-price prototype does not support split rebasing')
    entry = portfolio.cycle_entry
    first = int(history.Date.searchsorted(entry, side='right'))
    cycle = history.iloc[first:]
    if cycle.empty:
        raise ValueError('no completed close after actual entry interval start')
    basis = float(portfolio.cycle_cost / portfolio.quantity)
    mode = parameters['exit_mode']
    daily_atr = None
    if mode in ('ATR_TRAIL', 'INITIAL_ATR_ONLY'):
        # The finite prefix covers more than 15 full RTH sessions. Remove its
        # first session since the positional slice may start midway through it.
        tail = history.iloc[max(0, first-400):].copy()
        tail['_session'] = tail.Date.dt.tz_convert('America/New_York').dt.date
        daily = tail.groupby('_session', sort=True).agg(High=('High','max'), Low=('Low','min'), Close=('Close','last'))
        previous = daily.Close.shift(1)
        ranges = (daily.High-daily.Low).to_frame('range')
        ranges['up'] = (daily.High-previous).abs()
        ranges['down'] = (daily.Low-previous).abs()
        # The discarded partial day's final close is still the correct prior
        # close for the following full day's gap-aware true range.
        ranges = ranges.iloc[1:]
        daily_atr = ranges.max(axis=1).rolling(parameters['atr_days'], min_periods=parameters['atr_days']).mean().shift(1)
        entry_day = entry.astimezone(ZoneInfo('America/New_York')).date()
        initial_atr = float(daily_atr.loc[entry_day])
        if not initial_atr > 0:
            raise ValueError('entry requires positive ATR from prior completed sessions')
        level = basis - parameters['initial_atr_multiple']*initial_atr
    elif mode == 'PERCENT_TRAIL':
        initial_atr = None
        level = basis*(1.-parameters['stop_fraction'])
    else:
        raise ValueError('unsupported cycle stop mode')
    initial_stop = level
    closes = cycle.Close.astype(float)
    peaks = closes.cummax().clip(lower=basis)
    if mode == 'PERCENT_TRAIL':
        levels = peaks*(1.-parameters['stop_fraction'])
    elif mode == 'ATR_TRAIL':
        atrs = cycle.Date.dt.tz_convert('America/New_York').dt.date.map(daily_atr)
        if not bool(atrs.gt(0).all()):
            raise ValueError('cycle ATR must be positive and causal')
        levels = (peaks-parameters['atr_multiple']*atrs).clip(lower=initial_stop).cummax()
        if parameters['profit_protection']:
            floor = peaks*0.+initial_stop
            floor.loc[peaks.ge(basis+parameters['protect_gain_atr']*initial_atr)] = basis
            levels = levels.clip(lower=floor).cummax()
    else:
        levels = closes*0.+initial_stop
    return dict(stop=float(levels.iloc[-1]), initial_stop=initial_stop,
                peak_close=float(peaks.iloc[-1]), stop_hit=bool(closes.le(levels).any()),
                entry_cost_per_share=basis, entry_atr=initial_atr, levels=levels.tolist(),
                cycle_observations=len(cycle))



def recovery_level(history, portfolio, parameters):
    """Freeze the FIRST stop-triggering close, bounded by actual exit observation."""
    feedback = portfolio.closed_cycle_feedback
    if feedback is None:
        raise ValueError('CLOSED_CYCLE_FEEDBACK_UNAVAILABLE')
    closed = feedback.latest
    if closed is None:
        return None
    prior = history.loc[history.Date <= closed.exit_observed_through]
    actual = replace(portfolio, quantity=closed.entry_quantity,
                     cycle_entry=closed.entry_interval.start, cycle_cost=closed.entry_cost,
                     reference_price_scale=1.)
    state = cycle_levels(prior, actual, parameters)
    cycle = prior.loc[prior.Date > closed.entry_interval.start]
    for row, level in zip(cycle.itertuples(), state['levels']):
        if float(row.Close) <= level:
            return dict(recovery_stop=float(level), recovery_trigger_at=row.Date.isoformat(),
                        closed_cycle_id=closed.cycle_id,
                        closed_exit_observed=closed.exit_observed_through.isoformat())
    raise ValueError('closed cycle has no causal stop trigger under this fixed strategy')


def recovery_background(history, parameters):
    """Price position and slope of trailing means, excluding current close."""
    mode = parameters['recovery_gate']
    if mode not in ('NONE', 'ABOVE_MEAN', 'ABOVE_RISING_MEAN'):
        raise ValueError('unsupported recovery background')
    if mode == 'NONE':
        return dict(background_allowed=True, recovery_gate=mode)
    n, lag = parameters['background_bars'], parameters['background_slope_bars']
    if len(history) < n+lag+1:
        raise ValueError('insufficient completed history for recovery background')
    close = float(history.Close.iloc[-1])
    mean = float(history.Close.iloc[-n-1:-1].mean())
    earlier = float(history.Close.iloc[-n-lag-1:-lag-1].mean())
    above, rising = close > mean, mean > earlier
    allowed = above and (mode == 'ABOVE_MEAN' or rising)
    return dict(background_allowed=allowed, recovery_gate=mode,
                prior_mean=mean, lagged_prior_mean=earlier,
                above_prior_mean=above, mean_rising=rising,
                background_bars=n, background_slope_bars=lag)


def decide(ctx):
    p, h, portfolio = ctx.parameters, ctx.history, ctx.portfolio
    held = portfolio.quantity > 0
    close = float(h.Close.iloc[-1])
    upper = float(h.High.iloc[-p['entry_bars']-1:-1].max())
    facts = dict(close=close, held=held, prior_upper=upper, entry_bars=p['entry_bars'],
                 exit_mode=p['exit_mode'], stop_fraction=p['stop_fraction'],
                 atr_days=p['atr_days'], atr_multiple=p['atr_multiple'],
                 initial_atr_multiple=p['initial_atr_multiple'], profit_protection=p['profit_protection'],
                 protect_gain_atr=p['protect_gain_atr'])
    if not held:
        recovery = recovery_level(h, portfolio, p)
        breakout = close > upper
        background = recovery_background(h, p)
        recovered = (recovery is not None and close > recovery['recovery_stop']
                     and background['background_allowed'])
        facts.update(background)
        target = int(breakout or recovered)
        facts.update(breakout_entry=breakout, recovery_entry=recovered,
                     closed_history=portfolio.closed_cycle_feedback.latest is not None)
        if recovery is not None:
            facts.update(recovery)
        reason = ('突破此前区间，尝试进入上涨趋势' if breakout else
                  '真实平仓后价格恢复且背景条件成立，尝试恢复参与' if recovered else
                  '等待原区间突破或满足背景的真实平仓后恢复')
    elif p['exit_mode'] == 'CHANNEL':
        lower = float(h.Low.iloc[-p['exit_bars']-1:-1].min())
        target = int(close >= lower)
        facts.update(prior_lower=lower, exit_bars=p['exit_bars'])
        reason = '短区间支持仍在，保持持仓' if target else '跌破短区间支持，退出'
    else:
        state = cycle_levels(h, portfolio, p)
        target = int(not state['stop_hit'])
        facts.update({key:value for key,value in state.items() if key != 'levels'})
        reason = '已触发止损，继续请求退出直至成交' if not target else '止损未触发，跟随上涨并保留持仓'
    return EquityDecision.from_facts(target, reason, facts=facts,
        next_watch='下一根完成K线核对实际持仓；止损只上移，触发后下一可执行区间卖出')
