"""C9380 financial predicates expressed as staged targets on the original entry cash.

Only confirmed position feedback and HFQ observations enter the decision.
Execution prices, cash, quantities and orders are exclusively channel-owned.
"""
import numpy as np
import pandas as pd

from strategy_runtime import SignalBasisSnapshot, SignalExplanationSnapshot
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def _decision(target, judgment, summary, next_watch, details):
    basis = (SignalBasisSnapshot('summary', summary),
             *(SignalBasisSnapshot(key, text) for key, text in details),
             SignalBasisSnapshot('target_weight', f'累计投入目标为首次入场可用现金的 {target * 100:.6g}%。' if target else '目标空仓。'))
    return AccountDecision(float(target), SignalExplanationSnapshot(
        'target', 'long' if target else 'flat', judgment, basis, next_watch,
        ' '.join(item.text for item in basis)))


def _entry_explanation(closes, dates, n, enter, group, common, total, p, allocation, target):
    span = '两个交易日' if n == 2 else f'{n} 个交易日'
    stamps = pd.DatetimeIndex(dates[-(n+1):]).tz_convert('America/New_York')
    path = ' → '.join(f'{stamp.month} 月 {stamp.day} 日 {price:,.2f}'
                     for stamp, price in zip(stamps, closes, strict=True))
    basis = [('adjusted_closes', f'MU 后复权收盘价：{path}。')]
    if enter:
        summary = f'MU 连续{span}收跌，首次累计投入目标为入场资金的 {target:.2%}。'
        basis.append(('entry_allocation',
                      f'按板块贡献判定，采用 {"板块主导" if group else "其他"} 档配置。'
                      f'板块估计贡献 {common:.4%}，分类门槛 {p["common_share"] * total:.4%}（对数收益）。'
                      f'本轮配置 {allocation:.2%}，首次采用其中的 {p["initial_fraction"]:.2%}。'))
        return _decision(target, '触发入场', summary, '关注渠道成交回报和下一交易日收盘。', basis)
    if closes[-1] > closes[-2]:
        reason = 'MU 当日收盘反弹'
    elif closes[-1] == closes[-2]:
        reason = 'MU 当日收盘持平'
    else:
        reason = 'MU 此前的收盘走势中断了连续下跌'
    summary = f'{reason}，未满足连续{span}收跌的买入条件。'
    return _decision(target, '继续空仓', f'{summary} MU 后复权收盘价 {path}。',
                     '等下一交易日收盘，再检查买入条件。', basis)


def _confirmation_basis(mode, price, sector_price, anchor, sector_anchor, p):
    if mode == 'scheduled':
        return '按约定持有日执行加仓，无需额外价格确认。'
    if mode == 'never':
        return '本轮不设加仓。'
    line = anchor * (1+p['add_mu_margin'])
    comparison = '不高于' if mode == 'weakness' else '高于'
    rule = f'MU 收盘 {price:,.4f}，要求{comparison} {line:,.4f}'
    if mode == 'repair_both':
        rule += f'；SOXX 收盘 {sector_price:,.4f}，要求高于 {sector_anchor * (1+p["add_sector_margin"]):,.4f}'
    return rule + '。以上均为后复权价格。'


def entry_observation(windows, beta_window, entry_days, common_share):
    mu, soxx = windows
    dates = tuple(pd.Timestamp(row['Date']).to_pydatetime() for row in mu)
    sector_dates = tuple(pd.Timestamp(row['Date']).to_pydatetime() for row in soxx)
    if dates != sector_dates:
        raise ValueError('MU and SOXX observation dates must agree')
    prices = np.array([row['Close'] for row in mu], dtype=float)
    sector_prices = np.array([row['Close'] for row in soxx], dtype=float)
    w, n = int(beta_window), int(entry_days)
    m, s = np.diff(np.log(prices)), np.diff(np.log(sector_prices))
    variance = np.var(s[-(w+n):-n], ddof=1)
    if not np.isfinite(variance) or variance <= 0:
        raise ValueError('sector return variance must be finite and positive')
    beta = float(np.cov(m[-(w+n):-n], s[-(w+n):-n], ddof=1)[0, 1] / variance)
    common = beta * float(s[-n:].sum())
    total = float(m[-n:].sum())
    group = bool(common < common_share * total)
    enter = bool(np.all(np.diff(prices[-(n+1):]) < 0))
    return (float(prices[-1]), float(sector_prices[-1]), common, total, group, enter,
            *map(float, prices[-(n+1):]), *dates)


from datetime import timedelta
from zoneinfo import ZoneInfo
from strategy_runtime import StepDataWindow

_ZONE = ZoneInfo("America/New_York")


def bars(ctx, name, first, last, count=None):
    frame = ctx.dfls.fetch(StepDataWindow(name, first, last))
    if count is not None:
        if len(frame) < count:
            raise ValueError(f"{name}: 已完结行情不足 {count} 根")
        frame = frame.tail(count)
    return tuple(frame.to_dict("records"))


