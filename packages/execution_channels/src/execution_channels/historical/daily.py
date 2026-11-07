from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .fills import OrderSpec, resolve_fill, DailyQuote
from .market import MarketExecutionRules


@dataclass(frozen=True)
class DailyExecutionResult:
    equity: pd.Series
    orders: pd.DataFrame
    state: pd.DataFrame
    attempts: pd.DataFrame = field(default_factory=pd.DataFrame)


def execute_target_positions(
    prices: pd.DataFrame,
    execution_target: pd.Series,
    *,
    fee_rate: float,
    initial_cash: float,
    slippage_bp: float = 0.0,
    lot_size: int | None = None,
    market_rules: MarketExecutionRules | None = None,
) -> DailyExecutionResult:
    """Execute long-only target fractions at each session open.

    The caller decides when a signal becomes executable and passes the already
    shifted ``execution_target``.  TXE owns fills, fees, cash and equity.
    """

    # Copy values once, without deep-copying attached evidence metadata.
    frame = pd.DataFrame(prices, copy=True)
    if "dt" in frame.columns:
        frame = frame.set_index("dt")
    frame.index = pd.DatetimeIndex(pd.to_datetime(frame.index), name="dt")
    frame = frame.sort_index()
    if not {"open", "close"} <= set(frame.columns):
        raise ValueError("prices require open and close columns")
    try:
        price_values = frame[["open", "close"]].to_numpy(dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("prices must be positive and finite") from exc
    halted_mask = pd.Series(False, index=frame.index) if market_rules is None else pd.Series(frame.index.isin(pd.to_datetime(market_rules.suspended_sessions)), index=frame.index)
    price_values = frame.loc[~halted_mask, ["open", "close"]].to_numpy(dtype=float)
    if not np.isfinite(price_values).all() or (price_values <= 0).any():
        raise ValueError("prices must be positive and finite")
    if market_rules is not None:
        if not isinstance(market_rules, MarketExecutionRules):
            raise TypeError("market_rules must be MarketExecutionRules")
        if frame.index.hasnans or frame.index.has_duplicates or frame.index.tz is not None:
            raise ValueError("market prices require unique local session dates")
        for timestamp, row in frame.iterrows():
            if timestamp != timestamp.normalize():
                raise ValueError("market prices require session dates")
            if timestamp.date() in market_rules.suspended_sessions:
                continue
            limits = market_rules.for_session(timestamp.date())
            for column in ("open", "high", "low", "close"):
                if column in row and (
                    not np.isfinite(float(row[column])) or not limits.contains(float(row[column]))
                ):
                    raise ValueError("market prices are outside session price limits")
            if "high" in row and "low" in row and not (
                float(row["low"]) <= min(float(row["open"]), float(row["close"]))
                <= max(float(row["open"]), float(row["close"])) <= float(row["high"])
            ):
                raise ValueError("market OHLC prices are inconsistent")
    target = pd.Series(execution_target, copy=True).astype(float)
    target.index = pd.DatetimeIndex(pd.to_datetime(target.index), name="dt")
    target = target.reindex(frame.index)
    if target.isna().any() or not np.isfinite(target).all() or not target.between(0, 1).all():
        raise ValueError("execution_target must contain finite values in [0, 1]")
    if not np.isfinite(float(fee_rate)) or not 0 <= float(fee_rate) < 1:
        raise ValueError("fee_rate must be finite and in [0, 1)")
    if not np.isfinite(float(initial_cash)) or initial_cash <= 0:
        raise ValueError("initial_cash must be positive and finite")
    if not np.isfinite(float(slippage_bp)) or not 0 <= slippage_bp < 10_000:
        raise ValueError("slippage_bp must be finite and in [0, 10000)")
    if lot_size is not None:
        if type(lot_size) is not int:
            raise TypeError("lot_size must be an integer")
        if lot_size <= 0:
            raise ValueError("lot_size must be positive")

    cash = float(initial_cash)
    shares = 0.0
    previous_target = 0.0
    slippage = float(slippage_bp) / 10_000.0
    equity_rows: list[float] = []
    order_rows: list[dict[str, object]] = []
    attempt_rows: list[dict[str, object]] = []
    state_rows: list[dict[str, object]] = []
    for position, (timestamp, opened, closed) in enumerate(zip(
        frame.index, frame["open"].array, frame["close"].array
    )):
        desired = float(target.loc[timestamp])
        if market_rules is not None and timestamp.date() in market_rules.suspended_sessions:
            close_price = float(closed)
            if not np.isfinite(close_price) or close_price <= 0:
                raise ValueError("suspended session requires a valid valuation close")
            equity_rows.append(cash + shares * close_price)
            state_rows.append({"date": timestamp, "target": float(target.loc[timestamp]), "cash": cash, "quantity": shares, "close": close_price, "equity": cash + shares * close_price})
            continue
        open_price = float(opened)
        close_price = float(closed)
        if desired != previous_target:
            completed = True
            portfolio_value = cash + shares * open_price
            delta_value = desired * portfolio_value - shares * open_price
            if delta_value > 0:
                price = open_price * (1.0 + slippage)
                if not np.isfinite(price) or price <= 0:
                    raise ValueError("fill price must be positive and finite")
                requested = delta_value / price
                affordable = cash / (price * (1.0 + fee_rate))
                quantity = min(requested, affordable)
                if lot_size is not None:
                    quantity = float(int(quantity // lot_size) * lot_size)
                if quantity > 0:
                    fill = resolve_fill(
                        OrderSpec("BUY", "MARKET", quantity), session_open=open_price,
                        session_time=(timestamp + pd.Timedelta(hours=9, minutes=30)).to_pydatetime(),
                        intraday_touches=(), slippage_bp=slippage_bp,
                        session_limits=None if market_rules is None else market_rules.for_session(timestamp.date()),
                        daily_quote=None if market_rules is None else DailyQuote(float(frame["low"].iat[position]), float(frame["high"].iat[position])),
                    )
                    attempt_rows.append({"execution_date": timestamp, "side": "BUY", "quantity": quantity,
                                         "status": "FILLED" if fill.filled else "UNFILLED", "reason": fill.reason})
                    completed = fill.filled
                    if fill.filled:
                        price = float(fill.price)
                        fees = quantity * price * fee_rate
                        cash -= quantity * price + fees
                        shares += quantity
                        order_rows.append(
                            {"execution_date": timestamp, "side": "BUY", "quantity": quantity,
                             "price": price, "fees": fees}
                        )
            elif delta_value < 0:
                price = open_price * (1.0 - slippage)
                if not np.isfinite(price) or price <= 0:
                    raise ValueError("fill price must be positive and finite")
                quantity = min(-delta_value / price, shares)
                if lot_size is not None and desired > 0:
                    quantity = float(int(quantity // lot_size) * lot_size)
                if quantity > 0:
                    fill = resolve_fill(
                        OrderSpec("SELL", "MARKET", quantity), session_open=open_price,
                        session_time=(timestamp + pd.Timedelta(hours=9, minutes=30)).to_pydatetime(),
                        intraday_touches=(), slippage_bp=slippage_bp,
                        session_limits=None if market_rules is None else market_rules.for_session(timestamp.date()),
                        daily_quote=None if market_rules is None else DailyQuote(float(frame["low"].iat[position]), float(frame["high"].iat[position])),
                    )
                    attempt_rows.append({"execution_date": timestamp, "side": "SELL", "quantity": quantity,
                                         "status": "FILLED" if fill.filled else "UNFILLED", "reason": fill.reason})
                    completed = fill.filled
                    if fill.filled:
                        price = float(fill.price)
                        gross = quantity * price
                        fees = gross * fee_rate
                        cash += gross - fees
                        shares -= quantity
                        order_rows.append(
                            {"execution_date": timestamp, "side": "SELL", "quantity": quantity,
                             "price": price, "fees": fees}
                        )
            if completed:
                previous_target = desired
        equity = cash + shares * close_price
        equity_rows.append(equity)
        state_rows.append(
            {"date": timestamp, "target": desired, "cash": cash, "quantity": shares,
             "close": close_price, "equity": equity}
        )
    return DailyExecutionResult(
        pd.Series(equity_rows, index=frame.index, name="equity"),
        pd.DataFrame(order_rows, columns=["execution_date", "side", "quantity", "price", "fees"]),
        pd.DataFrame(state_rows).set_index("date"),
        pd.DataFrame(attempt_rows, columns=["execution_date", "side", "quantity", "status", "reason"]),
    )
