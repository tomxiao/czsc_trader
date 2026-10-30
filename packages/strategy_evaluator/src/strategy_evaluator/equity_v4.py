"""Independent numerical audit of V4 sized, multi-order RAW equity accounts.

Only serialized source and ledger facts are consumed. Runtime planners, fill
resolvers and execution engines are deliberately not dependencies of this audit.
"""

from collections import defaultdict
from bisect import bisect_left, bisect_right
from datetime import timedelta
from decimal import Decimal, ROUND_FLOOR
import math
from statistics import median
from zoneinfo import ZoneInfo

from .equity import EquityAuditResult, _time, _same, _drawdown


def _integer(value, name, *, positive=False):
    if type(value) is not int or value < int(positive):
        raise ValueError(f"v4 {name} requires nonnegative integer units")
    return value


def _finite(value, name, *, positive=False):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or value < 0
        or (positive and value == 0)
    ):
        raise ValueError(f"v4 {name} requires finite nonnegative numbers")
    return float(value)


def _unique(rows, field):
    result = {row[field]: row for row in rows}
    if len(result) != len(rows):
        raise ValueError(f"v4 duplicate {field}")
    return result


def _budget(value):
    if value is None:
        return None
    required = {
        "cycle_id",
        "target_quantity",
        "allocation_fraction",
        "cash_budget",
        "buy_cost_including_fees",
        "phase",
    }
    if type(value) is not dict or set(value) != required:
        raise ValueError("v4 cycle budget fields differ")
    if type(value["cycle_id"]) is not str or not value["cycle_id"]:
        raise ValueError("v4 cycle budget requires identity")
    _integer(value["target_quantity"], "cycle target", positive=True)
    result = dict(value)
    for name in ("allocation_fraction", "cash_budget", "buy_cost_including_fees"):
        amount = Decimal(value[name])
        if not amount.is_finite() or amount < 0:
            raise ValueError("v4 invalid cycle budget amount")
        result[name] = amount
    if not 0 < Decimal(value["allocation_fraction"]) <= 1 or Decimal(value["cash_budget"]) <= 0:
        raise ValueError("v4 invalid cycle allocation")
    if value["phase"] not in {"ACTIVE", "EXITING"}:
        raise ValueError("v4 invalid cycle phase")
    return result


def _at_boundary(leg, start, end, zone, bar):
    name = leg["checkpoint"]
    if name in {"OPEN", start.astimezone(zone).strftime("%H:%M") + "_OPEN"}:
        stamp, price = start, bar["Open"]
    elif name in {"CLOSE", end.astimezone(zone).strftime("%H:%M") + "_CLOSE"}:
        stamp, price = end, bar["Close"]
    else:
        raise ValueError("v4 checkpoint lacks an exact observed boundary quote")
    if not _time(leg["submit_after"]) <= stamp <= _time(leg["submit_before"]):
        raise ValueError("v4 checkpoint lies outside submission lifetime")
    return stamp, price


def _checkpoint(leg, start, end, zone, bar, execution_lookup):
    """Locate an actual source boundary without inferring an intraday price."""
    if execution_lookup is None:
        stamp, price = _at_boundary(leg, start, end, zone, bar)
        return bar, stamp, price, "DECISION_BAR"
    name = leg["checkpoint"]
    if name == "OPEN":
        selected = execution_lookup[0].get(start)
    elif name == "CLOSE":
        selected = execution_lookup[1].get(end)
    else:
        selected = execution_lookup[2].get((start.astimezone(zone).date().isoformat(), name))
    if selected is None:
        raise ValueError("CHECKPOINT_DATA_UNAVAILABLE: exact execution quote is absent")
    lower, upper = _time(selected["BarStart"]), _time(selected["Date"])
    if not start <= lower < upper <= end:
        raise ValueError("v4 execution quote exceeds plan interval")
    stamp, price = (
        (lower, selected["Open"])
        if name == "OPEN" or name.endswith("_OPEN")
        else (upper, selected["Close"])
    )
    if not _time(leg["submit_after"]) <= stamp <= _time(leg["submit_before"]):
        raise ValueError("v4 checkpoint lies outside submission lifetime")
    return selected, stamp, price, "EXECUTION_BARS"


