"""Convert the shared V4 single-step result to a durable PTE decision proposal."""
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
import json

from strategy_runtime import AccountDecisionEngine, AccountStrategyState, EquityPortfolio
from strategy_runtime.account_strategy import PositionFeedback
from strategy_runtime.equity_replay import CycleState
from strategy_runtime.replay_contracts import AccountSnapshot
from .contracts import AdviceDecision, OrderSpec, PlanLegSpec
from .equity_account_state import (load_document, validate_document, position_from_dict,
    budget_from_dict, budget_to_dict, recognized_events)


def _cached(payload, actual, available, portfolio_revision, state_revision):
    value = {key.name: payload[key.name] for key in fields(AdviceDecision) if key.name in payload}
    for name in ("signal_date", "valid_session", "data_cutoff"):
        value[name] = date.fromisoformat(value[name])
    value["orders"] = tuple(OrderSpec(**order) for order in value["orders"])
    value["order"] = None if value["order"] is None else OrderSpec(**value["order"])
    value["plan_legs"] = tuple(PlanLegSpec(**{**leg, "submit_after": datetime.fromisoformat(leg["submit_after"]),
        "submit_before": datetime.fromisoformat(leg["submit_before"]), "order": OrderSpec(**leg["order"])})
        for leg in value["plan_legs"])
    value.update(actual_quantity=actual, delta_quantity=value["target_quantity"]-actual,
                 available_cash=available, portfolio_revision=portfolio_revision, state_revision=state_revision)
    return AdviceDecision(**value)


