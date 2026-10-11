"""Causal end-of-session observations from eight fixed HFQ 30-minute bars.

This module has no market, account, networking, or publication calls.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

BAR_END_TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
FEATURES = ("late_recovery", "early_volume_reclaim")
EXPLANATIONS = ("late_return", "early_return", "tail_volume_share")
METHOD = {
    "version": "s013-late-recovery-components-v1",
    "status": "PROSPECTIVE_PURE_IMPLEMENTATION_NO_MARKET_STATISTICS",
    "features": {
        "late_recovery": "log(C8/C6)",
        "early_volume_reclaim": "sum(j=1..6, Vj*sign(C8-Cj))/sum(j=1..6,Vj)",
    },
    "explanations": {
        "late_return": "log(C8/C6)",
        "early_return": "log(C6/O1)",
        "tail_volume_share": "(V7+V8)/sum(j=1..8,Vj)",
    },
    "interpretation": {
        "late_recovery": "Signed price change during the last two 30-minute bars.",
        "early_volume_reclaim": "Volume-weighted recovery relative to the first six bar-close proxy levels; bounded [-1,1].",
        "not_claimed": ["VWAP", "fund flow", "investor positions", "actual intra-bar volume-at-price"],
    },
    "input": {
        "index": "strictly increasing unique timezone-naive DatetimeIndex, one full session per date",
        "required_columns": ["Open", "Close", "Volume"],
        "required_bar_end_times": list(BAR_END_TIMES),
        "daily_count": 8,
        "numeric_contract": "every Open/Close/Volume strictly positive and finite",
        "price_units": "consistent HFQ within each complete session; cross-day positive scaling cancels",
        "unused_fields": ["High", "Low"],
    },
    "output": {
        "index": "normalized timezone-naive DatetimeIndex named Date",
        "columns": [*FEATURES, *EXPLANATIONS],
        "available_at": "after all eight bars of signal session T are complete; earliest execution T+1",
        "warmup": "none; every complete eight-bar session yields both features",
        "selection": "retain every complete session including negative and zero features",
    },
    "parameters": "none: no window, threshold, weighting or hyperparameter search",
    "numerics": "log(a/b) computed as log(a)-log(b); volumes normalized by each ratio segment maximum before ratios",
    "design_history": {
        "retired": "draft_history/late_recovery_three_features_draft.py",
        "reason": "replaced early-loss and volume-support product expressions with a direct observation before formal publication or real-data statistics",
        "all_versions_real_data_read": False,
    },
    "limitations": [
        "First-six closes proxy observed price levels; the feature does not measure actual volume-at-price.",
        "Input HFQ identity and completeness relative to the authorized calendar require caller evidence.",
        "This definition and synthetic validation provide no evidence of predictiveness or profitability.",
    ],
}


def _daily_arrays(bars: pd.DataFrame) -> tuple[pd.DatetimeIndex, np.ndarray]:
    if not isinstance(bars, pd.DataFrame) or not isinstance(bars.index, pd.DatetimeIndex):
        raise ValueError("bars require a DataFrame with DatetimeIndex")
    if bars.empty:
        raise ValueError("at least one complete eight-bar session required")
    if bars.index.tz is not None or bars.index.hasnans:
        raise ValueError("finite timezone-naive timestamps required")
    if bars.index.has_duplicates or not bars.index.is_monotonic_increasing:
        raise ValueError("timestamps must be unique and strictly increasing")
    if bars.columns.has_duplicates or not {"Open", "Close", "Volume"}.issubset(bars.columns):
        raise ValueError("unique Open/Close/Volume columns required")
    values = bars.loc[:, ["Open", "Close", "Volume"]].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not (values > 0).all():
        raise ValueError("every Open/Close/Volume must be positive and finite")
    dates = bars.index.normalize().unique().rename("Date")
    offsets = pd.to_timedelta([f"{clock}:00" for clock in BAR_END_TIMES])
    expected = pd.DatetimeIndex(np.repeat(dates.to_numpy(), 8) + np.tile(offsets.to_numpy(), len(dates)))
    if not bars.index.equals(expected):
        raise ValueError("each date must have exactly the eight fixed 30-minute bar-end timestamps")
    return dates, values.reshape(len(dates), 8, 3)


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Return all declared observations without selecting positive signals."""
    dates, daily = _daily_arrays(bars)
    opens, closes, volumes = daily[:, :, 0], daily[:, :, 1], daily[:, :, 2]
    late_return = np.log(closes[:, 7]) - np.log(closes[:, 5])
    early_return = np.log(closes[:, 5]) - np.log(opens[:, 0])
    relative_volume = volumes / volumes.max(axis=1, keepdims=True)
    early_volume = volumes[:, :6] / volumes[:, :6].max(axis=1, keepdims=True)
    reclaim = (early_volume * np.sign(closes[:, 7, None] - closes[:, :6])).sum(axis=1) / early_volume.sum(axis=1)
    share = relative_volume[:, 6:].sum(axis=1) / relative_volume.sum(axis=1)
    result = pd.DataFrame({
        "late_recovery": late_return,
        "early_volume_reclaim": reclaim,
        "late_return": late_return,
        "early_return": early_return,
        "tail_volume_share": share,
    }, index=dates)
    if not np.isfinite(result.to_numpy()).all():
        raise ValueError("feature arithmetic produced nonfinite values")
    return result


def write_method(path: str | Path) -> None:
    payload = {"method": METHOD,
               "method_sha256": hashlib.sha256(json.dumps(METHOD, sort_keys=True,
                    separators=(",", ":")).encode()).hexdigest(),
               "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