def _price(order, bar, rule, spec, *, leg, start, end, zone, checkpoint=None):
    """Resolve only price/precision; funding, locks, volume and dependencies are separate."""
    side, kind, limit = order["side"], order["order_type"], order["limit_price"]
    at, opening = (start, float(bar["Open"])) if leg is None else checkpoint
    bounds = None
    if rule["PriceLimitPolicy"] == "DATED_LIMITS":
        lower, upper = float(rule["PriceLimitLower"]), float(rule["PriceLimitUpper"])
        tolerance = max(abs(lower), abs(upper)) * 1e-10
        bounds = (lower, upper, tolerance)

        def inside(value):
            return lower - tolerance <= value <= upper + tolerance

        if kind == "LIMIT" and not inside(limit):
            return None, "ORDER_PRICE_OUTSIDE_LIMITS", None, None
        if side == "BUY" and abs(opening - upper) <= abs(upper) * 1e-10:
            return None, "OPEN_UP_LIMIT_BUY_BLOCKED", None, None
        if side == "SELL" and abs(opening - lower) <= abs(lower) * 1e-10:
            return None, "OPEN_DOWN_LIMIT_SELL_BLOCKED", None, None
    if kind == "MARKET":
        raw, trigger = opening, "OPEN"
    elif (side == "BUY" and opening <= limit) or (side == "SELL" and opening >= limit):
        raw, trigger = opening, "OPEN"
    elif leg is None and (
        (bar["Low"] <= limit if spec["inclusive_touch"] else bar["Low"] < limit)
        if side == "BUY"
        else (bar["High"] >= limit if spec["inclusive_touch"] else bar["High"] > limit)
    ):
        raw, trigger = limit, "INTERVAL"
    else:
        return None, "LIMIT_NOT_CROSSED", None, None
    slip = spec["slippage_bp"] / 10000
    price = raw * (1 + slip if side == "BUY" else 1 - slip)
    if bounds is not None and not bounds[0] - bounds[2] <= price <= bounds[1] + bounds[2]:
        return None, "FILL_PRICE_OUTSIDE_LIMITS", None, None
    if side == "BUY" and kind == "LIMIT" and price > limit:
        return None, "SLIPPAGE_EXCEEDS_LIMIT", None, None
    precision = (
        "MODEL_CHECKPOINT"
        if leg is not None
        else "BAR_INTERVAL"
        if trigger == "INTERVAL"
        else "MODEL_BAR_OPEN"
    )
    executed = at if leg is not None or trigger == "OPEN" else end
    return price, "FILLED", precision, executed