def account_decision(store, prepared, account, actual_quantity, available_cash, trading_date,
                     portfolio_revision, state_revision):
    candidate = prepared.candidate
    definition, rules = candidate.definition, store.equity_account_rules(account["account_id"])
    if prepared.v4_replay is None or prepared.buy_sellable_at is None:
        raise ValueError("native V4 decision requires its prepared clock and trading constraints")
    document = load_document(account, definition)
    state = validate_document(document)
    definition.state_schema.validate_record(state.account, scope="account")
    if state.cycle is not None:
        definition.state_schema.validate_record(state.cycle.values, scope="cycle")
    interval = {key: getattr(prepared.interval, key).isoformat() for key in ("start", "end")}
    if document["last_interval"] == interval:
        if document["last_inputs"] != prepared.data_identity:
            raise ValueError("adopted V4 interval cannot change its prepared input identity")
        return _cached(json.loads(account["last_decision_payload"]), actual_quantity, available_cash,
                       portfolio_revision, state_revision)
    if document["last_interval"] is not None and datetime.fromisoformat(document["last_interval"]["end"]) > prepared.interval.start:
        raise ValueError("V4 decisions cannot overlap or move backwards")
    active = position_from_dict(document["active"])
    feedback = PositionFeedback(active, position_from_dict(document["latest_closed"]))
    if active is not None and active.quantity != actual_quantity:
        raise ValueError("V4 position feedback differs from confirmed holdings")
    locked = sum(lock["quantity"] for lock in document["buy_locks"]
                 if datetime.fromisoformat(lock["at"]) > prepared.interval.start)
    if locked > actual_quantity:
        raise ValueError("V4 locked holdings exceed confirmed quantity")
    portfolio = EquityPortfolio(available_cash, actual_quantity, float(account["receivable"]), state.revision,
        cycle_entry=None if active is None else active.entry_interval.start,
        cycle_cost=0. if active is None else active.buy_cost, feedback_source="CONFIRMED_EXECUTION",
        reference_price_scale=prepared.reference_price_scale)
    snapshot = AccountSnapshot(candidate.instrument, rules.execution.account.currency, prepared.interval.start,
        state.revision, Decimal(account["cash"])+Decimal(account["frozen_cash"]), Decimal(str(available_cash)),
        Decimal(account["receivable"]), actual_quantity, actual_quantity-locked)
    live_constraint = None
    if prepared.live_interval:
        live_constraint = dict(prepared.v4_constraint)
        for key in ('Date', 'AvailableDate'):
            live_constraint[key] = datetime.fromisoformat(live_constraint[key])
    engine = AccountDecisionEngine(candidate, prepared.v4_replay, live_constraint=live_constraint)
    events, cursor = recognized_events(store, account["account_id"], state.event_cursor, prepared.interval.start)
    owner = account["account_id"] + ":" + account["release_hash"]
    result = engine.plan(prepared.interval, portfolio, snapshot, state, feedback, owner=owner,
        fee_rate=prepared.fee_rate, budget=budget_from_dict(document["budget"]), events=events,
        next_event_cursor=cursor)
    proposal, plan = result.proposal, result.plan
    if plan.legs:
        if tuple(leg.sequence for leg in plan.legs) != tuple(range(len(plan.legs))):
            raise ValueError("V4 leg sequences must be contiguous")
        for leg in plan.legs:
            if not prepared.interval.start <= leg.submit_after < leg.submit_before <= prepared.interval.end:
                raise ValueError("V4 leg is outside its declared execution interval")
            if leg.dependency_sequence is not None and leg.dependency_required_status != "FILLED_ALL":
                raise ValueError("V4 dependent legs require confirmed complete execution")
        # Reserve existing inventory and cash. Future entry fills do not finance
        # an exit at adoption; this preserves core-position rotation semantics.
        if sum(leg.order.quantity for leg in plan.legs if leg.order.side.value == "SELL") > snapshot.sellable_quantity:
            raise ValueError("V4 plan sell legs exceed confirmed sellable holdings")
    if plan.orders and len({order.side for order in plan.orders}) > 1:
        raise ValueError("V4 mixed-side orders require supported dependency execution")
    prior_budget = budget_from_dict(document["budget"])
    if plan.capital_mode == "signal_cash_fraction":
        if plan.cycle_before != prior_budget:
            raise ValueError("V4 cycle budget differs from confirmed state")
        if plan.cycle_after is None and plan.target_quantity:
            raise ValueError("V4 cycle allocation requires a declared budget")
        if prior_budget is not None and plan.cycle_after is not None and any(
                getattr(prior_budget, key) != getattr(plan.cycle_after, key)
                for key in ("cycle_id", "target_quantity", "allocation_fraction", "cash_budget", "buy_cost_including_fees")):
            raise ValueError("V4 active cycle budget cannot be rebuilt")
        if plan.cycle_after is not None:
            if plan.target_quantity > plan.cycle_after.target_quantity:
                raise ValueError("V4 plan exceeds its declared cycle target")
            if prior_budget is None and plan.cycle_after.cash_budget > Decimal(str(available_cash))*plan.cycle_after.allocation_fraction:
                raise ValueError("V4 cycle budget exceeds declared available cash allocation")
    orders = tuple(OrderSpec(order.side.value, order.quantity, order.order_type.value,
        float(order.limit_price) if order.limit_price is not None else float(plan.evidence["reference_price"]), "DAY")
        for order in plan.orders)
    legs = tuple(PlanLegSpec(leg.sequence, "V4", leg.checkpoint, leg.submit_after, leg.submit_before,
        leg.dependency_sequence, leg.dependency_required_status,
        OrderSpec(leg.order.side.value, leg.order.quantity, leg.order.order_type.value,
            float(leg.order.limit_price) if leg.order.limit_price is not None else float(plan.evidence["reference_price"]), "DAY"))
        for leg in plan.legs)
    all_orders = orders or tuple(leg.order for leg in legs)
    if any(order.side == "BUY" and order.order_type != "LIMIT" for order in all_orders):
        raise ValueError("PTE V4 cash reservation requires explicit limit buy orders")
    sellable = snapshot.sellable_quantity
    for order in all_orders:
        if order.side == "BUY" and prepared.buy_sellable_at <= prepared.interval.start:
            sellable += order.quantity
        if order.side == "SELL":
            sellable -= order.quantity
            if sellable < 0:
                raise ValueError("V4 order exceeds currently sellable holdings")
    for order in all_orders:
        if order.quantity % rules.execution.quantity_step:
            # Full liquidation of integer split remainders is allowed only when
            # the dated constraint explicitly permits it (the shared planner checks it).
            if (order.side != "SELL" or order.quantity != actual_quantity
                    or prepared.v4_constraint["SellRemainderPolicy"] != "FULL_LIQUIDATION"):
                raise ValueError("V4 order differs from declared trading lot")
        if order.order_type == "LIMIT":
            price = Decimal(str(order.limit_price))
            if price % Decimal(str(rules.execution.price_tick)):
                raise ValueError("V4 limit price differs from declared tick")
            limits = prepared.v4_constraint
            if limits["PriceLimitPolicy"] == "DATED_LIMITS" and not limits["PriceLimitLower"] <= float(price) <= limits["PriceLimitUpper"]:
                raise ValueError("V4 limit order exceeds dated price limits")
    cycle = None if state.cycle is None else CycleState(state.cycle.cycle_id, state.cycle.entry_at, proposal.cycle_values)
    next_state = AccountStrategyState(state.revision + 1, proposal.account, cycle,
                                     engine.state_binding(owner, prepared.fee_rate), result.next_event_cursor)
    after = {**document, "state": next_state.to_dict(),
        "pending_cycle": None if proposal.cycle_values is None else proposal.cycle_values.to_dict(),
        "budget": budget_to_dict(plan.cycle_after if plan.cycle_after is not None else prior_budget), "last_interval": interval, "last_inputs": prepared.data_identity,
        "buy_locks": [lock for lock in document["buy_locks"] if datetime.fromisoformat(lock["at"]) > prepared.interval.start]}
    validate_document(after)
    reference = float(plan.evidence["reference_price"])
    exact_estimate = sum((Decimal(str(order.limit_price))*order.quantity*(1+Decimal(str(prepared.fee_rate)))
                          for order in all_orders if order.side == "BUY"), Decimal(0))
    estimate = float(exact_estimate)
    budget = budget_from_dict(after["budget"])
    if plan.capital_mode == "signal_cash_fraction" and budget is not None and exact_estimate > budget.cash_budget-budget.buy_cost_including_fees:
        raise ValueError("V4 orders exceed remaining cycle budget")
    sides = {order.side for order in all_orders}
    action = ("ROTATE" if len(sides) > 1 else "BUY" if "BUY" in sides else "SELL") if all_orders else ("HOLD" if actual_quantity else "WAIT")
    return AdviceDecision("advice.equity.v4", plan.plan_identity, candidate.instrument.symbol,
        prepared.available_through, trading_date, actual_quantity, plan.target_quantity, plan.target_quantity,
        plan.target_quantity-actual_quantity, action,
        {"strategy_id": account["strategy_id"], "version": account["strategy_version"], "release_hash": account["release_hash"]},
        reference, reference, prepared.available_through, orders[0] if orders else None,
        plan.plan_identity, plan.plan_identity, portfolio_revision, state_revision,
        orders=orders, available_cash=available_cash, fee_rate=prepared.fee_rate,
        estimated_order_cost=estimate, unallocated_cash=available_cash-estimate,
        capital_mode=plan.capital_mode, runtime_sha256=candidate.implementation_hash, plan_mode="V4" if legs else "NONE", plan_legs=legs,
        strategy_output={"explanation": proposal.decision.explanation.to_dict(),
                         "market_rule": {"version": prepared.v4_constraint["MarketRuleVersion"],
                                         "sha256": prepared.v4_constraint["MarketRuleHash"]}},
        equity_execution_interval=interval, equity_observed_through=plan.point.observed_through.isoformat(),
        v4_state_transition={"before": account.get("account_v4_json"), "after": after,
                             "buy_sellable_at": prepared.buy_sellable_at.isoformat(),
                             "sell_remainder_policy": prepared.v4_constraint["SellRemainderPolicy"]})
