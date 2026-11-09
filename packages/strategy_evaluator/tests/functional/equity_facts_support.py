"""Hand-declared V4 facts for the independent auditor.

No planner, execution engine, supplier, or production sizing function is used.
Each instruction declares its actual outcome and price; this builder only writes
the journal and adds cash/quantity arithmetic. It does not resolve executions.
"""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo


def timestamp(value):
    return value.isoformat()


def bar(start, end=None, *, price=10., close=None, volume=10000.):
    end = end or start + timedelta(minutes=30)
    close = price if close is None else close
    return dict(BarStart=timestamp(start), Date=timestamp(end), AvailableDate=timestamp(end),
                Open=price, High=max(price, close), Low=min(price, close), Close=close,
                Volume=volume, Amount=price * volume)


def order(side, quantity, limit=None, **facts):
    return dict(side=side, quantity=quantity,
                order_type="MARKET" if limit is None else "LIMIT", limit_price=limit, **facts)


def manual_ledger(steps, *, market="US", initial=10000., fee=.001, step=100,
                  origin=None, initial_price=10., settled=False, execution_bars=None):
    market = str(market)
    zone = ZoneInfo("Asia/Shanghai" if market == "CN" else "America/New_York")
    origin = origin or datetime(2026, 10, 8, 9, 30, tzinfo=zone)
    raw = dict(initial_cash=initial, fee_rate=fee, price_basis="HFQ",
               quantity_basis="SIMULATED_INTEGER_UNITS",
               specification={"market": {"rule_version": market + "_EQUITY_V1"},
                              "account": {"currency": "CNY" if market == "CN" else "USD",
                                          "cash_availability": "SETTLED_ONLY" if settled else "IMMEDIATE_RESEARCH"},
                              "frequency": "30m", "quantity_step": step, "price_tick": .01,
                              "buy_premium": .01, "slippage_bp": 0., "inclusive_touch": True,
                              "data_latency_seconds": 0},
               bars=[bar(origin - timedelta(minutes=30), origin, price=initial_price)],
               constraints=[], decisions=[], orders=[], fills=[], account_entries=[],
               account_points=[], trades=[])
    if execution_bars is not None:
        raw["execution_bars"] = deepcopy(execution_bars)
    cash, quantity, cycle, cost, income, entry = Decimal(str(initial)), 0, None, Decimal(0), Decimal(0), None
    for revision, declared in enumerate(steps):
        start = declared.get("start", origin + timedelta(minutes=30 * revision))
        end = declared.get("end", start + timedelta(minutes=30))
        quote = bar(start, end, price=declared.get("price", 10.),
                    close=declared.get("close"), volume=declared.get("volume", 10000.))
        if "high" in declared:
            quote["High"] = declared["high"]
        previous = raw["bars"][-1]
        observed, reference = previous["Date"], previous["Close"]
        raw["bars"].append(quote)
        rule = dict(Date=timestamp(start), AvailableDate=timestamp(start), QuantityStep=step,
                    PriceTick=.01, Tradable=True, BuySellableAt=timestamp(declared.get("unlock", start)),
                    SettlementAt=timestamp(end), SellRemainderPolicy="FULL_LIQUIDATION",
                    PriceLimitPolicy="EXPLICIT_UNBOUNDED", PriceLimitLower=None, PriceLimitUpper=None)
        raw["constraints"].append(rule)
        identifier = f"decision-{revision}"
        facts = declared.get("orders", ())
        instructions = [{key: value[key] for key in ("side", "quantity", "order_type", "limit_price")}
                        for value in facts]
        target_quantity = quantity + sum(o["quantity"] * (1 if o["side"] == "BUY" else -1) for o in instructions)
        point = dict(observed_through=observed, decision_at=timestamp(start),
                     execution_start=timestamp(start), execution_end=timestamp(end),
                     session_id=start.astimezone(zone).date().isoformat(), precision="BAR_INTERVAL")
        evidence = dict(sizing="TARGET_FRACTION" if "desired" in declared else "EXPLICIT_ORDERS",
                        reference_price=reference, target=declared.get("target", float(target_quantity > 0)))
        if "desired" in declared:
            evidence["desired_quantity"] = declared["desired"]
        legs = []
        if declared.get("legs"):
            legs = [dict(sequence=i, order=instruction, checkpoint=facts[i]["checkpoint"],
                         submit_after=timestamp(start), submit_before=timestamp(end),
                         dependency_sequence=facts[i].get("dependency"),
                         dependency_required_status="FILLED_ALL" if facts[i].get("dependency") is not None else None)
                    for i, instruction in enumerate(instructions)]
        plan = dict(plan_identity=identifier, owner="candidate:manual", point=point,
                    expected_revision=revision, target_quantity=target_quantity,
                    orders=[] if legs else instructions, legs=legs,
                    capital_mode=declared.get("mode", "target_equity_fraction"),
                    cycle_before=deepcopy(declared.get("budget_before")),
                    cycle_after=deepcopy(declared.get("budget_after")), evidence=evidence)
        sides = {o["side"] for o in instructions}
        raw["decisions"].append(dict(decision_id=identifier, portfolio_revision=revision,
            **{k: point[k] for k in ("observed_through", "decision_at", "execution_start", "execution_end")},
            signal_status="EVALUATED", plan=plan, target_quantity=target_quantity,
            side=next(iter(sides)) if len(sides) == 1 else "MIXED" if sides else "HOLD",
            quantity=sum(o["quantity"] for o in instructions),
            limit_price=instructions[0]["limit_price"] if len(instructions) == 1 and instructions[0]["order_type"] == "LIMIT" else None,
            reference_price=reference, target=evidence["target"]))
        for sequence, (instruction, fact) in enumerate(zip(instructions, facts, strict=True)):
            identity = f"{identifier}:{sequence}"
            quote_fact = quote if "quote_index" not in fact else raw["execution_bars"][fact["quote_index"]]
            quoted = dict(quote_interval_start=quote_fact["BarStart"], quote_interval_end=quote_fact["Date"],
                          quote_source="EXECUTION_BARS" if "quote_index" in fact else "DECISION_BAR")
            leg = legs[sequence] if legs else {}
            outcome = fact.get("outcome", "FILLED")
            raw["orders"].append(dict(order_id=identity, decision_id=identifier, sequence=sequence,
                **instruction, valid_start=timestamp(start), valid_end=timestamp(end),
                **{k: leg.get(k) for k in ("checkpoint", "dependency_sequence", "dependency_required_status")},
                status=outcome, reason=fact.get("reason", outcome), **quoted))
            if outcome != "FILLED":
                continue
            price = Decimal(str(fact.get("fill_price", declared.get("price", 10.))))
            gross, amount_fee = price * instruction["quantity"], price * instruction["quantity"] * Decimal(str(fee))
            if instruction["side"] == "BUY":
                if cycle is None:
                    cycle, entry, cost, income = identity, timestamp(start), Decimal(0), Decimal(0)
                cash -= gross + amount_fee
                quantity += instruction["quantity"]
                cost += gross + amount_fee
            else:
                quantity -= instruction["quantity"]
                cash += gross - amount_fee
                income += gross - amount_fee
                if settled:
                    raw["account_entries"].append(dict(event_id=identity, time=timestamp(end),
                        kind="SALE_SETTLEMENT", account_revision=revision, quantity_before=quantity,
                        quantity_after=quantity, amount=float(gross-amount_fee),
                        cash_delta=float(gross-amount_fee), receivable_delta=-float(gross-amount_fee)))
            raw["fills"].append(dict(fill_id=identity, order_id=identity, account_revision=revision,
                side=instruction["side"], quantity=instruction["quantity"], price=float(price), fees=float(amount_fee),
                interval_start=timestamp(start), interval_end=timestamp(end),
                executed_at=timestamp(fact.get("executed_at", start)),
                time_precision="MODEL_CHECKPOINT" if legs else "MODEL_BAR_OPEN", cycle_id=cycle, **quoted))
            if quantity == 0:
                raw["trades"].append(dict(cycle_id=cycle, entry_at=entry, exit_at=timestamp(end), status="CLOSED",
                    cost=float(cost), income=float(income), net_pnl=float(income-cost), net_return=float(income/cost-1)))
                cycle = None
        raw["account_points"].append(dict(time=timestamp(end), session=point["session_id"],
            account_revision=revision, decision_id=identifier, cash=float(cash), quantity=quantity,
            receivable=0., close=quote["Close"], equity=float(cash + quantity * Decimal(str(quote["Close"]))),
            bar_status="OBSERVED", valuation_stale=False, valuation_price_at=timestamp(end),
            execution_blocked=False, cycle_id=cycle))
    return raw


def daily_profit_ledger(days=12):
    """20 units bought at 5, marked 4 then 5, sold at 6.1: +22 cash/day."""
    origin = datetime(2026, 10, 1, 14, tzinfo=ZoneInfo("UTC"))
    steps = []
    for day in range(days):
        start = origin + timedelta(days=day)
        steps.extend((
            dict(start=start, price=5., close=4., orders=(order("BUY", 20, 5.1),)),
            dict(start=start + timedelta(minutes=30), price=5., orders=()),
            dict(start=start + timedelta(minutes=60), price=6.1, orders=(order("SELL", 20),), target=0.),
            dict(start=start + timedelta(minutes=90), price=6.1, orders=(), target=0.),
        ))
    return {**manual_ledger(steps, origin=origin, fee=0., step=10, initial_price=5.), "account_contract": 4}
