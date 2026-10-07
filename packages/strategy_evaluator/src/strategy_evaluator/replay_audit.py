from __future__ import annotations

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
    if not expected.difference(execution).empty:
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
        if not decisions.equals(expected):
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
        if quantity <= 0 or quantity % lot_size:
            reasons.append("INVALID_ORDER_LOT")
        if str(order["status"]) != "FILLED" or order_id not in fills_by_order:
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

    bars_by_time = {str(row["time"])[0:16]: row for row in evidence.execution_intraday}
    daily_by_date = {str(row["date"])[:10]: row for row in evidence.execution_daily}
    for order in evidence.orders:
        fill = fills_by_order.get(str(order["order_id"]))
        if fill is None:
            continue
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
                    cash += gross - fees
                    quantity -= fill_quantity
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
    digest = hash_replay_evidence(evidence)
    if evidence.execution_spec.get("mode") == "CORE_EVENT_INTRADAY_ROTATION":
        return _audit_intraday_overlay(evidence, digest, tolerance)
    reasons: list[str] = []
    checks: list[str] = []
    _audit_session_coverage(evidence, reasons, checks, sparse_decisions=False)
    spec = evidence.execution_spec
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
        if signal is None or execution is None:
            reasons.append("MISSING_EXECUTION_PRICE")
            continue
        if order["side"] == "BUY":
            expected_order_type = str(spec.get("entry_order_type", "LIMIT"))
            signal_close = float(signal["unadjusted_close"])
            expected_limit = min(
                _floor(signal_close * (1 + float(spec["entry_limit_parameter"])), tick),
                _floor(signal_close * (1 + price_limit_ratio), tick) - tick,
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
        if str(order["status"]) == "FILLED" and fill is None:
            reasons.append("FILLED_ORDER_WITHOUT_FILL")
            continue
        if str(order["status"]) == "UNFILLED" and fill is not None:
            reasons.append("UNFILLED_ORDER_HAS_FILL")
            continue
        if fill is None:
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
        if int(fill["quantity"]) != quantity or str(fill["side"]) != str(order["side"]):
            reasons.append("FILL_ORDER_MISMATCH")
        price = float(fill["price"])
        trigger = str(fill["trigger"])
        if expected_order_type == "MARKET":
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
    checks.append("ORDER_AND_FILL_CAUSALITY")

    cash = float(evidence.initial_cash)
    quantity = 0
    fills_by_day: dict[str, list[Mapping[str, Any]]] = {}
    for fill in evidence.fills:
        fills_by_day.setdefault(str(fill["fill_time"])[:10], []).append(fill)
    previous_date = ""
    for row in evidence.account_daily:
        day = str(row["date"])[:10]
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
