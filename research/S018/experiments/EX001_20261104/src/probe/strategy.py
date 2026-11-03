"""Fixed full-target benchmark for the V4 account contract."""
from strategy_runtime.account_strategy import AccountDecision, AccountStepResult
from strategy_runtime.equity_replay import StateRecord

def step(ctx, state):
    return AccountStepResult(AccountDecision.from_facts(1., "buy and hold",
        facts={"target": 1.}, next_watch="next completed decision", capital_mode="full_available_cash"), cycle_values=StateRecord())
