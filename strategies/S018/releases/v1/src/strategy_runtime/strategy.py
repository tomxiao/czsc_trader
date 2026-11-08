"""C9380 financial predicates expressed as current-equity target weights.

Only confirmed position feedback and HFQ observations enter the decision.
Execution prices, cash, quantities and orders are exclusively channel-owned.
"""
import numpy as np

from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    p = ctx.parameters
    w, n = int(p['beta_window']), int(p['entry_days'])
    size = max(63, w + n + 1, int(p['max_hold']) + 1)
    mu = ctx.history.to_frame(tail=size)
    sector = ctx.auxiliary_histories['soxx_hfq'].to_frame(tail=size)
    if mu.Date.tolist() != sector.Date.tolist():
        raise ValueError('MU and SOXX observation dates must agree')
    if max(mu.AvailableDate.max(), sector.AvailableDate.max()) > ctx.point.decision_at:
        raise ValueError('observations must be available by the decision time')
    price, sector_price = float(mu.Close.iloc[-1]), float(sector.Close.iloc[-1])
    m, s = np.diff(np.log(mu.Close.to_numpy())), np.diff(np.log(sector.Close.to_numpy()))
    variance = np.var(s[-(w+n):-n], ddof=1)
    if not np.isfinite(variance) or variance <= 0:
        raise ValueError('sector return variance must be finite and positive')
    beta = float(np.cov(m[-(w+n):-n], s[-(w+n):-n], ddof=1)[0, 1] / variance)
    common = beta * float(s[-n:].sum())
    total = float(m[-n:].sum())
    group = bool(common < p['common_share'] * total)
    allocation_now = float(p['common_budget'] if group else p['other_budget'])
    enter = bool(np.all(np.diff(mu.Close.to_numpy()[-(n+1):]) < 0))
    active = ctx.position.active
    held, confirmation, exit_signal = 0, False, False
    if active is None:
        anchor, sector_anchor = price, sector_price
        allocation = allocation_now
        promoted = exiting = False
        target = allocation * float(p['initial_fraction']) if enter else 0.
        reason = 'entry' if enter else 'no opportunity'
    else:
        if state.cycle is None or state.cycle.cycle_id != active.cycle_id:
            raise ValueError('confirmed position requires matching financial cycle state')
        anchor = state.cycle.values.get('anchor')
        sector_anchor = state.cycle.values.get('sector_anchor')
        allocation = state.cycle.values.get('allocation')
        promoted = state.cycle.values.get('promoted')
        exiting = state.cycle.values.get('exiting')
        held = int(sum(t >= active.entry_interval.start for t in mu.Date))
        exit_signal = bool(held >= p['max_hold'] or
                           (held >= p['review_after'] and price <= anchor * (1+p['exit_margin'])))
        mode = p['add_mode']
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
        exiting = bool(exiting or exit_signal)
        if exiting:
            target, reason = 0., 'complete'
        else:
            lift = bool(not promoted and p['initial_fraction'] < 1 and
                        held >= p['earliest_add'] and confirmation)
            promoted = bool(promoted or lift)
            target = float(allocation if promoted else allocation * p['initial_fraction'])
            reason = 'increase target after ' + mode if lift else 'hold'
    decision = AccountDecision.from_facts(float(target), reason,
        facts={'anchor': anchor, 'sector_anchor': sector_anchor,
               'observed_signal': enter, 'common_group': group,
               'entry_allocation': allocation, 'current_group_allocation': allocation_now,
               'confirmation': confirmation, 'initial_fraction': float(p['initial_fraction']),
               'held_sessions': held, 'exit_signal': exit_signal,
               'promoted': promoted, 'exiting': exiting, 'target_weight': float(target)},
        next_watch='next completed daily bar')
    values = StateRecord((('anchor', anchor), ('sector_anchor', sector_anchor),
                          ('allocation', allocation), ('promoted', promoted), ('exiting', exiting)))
    return AccountStepResult(decision, cycle_values=values if active is not None or target else None)
