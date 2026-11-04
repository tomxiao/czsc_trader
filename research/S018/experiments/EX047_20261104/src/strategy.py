import numpy as np
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    raw = ctx.history.to_frame(tail=63)
    mu = ctx.auxiliary_histories['mu_hfq'].to_frame(tail=63)
    sector = ctx.auxiliary_histories['soxx_hfq'].to_frame(tail=63)
    assert mu.Date.tolist() == sector.Date.tolist() == raw.Date.tolist()
    assert mu.AvailableDate.max() <= ctx.point.decision_at
    p = ctx.parameters
    c = raw.Close if p['entry'] == 'raw_control' else mu.Close
    price = float(c.iloc[-1])
    m, s = np.diff(np.log(mu.Close.to_numpy())), np.diff(np.log(sector.Close.to_numpy()))
    beta = float(np.cov(m[-62:-2], s[-62:-2], ddof=1)[0, 1] / np.var(s[-62:-2], ddof=1))
    common = beta * float(s[-2:].sum())
    relative = float(m[-2:].sum()) - common
    two_down = bool(c.iloc[-1] < c.iloc[-2] < c.iloc[-3])
    residual_today = float(m[-1] - beta*s[-1])
    industry_down = bool(s[-1] < 0)
    signals = {
        'all': two_down,
        'common': two_down and common < relative,
        'industry_down': industry_down,
        'resist': industry_down and residual_today >= 0,
        'yield': industry_down and residual_today < 0,
        'persistent_resist': industry_down and s[-2] < 0 and residual_today >= 0,
        'wait_rebound': s[-2] < 0 and s[-1] > 0 and residual_today >= 0,
    }
    enter = bool(signals[p['entry']])
    active = ctx.position.active
    sector_price = float(sector.Close.iloc[-1])
    failure = repair = False
    relative_since_entry = 0.
    if active is None:
        anchor, sector_anchor, entry_beta = price, sector_price, beta
        sector_target = float(sector.Close.iloc[-3:].max())
        target, reason = float(enter), 'entry' if enter else 'no opportunity'
    else:
        anchor = state.cycle.values.get('anchor')
        sector_anchor = state.cycle.values.get('sector_anchor')
        sector_target = state.cycle.values.get('sector_target')
        entry_beta = state.cycle.values.get('entry_beta')
        held = sum(t >= active.entry_interval.start for t in raw.Date)
        relative_since_entry = float(np.log(price/anchor) - entry_beta*np.log(sector_price/sector_anchor))
        failure = relative_since_entry < 0 and p['exit'] in ('failure', 'both')
        repair = sector_price >= sector_target and p['exit'] in ('repair', 'both')
        original = held >= 6 or (held >= 3 and price <= anchor)
        done = original or failure or repair
        target = float(not done)
        reason = 'relative failure' if failure else 'sector repaired' if repair else 'original exit' if original else 'hold'
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={'anchor':anchor, 'observed_signal':enter, 'beta_entry':entry_beta,
            'sector_anchor':sector_anchor, 'sector_target':sector_target, 'relative_since_entry':relative_since_entry,
            'relative_failure':bool(failure), 'sector_repair':bool(repair), 'price_basis':'HFQ'},
        next_watch='next completed daily bar', capital_mode='full_available_cash'),
        cycle_values=StateRecord((('anchor',anchor),('sector_anchor',sector_anchor),
            ('sector_target',sector_target),('entry_beta',entry_beta))) if active is not None or target else None)
