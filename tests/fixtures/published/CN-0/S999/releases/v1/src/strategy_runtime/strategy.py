from strategy_runtime import AccountDecision, AccountStepResult, StateRecord
def decision(ctx):
    raw = float(ctx.history.last()['Close'])
    observed = [float(view.last()['Close']) for view in ctx.auxiliary_histories.values()]
    assert raw == 20.
    assert not observed or observed == [20., 200.]
    return AccountDecision.from_facts(1, 'hold', facts={'raw': raw, 'observed': str(observed)}, next_watch='next session')
def step(ctx, state):
    return AccountStepResult(decision(ctx), cycle_values=StateRecord())
def batch(ctx):
    return tuple(decision(row) for row in ctx.observations)
