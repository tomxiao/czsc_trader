"""Comparable portfolio and closed-trade metrics for ordinary backtests."""

from __future__ import annotations

import numpy as np
import pandas as pd


def closed_trade_ledger(
    orders: pd.DataFrame,
    size_rtol: float = 1e-8,
) -> pd.DataFrame:
    """Pair alternating full-position orders and ignore one open tail."""
    columns = (
        "entry_signal_date",
        "entry_date",
        "exit_signal_date",
        "exit_date",
        "size",
        "entry_price",
        "exit_price",
        "entry_fees",
        "exit_fees",
        "net_return",
    )
    if orders.empty:
        return pd.DataFrame(columns=columns)
    required = {"signal_date", "execution_date", "side", "size", "price", "fees"}
    if not required <= set(orders.columns):
        raise ValueError(f"orders missing columns: {sorted(required - set(orders.columns))}")
    records = orders.reset_index(drop=True)
    if str(records.iloc[0]["side"]).lower() != "buy":
        raise ValueError("closed trade order sequence must start with Buy")
    rows: list[dict[str, object]] = []
    pending: pd.Series | None = None
    for _, order in records.iterrows():
        side = str(order["side"]).lower()
        if side == "buy":
            if pending is not None:
                raise ValueError("closed trade order sequence contains consecutive Buy orders")
            pending = order
            continue
        if side != "sell":
            raise ValueError(f"unknown order side: {order['side']}")
        if pending is None:
            raise ValueError("closed trade order sequence contains Sell without Buy")
        buy_size = float(pending["size"])
        sell_size = float(order["size"])
        numeric = np.asarray(
            [
                buy_size,
                sell_size,
                pending["price"],
                order["price"],
                pending["fees"],
                order["fees"],
            ],
            dtype=float,
        )
        if not np.isfinite(numeric).all():
            raise ValueError("closed trade order values must be finite")
        if not np.isclose(buy_size, sell_size, rtol=float(size_rtol), atol=1e-12):
            raise ValueError("closed trade buy and sell sizes differ")
        cost = buy_size * float(pending["price"]) + float(pending["fees"])
        proceeds = sell_size * float(order["price"]) - float(order["fees"])
        if cost <= 0.0:
            raise ValueError("closed trade entry cost must be positive")
        rows.append(
            {
                "entry_signal_date": pending["signal_date"],
                "entry_date": pending["execution_date"],
                "exit_signal_date": order["signal_date"],
                "exit_date": order["execution_date"],
                "size": buy_size,
                "entry_price": float(pending["price"]),
                "exit_price": float(order["price"]),
                "entry_fees": float(pending["fees"]),
                "exit_fees": float(order["fees"]),
                "net_return": proceeds / cost - 1.0,
            }
        )
        pending = None
    return pd.DataFrame(rows, columns=columns)


def _finite_or_none(value: float) -> float | None:
    return float(value) if np.isfinite(float(value)) else None


def annualized_sharpe(
    equity: pd.Series,
    init_cash: float,
    *,
    annualization: float = 252.0,
) -> float | None:
    """Calculate one comparison Sharpe from independently funded equity."""
    values = equity.astype(float)
    if values.empty or not np.isfinite(values.to_numpy()).all():
        raise ValueError("equity must be finite and non-empty")
    if not np.isfinite(float(init_cash)) or float(init_cash) <= 0.0:
        raise ValueError("initial cash must be positive and finite")
    if not np.isfinite(float(annualization)) or float(annualization) <= 0.0:
        raise ValueError("annualization must be positive and finite")
    if len(values) < 2:
        return None
    prior = values.shift(1)
    prior.iloc[0] = float(init_cash)
    returns = values.div(prior).sub(1.0)
    volatility = float(returns.std(ddof=1))
    if not np.isfinite(volatility) or volatility <= 0.0:
        return None
    result = np.sqrt(float(annualization)) * float(returns.mean()) / volatility
    return _finite_or_none(float(result))


def strategy_comparison_metrics(
    equity: pd.Series,
    orders: pd.DataFrame,
    init_cash: float,
) -> dict[str, float | str | None]:
    """Return the account and closed-trade metrics shared by comparison strategies."""
    values = equity.astype(float)
    if values.empty or not np.isfinite(values.to_numpy()).all():
        raise ValueError("equity must be finite and non-empty")
    if not np.isfinite(float(init_cash)) or float(init_cash) <= 0.0:
        raise ValueError("initial cash must be positive and finite")
    total_return = float(values.iloc[-1] / float(init_cash) - 1.0)
    drawdown = values.div(values.cummax().clip(lower=init_cash)).sub(1.0)
    max_drawdown = float(drawdown.min())
    annualized_return = float(
        (values.iloc[-1] / float(init_cash)) ** (252.0 / len(values)) - 1.0
    )
    calmar = (
        annualized_return / abs(max_drawdown)
        if abs(max_drawdown) > 1e-12
        else float("nan")
    )
    ledger = closed_trade_ledger(orders)
    returns = ledger["net_return"].astype(float) if not ledger.empty else pd.Series(dtype=float)
    wins = returns.loc[returns.gt(0.0)]
    losses = returns.loc[returns.lt(0.0)]
    if ledger.empty:
        win_loss_ratio = float("nan")
        win_loss_ratio_status = "NO_CLOSED_TRADES"
    elif wins.empty:
        win_loss_ratio = float("nan")
        win_loss_ratio_status = "NO_WINS"
    elif losses.empty:
        win_loss_ratio = float("nan")
        win_loss_ratio_status = "NO_LOSSES"
    else:
        win_loss_ratio = float(wins.mean() / abs(losses.mean()))
        win_loss_ratio_status = "VALID"
    return {
        "max_drawdown": _finite_or_none(max_drawdown),
        "calmar": _finite_or_none(calmar),
        "win_loss_ratio": _finite_or_none(win_loss_ratio),
        "win_loss_ratio_status": win_loss_ratio_status,
        "win_rate": float(len(wins) / len(ledger)) if len(ledger) else None,
        "return": _finite_or_none(total_return),
        "sharpe": annualized_sharpe(values, init_cash),
    }
