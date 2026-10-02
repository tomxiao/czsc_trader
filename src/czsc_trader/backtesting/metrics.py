from __future__ import annotations

import numpy as np

from .result import BacktestResult


def calculate_metrics(result: BacktestResult, initial_cash: float) -> dict[str, object]:
    """Calculate the compact OPC metric set from the unadjusted account ledger."""
    equity = result.account_daily["equity"].astype(float)
    total_return = float(equity.iloc[-1] / initial_cash - 1.0)
    max_drawdown = float(equity.div(equity.cummax().clip(lower=initial_cash)).sub(1.0).min())
    annualized_return = float((equity.iloc[-1] / initial_cash) ** (252 / len(equity)) - 1)
    calmar = annualized_return / abs(max_drawdown) if abs(max_drawdown) > 1e-12 else None
    prior = equity.shift(1)
    prior.iloc[0] = initial_cash
    returns = equity.div(prior).sub(1.0)
    volatility = float(returns.std(ddof=1))
    sharpe = (
        float(np.sqrt(252.0) * returns.mean() / volatility)
        if np.isfinite(volatility) and volatility > 0
        else None
    )
    closed = result.trades.loc[result.trades["status"].eq("CLOSED")]
    trade_returns = closed["net_return"].astype(float)
    wins = trade_returns.loc[trade_returns.gt(0)]
    losses = trade_returns.loc[trade_returns.lt(0)]
    if closed.empty:
        ratio, ratio_status = None, "NO_CLOSED_TRADES"
    elif wins.empty:
        ratio, ratio_status = None, "NO_WINS"
    elif losses.empty:
        ratio, ratio_status = None, "NO_LOSSES"
    else:
        ratio = float(wins.mean() / abs(losses.mean()))
        ratio_status = "VALID"
    return {
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "win_loss_ratio": ratio,
        "win_loss_ratio_status": ratio_status,
        "return": total_return,
        "sharpe": sharpe,
        "closed_trades": int(len(closed)),
        "win_rate": float(len(wins) / len(closed)) if len(closed) else None,
    }
