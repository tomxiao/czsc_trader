"""Research-only benchmark with an independent account identity."""
from strategy_runtime.equity_definition import EquityDecision
from strategy_runtime.equity_replay import StepResult, StateRecord


def step(context, state):
    decision = EquityDecision.from_facts(1, "Buy and hold under the same execution contract",
        facts={"target": 1, "quantity": context.portfolio.quantity}, next_watch="next completed bar")
    return StepResult(decision, StateRecord(), StateRecord())
