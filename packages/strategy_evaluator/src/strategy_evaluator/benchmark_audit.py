from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .audit_models import AuditStatus
from .models import Record
from ._metric_validation import metric_matches


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        return _jsonable(value.item())
    return value


@dataclass(frozen=True)
class BenchmarkEvidence(Record):
    benchmark_type: str
    initial_cash: float
    fee_rate: float
    evaluation_sessions: tuple[str, ...]
    execution_prices: tuple[Mapping[str, Any], ...]
    signal_history: tuple[Mapping[str, Any], ...]
    account_daily: tuple[Mapping[str, Any], ...]
    orders: tuple[Mapping[str, Any], ...]
    trades: tuple[Mapping[str, Any], ...]
    metrics: Mapping[str, Any]
    lot_size: int

    def __post_init__(self) -> None:
        if type(self.lot_size) is not int:
            raise TypeError("lot_size must be an integer")
        if self.lot_size <= 0:
            raise ValueError("lot_size must be positive")

    def to_dict(self) -> dict[str, Any]:
        return _jsonable({name: getattr(self, name) for name in self.__dataclass_fields__})


@dataclass(frozen=True)
class BenchmarkAuditResult(Record):
    status: AuditStatus
    evidence_hash: str
    checks: tuple[str, ...]
    reason_codes: tuple[str, ...] = ()


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(float(value)) else None


def _metrics(equity: pd.Series, initial_cash: float, trades: pd.DataFrame) -> dict[str, Any]:
    total_return = float(equity.iloc[-1] / initial_cash - 1.0)
    drawdown = equity.div(equity.cummax().clip(lower=initial_cash)).sub(1.0)
    maximum = float(drawdown.min())
    annualized = float((equity.iloc[-1] / initial_cash) ** (252.0 / len(equity)) - 1.0)
    calmar = annualized / abs(maximum) if abs(maximum) > 1e-12 else None
    prior = equity.shift(1)
    prior.iloc[0] = initial_cash
    returns = equity.div(prior).sub(1.0)
    volatility = float(returns.std(ddof=1))
    sharpe = (
        float(np.sqrt(252.0) * returns.mean() / volatility)
        if np.isfinite(volatility) and volatility > 0.0
        else None
    )
    closed = (
        trades.loc[trades["status"].astype(str).eq("CLOSED")]
        if not trades.empty and "status" in trades
        else trades
    )
    values = pd.to_numeric(closed.get("net_return", pd.Series(dtype=float)), errors="coerce")
    wins = values.loc[values.gt(0.0)]
    losses = values.loc[values.lt(0.0)]
    if values.empty:
        ratio, status = None, "NO_CLOSED_TRADES"
    elif wins.empty:
        ratio, status = None, "NO_WINS"
    elif losses.empty:
        ratio, status = None, "NO_LOSSES"
    else:
        ratio, status = float(wins.mean() / abs(losses.mean())), "VALID"
    return {
        "return": _finite_or_none(total_return),
        "max_drawdown": _finite_or_none(maximum),
        "calmar": _finite_or_none(calmar) if calmar is not None else None,
        "sharpe": _finite_or_none(sharpe) if sharpe is not None else None,
        "win_loss_ratio": ratio,
        "win_loss_ratio_status": status,
        "closed_trades": int(len(closed)),
        "win_rate": float(len(wins) / len(closed)) if len(closed) else None,
    }


