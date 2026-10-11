"""Prospective fixed intraday-order observations; no market or account I/O."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

BAR_END_TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
FEATURES = ("early_down_share", "max_down_run_share")
CONTROLS = ("total_down", "total_up")
METHOD = {
    "version": "s013-intraday-order-v1",
    "status": "PROSPECTIVE_PURE_IMPLEMENTATION_NO_MARKET_STATISTICS",
    "returns": "r_i=log(C_i)-log(C_(i-1)), i=1..8; C_0=first Open; d_i=max(-r_i,0), u_i=max(r_i,0)",
    "features": {
        "early_down_share": "sum(d_1..d_4)/sum(d_1..d_8)",
        "max_down_run_share": "max over contiguous strictly negative-return runs of sum(d_i), divided by sum(d_1..d_8)",
    },
    "controls": {"total_down": "sum(d_1..d_8)", "total_up": "sum(u_1..u_8)"},
    "semantics": {
        "run": "r_i<0 extends a run; zero or positive r_i interrupts it; select largest cumulative down move, not longest run length",
        "no_down": "If total_down=0 both shares=0; this denotes no negative close transition, not exhaustion or recovery",
        "volume": "Validated to match original eight-bar input contract; does not enter any feature",
        "later_opens": "Validated but unused; first Open anchors the first close transition",
        "ratio_rounding": "Shares bounded at 1 for floating sum roundoff only",
    },
    "hypothesis": {
        "early_down_share": "positive relation to h4 next-open-entry net-return proxy after old information and daily down/up magnitude controls",
        "max_down_run_share": "negative relation to that h4 label",
        "primary_horizon": 4,
        "hypothesis_only": True,
        "controls_required_for_future_statistics": "old14 + both EX061 observations + total_down + total_up; no actual statistics in this package",
    },
    "input": {
        "index": "unique strictly increasing finite timezone-naive DatetimeIndex; exact full eight-bar sessions",
        "required_columns": ["Open", "Close", "Volume"],
        "required_bar_end_times": list(BAR_END_TIMES),
        "numeric_contract": "positive finite Open/Close/Volume",
        "unused_fields": ["High", "Low"],
    },
    "output": {
        "index": "normalized timezone-naive DatetimeIndex named Date",
        "columns": [*FEATURES, *CONTROLS],
        "availability": "after all eight T bars complete, earliest execution T+1",
        "warmup": "one complete session; no historical window",
        "selection": "retain every complete session including no-down cases",
    },
    "parameters": "none; fixed first four bars, fixed strictly negative runs; no threshold or direction search",
    "limitations": [
        "Close transitions do not identify intrabar ordering, fund flows, or buyer/seller pressure.",
        "Synthetic correctness is not evidence of profitability or independent predictive information.",
        "Caller must establish authorized calendar, asset identity, HFQ units and time availability.",
        "Future labels and realized profit must never determine signal population or feature definition.",
    ],
}


def _daily_arrays(bars: pd.DataFrame) -> tuple[pd.DatetimeIndex, np.ndarray]:
    if not isinstance(bars, pd.DataFrame) or not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars require DataFrame with DatetimeIndex")
    if bars.empty:
        raise ValueError("at least one complete session required")
    if bars.index.tz is not None or bars.index.hasnans:
        raise ValueError("finite timezone-naive timestamps required")
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if bars.columns.has_duplicates or not {"Open", "Close", "Volume"}.issubset(bars.columns):
        raise ValueError("unique Open/Close/Volume columns required")
    values = bars.loc[:, ["Open", "Close", "Volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("positive finite Open/Close/Volume required")
    dates = bars.index.normalize().unique().rename("Date")
    offsets = pd.to_timedelta([f"{clock}:00" for clock in BAR_END_TIMES])
    expected = pd.DatetimeIndex(np.repeat(dates.to_numpy(), 8) + np.tile(offsets.to_numpy(), len(dates)))
    if not bars.index.equals(expected):
        raise ValueError("exact eight fixed bar-end timestamps per session required")
    return dates, values.reshape(len(dates), 8, 3)


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    dates, daily = _daily_arrays(bars)
    closes = daily[:, :, 1]
    previous = np.column_stack((daily[:, 0, 0], closes[:, :-1]))
    returns = np.log(closes) - np.log(previous)
    down = np.maximum(-returns, 0.)
    total_down = down.sum(axis=1)
    total_up = np.maximum(returns, 0.).sum(axis=1)
    running = np.zeros(len(dates))
    largest = np.zeros(len(dates))
    for bar in range(8):
        running = np.where(returns[:, bar] < 0., running + down[:, bar], 0.)
        largest = np.maximum(largest, running)
    early = np.divide(down[:, :4].sum(axis=1), total_down,
                      out=np.zeros_like(total_down), where=total_down > 0.)
    run = np.divide(largest, total_down, out=np.zeros_like(total_down), where=total_down > 0.)
    result = pd.DataFrame({
        "early_down_share": np.minimum(early, 1.),
        "max_down_run_share": np.minimum(run, 1.),
        "total_down": total_down,
        "total_up": total_up,
    }, index=dates)
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError("nonfinite feature arithmetic")
    return result


def write_method(path: str | Path) -> None:
    payload = {
        "method": METHOD,
        "method_sha256": hashlib.sha256(json.dumps(METHOD, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
