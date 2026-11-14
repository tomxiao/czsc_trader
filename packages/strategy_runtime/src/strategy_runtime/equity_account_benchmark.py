"""Fixed full-target benchmark for equity account replay."""
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord

def step(ctx, state):
    return AccountStepResult(AccountDecision.from_facts(1., "buy and hold",
        facts={"target": 1.}, next_watch="next completed decision"), cycle_values=StateRecord())
