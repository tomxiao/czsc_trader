"""Price-only breakout with actual-cycle, causal, ratcheting close-based stops."""
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
        target = int(close > upper)
        reason = '突破此前区间，尝试进入上涨趋势' if target else '等待收盘突破此前区间'
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
