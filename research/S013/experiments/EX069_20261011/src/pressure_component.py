"""Fixed causal four-session pressure observations; no market/account I/O."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

FEATURES = ("short_stretch4", "overnight_down_share4")
METHOD = {
    "version": "s013-four-session-pressure-v1",
    "status": "PROSPECTIVE_PURE_IMPLEMENTATION_NO_MARKET_STATISTICS",
    "features": {
        "short_stretch4": "(log(C_T)-log(C_(T-4)))/(volatility20_T*sqrt(4)); volatility20=simple Close pct_change rolling20 sample std ddof1",
        "overnight_down_share4": "sum_s(T-3..T)max(-(log(O_s)-log(C_(s-1))),0) divided by same overnight sum plus sum_s(T-3..T)max(-(log(C_s)-log(O_s)),0)",
    },
    "hypotheses": {
        "short_stretch4": "negative relation to next-open-entry h4 net-return proxy",
        "overnight_down_share4": "positive relation to that label",
    },
    "semantics": {
        "window": "four complete sessions T-3..T, endpoint close T-4; no future rows",
        "volatility": "exact original20 simple-return sample std; no epsilon replacement",
        "unavailable": "short_stretch4 is NaN with explicit short_stretch_reason when20-return history incomplete or volatility=0; retained rows, not economic gate",
        "no_down": "if complete4-session denominator=0 share=0; means no negative overnight/intraday change, not repair",
        "magnitude": "sum negative logarithmic price changes, not squared return energy",
        "zero_interrupt": "not applicable to these aggregate expressions",
    },
    "input": {
        "index": "finite unique strictly increasing timezone-naive daily-midnight DatetimeIndex; caller validates calendar",
        "required_columns": ["Open", "Close"],
        "values": "positive finite prices in consistent HFQ units; High/Low/Volume unused",
    },
    "output": {
        "index": "Date",
        "columns": [
            *FEATURES,
            "volatility20",
            "overnight_down4",
            "intraday_down4",
            "short_stretch_reason",
        ],
        "availability": "all T daily observations formed, earliest T+1 execution",
        "warmup": "20 previous sessions needed for20 returns; first4 sessions lack pressure windows",
    },
    "parameters": "none; fixed4/20 periods and fixed directions, no optimization",
    "limitations": [
        "Price patterns do not identify funds, trading pressure or intent.",
        "The overnight move is before proposed T+1 entry and not a tradable label.",
        "Definition and synthetic tests provide no predictive/profit evidence.",
    ],
}


def build_features(daily: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(daily, pd.DataFrame) or not isinstance(daily.index, pd.DatetimeIndex):
        raise ValueError("daily DataFrame with DatetimeIndex required")
    if daily.empty or daily.index.tz is not None or daily.index.hasnans:
        raise ValueError("nonempty finite timezone-naive daily index required")
    if (
        daily.index.has_duplicates
        or not daily.index.is_monotonic_increasing
        or not daily.index.equals(daily.index.normalize())
    ):
        raise ValueError("unique increasing midnight daily timestamps required")
    if daily.columns.has_duplicates or not {"Open", "Close"}.issubset(daily.columns):
        raise ValueError("unique Open/Close columns required")
    prices = daily[["Open", "Close"]].astype(float)
    if not np.isfinite(prices.to_numpy()).all() or not (prices.to_numpy() > 0).all():
        raise ValueError("positive finite Open/Close required")
    opening, close = prices.Open, prices.Close
    volatility = close.pct_change(fill_method=None).rolling(20).std(ddof=1)
    if np.isinf(volatility.to_numpy()).any():
        raise ValueError("nonfinite volatility arithmetic")
    change4 = np.log(close) - np.log(close.shift(4))
    stretch = change4 / (volatility.where(volatility > 0.0) * 2.0)
    overnight = np.maximum(-(np.log(opening) - np.log(close.shift(1))), 0.0).rolling(4).sum()
    intraday = np.maximum(-(np.log(close) - np.log(opening)), 0.0).rolling(4).sum()
    total = overnight + intraday
    share = overnight / total.where(total > 0.0)
    share = share.where(total.ne(0.0), 0.0)
    reason = pd.Series("AVAILABLE", index=daily.index)
    reason.loc[volatility.isna() | change4.isna()] = "INSUFFICIENT_HISTORY"
    reason.loc[volatility.eq(0.0) & change4.notna()] = "ZERO_VOLATILITY"
    out = pd.DataFrame(
        {
            "short_stretch4": stretch,
            "overnight_down_share4": share,
            "volatility20": volatility,
            "overnight_down4": overnight,
            "intraday_down4": intraday,
            "short_stretch_reason": reason,
        }
    )
    out.index = out.index.rename("Date")
    if np.isinf(out.drop(columns="short_stretch_reason").to_numpy()).any():
        raise ValueError("nonfinite component arithmetic")
    return out


def write_method(path: str | Path) -> None:
    payload = {
        "method": METHOD,
        "method_sha256": hashlib.sha256(
            json.dumps(METHOD, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), "utf-8")