def audit_benchmark_replay(
    evidence: BenchmarkEvidence,
    tolerance: float = 1e-7,
) -> BenchmarkAuditResult:
    """Independently verify benchmark definition, sessions, ledger, and metrics."""

    encoded = json.dumps(
        evidence.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    reasons: list[str] = []
    checks: list[str] = []
    sessions = pd.DatetimeIndex(pd.to_datetime(evidence.evaluation_sessions, errors="coerce"))
    if sessions.isna().any() or sessions.empty or sessions.has_duplicates:
        reasons.append("INVALID_BENCHMARK_SESSIONS")
    prices = pd.DataFrame(evidence.execution_prices)
    accounts = pd.DataFrame(evidence.account_daily)
    if prices.empty or accounts.empty:
        reasons.append("EMPTY_BENCHMARK_LEDGER")
        return BenchmarkAuditResult(AuditStatus.FAIL, digest, ("BENCHMARK_SESSIONS",), tuple(reasons))
    prices["date"] = pd.to_datetime(prices["date"], errors="coerce").dt.normalize()
    accounts["date"] = pd.to_datetime(accounts["date"], errors="coerce").dt.normalize()
    if not pd.DatetimeIndex(prices["date"]).equals(sessions):
        reasons.append("INCOMPLETE_BENCHMARK_PRICE_COVERAGE")
    if not pd.DatetimeIndex(accounts["date"]).equals(sessions):
        reasons.append("INCOMPLETE_BENCHMARK_ACCOUNT_COVERAGE")
    checks.append("BENCHMARK_SESSIONS")
    if reasons:
        return BenchmarkAuditResult(
            AuditStatus.FAIL,
            digest,
            tuple(checks),
            tuple(dict.fromkeys(reasons)),
        )

    target = pd.to_numeric(accounts["target_position"], errors="coerce")
    if target.isna().any() or not target.between(0.0, 1.0).all():
        reasons.append("INVALID_BENCHMARK_TARGET")
    if evidence.benchmark_type == "BUYHOLD":
        if not target.eq(1.0).all():
            reasons.append("BUYHOLD_DEFINITION_MISMATCH")
    elif evidence.benchmark_type == "MA5_MA20":
        signals = pd.DataFrame(evidence.signal_history)
        if signals.empty:
            reasons.append("EMPTY_BENCHMARK_SIGNAL_HISTORY")
        else:
            signals["date"] = pd.to_datetime(signals["date"], errors="coerce").dt.normalize()
            signals = signals.set_index("date").sort_index()
            close = pd.to_numeric(signals["close"], errors="coerce")
            expected = close.rolling(5, min_periods=5).mean().gt(
                close.rolling(20, min_periods=20).mean()
            ).astype(float)
            prior = signals.index[signals.index < sessions[0]]
            if prior.empty:
                reasons.append("MISSING_BENCHMARK_PRIOR_SIGNAL")
            else:
                expected_execution = expected.reindex(sessions).shift(1)
                expected_execution.iloc[0] = expected.loc[prior[-1]]
                if not np.allclose(
                    target.to_numpy(dtype=float),
                    expected_execution.to_numpy(dtype=float),
                    rtol=0.0,
                    atol=tolerance,
                ):
                    reasons.append("MA_DEFINITION_MISMATCH")
    else:
        reasons.append("UNKNOWN_BENCHMARK_TYPE")
    checks.append("BENCHMARK_DEFINITION")

    cash = float(evidence.initial_cash)
    shares = 0.0
    previous_target = 0.0
    equity_values: list[float] = []
    cash_values: list[float] = []
    quantity_values: list[float] = []
    expected_orders: list[dict[str, Any]] = []
    for desired, (_, price) in zip(target, prices.iterrows(), strict=True):
        open_price = float(price["open"])
        close_price = float(price["close"])
        if float(desired) != previous_target:
            portfolio_value = cash + shares * open_price
            delta = float(desired) * portfolio_value - shares * open_price
            if delta > 0.0:
                bought = min(delta / open_price, cash / (open_price * (1.0 + evidence.fee_rate)))
                bought = float(int(bought // evidence.lot_size) * evidence.lot_size)
                cash -= bought * open_price * (1.0 + evidence.fee_rate)
                shares += bought
                if bought > 0:
                    expected_orders.append(
                        {
                            "execution_date": price["date"],
                            "side": "Buy",
                            "size": bought,
                            "price": open_price,
                            "fees": bought * open_price * evidence.fee_rate,
                        }
                    )
            elif delta < 0:
                sold = min(-delta / open_price, shares)
                if desired > 0:
                    sold = float(int(sold // evidence.lot_size) * evidence.lot_size)
                cash += sold * open_price * (1.0 - evidence.fee_rate)
                shares -= sold
                if sold > 0:
                    expected_orders.append(
                        {
                            "execution_date": price["date"],
                            "side": "Sell",
                            "size": sold,
                            "price": open_price,
                            "fees": sold * open_price * evidence.fee_rate,
                        }
                    )
            previous_target = float(desired)
        equity_values.append(cash + shares * close_price)
        cash_values.append(cash)
        quantity_values.append(shares)
    for name, expected in (("cash", cash_values), ("quantity", quantity_values)):
        actual = pd.to_numeric(accounts.get(name, pd.Series(dtype=float)), errors="coerce")
        if len(actual) != len(expected) or not np.isfinite(actual).all() or not np.allclose(
            actual.to_numpy(), expected, rtol=0, atol=tolerance,
        ):
            reasons.append("BENCHMARK_LEDGER_MISMATCH")
    expected_equity = pd.Series(equity_values, index=sessions, dtype=float)
    actual_equity = pd.to_numeric(accounts["equity"], errors="coerce")
    if actual_equity.isna().any() or not np.allclose(
        actual_equity.to_numpy(dtype=float),
        expected_equity.to_numpy(dtype=float),
        rtol=1e-8,
        atol=1e-6,
    ):
        reasons.append("BENCHMARK_LEDGER_MISMATCH")
    checks.append("BENCHMARK_LEDGER")

    orders = pd.DataFrame(evidence.orders)
    if len(orders) != len(expected_orders):
        reasons.append("BENCHMARK_ORDER_MISMATCH")
    else:
        for actual, expected_order in zip(
            orders.to_dict(orient="records"), expected_orders, strict=True
        ):
            if (
                pd.Timestamp(actual["execution_date"]).normalize()
                != pd.Timestamp(expected_order["execution_date"]).normalize()
                or str(actual["side"]).lower() != str(expected_order["side"]).lower()
                or abs(float(actual["size"]) - float(expected_order["size"])) > tolerance
                or abs(float(actual["price"]) - float(expected_order["price"])) > tolerance
                or abs(float(actual["fees"]) - float(expected_order["fees"])) > tolerance
            ):
                reasons.append("BENCHMARK_ORDER_MISMATCH")
                break
    checks.append("BENCHMARK_ORDERS")

    closed_returns: list[float] = []
    pending: Mapping[str, Any] | None = None
    for order in orders.to_dict(orient="records"):
        side = str(order.get("side", "")).lower()
        if side == "buy":
            if pending is not None:
                reasons.append("BENCHMARK_TRADE_PAIRING_MISMATCH")
                break
            pending = order
        elif side == "sell" and pending is not None:
            cost = float(pending["size"]) * float(pending["price"]) + float(pending["fees"])
            proceeds = float(order["size"]) * float(order["price"]) - float(order["fees"])
            if abs(float(order["size"]) - float(pending["size"])) > tolerance:
                reasons.append("BENCHMARK_TRADE_PAIRING_MISMATCH")
                break
            closed_returns.append(proceeds / cost - 1.0)
            pending = None
        else:
            reasons.append("BENCHMARK_TRADE_PAIRING_MISMATCH")
            break
    trades = pd.DataFrame(evidence.trades)
    actual_returns = pd.to_numeric(
        trades.get("net_return", pd.Series(dtype=float)), errors="coerce"
    ).tolist()
    if len(actual_returns) != len(closed_returns) or any(
        abs(float(actual) - expected) > tolerance
        for actual, expected in zip(actual_returns, closed_returns, strict=True)
    ):
        reasons.append("BENCHMARK_TRADE_PAIRING_MISMATCH")
    checks.append("BENCHMARK_TRADE_PAIRING")

    audited_trades = pd.DataFrame(
        {"status": ["CLOSED"] * len(closed_returns), "net_return": closed_returns}
    )
    expected_metrics = _metrics(
        expected_equity, float(evidence.initial_cash), audited_trades
    )
    for name, expected_value in expected_metrics.items():
        actual = evidence.metrics.get(name)
        if name == "win_rate" and (
            name not in evidence.metrics or (actual is not None and (
                isinstance(actual, bool) or not isinstance(actual, (int, float)) or not 0 <= actual <= 1
            ))
        ):
            reasons.append("BENCHMARK_METRIC_MISMATCH")
            continue
        if name not in evidence.metrics or not metric_matches(actual, expected_value, tolerance):
            reasons.append("BENCHMARK_METRIC_MISMATCH")
    checks.append("BENCHMARK_METRICS")
    unique = tuple(dict.fromkeys(reasons))
    return BenchmarkAuditResult(
        AuditStatus.PASS if not unique else AuditStatus.FAIL,
        digest,
        tuple(checks),
        unique,
    )
