"""Independent equity account audit over serialized facts (no runtime imports)."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_FLOOR
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


def _bar_status(bar):
    status = bar.get("BarStatus", "OBSERVED")
    if status not in {"OBSERVED", "MISSING", "ZERO_VOLUME"}:
        raise ValueError("unknown equity bar status")
    return status


def _blocked_reason(bar):
    status = _bar_status(bar)
    if status == "MISSING":
        return "MISSING_BAR"
    if status == "ZERO_VOLUME":
        return "ZERO_VOLUME"
    if bar.get("ExecutionBlocked", False):
        return "KNOWN_INTERRUPTION"
    return None


def _formal_decision(row, *, cash, quantity, specification, observed_bar, action_facts, fee_rate):
    """Independently reconstruct the formal full-position plan after effective events."""
    target = row["target"]
    if type(target) not in (int, float) or target not in (0, 1):
        raise ValueError("formal decision target must be binary long-only")
    start, observed = _time(row["execution_start"]), _time(row["observed_through"])
    if _time(row["decision_at"]) != start:
        raise ValueError("formal decision must use the execution-start account snapshot")
    if observed_bar is None or _time(observed_bar["Date"]) != observed:
        raise ValueError("formal decision observed history differs from available bars")
    reference = float(observed_bar["Close"])
    for fact in action_facts:
        if fact["Kind"] == "SPLIT" and observed <= _time(fact["Date"]) <= start:
            reference /= float(fact["Ratio"])
    _same(row["reference_price"], reference, "decision reference price")
    if row.get("signal_status") == "SUPPRESSED_UNOBSERVED_BAR":
        if (type(row["quantity"]) is not int
                or (row["side"], row["quantity"], row["limit_price"], target) != ("WAIT", 0, None, float(quantity > 0))):
            raise ValueError("suppressed signal must preserve holdings without an order")
        return
    side, planned, limit = "HOLD", 0, None
    if target == 1 and quantity == 0:
        tick = Decimal(str(specification["price_tick"]))
        limit = float((Decimal(str(reference)) * (1 + Decimal(str(specification["buy_premium"])))
                      / tick).to_integral_value(rounding=ROUND_FLOOR) * tick)
        if limit <= 0:
            raise ValueError("formal decision limit must be positive")
        step = specification["quantity_step"]
        planned = int(Decimal(str(cash)) / (Decimal(str(limit)) * (1 + Decimal(str(fee_rate))) * step)) * step
        side = "BUY" if planned else "WAIT"
    elif target == 0 and quantity:
        side, planned = "SELL", quantity
    if type(row["quantity"]) is not int or row["quantity"] != planned or row["side"] != side:
        raise ValueError("formal decision side or quantity differs from account and target")
    if limit is None:
        if row["limit_price"] is not None:
            raise ValueError("formal non-buy decision has an unexpected limit")
    else:
        _same(row["limit_price"], limit, "decision buy limit")


def _formal_order(row, *, cash, specification, bar, constraint, fee_rate):
    """An expired order must be justified by the same dated execution facts."""
    if (constraint is None or _time(constraint["AvailableDate"]) > _time(row["valid_start"])
            or constraint["QuantityStep"] != specification["quantity_step"]
            or constraint["PriceTick"] != specification["price_tick"]):
        raise ValueError("formal order dated execution rules differ")
    quantity, limit = row["quantity"], row["limit_price"]
    price, reason = None, "NOT_TRADABLE"
    blocked = _blocked_reason(bar)
    if blocked is not None:
        reason = blocked
    elif constraint["Tradable"]:
        if bar["Volume"] <= 0 or quantity > bar["Volume"]:
            reason = "INSUFFICIENT_BAR_VOLUME"
        elif row["side"] == "SELL":
            price, reason = bar["Open"] * (1 - specification["slippage_bp"] / 10000), "FILLED"
        else:
            crossed = bar["Low"] <= limit if specification["inclusive_touch"] else bar["Low"] < limit
            raw = bar["Open"] if bar["Open"] <= limit else limit if crossed else None
            if raw is None:
                reason = "LIMIT_NOT_CROSSED"
            else:
                price = raw * (1 + specification["slippage_bp"] / 10000)
                reason = "FILLED"
                if price > limit:
                    price, reason = None, "SLIPPAGE_EXCEEDS_LIMIT"
                elif quantity * price * (1 + fee_rate) > cash + 1e-9:
                    price, reason = None, "INSUFFICIENT_CASH"
    if row["status"] != ("FILLED" if price is not None else "EXPIRED") or row["reason"] != reason:
        raise ValueError("formal order outcome differs from dated execution facts")


def audit_equity_account(*, initial_cash, specification, bars, decisions, orders,
                         fills, actions, account_points, trades, action_facts, constraints, fee_rate,
                         decision_contract=None, account_contract=None, execution_bars=None):
    """Reconstruct balances and closed cycles, then calculate daily/bar diagnostics.

    Bar drawdown is sampled at bar closes; it is not tick-level or intrabar risk.
    Observation count never implies independent statistical samples.
    """
    if account_contract is not None and (type(account_contract) is not int or account_contract != 4):
        raise ValueError('unknown account audit contract')
    if account_contract == 4 or decision_contract == 'FORMAL_V4':
        if account_contract != 4 or decision_contract not in (None, 'FORMAL_V4'):
            raise ValueError('account audit contract marker differs')
        from .equity_v4 import audit_account_v4
        return audit_account_v4(initial_cash=initial_cash, specification=specification, bars=bars,
            decisions=decisions, orders=orders, fills=fills, actions=actions,
            account_points=account_points, trades=trades, action_facts=action_facts,
            constraints=constraints, fee_rate=fee_rate, execution_bars=execution_bars)
    if account_contract is not None:
        raise ValueError('unknown account audit contract')
    if decision_contract not in (None, "FORMAL_V2"):
        raise ValueError("unsupported equity decision audit contract")
    strict = decision_contract == "FORMAL_V2"
    gap_mode = any("BarStatus" in row for row in bars)
    if gap_mode:
        for bar in bars:
            if "BarStatus" not in bar or type(bar.get("ExecutionBlocked")) is not bool:
                raise ValueError("explicit bar status and execution block required for gap facts")
            status = _bar_status(bar)
            fields = ("Open", "High", "Low", "Close", "Volume", "Amount")
            if status == "MISSING":
                if any(bar.get(field) is not None for field in fields):
                    raise ValueError("missing bar must not contain fabricated OHLCV")
            elif any(type(bar.get(field)) not in (int, float) or not math.isfinite(bar[field]) for field in fields):
                raise ValueError("observed bar fields must be finite")
            elif (min(bar[field] for field in fields[:4]) <= 0 or bar["Volume"] < 0 or bar["Amount"] < 0
                  or (status == "ZERO_VOLUME") != (bar["Volume"] == 0)):
                raise ValueError("bar status differs from observed volume or prices")
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
    observed_by_decision = {}
    if strict or gap_mode:
        if len(bar_by_end) != len(bars) or len(constraint_by_start) != len(constraints):
            raise ValueError("formal source intervals must be unique")
        if [_time(row["Date"]) for row in bars] != sorted(bar_by_end):
            raise ValueError("formal source bars must be ordered")
        latency = timedelta(seconds=specification["data_latency_seconds"])
        available_bars = sorted(bars, key=lambda row: max(_time(row["Date"]), _time(row["AvailableDate"]) + latency))
        cursor, latest, latest_valid = 0, None, None
        for decision in sorted(decisions, key=lambda row: _time(row["execution_start"])):
            start = _time(decision["execution_start"])
            while cursor < len(available_bars):
                bar = available_bars[cursor]
                if max(_time(bar["Date"]), _time(bar["AvailableDate"]) + latency) > start:
                    break
                if latest is None or _time(bar["Date"]) > _time(latest["Date"]):
                    latest = bar
                if _bar_status(bar) == "OBSERVED" and (latest_valid is None or _time(bar["Date"]) > _time(latest_valid["Date"])):
                    latest_valid = bar
                cursor += 1
            observed_by_decision[decision["decision_id"]] = latest_valid
            if gap_mode:
                expected_status = ("SUPPRESSED_UNOBSERVED_BAR" if latest is not None and _bar_status(latest) != "OBSERVED"
                                   else "EVALUATED")
                if decision.get("signal_status") != expected_status:
                    raise ValueError("signal suppression differs from completed available bars")
                if latest_valid is None or _time(decision["observed_through"]) != _time(latest_valid["Date"]):
                    raise ValueError("decision history must end at the latest available observed bar")
        orders_by_decision = {}
        for order in orders:
            decision = decision_by_id.get(order["decision_id"])
            if decision is None or order["decision_id"] in orders_by_decision:
                raise ValueError("formal order requires a unique existing decision")
            if (order["side"] not in {"BUY", "SELL"} or type(order["quantity"]) is not int or order["quantity"] <= 0
                    or (order["side"], order["quantity"], order["limit_price"]) !=
                    (decision["side"], decision["quantity"], decision["limit_price"])
                    or (_time(order["valid_start"]), _time(order["valid_end"])) !=
                    (_time(decision["execution_start"]), _time(decision["execution_end"]))):
                raise ValueError("formal order differs from its decision or interval")
            orders_by_decision[order["decision_id"]] = order
        for index, decision in enumerate(decisions):
            point = account_points[index]
            start, end = _time(decision["execution_start"]), _time(decision["execution_end"])
            if (decision["portfolio_revision"] != index or point["decision_id"] != decision["decision_id"]
                    or end not in bar_by_end or _time(bar_by_end[end]["BarStart"]) != start
                    or bool(decision["quantity"]) != (decision["decision_id"] in orders_by_decision)):
                raise ValueError("formal decision coverage or order cardinality differs")
            events.append((index, _time(decision["decision_at"]), 1.5, index, "decision", decision))
            if decision["decision_id"] in orders_by_decision:
                events.append((index, start, 1.75, index, "order", orders_by_decision[decision["decision_id"]]))
    for position, row in enumerate(actions):
        if strict:
            revision, stamp = row["account_revision"], _time(row["time"])
            if type(revision) is not int or not 0 <= revision < len(decisions):
                raise ValueError("formal action revision is invalid")
            lower = _time(account_points[revision - 1]["time"]) if revision else first_decision
            upper = (_time(decisions[revision]["decision_at"]) if row["kind"] in {"SPLIT", "CASH_DIVIDEND"}
                     else _time(account_points[revision]["time"]))
            if not lower <= stamp <= upper:
                raise ValueError("formal action time differs from its account revision")
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
        if _blocked_reason(bar) is not None:
            raise ValueError("fill occurred in an unavailable execution interval")
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
    cycle_entry, cycle_times = None, []
    point_values, daily, prior_point = [], {}, None
    mark_price, mark_time = None, None
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
                if mark_price is not None:
                    mark_price /= fact["Ratio"]
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
        elif kind == "decision":
            if strict or row.get("signal_status") == "SUPPRESSED_UNOBSERVED_BAR":
                _formal_decision(row, cash=cash, quantity=quantity, specification=specification,
                                 observed_bar=observed_by_decision[row["decision_id"]], action_facts=action_facts, fee_rate=fee_rate)
        elif kind == "order":
            _formal_order(row, cash=cash, specification=specification, bar=bar_by_end[_time(row["valid_end"])],
                          constraint=constraint_by_start.get(_time(row["valid_start"])), fee_rate=fee_rate)
        elif kind == "fill":
            if strict and (type(row["quantity"]) is not int or (cycle is not None and row["cycle_id"] != cycle)):
                raise ValueError("formal fill quantity or active cycle differs")
            gross = row["price"] * row["quantity"]
            fees += row["fees"]
            if row["side"] == "BUY":
                if cycle is None:
                    cycle, cost, income = row["cycle_id"], 0., 0.
                    cycle_entry = _time(row["interval_start"])
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
                    cycle_times.append((cycle_entry, _time(row["interval_end"])))
                    cycle = None
        else:
            if strict and type(row["quantity"]) is not int:
                raise ValueError("formal account quantity must be an integer")
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
            stale = _bar_status(bar) != "OBSERVED"
            if not stale:
                mark_price, mark_time = bar["Close"], stamp
            elif mark_price is None:
                observed = observed_by_decision[decision["decision_id"]]
                if observed is None:
                    raise ValueError("missing valid price before first stale valuation")
                mark_price, mark_time = observed["Close"], _time(observed["Date"])
                for fact in action_facts:
                    if fact["Kind"] == "SPLIT" and mark_time <= _time(fact["Date"]) < stamp:
                        mark_price /= fact["Ratio"]
            if gap_mode:
                if (row.get("bar_status") != _bar_status(bar) or row.get("valuation_stale") is not stale
                        or _time(row.get("valuation_price_at")) != mark_time
                        or row.get("execution_blocked") is not bar["ExecutionBlocked"]):
                    raise ValueError("account gap or stale valuation metadata differs from facts")
            _same(row["close"], mark_price, "mark price")
            for field, expected in (("cash", cash), ("quantity", quantity), ("receivable", receivable),
                                    ("equity", cash + receivable + quantity * mark_price)):
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
    if strict:
        for (entry, exit_at), row in zip(cycle_times, trades, strict=True):
            if (_time(row["entry_at"]), _time(row["exit_at"])) != (entry, exit_at) or row["status"] != "CLOSED":
                raise ValueError("formal cycle interval differs from its fills")
            _same(row["net_return"], row["net_pnl"] / row["cost"], "cycle net return")
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
