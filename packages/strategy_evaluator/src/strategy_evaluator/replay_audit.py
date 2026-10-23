from __future__ import annotations
from datetime import datetime

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from hashlib import sha256
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .audit_models import AuditStatus
from .models import Record, _exact
from ._metric_validation import metric_matches
from ._market_execution import (
    market_limits, blocked_order, validate_market_prices, strict_market_number,
    market_timestamp, market_session, expected_market_fill,
)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


@dataclass(frozen=True)
class ReplayEvidence(Record):
    strategy_hash: str
    data_hash: str
    initial_cash: float
    evaluation_sessions: tuple[str, ...]
    execution_spec: Mapping[str, Any]
    decisions: tuple[Mapping[str, Any], ...]
    orders: tuple[Mapping[str, Any], ...]
    fills: tuple[Mapping[str, Any], ...]
    account_daily: tuple[Mapping[str, Any], ...]
    trades: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]
    execution_daily: tuple[Mapping[str, Any], ...]
    execution_intraday: tuple[Mapping[str, Any], ...]
    content_hash: str = ""

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ReplayEvidence:
        _exact(data, set(cls.__dataclass_fields__))
        sequence_fields = {
            "evaluation_sessions", "decisions", "orders", "fills", "account_daily",
            "trades", "execution_daily", "execution_intraday",
        }
        return cls(**{key: tuple(value) if key in sequence_fields else value for key, value in data.items()})

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})


@dataclass(frozen=True)
class ReplayAuditResult(Record):
    status: AuditStatus
    evidence_hash: str
    checks: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()


def hash_replay_evidence(evidence: ReplayEvidence) -> str:
    payload = evidence.to_dict()
    payload.pop("content_hash")
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _floor(price: float, tick: float) -> float:
    return float(
        (Decimal(str(price)) / Decimal(str(tick))).to_integral_value(rounding=ROUND_FLOOR)
        * Decimal(str(tick))
    )


def _nearest(price: float, tick: float) -> float:
    return float(
        (Decimal(str(price)) / Decimal(str(tick))).to_integral_value(rounding=ROUND_HALF_UP)
        * Decimal(str(tick))
    )


def _ceil(price: float, tick: float) -> float:
    return float(
        (Decimal(str(price)) / Decimal(str(tick))).to_integral_value(rounding=ROUND_CEILING)
        * Decimal(str(tick))
    )


def _session_index(values: tuple[str, ...] | list[str], field_name: str) -> pd.DatetimeIndex:
    parsed = pd.to_datetime(list(values), errors="coerce")
    if parsed.isna().any():
        raise ValueError(f"{field_name} contains invalid sessions")
    return pd.DatetimeIndex(parsed).normalize()


def _audit_session_coverage(
    evidence: ReplayEvidence,
    reasons: list[str],
    checks: list[str],
    *,
    sparse_decisions: bool,
) -> None:
    try:
        expected = _session_index(evidence.evaluation_sessions, "evaluation_sessions")
    except ValueError:
        reasons.append("INVALID_EVALUATION_SESSIONS")
        checks.append("EVALUATION_SESSION_COVERAGE")
        return
    if expected.empty or expected.has_duplicates or not expected.is_monotonic_increasing:
        reasons.append("INVALID_EVALUATION_SESSIONS")
    try:
        accounts = _session_index(
            [str(row.get("date", ""))[:10] for row in evidence.account_daily],
            "account_daily",
        )
    except ValueError:
        accounts = pd.DatetimeIndex([])
        reasons.append("INVALID_ACCOUNT_INDEX")
    if not accounts.equals(expected):
        reasons.append("INCOMPLETE_ACCOUNT_SESSION_COVERAGE")
    try:
        execution = _session_index(
            [str(row.get("date", ""))[:10] for row in evidence.execution_daily],
            "execution_daily",
        )
    except ValueError:
        execution = pd.DatetimeIndex([])
        reasons.append("MISSING_EXECUTION_PRICE")
    halted = pd.DatetimeIndex(pd.to_datetime((evidence.execution_spec.get("market_rules") or {}).get("suspended_sessions", [])))
    expected_trading = expected.difference(halted)
    if not expected_trading.difference(execution).empty:
        reasons.append("INCOMPLETE_EXECUTION_SESSION_COVERAGE")
    if not sparse_decisions and evidence.execution_spec.get("decision_coverage") == "COMPLETE":
        try:
            decisions = _session_index(
                [str(row.get("valid_session", ""))[:10] for row in evidence.decisions],
                "decisions",
            )
        except ValueError:
            decisions = pd.DatetimeIndex([])
            reasons.append("INVALID_DECISION_SESSION")
        if not decisions.equals(expected_trading):
            reasons.append("INCOMPLETE_DECISION_SESSION_COVERAGE")
    checks.append("EVALUATION_SESSION_COVERAGE")


