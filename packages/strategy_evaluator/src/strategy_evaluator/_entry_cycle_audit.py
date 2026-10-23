"""Independent arithmetic audit of signal-owned cycle allocation facts.

This module consumes retained facts only; it never imports SRT or TXE.
"""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
import json
import re


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("invalid decimal fact")
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        raise ValueError("invalid decimal fact")
    return number


def _state(encoded):
    value = json.loads(encoded)
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {
        "cycle_id", "opening_signal_identity", "allocation_fraction", "cash_budget",
        "target_quantity", "buy_cost_including_fees", "phase",
    }:
        raise ValueError("invalid cycle fields")
    for field in ("cycle_id", "opening_signal_identity"):
        if not isinstance(value[field], str) or re.fullmatch(r"[0-9a-f]{64}", value[field]) is None:
            raise ValueError("invalid cycle identity")
    for field in ("allocation_fraction", "cash_budget", "buy_cost_including_fees"):
        value[field] = _decimal(value[field])
    if not 0 < value["allocation_fraction"] <= 1 or value["cash_budget"] <= 0:
        raise ValueError("invalid cycle allocation")
    if (type(value["target_quantity"]) is not int or value["target_quantity"] <= 0
            or value["phase"] not in {"ACTIVE", "EXITING"}):
        raise ValueError("invalid cycle quantity or phase")
    return value


def audit_entry_cycles(evidence, tolerance):
    """Return a reason code for malformed or economically inconsistent facts."""
    dynamic = evidence.execution_spec.get("capital_mode") == "signal_cash_fraction"
    if not dynamic:
        return ("UNDECLARED_ENTRY_CYCLE_FACTS",) if any(
            "entry_cycle_before" in row for row in evidence.decisions) else ()
    try:
        _audit(evidence, Decimal(str(tolerance)))
    except (ValueError, TypeError, KeyError, InvalidOperation, ZeroDivisionError, OverflowError):
        return ("ENTRY_CYCLE_ALLOCATION_MISMATCH",)
    return ()


