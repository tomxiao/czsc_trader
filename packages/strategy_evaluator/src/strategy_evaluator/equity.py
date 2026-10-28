"""Independent equity account audit over serialized facts (no runtime imports)."""
from dataclasses import dataclass
from datetime import datetime
import math
from statistics import median


@dataclass(frozen=True, slots=True)
class EquityAuditResult:
    total_return: float
    annualized_return: float
    daily_max_drawdown: float
    bar_max_drawdown: float
    sessions: int
    observations: int
    closed_cycles: int
    fees: float
    rolling_60_closed_cycle_counts: tuple[int, ...]
    rolling_60_closed_cycle_median: float | None


def _time(value):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("audit requires aware timestamps")
    return stamp


def _same(actual, expected, label):
    if not math.isfinite(float(actual)) or not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7):
        raise ValueError(f"equity audit mismatch: {label}")


def _drawdown(values, initial):
    peak, result = initial, 0.
    for value in values:
        peak = max(peak, value)
        result = max(result, 1 - value / peak)
    return result


def audit_equity_account(*, initial_cash, specification, bars, decisions, orders,
                         fills, actions, account_points, trades, action_facts, constraints, fee_rate):
    """Reconstruct balances and closed cycles, then calculate daily/bar diagnostics.

    Bar drawdown is sampled at bar closes; it is not tick-level or intrabar risk.
    Observation count never implies independent statistical samples.
    """
    if not math.isfinite(initial_cash) or initial_cash <= 0 or not account_points:
        raise ValueError("audit requires initial cash and account observations")
    bar_by_end = {_time(row["Date"]): row for row in bars}
    constraint_by_start = {_time(row["Date"]): row for row in constraints}
    source_actions = {row["EventId"]: row for row in action_facts if row["Kind"] != "NONE"}
    entitlements = {}
    order_by_id = {row["order_id"]: row for row in orders}
    decision_by_id = {row["decision_id"]: row for row in decisions}
    if len(order_by_id) != len(orders) or len(decision_by_id) != len(decisions):
        raise ValueError("duplicate decision or order identity")
    if len({row["fill_id"] for row in fills}) != len(fills):
        raise ValueError("duplicate fill identity")
    if {row["order_id"] for row in fills} != {row["order_id"] for row in orders if row["status"] == "FILLED"}:
        raise ValueError("filled orders and fills differ")
    if len(decisions) != len(account_points):
        raise ValueError("account observations and decisions differ")
    for decision in decisions:
        if not (_time(decision["observed_through"]) <= _time(decision["decision_at"])
                <= _time(decision["execution_start"]) < _time(decision["execution_end"])):
            raise ValueError("audit found a noncausal decision")
    first_decision = min(_time(row["decision_at"]) for row in decisions)
    last_end = max(_time(row["time"]) for row in account_points)
    expected_actions = {identity for identity, row in source_actions.items()
                        if first_decision <= _time(row["Date"]) < last_end}
    recorded_actions = [row["event_id"] for row in actions if row["kind"] in {"SPLIT", "CASH_DIVIDEND"}]
    if len(recorded_actions) != len(set(recorded_actions)) or set(recorded_actions) != expected_actions:
        raise ValueError("corporate action journal does not cover source events")
    events = []
    for position, row in enumerate(actions):
        events.append((row["account_revision"], _time(row["time"]), 0 if row["kind"] in {"SPLIT", "CASH_DIVIDEND"} else 1, position, "action", row))
    for position, row in enumerate(fills):
        order = order_by_id.get(row["order_id"])
        if order is None or order["status"] != "FILLED" or order["decision_id"] not in decision_by_id:
            raise ValueError("fill lacks its executed order and decision")
        if row["side"] != order["side"] or row["quantity"] != order["quantity"]:
            raise ValueError("fill differs from order")
        decision = decision_by_id[order["decision_id"]]
        if order["side"] != decision["side"]:
            raise ValueError("order side differs from decision")
        start, end = _time(row["interval_start"]), _time(row["interval_end"])
        if (start, end) != (_time(order["valid_start"]), _time(order["valid_end"])):
            raise ValueError("fill lies outside its order lifetime")
        if (start, end) != (_time(decision["execution_start"]), _time(decision["execution_end"])):
            raise ValueError("order lifetime differs from decision")
        bar = bar_by_end.get(end)
        if bar is None or _time(bar["BarStart"]) != start:
            raise ValueError("fill lacks its execution bar")
        price = row["price"]
        slip = specification["slippage_bp"] / 10000
        if row["side"] == "BUY":
            limit = order["limit_price"]
            crossed = bar["Low"] <= limit if specification["inclusive_touch"] else bar["Low"] < limit
            if bar["Open"] <= limit:
                expected = bar["Open"] * (1 + slip)
            elif crossed:
                expected = limit * (1 + slip)
            else:
                raise ValueError("buy did not touch its limit")
            if price > limit + 1e-10:
                raise ValueError("buy exceeded its limit")
        elif row["side"] == "SELL":
            expected = bar["Open"] * (1 - slip)
        else:
            raise ValueError("unsupported fill side")
        _same(price, expected, "fill price")
        if row["quantity"] <= 0 or row["fees"] < 0:
            raise ValueError("invalid fill quantity or fees")
        if row["quantity"] > bar["Volume"]:
            raise ValueError("fill exceeds observed bar volume")
        _same(row["fees"], row["quantity"] * price * fee_rate, "fill fees")
        constraint = constraint_by_start.get(start)
        if constraint is None or _time(constraint["AvailableDate"]) > start or not constraint["Tradable"]:
            raise ValueError("fill lacks a tradable dated constraint")
        if row["quantity"] % constraint["QuantityStep"]:
            raise ValueError("fill violates dated quantity step")
        if row["side"] == "SELL" and specification["account"]["cash_availability"] == "SETTLED_ONLY":
            entitlements[row["fill_id"]] = (_time(constraint["SettlementAt"]), price * row["quantity"] - row["fees"], "SALE_SETTLEMENT")
        # BAR_RANGE fills have an interval, not an invented exact trade time.
        events.append((row["account_revision"], start, 2, position, "fill", row))
    for position, row in enumerate(account_points):
        if row["account_revision"] != position:
            raise ValueError("account revisions must be consecutive")
        events.append((row["account_revision"], _time(row["time"]), 3, position, "point", row))
    if any(item[0] not in range(len(account_points)) for item in events):
        raise ValueError("ledger entry outside account revisions")
    events.sort(key=lambda item: item[:4])
    cash, quantity, receivable, fees = float(initial_cash), 0, 0., 0.
    cycle, cost, income, closed = None, 0., 0., []
    point_values, daily, prior_point = [], {}, None
    for _, stamp, _, _, kind, row in events:
        if kind == "action":
            if row["quantity_before"] != quantity:
                raise ValueError("action entitlement differs from holdings")
            action = row["kind"]
            if action == "SPLIT":
                fact = source_actions.get(row["event_id"])
                if fact is None or fact["Kind"] != action or _time(fact["Date"]) != stamp:
                    raise ValueError("split lacks source evidence")
                _same(row["quantity_after"], quantity * fact["Ratio"], "split entitlement")
                _same(row["cash_delta"], 0., "split cash")
                _same(row["receivable_delta"], 0., "split receivable")
                if row["quantity_after"] < 0 or row["amount"] != 0:
                    raise ValueError("invalid split ledger entry")
                quantity = row["quantity_after"]
            elif action == "CASH_DIVIDEND":
                fact = source_actions.get(row["event_id"])
                if fact is None or fact["Kind"] != action or _time(fact["Date"]) != stamp:
                    raise ValueError("dividend lacks source evidence")
                _same(row["amount"], quantity * fact["CashPerShare"], "dividend entitlement")
                _same(row["cash_delta"], 0., "dividend cash")
                _same(row["receivable_delta"], row["amount"], "dividend receivable")
                entitlements[row["event_id"]] = (_time(fact["PayAt"]), row["amount"], "DIVIDEND_PAYMENT")
                if cycle is not None:
                    income += row["amount"]
            elif action in {"DIVIDEND_PAYMENT", "SALE_SETTLEMENT"}:
                expected = entitlements.pop(row["event_id"], None)
                if expected is None or expected[0] != stamp or expected[2] != action:
                    raise ValueError("payment lacks its entitlement or settlement date")
                _same(row["cash_delta"], expected[1], "payment cash")
                _same(row["receivable_delta"], -expected[1], "payment receivable")
            else:
                raise ValueError("unknown account event")
            cash += row["cash_delta"]
            receivable += row["receivable_delta"]
        elif kind == "fill":
            gross = row["price"] * row["quantity"]
            fees += row["fees"]
            if row["side"] == "BUY":
                if cycle is None:
                    cycle, cost, income = row["cycle_id"], 0., 0.
                cash -= gross + row["fees"]
                cost += gross + row["fees"]
                quantity += row["quantity"]
            else:
                quantity -= row["quantity"]
                proceeds = gross - row["fees"]
                income += proceeds
                if specification["account"]["cash_availability"] == "IMMEDIATE_RESEARCH":
                    cash += proceeds
                else:
                    receivable += proceeds
                if quantity == 0:
                    closed.append((cycle, cost, income))
                    cycle = None
        else:
            if prior_point is not None and stamp <= prior_point:
                raise ValueError("account observations must be strictly ordered")
            prior_point = stamp
            if row["decision_id"] not in decision_by_id:
                raise ValueError("account point lacks a decision")
            decision = decision_by_id[row["decision_id"]]
            if _time(decision["execution_end"]) != stamp or decision["portfolio_revision"] != row["account_revision"]:
                raise ValueError("account point differs from its decision interval or revision")
            bar = bar_by_end.get(stamp)
            if bar is None:
                raise ValueError("account point lacks its market bar")
            _same(row["close"], bar["Close"], "mark price")
            for field, expected in (("cash", cash), ("quantity", quantity), ("receivable", receivable),
                                    ("equity", cash + receivable + quantity * bar["Close"])):
                _same(row[field], expected, field)
            point_values.append(row["equity"])
            daily[row["session"]] = row["equity"]
        if cash < -1e-7 or quantity < 0 or receivable < -1e-7:
            raise ValueError("audit found an overdrawn or short account")
    if len(closed) != len(trades):
        raise ValueError("closed cycle count differs")
    for (identity, expected_cost, expected_income), row in zip(closed, trades, strict=True):
        if identity != row["cycle_id"]:
            raise ValueError("closed cycle identity differs")
        _same(row["cost"], expected_cost, "cycle cost")
        _same(row["income"], expected_income, "cycle income")
        _same(row["net_pnl"], expected_income - expected_cost, "cycle pnl")
    if any(stamp <= last_end for stamp, _, _ in entitlements.values()):
        raise ValueError("due payment missing from account journal")
    session_by_time = {_time(point["time"]): point["session"] for point in account_points}
    closed_by_session = {session: 0 for session in daily}
    for row in trades:
        stamp = _time(row["exit_at"])
        if stamp not in session_by_time:
            raise ValueError("closed cycle exit outside account observations")
        closed_by_session[session_by_time[stamp]] += 1
    counts = list(closed_by_session.values())
    rolling = tuple(sum(counts[i - 59:i + 1]) for i in range(59, len(counts)))
    return EquityAuditResult(point_values[-1] / initial_cash - 1,
                             (point_values[-1] / initial_cash) ** (252 / len(daily)) - 1,
                             _drawdown(daily.values(), initial_cash), _drawdown(point_values, initial_cash),
                             len(daily), len(point_values), len(closed), fees,
                             rolling, float(median(rolling)) if rolling else None)