def step(ctx, state):
    p = ctx.parameters
    n = int(p['entry_days'])
    day = ctx.point.observed_through.astimezone(_ZONE).date()
    first = day - timedelta(days=119)
    mu = bars(ctx, 'mu_daily', first, day, 63)
    soxx = bars(ctx, 'soxx_daily', first, day, 63)
    if mu[-1]['Date'].astimezone(_ZONE).date() != day:
        raise ValueError('缺少信号日的 MU 收盘行情')
    price, sector_price, common, total, group, enter, *history = entry_observation(
        (mu, soxx), p['beta_window'], n, p['common_share'])
    closes, dates = history[:n+1], history[n+1:]
    allocation_now = float(p['common_budget'] if group else p['other_budget'])
    active = ctx.position.active
    if active is None:
        anchor, sector_anchor = price, sector_price
        allocation = allocation_now
        promoted = exiting = False
        target = allocation * float(p['initial_fraction']) if enter else 0.
        decision = _entry_explanation(closes, dates, n, enter, group, common, total, p, allocation, target)
    else:
        if state.cycle is None or state.cycle.cycle_id != active.cycle_id:
            raise ValueError('confirmed position requires matching financial cycle state')
        anchor = state.cycle.values.get('anchor')
        sector_anchor = state.cycle.values.get('sector_anchor')
        allocation = state.cycle.values.get('allocation')
        confirmed_add = bool(state.cycle.values.get('promoted') and active.buy_fills > 1)
        promoted = confirmed_add
        was_exiting = state.cycle.values.get('exiting')
        held = int(sum(t >= active.entry_interval.start for t in dates))
        exit_line = anchor * (1+p['exit_margin'])
        time_exit = held >= p['max_hold']
        exit_signal = bool(time_exit or (held >= p['review_after'] and price <= exit_line))
        mode = p['add_mode']
        confirmation = False
        if mode == 'repair':
            confirmation = bool(price > anchor * (1+p['add_mu_margin']))
        elif mode == 'repair_both':
            confirmation = bool(price > anchor * (1+p['add_mu_margin']) and
                                sector_price > sector_anchor * (1+p['add_sector_margin']))
        elif mode == 'scheduled':
            confirmation = True
        elif mode == 'weakness':
            confirmation = bool(price <= anchor * (1+p['add_mu_margin']))
        elif mode != 'never':
            raise ValueError('unsupported confirmation mode')
        exiting = exit_signal
        held_basis = ('held_sessions', f'已持有 {held} 个交易日。第 {p["review_after"]} 日起检查价格退出，'
                       f'最长持有 {p["max_hold"]} 个交易日。')
        if exiting:
            target = 0.
            if was_exiting:
                summary = '此前已决定退出，渠道仍确认有剩余持仓。'
            elif time_exit:
                summary = f'已达到最长持有期 {p["max_hold"]} 个交易日，目标清仓。'
            else:
                summary = '已到复核期，MU 收盘未超过退出线，目标清仓。'
            decision = _decision(target, '目标清仓', summary, '关注渠道成交回报，确认是否完成清仓。',
                                 (held_basis, ('exit_check',
                                    f'MU 后复权收盘 {price:,.4f}，价格退出线 {exit_line:,.4f}。')))
        else:
            lift = bool(active.buy_fills == 1 and p['initial_fraction'] < 1 and
                        held >= p['earliest_add'] and confirmation)
            promoted = bool(promoted or lift)
            target = float(allocation if promoted else allocation * p['initial_fraction'])
            if lift:
                summary = f'已到允许加仓的日期，确认条件已满足，累计投入目标提高至入场资金的 {target:.2%}。'
            elif promoted or p['initial_fraction'] >= 1:
                summary = f'尚未触发退出，延续本轮累计投入目标 {target:.2%}。'
            elif mode == 'never':
                summary = f'本轮不加仓，尚未触发退出，延续首次累计投入目标 {target:.2%}。'
            elif held < p['earliest_add']:
                summary = f'尚未到第 {p["earliest_add"]} 个交易日，延续首次累计投入目标 {target:.2%}。'
            elif active.buy_fills != 1:
                summary = f'实际买入成交次数为 {active.buy_fills}，沿用首次目标仓位 {target:.2%}。'
            else:
                summary = f'加仓确认条件尚未满足，延续首次累计投入目标 {target:.2%}。'
            confirmation_basis = _confirmation_basis(mode, price, sector_price, anchor, sector_anchor, p)
            details = (held_basis, ('exit_check', f'MU 后复权收盘 {price:,.4f}，价格退出线 {exit_line:,.4f}。'),
                       ('confirmation', confirmation_basis))
            decision = _decision(target, '提高目标仓位' if lift else '延续目标仓位', summary,
                                 '下一交易日收盘后，复核持有和退出条件。', details)
    values = StateRecord((('anchor', anchor), ('sector_anchor', sector_anchor),
                          ('allocation', allocation), ('promoted', promoted), ('exiting', exiting)))
    return AccountStepResult(decision, cycle_values=values if active is not None or target else None)