def _audit(evidence, tolerance):
    spec = evidence.execution_spec
    if spec.get("target_scope") != "entry_cycle" or spec.get("entry_order_type") != "LIMIT":
        raise ValueError("dynamic allocation requires entry cycle scope and limit buys")
    lot = spec["instrument"]["lot_size"]
    maximum = spec["instrument"]["maximum_order_quantity"]
    fee = _decimal(spec["fee_rate"])
    decisions = {str(row["valid_session"])[:10]: row for row in evidence.decisions}
    daily = {str(row["date"])[:10]: row for row in evidence.execution_daily}
    orders, fills = {}, {}
    for row in evidence.orders:
        orders.setdefault(str(row["decision_id"]), []).append(row)
    for row in evidence.fills:
        fills.setdefault(str(row["fill_time"])[:10], []).append(row)
    previous = None
    opened = set()

    def equal(left, right):
        if left != right:
            raise ValueError("cycle facts differ")

    def close(left, right):
        if abs(left - right) > tolerance:
            raise ValueError("cycle money differs")

    def affordable(cash, unit):
        return int((max(Decimal(0), cash) / (unit * lot)).to_integral_value(rounding=ROUND_FLOOR)) * lot

    for account in evidence.account_daily:
        day = str(account["date"])[:10]
        decision = decisions.get(day)
        after = previous
        active_orders = []
        if decision is not None:
            before = _state(decision["entry_cycle_before"])
            equal(before, previous)
            after = _state(decision["entry_cycle_after"])
            target = json.loads(decision["cycle_target"])
            if not isinstance(target, dict) or set(target) != {"active", "entry_fraction"} or type(target["active"]) is not bool:
                raise ValueError("invalid cycle target")
            fraction = _decimal(target["entry_fraction"]) if target["active"] else None
            if target["active"] and not 0 < fraction <= 1 or not target["active"] and target["entry_fraction"] is not None:
                raise ValueError("invalid target fraction")
            equal(decision["target_position"], int(target["active"]))
            equal(None if decision["entry_allocation_fraction"] is None else _decimal(decision["entry_allocation_fraction"]), fraction)
            cash = _decimal(account["cash_before"])
            held = account["quantity_before"]
            signal = daily[str(decision["signal_date"])[:10]]
            # SRT first computes a raw-price tick limit and only then applies
            # the declared research price scale. Match those binary64 facts.
            from .replay_audit import _floor, _nearest
            tick = float(spec["instrument"]["price_tick"])
            raw = float(signal["unadjusted_close"])
            price = min(_floor(raw * (1 + float(spec["entry_limit_parameter"])), tick),
                        _nearest(_floor(raw * (1 + float(spec["instrument"]["price_limit_ratio"])), tick) - tick, tick)) * float(signal["price_scale"])
            unit = Decimal(str(price)) * (1 + fee)
            status = "IDLE"
            if before is None:
                equal(held, 0)
                desired = affordable(cash * fraction, unit) if target["active"] else 0
                if desired:
                    if after is None or after["cycle_id"] in opened:
                        raise ValueError("missing or reused cycle")
                    opened.add(after["cycle_id"])
                    equal(after["opening_signal_identity"], decision["signal_identity"])
                    equal(after["allocation_fraction"], fraction)
                    close(after["cash_budget"], cash * fraction)
                    equal(after["target_quantity"], desired)
                    equal(after["buy_cost_including_fees"], Decimal(0))
                    equal(after["phase"], "ACTIVE")
                    status = "OPEN"
                else:
                    equal(after, None)
                    status = "INSUFFICIENT_LOT" if target["active"] else "IDLE"
            else:
                expected = dict(before)
                if not target["active"] or before["phase"] == "EXITING":
                    expected["phase"] = "EXITING"
                equal(after, expected)
                status = "EXIT" if after["phase"] == "EXITING" else "HOLD"
            active_orders = orders.get(str(decision["decision_id"]), [])
            if after is not None and after["phase"] == "ACTIVE":
                if held > after["target_quantity"] or after["target_quantity"] % lot:
                    raise ValueError("position exceeds cycle quantity")
                remaining = max(Decimal(0), after["cash_budget"] - after["buy_cost_including_fees"])
                expected_quantity = min(after["target_quantity"] - held, affordable(min(cash, remaining), unit))
                if expected_quantity == 0 and held < after["target_quantity"]:
                    status = "BUDGET_LIMIT"
                side = "BUY"
            else:
                expected_quantity, side = held, "SELL"
            equal(decision["cycle_status"], status)
            equal(sum(row["quantity"] for row in active_orders), expected_quantity)
            for order in active_orders:
                equal(order["side"], side)
                equal(order["cycle_id"], after["cycle_id"])
                if order["quantity"] > maximum:
                    raise ValueError("order exceeds maximum")
            equal(decision["cycle_id"], None if after is None else after["cycle_id"])
            equal(decision["cycle_target_quantity"], None if after is None else after["target_quantity"])
            for column, field in (("cycle_allocation_fraction", "allocation_fraction"), ("cycle_cash_budget", "cash_budget")):
                equal(None if decision[column] is None else _decimal(decision[column]), None if after is None else after[field])
        for fill in fills.get(day, []):
            if after is None or fill["cycle_id"] != after["cycle_id"]:
                raise ValueError("fill has no cycle")
            if fill["side"] == "BUY":
                if after["phase"] != "ACTIVE":
                    raise ValueError("buy in exiting cycle")
                gross = _decimal(fill["quantity"]) * _decimal(fill["price"])
                # Fill tables retain binary64 fees, while the cycle contract
                # accumulates exact decimal price/quantity/configured-fee facts.
                # Check the reported fee, then reconstruct that exact contract.
                close(_decimal(fill["fees"]), gross * fee)
                after = {**after, "buy_cost_including_fees": after["buy_cost_including_fees"]
                         + gross * (1 + fee)}
                # Historical replay uses the configured fee and a LIMIT buy.
                # PTE's unexpected real-channel fee facts have a separate audit.
                if after["buy_cost_including_fees"] > after["cash_budget"] + tolerance:
                    raise ValueError("historical fill exceeded the cycle budget")
        if decision is not None:
            equal(None if decision["cycle_buy_cost_including_fees"] is None else _decimal(decision["cycle_buy_cost_including_fees"]),
                  None if after is None else after["buy_cost_including_fees"])
        if after is not None and after["phase"] == "EXITING" and account["quantity"] == 0:
            after = None
        equal(_state(account["entry_cycle"]), after)
        equal(account["entry_cycle_id"], None if after is None else after["cycle_id"])
        equal(account["entry_cycle_phase"], None if after is None else after["phase"])
        for column, field in (("entry_cycle_cash_budget", "cash_budget"), ("entry_cycle_buy_cost_including_fees", "buy_cost_including_fees")):
            equal(None if account[column] is None else _decimal(account[column]), None if after is None else after[field])
        previous = after