def audit_account_v4(
    *,
    initial_cash,
    specification,
    bars,
    decisions,
    orders,
    fills,
    actions,
    account_points,
    trades,
    action_facts,
    constraints,
    fee_rate,
    execution_bars=None,
):
    initial_cash = _finite(initial_cash, "initial cash", positive=True)
    fee_rate = _finite(fee_rate, "fee rate")
    if fee_rate >= 1 or not decisions or len(decisions) != len(account_points):
        raise ValueError("v4 account requires aligned decisions and observations")
    step = _integer(specification["quantity_step"], "quantity step", positive=True)
    tick = _finite(specification["price_tick"], "price tick", positive=True)
    _finite(specification["buy_premium"], "buy premium")
    if (
        not 0 <= specification["slippage_bp"] < 10000
        or type(specification["inclusive_touch"]) is not bool
    ):
        raise ValueError("v4 invalid execution price model")
    policy = specification["account"]["cash_availability"]
    if policy not in {"IMMEDIATE_RESEARCH", "SETTLED_ONLY"}:
        raise ValueError("v4 cash availability policy is unknown")
    market = specification["market"]["rule_version"]
    if market not in {"CN_EQUITY_V1", "US_EQUITY_V1"}:
        raise ValueError("v4 market contract is unknown")
    zone = ZoneInfo("Asia/Shanghai" if market == "CN_EQUITY_V1" else "America/New_York")
    by_end = _unique(bars, "Date")
    bar_times = [_time(row["Date"]) for row in bars]
    if bar_times != sorted(set(bar_times)):
        raise ValueError("v4 source bars must be ordered and unique")
    execution_lookup = None
    if execution_bars is not None:
        if not execution_bars:
            raise ValueError("v4 execution bars must contain actual source observations")
        start_lookup = {_time(row["BarStart"]): row for row in execution_bars}
        end_lookup = {_time(row["Date"]): row for row in execution_bars}
        if len(start_lookup) != len(execution_bars) or len(end_lookup) != len(execution_bars):
            raise ValueError("v4 execution source boundaries must be unique")
        slot_lookup = {}
        for row in execution_bars:
            for field, suffix in (("BarStart", "OPEN"), ("Date", "CLOSE")):
                local = _time(row[field]).astimezone(zone)
                key = (local.date().isoformat(), local.strftime("%H:%M") + "_" + suffix)
                if key in slot_lookup:
                    raise ValueError("v4 execution checkpoints must be unique")
                slot_lookup[key] = row
        execution_lookup = start_lookup, end_lookup, slot_lookup
    previous_end = None
    for row in list(bars) + list(execution_bars or []):
        if execution_bars and row is execution_bars[0]:
            previous_end = None
        lower, upper, available_at = (
            _time(row[name]) for name in ("BarStart", "Date", "AvailableDate")
        )
        if not lower < upper <= available_at or previous_end is not None and lower < previous_end:
            raise ValueError("v4 source bar chronology or availability is invalid")
        previous_end = upper
        if lower.astimezone(zone).date() != upper.astimezone(zone).date():
            raise ValueError("v4 regular-session source bar crosses its local session date")
        state = row.get("BarStatus", "OBSERVED")
        if (
            state not in {"OBSERVED", "MISSING", "ZERO_VOLUME"}
            or type(row.get("ExecutionBlocked", False)) is not bool
        ):
            raise ValueError("v4 source observation flags are invalid")
        if state == "MISSING":
            if any(
                row.get(name) is not None
                for name in ("Open", "High", "Low", "Close", "Volume", "Amount")
            ):
                raise ValueError("v4 source missing bar invents market prices")
        else:
            for name in ("Open", "High", "Low", "Close", "Volume", "Amount"):
                _finite(row[name], name, positive=name in {"Open", "High", "Low", "Close"})
            if row["Low"] > min(row["Open"], row["Close"]) or row["High"] < max(
                row["Open"], row["Close"]
            ):
                raise ValueError("v4 source bar price bounds differ")
            if "BarStatus" in row and (row["Volume"] == 0) != (state == "ZERO_VOLUME"):
                raise ValueError("v4 source zero-volume classification differs")
    bar_lookup = {_time(row["Date"]): row for row in bars}
    rules = {_time(row["Date"]): row for row in constraints}
    if len(rules) != len(constraints) or len(by_end) != len(bars):
        raise ValueError("v4 dated source facts must be unique")
    _unique(decisions, "decision_id")
    _unique(orders, "order_id")
    fill_map = _unique(fills, "fill_id")
    if set(fill_map) != {row["order_id"] for row in orders if row["status"] == "FILLED"}:
        raise ValueError("v4 filled orders and fill identities differ")
    by_decision = defaultdict(list)
    for row in orders:
        by_decision[row["decision_id"]].append(row)
    if set(by_decision) - {row["decision_id"] for row in decisions}:
        raise ValueError("v4 order lacks its decision")
    first_start, last_end = _time(decisions[0]["decision_at"]), _time(account_points[-1]["time"])
    source = _unique(action_facts, "EventId")
    source_events = sorted(
        (
            row
            for row in source.values()
            if row["Kind"] != "NONE" and first_start <= _time(row["Date"]) < last_end
        ),
        key=lambda row: (_time(row["Date"]), 0 if row["Kind"] == "SPLIT" else 1, row["EventId"]),
    )
    for fact in source_events:
        if fact["Kind"] not in {"SPLIT", "CASH_DIVIDEND"} or _time(fact["AvailableDate"]) > _time(
            fact["Date"]
        ):
            raise ValueError("v4 source corporate action is unavailable or unsupported")
    split_facts = [fact for fact in source_events if fact["Kind"] == "SPLIT"]
    split_times = [_time(fact["Date"]) for fact in split_facts]
    actual_actions = list(actions)
    action_index = event_index = 0
    pending, locks = {}, []
    cash, quantity, receivable, fees = initial_cash, 0, 0.0, 0.0
    cycle = None
    cycle_cost = cycle_income = 0.0
    cycle_entry = None
    budget, spent = None, Decimal(0)
    expected_trades = []
    values, daily = [], {}
    mark, mark_at = None, None
    owner = None
    available = sorted(
        bars,
        key=lambda row: max(
            _time(row["Date"]),
            _time(row["AvailableDate"]) + timedelta(seconds=specification["data_latency_seconds"]),
        ),
    )
    cursor, latest, latest_complete = 0, None, None

    def journal(
        identity, stamp, kind, before, after, amount, cash_delta, receivable_delta, revision
    ):
        nonlocal action_index, cash, receivable
        if action_index >= len(actual_actions):
            raise ValueError("v4 source event or due payment is missing from journal")
        row = actual_actions[action_index]
        if (
            row["event_id"],
            _time(row["time"]),
            row["kind"],
            row["account_revision"],
            row["quantity_before"],
            row["quantity_after"],
        ) != (identity, stamp, kind, revision, before, after):
            raise ValueError("v4 action journal identity, order, time or quantity differs")
        for name, expected in (
            ("amount", amount),
            ("cash_delta", cash_delta),
            ("receivable_delta", receivable_delta),
        ):
            _same(row[name], expected, "v4 action " + name)
        cash += cash_delta
        receivable += receivable_delta
        action_index += 1

    def payments(through, revision, inclusive=True):
        for identity, (stamp, amount, kind) in sorted(
            tuple(pending.items()), key=lambda item: item[1][0]
        ):
            if stamp < through or (inclusive and stamp == through):
                journal(
                    identity, stamp, kind, quantity, quantity, amount, amount, -amount, revision
                )
                del pending[identity]

    for revision, (decision, point) in enumerate(zip(decisions, account_points, strict=True)):
        start, end = _time(decision["execution_start"]), _time(decision["execution_end"])
        at, observed = _time(decision["decision_at"]), _time(decision["observed_through"])
        if not observed <= at <= start < end or at != start:
            raise ValueError("v4 decision is noncausal or uses an unsupported snapshot time")
        if revision and start < _time(account_points[revision - 1]["time"]):
            raise ValueError("v4 execution intervals overlap")
        _integer(decision["portfolio_revision"], "decision revision")
        _integer(point["account_revision"], "point revision")
        _integer(point["quantity"], "observed quantity")
        if (
            decision["portfolio_revision"] != revision
            or point["account_revision"] != revision
            or point["decision_id"] != decision["decision_id"]
            or _time(point["time"]) != end
        ):
            raise ValueError("v4 decision, account revision and observation differ")
        bar = bar_lookup.get(end)
        rule = rules.get(start)
        if bar is None or _time(bar["BarStart"]) != start or rule is None:
            raise ValueError("v4 execution interval lacks its source bar or dated rules")
        if (
            rule["QuantityStep"] != step
            or rule["PriceTick"] != tick
            or _time(rule["AvailableDate"]) > at
            or type(rule["Tradable"]) is not bool
        ):
            raise ValueError("v4 dated execution rules differ or are unavailable")
        if rule.get("SellRemainderPolicy") not in {"STRICT_STEP", "FULL_LIQUIDATION"}:
            raise ValueError("v4 explicit sell remainder policy is missing")
        unlock, settlement = _time(rule["BuySellableAt"]), _time(rule["SettlementAt"])
        if unlock < start or settlement < start:
            raise ValueError("v4 dated asset availability precedes execution")
        status, blocked = bar.get("BarStatus", "OBSERVED"), bar.get("ExecutionBlocked", False)
        if execution_lookup is not None:
            first, last = execution_lookup[0].get(start), execution_lookup[1].get(end)
            if first is None or last is None:
                raise ValueError("v4 execution quotes do not cover decision interval boundaries")
            if status != "MISSING":
                for actual, expected in (
                    (first["Open"], bar["Open"]),
                    (last["Close"], bar["Close"]),
                ):
                    if actual is not None and not math.isclose(
                        actual, expected, rel_tol=1e-10, abs_tol=0.0
                    ):
                        raise ValueError("v4 execution RAW price units differ")
        if status not in {"OBSERVED", "ZERO_VOLUME", "MISSING"} or type(blocked) is not bool:
            raise ValueError("v4 invalid source observation status")
        if status == "MISSING":
            if any(
                bar.get(name) is not None
                for name in ("Open", "High", "Low", "Close", "Volume", "Amount")
            ):
                raise ValueError("v4 missing bar contains fabricated prices")
        else:
            for name in ("Open", "High", "Low", "Close", "Volume", "Amount"):
                _finite(bar[name], name, positive=name in {"Open", "High", "Low", "Close"})
            if bar["Low"] > min(bar["Open"], bar["Close"]) or bar["High"] < max(
                bar["Open"], bar["Close"]
            ):
                raise ValueError("v4 source OHLC bounds are invalid")
            if "BarStatus" in bar and ((bar["Volume"] == 0) != (status == "ZERO_VOLUME")):
                raise ValueError("v4 volume and source observation status differ")
        if rule["PriceLimitPolicy"] == "DATED_LIMITS":
            low, high = float(rule["PriceLimitLower"]), float(rule["PriceLimitUpper"])
            if not 0 < low < high or not all(math.isfinite(v) for v in (low, high)):
                raise ValueError("v4 invalid dated price limits")
            tolerance = max(abs(low), abs(high)) * 1e-10
            if status != "MISSING" and any(
                not low - tolerance <= bar[name] <= high + tolerance
                for name in ("Open", "High", "Low", "Close")
            ):
                raise ValueError("v4 source prices exceed dated price limits")
        elif rule["PriceLimitPolicy"] != "EXPLICIT_UNBOUNDED" or any(
            rule[name] is not None for name in ("PriceLimitLower", "PriceLimitUpper")
        ):
            raise ValueError("v4 price limits lack an explicit source policy")
        while (
            event_index < len(source_events) and _time(source_events[event_index]["Date"]) <= start
        ):
            fact = source_events[event_index]
            stamp, before = _time(fact["Date"]), quantity
            payments(stamp, revision, inclusive=False)
            if fact["Kind"] == "SPLIT":
                ratio = _finite(fact["Ratio"], "split ratio", positive=True)
                changed = quantity * ratio
                if not changed.is_integer():
                    raise ValueError("v4 fractional split entitlement is unsupported")
                quantity = int(changed)
                if any(not float(qty * ratio).is_integer() for _, qty in locks):
                    raise ValueError("v4 fractional split sellability entitlement")
                locks = [(unlock_at, int(qty * ratio)) for unlock_at, qty in locks]
                if mark is not None:
                    mark /= ratio
                journal(fact["EventId"], stamp, "SPLIT", before, quantity, 0.0, 0.0, 0.0, revision)
            else:
                amount = quantity * _finite(fact["CashPerShare"], "cash dividend")
                pay_at = _time(fact["PayAt"])
                if pay_at < stamp:
                    raise ValueError("v4 dividend payment precedes entitlement")
                pending[fact["EventId"]] = (pay_at, amount, "DIVIDEND_PAYMENT")
                journal(
                    fact["EventId"],
                    stamp,
                    "CASH_DIVIDEND",
                    before,
                    quantity,
                    amount,
                    0.0,
                    amount,
                    revision,
                )
                if cycle is not None:
                    cycle_income += amount
            event_index += 1
        if (
            event_index < len(source_events)
            and start < _time(source_events[event_index]["Date"]) < end
        ):
            raise ValueError("v4 corporate event occurs inside an indivisible price interval")
        locks = [(unlock_at, qty) for unlock_at, qty in locks if unlock_at > start]
        payments(start, revision)
        locks = [(stamp, qty) for stamp, qty in locks if stamp > start]
        while (
            cursor < len(available)
            and max(
                _time(available[cursor]["Date"]),
                _time(available[cursor]["AvailableDate"])
                + timedelta(seconds=specification["data_latency_seconds"]),
            )
            <= at
        ):
            candidate = available[cursor]
            if latest_complete is None or _time(candidate["Date"]) > _time(latest_complete["Date"]):
                latest_complete = candidate
            if candidate.get("BarStatus", "OBSERVED") == "OBSERVED" and (
                latest is None or _time(candidate["Date"]) > _time(latest["Date"])
            ):
                latest = candidate
            cursor += 1
        if latest is None or _time(latest["Date"]) != observed:
            raise ValueError("v4 decision observed history differs from available source bars")
        expected_signal = (
            "SUPPRESSED_UNOBSERVED_BAR"
            if latest_complete.get("BarStatus", "OBSERVED") != "OBSERVED"
            else "EVALUATED"
        )
        if decision.get("signal_status") != expected_signal:
            raise ValueError("v4 signal suppression differs from latest available observation")
        reference = float(latest["Close"])
        for fact in split_facts[
            bisect_left(split_times, observed) : bisect_right(split_times, start)
        ]:
            reference /= float(fact["Ratio"])
        plan = decision["plan"]
        evidence = plan["evidence"]
        _integer(plan["expected_revision"], "plan revision")
        _integer(plan["target_quantity"], "plan target")
        if (
            plan["plan_identity"] != decision["decision_id"]
            or plan["expected_revision"] != revision
            or plan["target_quantity"] != decision["target_quantity"]
        ):
            raise ValueError("v4 plan identity, target or revision differs from decision")
        if owner is None:
            owner = plan["owner"]
        if not owner or plan["owner"] != owner:
            raise ValueError("v4 account plan owner differs")
        plan_point = plan["point"]
        if tuple(
            _time(plan_point[name])
            for name in ("observed_through", "decision_at", "execution_start", "execution_end")
        ) != (observed, at, start, end):
            raise ValueError("v4 plan time differs from decision")
        if (
            plan_point["session_id"] != start.astimezone(zone).date().isoformat()
            or point["session"] != plan_point["session_id"]
        ):
            raise ValueError("v4 account session differs from its market clock")
        sizing = evidence.get("sizing")
        if sizing not in {"TARGET_FRACTION", "EXPLICIT_ORDERS"}:
            raise ValueError("v4 plan must explicitly declare sizing semantics")
        if "reference_price" in evidence:
            _same(evidence["reference_price"], reference, "v4 sizing reference")
        direct, legs = plan["orders"], plan["legs"]
        if direct and legs:
            raise ValueError("v4 plan mixes direct orders and dependency legs")
        sequence = (
            [(leg["sequence"], leg["order"], leg) for leg in legs]
            if legs
            else [(i, row, None) for i, row in enumerate(direct)]
        )
        if [item[0] for item in sequence] != sorted({item[0] for item in sequence}):
            raise ValueError("v4 execution sequences are not unique and ordered")
        projected = quantity
        for number, order, leg in sequence:
            amount = _integer(order["quantity"], "order quantity", positive=True)
            if order["side"] not in {"BUY", "SELL"} or order["order_type"] not in {
                "LIMIT",
                "MARKET",
            }:
                raise ValueError("v4 order units, side or type are invalid")
            if amount % step and not (
                order["side"] == "SELL"
                and rule["SellRemainderPolicy"] == "FULL_LIQUIDATION"
                and amount == projected
            ):
                raise ValueError("v4 order violates its declared quantity or liquidation rule")
            limit = order["limit_price"]
            if order["order_type"] == "LIMIT":
                _finite(limit, "limit price", positive=True)
                if Decimal(str(limit)) % Decimal(str(tick)):
                    raise ValueError("v4 limit price violates declared price tick")
            elif limit is not None:
                raise ValueError("v4 market order carries a limit")
            projected += amount if order["side"] == "BUY" else -amount
            if projected < 0:
                raise ValueError("v4 plan requests a short position")
            if (
                leg is not None
                and leg["dependency_sequence"] is not None
                and (
                    leg["dependency_sequence"]
                    not in [item[0] for item in sequence if item[0] < number]
                    or leg["dependency_required_status"] not in {"FILLED", "EXPIRED"}
                )
            ):
                raise ValueError("v4 invalid execution dependency")
        if projected != plan["target_quantity"]:
            raise ValueError("v4 target quantity differs from declared orders")
        if expected_signal == "SUPPRESSED_UNOBSERVED_BAR" and (sequence or projected != quantity):
            raise ValueError("v4 suppressed signal changes the held position")
        instruction_sides = {item[1]["side"] for item in sequence}
        summary_side = (
            next(iter(instruction_sides))
            if len(instruction_sides) == 1
            else "MIXED"
            if instruction_sides
            else "HOLD"
        )
        summary_limit = (
            sequence[0][1]["limit_price"]
            if len(sequence) == 1 and sequence[0][1]["order_type"] == "LIMIT"
            else None
        )
        if (
            decision.get("side") != summary_side
            or decision.get("quantity") != sum(item[1]["quantity"] for item in sequence)
            or decision.get("limit_price") != summary_limit
        ):
            raise ValueError("v4 decision summary differs from full order instructions")
        if decision.get("reference_price") is not None:
            _same(decision["reference_price"], reference, "v4 decision reference")
        if decision.get("target") != evidence.get("target"):
            raise ValueError("v4 decision target summary differs from plan evidence")
        mode = plan["capital_mode"]
        if mode not in {"target_equity_fraction", "full_available_cash", "signal_cash_fraction"}:
            raise ValueError("v4 unsupported capital mode")
        after_budget = _budget(plan["cycle_after"])
        if mode == "signal_cash_fraction":
            if _budget(plan["cycle_before"]) != budget:
                raise ValueError("v4 budget before differs from confirmed account")
            if after_budget is not None:
                if budget is not None and any(
                    after_budget[name] != budget[name]
                    for name in (
                        "cycle_id",
                        "target_quantity",
                        "allocation_fraction",
                        "cash_budget",
                        "buy_cost_including_fees",
                    )
                ):
                    raise ValueError("v4 active cycle budget was rebuilt")
                if budget is None:
                    spent = Decimal(0)
                    if Decimal(after_budget["cash_budget"]) > Decimal(str(cash)) * Decimal(
                        after_budget["allocation_fraction"]
                    ):
                        raise ValueError("v4 budget exceeds available allocation")
                if (
                    Decimal(after_budget["buy_cost_including_fees"]) != spent
                    or plan["target_quantity"] > after_budget["target_quantity"]
                ):
                    raise ValueError("v4 cycle budget cost or target differs")
            elif plan["target_quantity"]:
                raise ValueError("v4 active target lacks a cycle budget")
            budget = after_budget
        elif plan["cycle_before"] is not None or after_budget is not None:
            raise ValueError("v4 non-cycle mode carries a cycle budget")
        if sizing == "TARGET_FRACTION":
            target = evidence.get("target")
            if (
                type(target) not in (int, float)
                or not math.isfinite(target)
                or not 0 <= target <= 1
            ):
                raise ValueError("v4 automatic target fraction is invalid")
            if (
                "reference_price" not in evidence
                or mode == "full_available_cash"
                and target not in (0, 1)
            ):
                raise ValueError(
                    "v4 automatic sizing lacks its declared reference or binary full-cash target"
                )
            desired = (
                int(
                    (
                        Decimal(str(cash))
                        + Decimal(str(receivable))
                        + Decimal(quantity) * Decimal(str(reference))
                    )
                    * Decimal(str(target))
                    / Decimal(str(reference))
                    / step
                )
                * step
            )
            if mode == "full_available_cash" and quantity and target:
                desired = quantity
            if mode == "signal_cash_fraction":
                if budget is None:
                    raise ValueError("v4 automatic cycle sizing lacks budget")
                desired = budget["target_quantity"] if target else 0
            expected = []
            if desired > quantity:
                limit = float(
                    (
                        Decimal(str(reference))
                        * (1 + Decimal(str(specification["buy_premium"])))
                        / Decimal(str(tick))
                    ).to_integral_value(rounding=ROUND_FLOOR)
                    * Decimal(str(tick))
                )
                spendable = Decimal(str(cash))
                if mode == "signal_cash_fraction":
                    spendable = min(
                        spendable,
                        Decimal(budget["cash_budget"]) - Decimal(budget["buy_cost_including_fees"]),
                    )
                amount = (
                    min(
                        desired - quantity,
                        max(
                            0,
                            int(
                                spendable
                                / (Decimal(str(limit)) * (1 + Decimal(str(fee_rate))))
                                / step
                            )
                            * step,
                        ),
                    )
                    // step
                    * step
                )
                if amount:
                    expected = [("BUY", amount, "LIMIT", limit)]
            elif desired < quantity:
                amount = min(
                    quantity - desired, quantity - sum(qty for stamp, qty in locks if stamp > at)
                )
                if amount % step and not (
                    rule["SellRemainderPolicy"] == "FULL_LIQUIDATION" and amount == quantity
                ):
                    amount = amount // step * step
                if amount:
                    expected = [("SELL", amount, "MARKET", None)]
            if (
                legs
                or [(o["side"], o["quantity"], o["order_type"], o["limit_price"]) for o in direct]
                != expected
            ):
                raise ValueError("v4 automatic orders differ from independently sized target")
            if evidence.get("desired_quantity") != desired:
                raise ValueError("v4 declared desired quantity differs from target fraction")
        actual = by_decision.get(decision["decision_id"], [])
        if len(actual) != len(sequence):
            raise ValueError("v4 order journal does not cover plan instructions")
        consumed, statuses, previous_checkpoint = {}, {}, None
        for row, (number, instruction, leg) in zip(actual, sequence, strict=True):
            identity = f"{decision['decision_id']}:{number}"
            if (
                row["order_id"],
                row["sequence"],
                row["side"],
                row["quantity"],
                row["order_type"],
                row["limit_price"],
            ) != (
                identity,
                number,
                instruction["side"],
                instruction["quantity"],
                instruction["order_type"],
                instruction["limit_price"],
            ) or (_time(row["valid_start"]), _time(row["valid_end"])) != (start, end):
                raise ValueError("v4 order differs from its plan or lifetime")
            for name in ("checkpoint", "dependency_sequence", "dependency_required_status"):
                if row[name] != (None if leg is None else leg[name]):
                    raise ValueError("v4 order dependency or checkpoint differs from plan")
            price, reason, precision, executed = None, None, None, None
            source_bar, stamp, source_price, quote_source = (
                (bar, start, bar["Open"], "DECISION_BAR")
                if leg is None
                else _checkpoint(leg, start, end, zone, bar, execution_lookup)
            )
            if leg is not None:
                if previous_checkpoint is not None and stamp < previous_checkpoint:
                    raise ValueError("v4 execution dependency reverses observed checkpoint time")
                previous_checkpoint = stamp
                payments(stamp, revision)
            quote_start, quote_end = _time(source_bar["BarStart"]), _time(source_bar["Date"])
            volume_key = quote_start, quote_end
            if (
                _time(row["quote_interval_start"]),
                _time(row["quote_interval_end"]),
                row["quote_source"],
            ) != (quote_start, quote_end, quote_source):
                raise ValueError("v4 order quote source differs from exact observation")
            source_status = source_bar.get("BarStatus", "OBSERVED")
            if status != "MISSING" and source_status != "MISSING":
                quote_tolerance = max(abs(bar["Low"]), abs(bar["High"])) * 1e-10
                if (
                    source_bar["Low"] < bar["Low"] - quote_tolerance
                    or source_bar["High"] > bar["High"] + quote_tolerance
                ):
                    raise ValueError("v4 execution quote exceeds decision bar price range")
            if rule["PriceLimitPolicy"] == "DATED_LIMITS" and source_status != "MISSING":
                if any(
                    not low - tolerance <= source_bar[name] <= high + tolerance
                    for name in ("Open", "High", "Low", "Close")
                ):
                    raise ValueError("v4 execution quotes exceed dated price limits")
            if source_status != "OBSERVED":
                reason = (
                    ("MISSING_EXECUTION_BAR" if quote_source == "EXECUTION_BARS" else "MISSING_BAR")
                    if source_status == "MISSING"
                    else "ZERO_VOLUME"
                )
            elif source_bar.get("ExecutionBlocked", False):
                reason = "KNOWN_INTERRUPTION"
            elif (
                leg is not None
                and leg["dependency_sequence"] is not None
                and statuses.get(leg["dependency_sequence"]) != leg["dependency_required_status"]
            ):
                reason = "DEPENDENCY_NOT_FILLED"
            elif not rule["Tradable"]:
                reason = "NOT_TRADABLE"
            elif consumed.get(volume_key, 0) + instruction["quantity"] > source_bar["Volume"]:
                reason = "INSUFFICIENT_BAR_VOLUME"
            elif (
                instruction["side"] == "SELL"
                and instruction["quantity"] % step
                and instruction["quantity"] != quantity
            ):
                reason = "ODD_LOT_REQUIRES_FULL_LIQUIDATION"
            elif instruction["side"] == "SELL" and instruction["quantity"] > quantity - sum(
                qty for unlock_at, qty in locks if unlock_at > stamp
            ):
                reason = "INSUFFICIENT_SELLABLE_QUANTITY"
            else:
                price, reason, precision, executed = _price(
                    instruction,
                    source_bar,
                    rule,
                    specification,
                    leg=leg,
                    start=start,
                    end=end,
                    zone=zone,
                    checkpoint=(stamp, float(source_price)),
                )
                if price is not None and instruction["side"] == "BUY":
                    if instruction["quantity"] * price * (1 + fee_rate) > cash + 1e-9:
                        price, reason = None, "INSUFFICIENT_CASH"
                    elif mode == "signal_cash_fraction" and spent + Decimal(
                        instruction["quantity"]
                    ) * Decimal(str(price)) * (1 + Decimal(str(fee_rate))) > Decimal(
                        budget["cash_budget"]
                    ):
                        price, reason = None, "CYCLE_BUDGET_EXCEEDED"
            expected_status = "EXPIRED" if price is None else "FILLED"
            if row["status"] != expected_status or row["reason"] != reason:
                raise ValueError(
                    "v4 order status or reason differs from independent execution facts"
                )
            statuses[number] = expected_status
            if price is None:
                continue
            fill = fill_map[identity]
            if (
                (fill["order_id"], fill["account_revision"], fill["side"], fill["quantity"])
                != (identity, revision, instruction["side"], instruction["quantity"])
                or (_time(fill["interval_start"]), _time(fill["interval_end"])) != (start, end)
                or fill["time_precision"] != precision
                or _time(fill["executed_at"]) != executed
                or (
                    _time(fill["quote_interval_start"]),
                    _time(fill["quote_interval_end"]),
                    fill["quote_source"],
                )
                != (quote_start, quote_end, quote_source)
            ):
                raise ValueError(
                    "v4 fill identity, sequence or observed execution precision differs"
                )
            _same(fill["price"], price, "v4 fill price")
            gross = price * instruction["quantity"]
            amount_fee = gross * fee_rate
            _same(fill["fees"], amount_fee, "v4 fill fee")
            fees += amount_fee
            if instruction["side"] == "BUY":
                if cycle is None:
                    cycle, cycle_entry, cycle_cost, cycle_income = identity, start, 0.0, 0.0
                cash -= gross + amount_fee
                quantity += instruction["quantity"]
                cycle_cost += gross + amount_fee
                spent += (
                    Decimal(instruction["quantity"])
                    * Decimal(str(price))
                    * (1 + Decimal(str(fee_rate)))
                )
                locks.append((unlock, instruction["quantity"]))
                if budget is not None:
                    budget["buy_cost_including_fees"] = spent
            else:
                quantity -= instruction["quantity"]
                proceeds = gross - amount_fee
                cycle_income += proceeds
                if policy == "IMMEDIATE_RESEARCH":
                    cash += proceeds
                else:
                    if settlement < (executed if precision == "MODEL_CHECKPOINT" else end):
                        raise ValueError("v4 sale settlement precedes execution completion")
                    receivable += proceeds
                    pending[identity] = (settlement, proceeds, "SALE_SETTLEMENT")
            if fill["cycle_id"] != cycle:
                raise ValueError("v4 fill cycle differs from real position lifecycle")
            if quantity == 0 and cycle is not None:
                expected_trades.append((cycle, cycle_entry, end, cycle_cost, cycle_income))
                cycle, budget = None, None
            consumed[volume_key] = consumed.get(volume_key, 0) + instruction["quantity"]
        payments(end, revision)
        stale = status != "OBSERVED"
        if not stale:
            mark, mark_at = float(bar["Close"]), end
        elif mark is None:
            mark, mark_at = reference, observed
        if (
            point["bar_status"] != status
            or point["valuation_stale"] is not stale
            or _time(point["valuation_price_at"]) != mark_at
            or point["execution_blocked"] is not blocked
            or point["cycle_id"] != cycle
        ):
            raise ValueError("v4 account observation metadata differs")
        for name, expected in (
            ("cash", cash),
            ("quantity", quantity),
            ("receivable", receivable),
            ("close", mark),
            ("equity", cash + receivable + quantity * mark),
        ):
            _same(point[name], expected, "v4 account " + name)
        if cash < -1e-7 or quantity < 0 or receivable < -1e-7:
            raise ValueError("v4 account became short or overdrawn")
        values.append(point["equity"])
        daily[point["session"]] = point["equity"]
    if (
        action_index != len(actual_actions)
        or event_index != len(source_events)
        or any(stamp <= last_end for stamp, _, _ in pending.values())
    ):
        raise ValueError("v4 action coverage or due payment journal differs")
    if len(expected_trades) != len(trades):
        raise ValueError("v4 closed-position count differs")
    by_session = dict.fromkeys(daily, 0)
    for expected, row in zip(expected_trades, trades, strict=True):
        identity, entry, exit_at, cost, income = expected
        if (row["cycle_id"], _time(row["entry_at"]), _time(row["exit_at"]), row["status"]) != (
            identity,
            entry,
            exit_at,
            "CLOSED",
        ):
            raise ValueError("v4 closed-position identity or time differs")
        for name, amount in (
            ("cost", cost),
            ("income", income),
            ("net_pnl", income - cost),
            ("net_return", income / cost - 1),
        ):
            _same(row[name], amount, "v4 closed-position " + name)
        by_session[exit_at.astimezone(zone).date().isoformat()] += 1
    counts = list(by_session.values())
    rolling = tuple(sum(counts[i - 59 : i + 1]) for i in range(59, len(counts)))
    return EquityAuditResult(
        values[-1] / initial_cash - 1,
        (values[-1] / initial_cash) ** (252 / len(daily)) - 1,
        _drawdown(daily.values(), initial_cash),
        _drawdown(values, initial_cash),
        len(daily),
        len(values),
        len(expected_trades),
        fees,
        rolling,
        float(median(rolling)) if rolling else None,
    )
