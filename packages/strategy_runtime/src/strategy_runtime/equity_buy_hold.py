"""Deterministic long-only benchmark using the formal equity decision contract."""
from strategy_runtime.equity_definition import EquityDecision


def decide(context):
    return EquityDecision.from_facts(1, "Buy and hold under the same execution contract",
        facts={"target": 1, "quantity": context.portfolio.quantity}, next_watch="next completed bar")