def _audit_intraday_overlay(
    evidence: ReplayEvidence,
    digest: str,
    tolerance: float,
) -> ReplayAuditResult:
    """Independently audit a sellable-core intraday rotation replay."""
    reasons: list[str] = []
    checks: list[str] = []
    _audit_session_coverage(evidence, reasons, checks, sparse_decisions=True)
    spec = evidence.execution_spec
    fee_rate = float(spec["fee_rate"])
    lot_size = int(spec["lot_size"])
    core_fraction = float(spec["core_fraction"])
    limits = market_limits(spec.get("market_rules"), evidence.evaluation_sessions)
    bars_by_time = {str(row["time"])[0:16]: row for row in evidence.execution_intraday}
    daily_by_date = {str(row["date"])[:10]: row for row in evidence.execution_daily}
    accounts_by_date = {str(row["date"])[:10]: row for row in evidence.account_daily}
    verified_rejected_buys: set[str] = set()
    if limits:
        try:
            for bar in evidence.execution_intraday:
                stamp = market_timestamp(bar["time"])
                if stamp.minute % 5 or stamp.second or stamp.microsecond:
                    raise ValueError("overlay requires exact 5m timestamps")
                for field in ("open", "high", "low", "close"):
                    strict_market_number(bar[field], positive=True)
                if not bar["low"] <= min(bar["open"], bar["close"]) <= max(bar["open"], bar["close"]) <= bar["high"]:
                    raise ValueError("invalid overlay 5m OHLC")
            for session in evidence.evaluation_sessions:
                day = str(session)[:10]
                for clock in ("09:35", "11:30"):
                    checkpoint = [bar for bar in evidence.execution_intraday if str(bar["time"])[:16] == f"{day}T{clock}"]
                    if len(checkpoint) != 1:
                        raise ValueError("missing or duplicate overlay checkpoint")
                opening = float(bars_by_time[f"{day}T09:35"]["open"])
                daily_open = float(daily_by_date[day]["open"])
                if abs(opening - daily_open) > max(abs(opening), abs(daily_open)) * 1e-12:
                    raise ValueError("overlay 5m opening price differs from daily open")
        except (ValueError, TypeError, KeyError):
            reasons.append("INVALID_INTRADAY_MARKET_PRICES")

    def rejection_reason(order):
        """Independent checkpoint proof; never import the executor fill engine."""
        day = str(order["execution_date"])[:10]
        checkpoint = str(order.get("checkpoint"))
        key = f"{day}T09:35" if checkpoint == "OPEN" else f"{day}T11:30"
        bar = bars_by_time[key]
        price = float(bar["open"] if checkpoint == "OPEN" else bar["close"])
        side = str(order["side"])
        kind = str(order["order_type"])
        bound = limits[day]
        limit = float(order["limit_price"])
        if blocked_order(side, price, bound, order_type=kind, limit_price=limit):
            return "ORDER_PRICE_OUTSIDE_LIMITS"
        if side == "BUY" and abs(price - bound[1]) <= abs(bound[1]) * 1e-10:
            return "OPEN_UP_LIMIT_BUY_BLOCKED"
        if side == "SELL" and abs(price - bound[0]) <= abs(bound[0]) * 1e-10:
            return "OPEN_DOWN_LIMIT_SELL_BLOCKED"
        if kind == "LIMIT" and (price > limit if side == "BUY" else price < limit):
            return "LIMIT_NOT_CROSSED"
        account = accounts_by_date[day]
        if side == "BUY" and int(order["quantity"]) * price * (1 + fee_rate) > float(account["cash_before"]) + 1e-8:
            return "INSUFFICIENT_CASH"
        if side == "SELL" and int(order["quantity"]) > int(account["quantity_before"]):
            return "INSUFFICIENT_SELLABLE_POSITION"
        return None
    if (
        not 0 < core_fraction < 1
        or str(spec.get("entry_checkpoint")) != "OPEN"
        or str(spec.get("exit_checkpoint")) != "11:30_CLOSE"
        or spec.get("t_plus_one_inventory_rotation") is not True
    ):
        reasons.append("INVALID_INTRADAY_OVERLAY_SPEC")
    if any(
        len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())
        for value in (evidence.strategy_hash, evidence.data_hash)
    ):
        reasons.append("INVALID_EVIDENCE_IDENTITY")

    decisions = {str(row["decision_id"]): row for row in evidence.decisions}
    if len(decisions) != len(evidence.decisions):
        reasons.append("DUPLICATE_DECISION_ID")
    orders_by_decision: dict[str, list[Mapping[str, Any]]] = {}
    fills_by_order: dict[str, Mapping[str, Any]] = {}
    for fill in evidence.fills:
        order_id = str(fill["order_id"])
        if order_id in fills_by_order:
            reasons.append("DUPLICATE_ORDER_FILL")
        fills_by_order[order_id] = fill
    order_ids: set[str] = set()
    for order in evidence.orders:
        order_id = str(order["order_id"])
        if order_id in order_ids:
            reasons.append("DUPLICATE_ORDER_ID")
        order_ids.add(order_id)
        decision_id = str(order["decision_id"])
        orders_by_decision.setdefault(decision_id, []).append(order)
        decision = decisions.get(decision_id)
        if (
            decision is None
            or str(decision["valid_session"])[:10] != str(order["execution_date"])[:10]
            or str(decision["signal_date"])[:10] >= str(order["execution_date"])[:10]
        ):
            reasons.append("ORDER_DECISION_MISMATCH")
        quantity = int(order["quantity"])
        if str(order["side"]) not in {"BUY", "SELL"}:
            reasons.append("INVALID_ORDER_SIDE")
        if quantity <= 0 or quantity % lot_size:
            reasons.append("INVALID_ORDER_LOT")
        if str(order["status"]) != "FILLED" or order_id not in fills_by_order:
            rejected = False
            if (limits and str(order["status"]) == "UNFILLED" and order_id not in fills_by_order
                    and str(order["side"]) == "BUY" and decision is not None
                    and str(decision.get("plan_mode")) == "CORE_EVENT_INTRADAY_ROTATION"):
                try:
                    expected_rejection = rejection_reason(order)
                    rejected = expected_rejection is not None and order.get("reason") == expected_rejection
                except (KeyError, TypeError, ValueError):
                    rejected = False
            if rejected:
                verified_rejected_buys.add(order_id)
            else:
                reasons.append("INTRADAY_ORDER_NOT_FILLED")
    for decision_id, decision in decisions.items():
        linked = orders_by_decision.get(decision_id, [])
        sides = [str(item["side"]) for item in linked]
        checkpoints = [str(item.get("checkpoint")) for item in linked]
        quantities = [int(item["quantity"]) for item in linked]
        plan_mode = str(decision.get("plan_mode"))
        if plan_mode == "CORE_SETUP":
            valid = (
                sides == ["BUY"]
                and checkpoints == ["OPEN"]
                and str(linked[0].get("role")) == "CORE_SETUP"
            )
        else:
            valid = (
                plan_mode == "CORE_EVENT_INTRADAY_ROTATION"
                and sides == ["BUY", "SELL"]
                and checkpoints == ["OPEN", "11:30_CLOSE"]
                and len(set(quantities)) == 1
                and str(decision.get("action")) == "INTRADAY_LONG_OVERLAY"
            )
            if (limits and len(linked) == 1 and str(linked[0]["order_id"]) in verified_rejected_buys
                    and plan_mode == "CORE_EVENT_INTRADAY_ROTATION"
                    and sides == ["BUY"] and checkpoints == ["OPEN"]
                    and str(decision.get("action")) == "INTRADAY_LONG_OVERLAY"):
                valid = True
            if verified_rejected_buys.intersection(str(item["order_id"]) for item in linked) and len(linked) != 1:
                valid = False
        if not valid:
            reasons.append("INVALID_INTRADAY_ORDER_PAIR")
    core_decisions = [
        decision_id
        for decision_id, decision in decisions.items()
        if str(decision.get("plan_mode")) == "CORE_SETUP"
    ]
    first_session = str(evidence.evaluation_sessions[0]) if evidence.evaluation_sessions else ""
    if (
        len(core_decisions) != 1
        or str(decisions[core_decisions[0]].get("valid_session"))[:10] != first_session
    ):
        reasons.append("INVALID_CORE_SETUP_COVERAGE")
    checks.append("INTRADAY_ORDER_CONTRACT")

    for order in evidence.orders:
        fill = fills_by_order.get(str(order["order_id"]))
        day = str(order["execution_date"])[:10]
        side = str(order["side"])
        checkpoint = str(order.get("checkpoint"))
        key = f"{day}T09:35" if checkpoint == "OPEN" else f"{day}T11:30"
        bar = bars_by_time.get(key)
        if bar is None:
            reasons.append("MISSING_INTRADAY_CHECKPOINT")
            continue
        expected_price = float(bar["open"] if checkpoint == "OPEN" else bar["close"])
        quantity = int(order["quantity"])
        signal = daily_by_date.get(str(order["signal_date"])[:10])
        if signal is None:
            reasons.append("MISSING_EXECUTION_PRICE")
            continue
        srt_plan = str(spec.get("order_semantics")) == "SRT_PLAN"
        expected_order_type = "LIMIT" if side == "BUY" else "MARKET"
        type_matches = (
            str(order.get("order_type")) == expected_order_type if srt_plan else True
        )
        if srt_plan and side == "BUY":
            expected_limit = _floor(float(signal["close"]) * 1.10, 0.001)
            limit_matches = abs(float(order["limit_price"]) - expected_limit) <= tolerance
        elif srt_plan:
            limit_matches = True
        else:
            limit_matches = abs(float(order["limit_price"]) - expected_price) <= tolerance
        if not type_matches or not limit_matches:
            reasons.append("INTRADAY_FILL_MISMATCH")
        if limits and side == "BUY":
            account = accounts_by_date.get(day)
            if account is None:
                reasons.append("INTRADAY_ACCOUNT_LEDGER_MISMATCH")
            elif str(decisions.get(str(order["decision_id"]), {}).get("plan_mode")) == "CORE_EVENT_INTRADAY_ROTATION":
                unit = Decimal(str(order["limit_price"])) * (1 + Decimal(str(fee_rate)))
                affordable = int(Decimal(str(account["cash_before"])) / (unit * lot_size)) * lot_size
                if quantity != min(int(account["quantity_before"]), affordable):
                    reasons.append("INVALID_INTRADAY_EVENT_QUANTITY")
        if fill is None:
            continue
        if limits:
            try:
                if rejection_reason(order) is not None:
                    reasons.append("INTRADAY_MARKET_FILL_BLOCKED")
                expected_time = f"{day}T09:30:00" if checkpoint == "OPEN" else f"{day}T11:30:00"
                if datetime.fromisoformat(str(fill["fill_time"])) != datetime.fromisoformat(expected_time):
                    reasons.append("INTRADAY_FILL_MISMATCH")
            except (KeyError, TypeError, ValueError):
                reasons.append("INVALID_INTRADAY_MARKET_PRICES")
        if (
            str(fill["side"]) != side
            or int(fill["quantity"]) != quantity
            or not type_matches
            or abs(float(fill["price"]) - expected_price) > tolerance
            or not limit_matches
            or abs(float(fill["fees"]) - quantity * expected_price * fee_rate) > tolerance
        ):
            reasons.append("INTRADAY_FILL_MISMATCH")
        decision = decisions.get(str(order["decision_id"]), {})
        if str(decision.get("plan_mode")) == "CORE_SETUP":
            expected_quantity = int(
                evidence.initial_cash
                * core_fraction
                / (float(order["limit_price"]) * (1 + fee_rate))
                // lot_size
                * lot_size
            )
            if quantity != expected_quantity:
                reasons.append("INVALID_CORE_SETUP_QUANTITY")
    checks.append("INTRADAY_CHECKPOINT_PRICES")

    account_rows = list(evidence.account_daily)
    if not account_rows:
        reasons.append("EMPTY_ACCOUNT_LEDGER")
    else:
        cash = evidence.initial_cash
        quantity = 0
        core_quantity: int | None = None
        fills_by_day: dict[str, list[Mapping[str, Any]]] = {}
        for fill in evidence.fills:
            fills_by_day.setdefault(str(fill["fill_time"])[:10], []).append(fill)
        previous_day = ""
        for row in account_rows:
            day = str(row["date"])[:10]
            if day <= previous_day:
                reasons.append("INVALID_ACCOUNT_INDEX")
            previous_day = day
            sellable_quantity = quantity
            if (
                abs(float(row["cash_before"]) - cash) > tolerance
                or int(row["quantity_before"]) != quantity
            ):
                reasons.append("ACCOUNT_OPENING_STATE_MISMATCH")
            for fill in sorted(fills_by_day.get(day, []), key=lambda item: str(item["fill_time"])):
                fill_quantity = int(fill["quantity"])
                gross = fill_quantity * float(fill["price"])
                fees = float(fill["fees"])
                if str(fill["side"]) == "BUY":
                    cash -= gross + fees
                    quantity += fill_quantity
                else:
                    if limits and fill_quantity > sellable_quantity:
                        reasons.append("T_PLUS_ONE_SELLABLE_CORE_EXCEEDED")
                    cash += gross - fees
                    quantity -= fill_quantity
                    sellable_quantity -= fill_quantity
                decision = decisions.get(str(fill["decision_id"]), {})
                if str(decision.get("plan_mode")) == "CORE_SETUP":
                    if core_quantity is not None or str(fill["side"]) != "BUY":
                        reasons.append("INVALID_CORE_SETUP_FILL")
                    core_quantity = fill_quantity
            expected_equity = cash + quantity * float(row["close"])
            if (
                abs(float(row["cash"]) - cash) > tolerance
                or int(row["quantity"]) != quantity
                or core_quantity is None
                or quantity != core_quantity
                or cash < -tolerance
                or abs(float(row["equity"]) - expected_equity) > tolerance
            ):
                reasons.append("INTRADAY_ACCOUNT_LEDGER_MISMATCH")
    checks.append("T_PLUS_ONE_CORE_ROTATION_LEDGER")

    cycles: dict[str, list[Mapping[str, Any]]] = {}
    for fill in evidence.fills:
        decision = decisions.get(str(fill["decision_id"]), {})
        if str(decision.get("plan_mode")) != "CORE_SETUP":
            cycles.setdefault(str(fill["cycle_id"]), []).append(fill)
    trades = {str(row["cycle_id"]): row for row in evidence.trades}
    if set(cycles) != set(trades):
        reasons.append("TRADE_PAIRING_MISMATCH")
    else:
        for cycle_id, cycle_fills in cycles.items():
            ordered = sorted(cycle_fills, key=lambda item: str(item["fill_time"]))
            if len(ordered) != 2 or [str(item["side"]) for item in ordered] != ["BUY", "SELL"]:
                reasons.append("TRADE_PAIRING_MISMATCH")
                continue
            buy, sell = ordered
            expected_return = float(sell["price"]) * (1 - fee_rate) / (
                float(buy["price"]) * (1 + fee_rate)
            ) - 1
            trade = trades[cycle_id]
            if (
                str(trade["status"]) != "CLOSED"
                or int(trade["quantity"]) != int(buy["quantity"])
                or int(buy["quantity"]) != int(sell["quantity"])
                or abs(float(trade["net_return"]) - expected_return) > tolerance
            ):
                reasons.append("TRADE_VALUE_MISMATCH")
    checks.append("INTRADAY_TRADE_PAIRING")

    if account_rows:
        equity = pd.Series([float(row["equity"]) for row in account_rows], dtype=float)
        total_return = float(equity.iloc[-1] / evidence.initial_cash - 1)
        max_drawdown = float(
            equity.div(equity.cummax().clip(lower=evidence.initial_cash)).sub(1).min()
        )
        annualized = float((equity.iloc[-1] / evidence.initial_cash) ** (252 / len(equity)) - 1)
        calmar = annualized / abs(max_drawdown) if abs(max_drawdown) > 1e-12 else None
        previous = equity.shift(1)
        previous.iloc[0] = evidence.initial_cash
        returns = equity.div(previous).sub(1)
        volatility = float(returns.std(ddof=1))
        sharpe = (
            float(np.sqrt(252) * returns.mean() / volatility)
            if np.isfinite(volatility) and volatility > 0 else None
        )
        closed_returns = [
            float(row["net_return"])
            for row in evidence.trades
            if str(row["status"]) == "CLOSED"
        ]
        wins = [value for value in closed_returns if value > 0]
        losses = [value for value in closed_returns if value < 0]
        ratio = (
            (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
            if wins and losses else None
        )
        ratio_status = (
            "NO_CLOSED_TRADES" if not closed_returns else
            "NO_WINS" if not wins else
            "NO_LOSSES" if not losses else
            "VALID"
        )
        expected_metrics = {
            "max_drawdown": max_drawdown,
            "calmar": calmar,
            "win_loss_ratio": ratio,
            "win_loss_ratio_status": ratio_status,
            "return": total_return,
            "sharpe": sharpe,
            "closed_trades": len(closed_returns),
            "win_rate": len(wins) / len(closed_returns) if closed_returns else None,
        }
        for name, expected in expected_metrics.items():
            actual = evidence.metrics.get(name)
            if name == "win_rate" and (
                name not in evidence.metrics or (actual is not None and (
                    isinstance(actual, bool) or not isinstance(actual, (int, float)) or not 0 <= actual <= 1
                ))
            ):
                reasons.append("METRIC_MISMATCH")
                continue
            if name not in evidence.metrics or not metric_matches(actual, expected, tolerance):
                reasons.append("METRIC_MISMATCH")
    checks.append("INTRADAY_METRICS")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return ReplayAuditResult(
        status=AuditStatus.PASS if not unique_reasons else AuditStatus.FAIL,
        evidence_hash=digest,
        checks=tuple(checks),
        reason_codes=unique_reasons,
    )


def audit_replay(evidence: ReplayEvidence, tolerance: float = 1e-7) -> ReplayAuditResult:
    """Independently recompute causal order, fill, and account invariants."""
    try:
        digest = hash_replay_evidence(evidence)
    except (TypeError, ValueError, OverflowError):
        return ReplayAuditResult(AuditStatus.FAIL, sha256(b"INVALID_EVIDENCE_ENCODING").hexdigest(),
                                 (), ("INVALID_EVIDENCE_ENCODING",))
    try:
        limits = market_limits(evidence.execution_spec.get("market_rules"), evidence.evaluation_sessions)
        validate_market_prices(evidence.execution_daily, limits, time_field="date")
        validate_market_prices(evidence.execution_intraday, limits, time_field="time")
        validate_market_prices(evidence.fills, limits, time_field="fill_time", fields=("price",))
        if limits and any(
            any(isinstance(fill.get(field), bool) or not isinstance(fill.get(field), (int, float))
                or not np.isfinite(fill[field]) or fill[field] < 0 for field in ("quantity", "price", "fees"))
            for fill in evidence.fills
        ):
            raise ValueError("invalid market fill values")
        if limits:
            evaluation_days = set(str(day)[:10] for day in evidence.evaluation_sessions)
            strict_market_number(evidence.initial_cash, positive=True)
            strict_market_number(evidence.execution_spec["fee_rate"])
            for order in evidence.orders:
                strict_market_number(order["quantity"], integer=True, positive=True)
                strict_market_number(order["limit_price"], positive=True)
                if market_session(order["execution_date"]) not in evaluation_days:
                    raise ValueError("order belongs to an unknown market session")
            for fill in evidence.fills:
                strict_market_number(fill["quantity"], integer=True, positive=True)
                timestamp = (datetime.fromisoformat(fill["fill_time"]) if fill.get("time_precision") == "SESSION"
                             else market_timestamp(fill["fill_time"]))
                if fill.get("time_precision") == "SESSION" and timestamp.time() != datetime.min.time():
                    raise ValueError("session-precision fill must not fabricate a clock time")
                if timestamp.date().isoformat() not in evaluation_days:
                    raise ValueError("fill belongs to an unknown market session")
            for account in evidence.account_daily:
                if (evidence.execution_spec["market_rules"]["suspension_information"] == "NOT_PROVIDED"
                        and account.get("trading_status") is not None):
                    raise ValueError("unprovided suspension information cannot assert a trading status")
                for field in ("quantity_before", "quantity"):
                    strict_market_number(account[field], integer=True)
                for field in ("cash_before", "cash", "close", "equity"):
                    strict_market_number(account[field], positive=field in {"close", "equity"})
            for trade in evidence.trades:
                strict_market_number(trade["quantity"], integer=True, positive=True)
            last_bar = None
            for bar in evidence.execution_intraday:
                timestamp = market_timestamp(bar["time"])
                if timestamp.date().isoformat() not in limits or last_bar is not None and timestamp <= last_bar:
                    raise ValueError("intraday observations require ordered known market sessions")
                for field in ("low", "high"):
                    strict_market_number(bar[field], positive=True)
                last_bar = timestamp
    except (TypeError, ValueError, KeyError):
        return ReplayAuditResult(AuditStatus.FAIL, digest, (), ("INVALID_MARKET_EXECUTION_RULES",))
    if evidence.execution_spec.get("mode") == "CORE_EVENT_INTRADAY_ROTATION":
        return _audit_intraday_overlay(evidence, digest, tolerance)
    reasons: list[str] = []
    checks: list[str] = []
    _audit_session_coverage(evidence, reasons, checks, sparse_decisions=False)
    spec = evidence.execution_spec
    try:
        limits = market_limits(spec.get("market_rules"), evidence.evaluation_sessions)
    except (TypeError, ValueError, KeyError):
        return ReplayAuditResult(AuditStatus.FAIL, digest, tuple(checks), ("INVALID_MARKET_EXECUTION_RULES",))
    instrument = spec["instrument"]
    fee_rate = float(spec["fee_rate"])
    lot_size = int(instrument["lot_size"])
    tick = float(instrument["price_tick"])
    price_limit_ratio = float(instrument["price_limit_ratio"])
    daily = {str(row["date"])[:10]: row for row in evidence.execution_daily}
    for row in daily.values():
        raw_close, scale = row.get("unadjusted_close"), row.get("price_scale")
        if (any(isinstance(x, bool) or not isinstance(x, (int, float))
                or not np.isfinite(x) or x <= 0 for x in (raw_close, scale))
            or abs(float(row["close"]) - raw_close * scale) > tolerance):
            return ReplayAuditResult(AuditStatus.FAIL, digest, tuple(checks),
                                     ("INVALID_EXECUTION_PRICE_SCALE",))
    rule_ticks = {row["session"]: float(row["price_tick"]) for row in (spec.get("market_rules") or {}).get("sessions", [])}
    halted = set((spec.get("market_rules") or {}).get("suspended_sessions", []))
    intraday_by_day: dict[str, list[Mapping[str, Any]]] = {}
    for row in evidence.execution_intraday:
        intraday_by_day.setdefault(str(row["time"])[:10], []).append(row)
    decisions = {str(row["decision_id"]): row for row in evidence.decisions}
    if len(decisions) != len(evidence.decisions):
        reasons.append("DUPLICATE_DECISION_ID")
    fills_by_order = {str(row["order_id"]): row for row in evidence.fills}
    accounts = {str(row["date"])[:10]: row for row in evidence.account_daily}
    if any(
        len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower())
        for value in (evidence.strategy_hash, evidence.data_hash)
    ):
        reasons.append("INVALID_EVIDENCE_IDENTITY")
    if len(fills_by_order) != len(evidence.fills):
        reasons.append("DUPLICATE_ORDER_FILL")
    order_ids: set[str] = set()
    for order in evidence.orders:
        order_id = str(order["order_id"])
        if order_id in order_ids:
            reasons.append("DUPLICATE_ORDER_ID")
            continue
        order_ids.add(order_id)
        decision = decisions.get(str(order["decision_id"]))
        if decision is None or str(decision["valid_session"])[:10] != str(order["execution_date"])[:10]:
            reasons.append("ORDER_DECISION_MISMATCH")
            continue
        quantity = int(order["quantity"])
        if quantity <= 0 or quantity % lot_size:
            reasons.append("INVALID_ORDER_LOT")
        signal = daily.get(str(order["signal_date"])[:10])
        execution = daily.get(str(order["execution_date"])[:10])
        if str(order["side"]) not in {"BUY", "SELL"}:
            reasons.append("INVALID_ORDER_SIDE")
        if str(order["execution_date"])[:10] in halted:
            reasons.append("SUSPENDED_SESSION_ORDER")
        if signal is None or execution is None:
            reasons.append("MISSING_EXECUTION_PRICE")
            continue
        if order["side"] == "BUY":
            expected_order_type = str(spec.get("entry_order_type", "LIMIT"))
            signal_close = float(signal["unadjusted_close"])
            expected_limit = min(
                _floor(signal_close * (1 + float(spec["entry_limit_parameter"])), tick),
                _nearest(_floor(signal_close * (1 + price_limit_ratio), tick) - tick, tick),
            )
        else:
            expected_order_type = str(spec.get("exit_order_type", "MARKET"))
            signal_close = float(signal["unadjusted_close"])
            if expected_order_type == "MARKET":
                expected_limit = _nearest(signal_close, tick)
            else:
                expected_limit = _nearest(
                    _ceil(
                        signal_close * (1 - float(spec["exit_limit_ratio"])), tick
                    )
                    + tick,
                    tick,
                )
        expected_limit *= float(signal["price_scale"])
        if str(order.get("order_type", "LIMIT")) != expected_order_type:
            reasons.append("ORDER_TYPE_MISMATCH")
        if abs(float(order["limit_price"]) - expected_limit) > tolerance:
            reasons.append("ORDER_LIMIT_MISMATCH")
        fill = fills_by_order.get(order_id)
        if str(order["status"]) not in {"FILLED", "UNFILLED"}:
            reasons.append("INVALID_ORDER_STATUS")
        try:
            blocked = blocked_order(str(order["side"]), float(execution["open"]),
                                    limits.get(str(order["execution_date"])[:10]),
                                    order_type=expected_order_type, limit_price=expected_limit)
        except ValueError:
            reasons.append("INVALID_MARKET_EXECUTION_PRICE")
            continue
        if blocked:
            if fill is not None or str(order["status"]) != "UNFILLED":
                reasons.append("MARKET_BLOCKED_ORDER_FILLED")
            continue
        if str(order["status"]) == "FILLED" and fill is None:
            reasons.append("FILLED_ORDER_WITHOUT_FILL")
            continue
        if str(order["status"]) == "UNFILLED" and fill is not None:
            reasons.append("UNFILLED_ORDER_HAS_FILL")
            continue
        if fill is None:
            if limits:
                expected_fill = expected_market_fill(str(order["side"]), expected_order_type, expected_limit,
                    float(execution["open"]), str(order["execution_date"])[:10],
                    intraday_by_day.get(str(order["execution_date"])[:10], []),
                    daily=execution, bounds=limits.get(str(order["execution_date"])[:10]),
                    price_tick=rule_ticks.get(str(order["execution_date"])[:10], tick))
                account = accounts.get(str(order["execution_date"])[:10])
                affordable = (str(order["side"]) == "SELL" or account is not None and expected_fill is not None
                    and quantity * expected_fill[1] * (1 + fee_rate) <= float(account["cash_before"]) + tolerance)
                if (affordable and order["side"] == "BUY" and expected_fill is not None
                        and spec.get("capital_mode") == "signal_cash_fraction"):
                    try:
                        cycle = json.loads(decision["entry_cycle_after"])
                        remaining = Decimal(cycle["cash_budget"]) - Decimal(cycle["buy_cost_including_fees"])
                        affordable = Decimal(quantity) * Decimal(str(expected_fill[1])) * (1 + Decimal(str(fee_rate))) <= remaining
                    except (ValueError, TypeError, KeyError, ArithmeticError):
                        affordable = False
                if expected_fill is not None and affordable:
                    reasons.append("MISSED_ELIGIBLE_FILL")
                continue
            if order["side"] == "SELL" and expected_order_type == "MARKET":
                reasons.append("MISSED_ELIGIBLE_FILL")
            elif order["side"] == "SELL":
                bars = intraday_by_day.get(str(order["execution_date"])[:10], [])
                eligible_price = (
                    float(execution["open"]) >= expected_limit - tolerance
                    or any(float(bar["high"]) > expected_limit for bar in bars)
                )
                if eligible_price:
                    reasons.append("MISSED_ELIGIBLE_FILL")
            else:
                bars = intraday_by_day.get(str(order["execution_date"])[:10], [])
                eligible_price = (
                    float(execution["open"]) <= expected_limit + tolerance
                    or any(float(bar["low"]) < expected_limit for bar in bars)
                )
                account = accounts.get(str(order["execution_date"])[:10])
                affordable = account is not None and (
                    quantity * expected_limit * (1 + fee_rate)
                    <= float(account["cash_before"]) + tolerance
                )
                if eligible_price and affordable:
                    reasons.append("MISSED_ELIGIBLE_FILL")
            continue
        if (int(fill["quantity"]) != quantity or str(fill["side"]) != str(order["side"])
                or str(fill["fill_time"])[:10] != str(order["execution_date"])[:10]
                or str(fill.get("decision_id")) != str(order["decision_id"])
                or str(fill.get("cycle_id")) != str(order.get("cycle_id"))):
            reasons.append("FILL_ORDER_MISMATCH")
        price = float(fill["price"])
        trigger = str(fill["trigger"])
        if limits:
            expected_fill = expected_market_fill(str(order["side"]), expected_order_type, expected_limit,
                float(execution["open"]), str(order["execution_date"])[:10],
                intraday_by_day.get(str(order["execution_date"])[:10], []),
                    daily=execution, bounds=limits.get(str(order["execution_date"])[:10]),
                    price_tick=rule_ticks.get(str(order["execution_date"])[:10], tick))
            if (expected_fill is None or trigger != expected_fill[0]
                    or abs(price - expected_fill[1]) > tolerance
                    or (datetime.fromisoformat(fill["fill_time"]) if trigger.startswith("DAILY_") else market_timestamp(fill["fill_time"])) != expected_fill[2]
                    or fill.get("time_precision", "TIMESTAMP") != ("SESSION" if trigger.startswith("DAILY_") else "TIMESTAMP")):
                reasons.append("INVALID_FILL_TRIGGER")
        if limits:
            eligible = expected_fill is not None
        elif expected_order_type == "MARKET":
            eligible = (
                trigger == "OPEN_MARKET"
                and abs(price - float(execution["open"])) <= tolerance
            )
        elif order["side"] == "SELL":
            bars = intraday_by_day.get(str(order["execution_date"])[:10], [])
            eligible = (
                trigger == "OPEN"
                and float(execution["open"]) >= expected_limit - tolerance
                and abs(price - float(execution["open"])) <= tolerance
            ) or (
                trigger == "INTRADAY_LIMIT"
                and any(float(bar["high"]) > expected_limit for bar in bars)
                and abs(price - expected_limit) <= tolerance
            )
        elif trigger == "OPEN":
            eligible = (
                float(execution["open"]) <= expected_limit + tolerance
                and abs(price - float(execution["open"])) <= tolerance
            )
        else:
            bars = intraday_by_day.get(str(order["execution_date"])[:10], [])
            eligible = trigger == "INTRADAY_LIMIT" and any(
                float(bar["low"]) < expected_limit for bar in bars
            ) and abs(price - expected_limit) <= tolerance
        if not eligible:
            reasons.append("INVALID_FILL_TRIGGER")
        if abs(float(fill["fees"]) - quantity * price * fee_rate) > tolerance:
            reasons.append("FEE_MISMATCH")
    if set(fills_by_order).difference(order_ids):
        reasons.append("FILL_WITHOUT_ORDER")
    checks.append("ORDER_AND_FILL_CAUSALITY")

    cash = float(evidence.initial_cash)
    quantity = 0
    fills_by_day: dict[str, list[Mapping[str, Any]]] = {}
    for fill in evidence.fills:
        fills_by_day.setdefault(str(fill["fill_time"])[:10], []).append(fill)
    previous_date = ""
    for row in evidence.account_daily:
        day = str(row["date"])[:10]
        if limits and day in daily and abs(float(row["close"]) - float(daily[day]["close"])) > tolerance:
            reasons.append("ACCOUNT_MARKET_CLOSE_MISMATCH")
        if day in halted:
            prior = sorted(item for item in daily if item < day)
            if (not prior or str(row.get("valuation_source_date", ""))[:10] != prior[-1]
                    or abs(float(row["close"]) - float(daily[prior[-1]]["close"])) > tolerance
                    or fills_by_day.get(day)):
                reasons.append("INVALID_SUSPENDED_VALUATION")
        if day <= previous_date:
            reasons.append("INVALID_ACCOUNT_INDEX")
        previous_date = day
        if abs(float(row["cash_before"]) - cash) > tolerance or int(row["quantity_before"]) != quantity:
            reasons.append("ACCOUNT_OPENING_STATE_MISMATCH")
        for fill in fills_by_day.get(day, []):
            gross = int(fill["quantity"]) * float(fill["price"])
            fee = float(fill["fees"])
            if fill["side"] == "BUY":
                cash -= gross + fee
                quantity += int(fill["quantity"])
            else:
                cash += gross - fee
                quantity -= int(fill["quantity"])
        expected_equity = cash + quantity * float(row["close"])
        if (
            abs(float(row["cash"]) - cash) > tolerance
            or int(row["quantity"]) != quantity
            or abs(float(row["equity"]) - expected_equity) > tolerance
            or cash < -tolerance
            or quantity < 0
        ):
            reasons.append("ACCOUNT_LEDGER_MISMATCH")
    checks.append("ACCOUNT_LEDGER")

    from ._entry_cycle_audit import audit_entry_cycles
    reasons.extend(audit_entry_cycles(evidence, tolerance))
    if spec.get("capital_mode") == "signal_cash_fraction":
        checks.append("ENTRY_CYCLE_ALLOCATION")

    expected_trades: dict[str, dict[str, Any]] = {}
    fills_by_cycle: dict[str, list[Mapping[str, Any]]] = {}
    for fill in evidence.fills:
        fills_by_cycle.setdefault(str(fill["cycle_id"]), []).append(fill)
    for cycle_id, cycle_fills in fills_by_cycle.items():
        buys = [item for item in cycle_fills if item["side"] == "BUY"]
        sells = [item for item in cycle_fills if item["side"] == "SELL"]
        buy_quantity = sum(int(item["quantity"]) for item in buys)
        sell_quantity = sum(int(item["quantity"]) for item in sells)
        buy_gross = sum(int(item["quantity"]) * float(item["price"]) for item in buys)
        sell_gross = sum(int(item["quantity"]) * float(item["price"]) for item in sells)
        buy_fees = sum(float(item["fees"]) for item in buys)
        sell_fees = sum(float(item["fees"]) for item in sells)
        closed = bool(buys and sell_quantity == buy_quantity)
        expected_trades[cycle_id] = {
            "status": "CLOSED" if closed else "OPEN",
            "quantity": buy_quantity,
            "entry_price": buy_gross / buy_quantity if buy_quantity else None,
            "exit_price": sell_gross / sell_quantity if closed else None,
            "net_return": (
                (sell_gross - sell_fees) / (buy_gross + buy_fees) - 1 if closed else None
            ),
        }
    actual_trades = {str(row["cycle_id"]): row for row in evidence.trades}
    if set(actual_trades) != set(expected_trades):
        reasons.append("TRADE_PAIRING_MISMATCH")
    else:
        for cycle_id, expected in expected_trades.items():
            actual = actual_trades[cycle_id]
            if (
                str(actual["status"]) != expected["status"]
                or int(actual["quantity"]) != expected["quantity"]
            ):
                reasons.append("TRADE_PAIRING_MISMATCH")
                continue
            for name in ("entry_price", "exit_price", "net_return"):
                expected_value = expected[name]
                actual_value = actual.get(name)
                if expected_value is None:
                    if actual_value is not None:
                        reasons.append("TRADE_VALUE_MISMATCH")
                elif actual_value is None or abs(float(actual_value) - float(expected_value)) > tolerance:
                    reasons.append("TRADE_VALUE_MISMATCH")
    checks.append("TRADE_PAIRING")

    equity_series = pd.Series(
        [float(row["equity"]) for row in evidence.account_daily], dtype=float
    )
    total_return = equity_series.iloc[-1] / evidence.initial_cash - 1
    max_drawdown = float(
        equity_series.div(equity_series.cummax().clip(lower=evidence.initial_cash)).sub(1).min()
    )
    annualized = float(
        (equity_series.iloc[-1] / evidence.initial_cash) ** (252 / len(equity_series)) - 1
    )
    calmar = annualized / abs(max_drawdown) if abs(max_drawdown) > 1e-12 else None
    previous = equity_series.shift(1)
    previous.iloc[0] = evidence.initial_cash
    returns = equity_series.div(previous).sub(1)
    volatility = float(returns.std(ddof=1))
    sharpe = (
        float(np.sqrt(252) * returns.mean() / volatility)
        if np.isfinite(volatility) and volatility > 0 else None
    )
    closed_returns = [
        float(item["net_return"])
        for item in expected_trades.values()
        if item["status"] == "CLOSED"
    ]
    wins = [value for value in closed_returns if value > 0]
    losses = [value for value in closed_returns if value < 0]
    if not closed_returns:
        ratio, ratio_status = None, "NO_CLOSED_TRADES"
    elif not wins:
        ratio, ratio_status = None, "NO_WINS"
    elif not losses:
        ratio, ratio_status = None, "NO_LOSSES"
    else:
        ratio = (sum(wins) / len(wins)) / abs(sum(losses) / len(losses))
        ratio_status = "VALID"
    expected_metrics = {
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "win_loss_ratio": ratio,
        "win_loss_ratio_status": ratio_status,
        "return": total_return,
        "sharpe": sharpe,
        "closed_trades": len(closed_returns),
        "win_rate": len(wins) / len(closed_returns) if closed_returns else None,
    }
    for name, expected in expected_metrics.items():
        actual = evidence.metrics.get(name)
        if name == "win_rate" and (
            name not in evidence.metrics or (actual is not None and (
                isinstance(actual, bool) or not isinstance(actual, (int, float)) or not 0 <= actual <= 1
            ))
        ):
            reasons.append("METRIC_MISMATCH")
            continue
        if name not in evidence.metrics or not metric_matches(actual, expected, tolerance):
            reasons.append("METRIC_MISMATCH")
    checks.append("METRICS")
    unique_reasons = tuple(dict.fromkeys(reasons))
    return ReplayAuditResult(
        AuditStatus.FAIL if unique_reasons else AuditStatus.PASS,
        digest,
        tuple(checks),
        unique_reasons,
    )
