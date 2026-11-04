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
        'industry_down': industry_down,
        'resist': industry_down and residual_today >= 0,
        'yield': industry_down and residual_today < 0,
        'persistent_resist': industry_down and s[-2] < 0 and residual_today >= 0,
        'wait_rebound': s[-2] < 0 and s[-1] > 0 and residual_today >= 0,
    }
    enter = bool(signals[p['entry']])
    active = ctx.position.active
    if active is None:
        anchor = price
        target, reason = float(enter), 'entry' if enter else 'no opportunity'
    else:
        anchor = state.cycle.values.get('anchor')
        held = sum(t >= active.entry_interval.start for t in raw.Date)
        done = held >= int(p['exit']) if p['exit'] in ('1', '3', '6') else (held >= 6 or (held >= 3 and price <= anchor))
        target, reason = float(not done), 'complete' if done else 'hold'
    return AccountStepResult(AccountDecision.from_facts(target, reason,
        facts={'anchor': anchor, 'observed_signal': enter, 'beta': beta, 'common2': common,
               'relative2': relative, 'relative_today': residual_today, 'price_basis': 'RAW' if p['entry'] == 'raw_control' else 'HFQ'},
        next_watch='next completed daily bar', capital_mode='full_available_cash'),
        cycle_values=StateRecord((('anchor', anchor),)) if active is not None or target else None)
