from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord


def step(ctx, state):
    bars = ctx.history.to_frame(tail=63)
    c = bars['Close']
    price, prev, before = map(float, c.iloc[-3:][::-1])
    down = price < prev
    two_down = down and prev < before
    signals = {'all': True, 'down': down, 'up': price > prev,
               'two_down': two_down, 'not_two_down': not two_down}
    enter = signals[ctx.parameters['entry']]
    active = ctx.position.active
    if active is None:
        anchor, floor = price, float(bars['Low'].iloc[-1])
        target = float(enter)
        reason = 'entry' if enter else 'no opportunity'
    else:
        anchor = state.cycle.values['anchor']
        floor = state.cycle.values['floor']
        held = sum(t >= active.entry_interval.start for t in bars['Date'])
        mode = ctx.parameters['exit']
        done = (held >= 6 or (held >= 3 and price <= anchor)) if mode == 'signal_line' else held >= int(mode)
        target = float(not done)
        reason = 'complete' if done else 'hold'
    return AccountStepResult(
        AccountDecision.from_facts(target, reason,
            facts={'anchor': anchor, 'floor': floor, 'observed_signal': enter},
            next_watch='next complete daily bar', capital_mode='full_available_cash'),
        cycle_values=StateRecord((('anchor', anchor), ('floor', floor))) if active is not None or target else None)
