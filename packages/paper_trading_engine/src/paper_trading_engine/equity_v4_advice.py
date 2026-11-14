"""Convert the shared V4 single-step result to a durable PTE decision proposal."""
from dataclasses import asdict, fields
from datetime import date, datetime
from decimal import Decimal
import json

from strategy_runtime import AccountDecisionEngine, AccountStrategyState, EquityPortfolio
from strategy_runtime.account_strategy import PositionFeedback
from .contracts import AdviceDecision, OrderSpec, PlanLegSpec
from execution_channels.daily_execution import DAILY_TARGET_TRIGGER, INTERVAL_TARGET_TRIGGER, TARGET_TRIGGERS
from execution_channels.futu.equity_account_state import (load_document, validate_document, position_from_dict,
    budget_from_dict, recognized_events)
from .ec_boundary import (initial_account_record, strategy_position, strategy_events, execution_plan, execution_admission, strategy_account_snapshot)


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
                     portfolio_revision, state_revision, *, through_cursor=None):
    candidate = prepared.candidate
    definition, rules = candidate.definition, store.equity_account_rules(account["account_id"])
    if prepared.v4_replay is None or prepared.buy_sellable_at is None:
        raise ValueError("native V4 decision requires its prepared clock and trading constraints")
    document = load_document(account, initial_account_record(definition))
    validate_document(document)
    state = AccountStrategyState.from_dict(document["state"])
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
    active = strategy_position(position_from_dict(document["active"]))
    feedback = PositionFeedback(active, strategy_position(position_from_dict(document["latest_closed"])))
    portfolio = EquityPortfolio(available_cash, actual_quantity, float(account["receivable"]), state.revision,
        cycle_entry=None if active is None else active.entry_interval.start,
        cycle_cost=0. if active is None else active.buy_cost, feedback_source="CONFIRMED_EXECUTION")
    trigger = definition.execution_policy.settings.get('execution_trigger')
    point = prepared.as_of if trigger == INTERVAL_TARGET_TRIGGER else prepared.interval.start
    snapshot = strategy_account_snapshot(account, document, rules, point,
        Decimal(str(available_cash)), candidate.instrument)
    if snapshot.quantity != actual_quantity:
        raise ValueError("strategy request quantity differs from confirmed channel account")
    engine = AccountDecisionEngine(candidate, prepared.v4_replay, step_data_load=prepared.step_data_load,
                                   data_cutoff=prepared.step_data_cutoff or prepared.as_of)
    events, cursor = recognized_events(store, account["account_id"], state.event_cursor,
                                       point, through_cursor=through_cursor)
    owner = account["account_id"] + ":" + account["release_hash"]
    result = engine.propose(prepared.interval, portfolio, snapshot, state, feedback, owner=owner,
        fee_rate=prepared.fee_rate, events=strategy_events(events), next_event_cursor=cursor,
        decision_at=prepared.as_of if trigger == INTERVAL_TARGET_TRIGGER else None)
    data_reads = [item.to_dict() for item in result.data_reads]
    if prepared.expected_step_reads is not None and tuple(data_reads) != prepared.expected_step_reads:
        raise ValueError('rerun strategy reads differ from adopted evidence')
    proposal = result.proposal
    previous_execution = None
    if trigger in TARGET_TRIGGERS:
        if prepared.execution_interval is not None:
            previous_execution = store.previous_execution(account['account_id'], interval=prepared.execution_interval)
        elif trigger == DAILY_TARGET_TRIGGER:
            previous_execution = store.previous_daily_execution(account['account_id'], previous_session=prepared.available_through)
        else:
            raise ValueError('interval execution requires the calendar-resolved current and previous windows')
    plan = execution_plan(result, snapshot, definition.execution_spec, owner=owner,
        reference=float(prepared.execution_reference.price), execution_policy=definition.execution_policy,
        cycle_budget=budget_from_dict(document["budget"]), locked_quantity=document["locked_quantity"],
        implementation=candidate.implementation_hash, fee_rate=prepared.fee_rate,
        sell_remainder_policy=prepared.v4_constraint["SellRemainderPolicy"], previous_daily_execution=previous_execution,
        execution_interval=prepared.execution_interval)
    effects = execution_admission(plan, snapshot, document, proposal,
        state_binding=engine.state_binding(owner, prepared.fee_rate),
        next_event_cursor=result.next_event_cursor, prepared=prepared, rules=rules)
    orders = tuple(OrderSpec(**asdict(order)) for order in effects.orders)
    legs = tuple(PlanLegSpec(**{**asdict(leg), "order": OrderSpec(**asdict(leg.order))})
                 for leg in effects.legs)
    reference, estimate, action, after = effects.reference, effects.estimated_order_cost, effects.action, effects.after
    execution_output = {"target": float(proposal.decision.target), "planning_result": plan.planning_result.to_dict()}
    if trigger in TARGET_TRIGGERS:
        execution_output["signal_status"] = plan.evidence.get("signal_status", "EVALUATED")
        execution_output["execution_trigger"] = plan.evidence.get("execution_trigger")
    if trigger == INTERVAL_TARGET_TRIGGER:
        execution_output["execution_interval"] = dict(plan.evidence["execution_interval"])
        execution_output["decision_at"] = result.point.decision_at.isoformat()
    if "entry_cash" in plan.evidence:
        execution_output["entry_cash"] = plan.evidence["entry_cash"]
    return AdviceDecision("advice.equity.v4", plan.plan_identity, candidate.instrument.symbol,
        prepared.available_through, trading_date, actual_quantity, plan.target_quantity, plan.target_quantity,
        plan.target_quantity-actual_quantity, action,
        {"strategy_id": account["strategy_id"], "version": account["strategy_version"], "release_hash": account["release_hash"]},
        float(prepared.history.Close.iloc[-1]), reference, prepared.available_through, orders[0] if orders else None,
        plan.plan_identity, plan.plan_identity, portfolio_revision, state_revision,
        orders=orders, available_cash=available_cash, fee_rate=prepared.fee_rate,
        estimated_order_cost=estimate, unallocated_cash=effects.unallocated_cash,
        capital_mode=plan.capital_mode, runtime_sha256=candidate.implementation_hash, plan_mode="V4" if legs else "NONE", plan_legs=legs,
        strategy_output={"explanation": proposal.decision.explanation.to_dict(),
             "data_reads": data_reads,
            "execution_plan": execution_output,
                         "market_rule": {"version": prepared.v4_constraint["MarketRuleVersion"],
                                         "sha256": prepared.v4_constraint["MarketRuleHash"]}},
        equity_execution_interval=interval, equity_observed_through=plan.point.observed_through.isoformat(),
        v4_state_transition={"before": account.get("account_v4_json"), "after": after,
                             "buy_sellable_at": prepared.buy_sellable_at.isoformat(),
                             "sell_remainder_policy": prepared.v4_constraint["SellRemainderPolicy"]})
