"""S014 natural-year acceptance, computed from continuous account ledgers."""
import math

import numpy as np
import pandas as pd


def _drawdown(values, opening):
    wealth = np.r_[opening, np.asarray(values, dtype=float)]
    return float(np.max(1.0 - wealth / np.maximum.accumulate(wealth)))


def evaluate_annual_contract(strategy, benchmark, closed_exits, *, initial_cash, expected_sessions):
    """Return annual gates and one full-period trading-frequency gate.

    expected_sessions comes from the exchange calendar; suspended sessions stay
    in both continuous ledgers. No annual liquidation or return annualization.
    """
    sessions = pd.DatetimeIndex(expected_sessions)
    if (sessions.empty or sessions.has_duplicates or not sessions.is_monotonic_increasing
            or sessions.hasnans or not sessions.equals(sessions.normalize()) or sessions.tz is not None):
        raise ValueError("expected sessions require ordered unique local dates")
    if isinstance(initial_cash, bool) or not math.isfinite(initial_cash) or initial_cash <= 0:
        raise ValueError("initial cash must be positive and finite")
    for equity in (strategy, benchmark):
        if not isinstance(equity, pd.Series) or not equity.index.equals(sessions):
            raise ValueError("both ledgers must cover the exact exchange sessions")
        values = equity.to_numpy(dtype=float)
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("account equity must be positive and finite")
    exits = pd.DatetimeIndex(closed_exits)
    if exits.hasnans or not exits.isin(sessions).all():
        raise ValueError("closed trades must exit inside the evaluation sessions")
    opening_strategy = opening_benchmark = float(initial_cash)
    annual = []
    for year in sorted(set(sessions.year)):
        left = strategy.loc[sessions.year == year]
        right = benchmark.loc[sessions.year == year]
        strategy_return = float(left.iloc[-1] / opening_strategy - 1)
        benchmark_return = float(right.iloc[-1] / opening_benchmark - 1)
        strategy_drawdown = _drawdown(left, opening_strategy)
        benchmark_drawdown = _drawdown(right, opening_benchmark)
        return_pass = (strategy_return >= 1.5 * benchmark_return
                       if benchmark_return > 0 else strategy_return > 0)
        annual.append({
            "year": int(year), "first_session": left.index[0].date().isoformat(),
            "last_session": left.index[-1].date().isoformat(), "sessions": len(left),
            "strategy_opening_equity": opening_strategy,
            "benchmark_opening_equity": opening_benchmark,
            "strategy_return": strategy_return, "benchmark_return": benchmark_return,
            "strategy_drawdown": strategy_drawdown, "benchmark_drawdown": benchmark_drawdown,
            "return_pass": bool(return_pass), "drawdown_pass": bool(strategy_drawdown < benchmark_drawdown),
        })
        opening_strategy, opening_benchmark = float(left.iloc[-1]), float(right.iloc[-1])
    frequency = 60 * len(exits) / len(sessions)
    return {"annual": annual, "frequency": frequency, "frequency_pass": frequency >= 3,
            "annual_return_pass": all(x["return_pass"] for x in annual),
            "annual_drawdown_pass": all(x["drawdown_pass"] for x in annual),
            "all_targets_pass": all(x["return_pass"] and x["drawdown_pass"] for x in annual) and frequency >= 3,
            "strategy_full_drawdown_diagnostic": _drawdown(strategy, initial_cash),
            "benchmark_full_drawdown_diagnostic": _drawdown(benchmark, initial_cash)}
