"""Completed-day representations and fixed estimators for a holding decision."""
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

BASE = ["ret1", "ret5", "ret20", "tr", "volume_ratio", "mark"]
GROUPS = {
    "structure": ["distance_ma20", "ma_alignment", "ma_slope", "support_distance"],
    "participation": ["volume_location", "signed_volume", "volume_momentum"],
    "holding_path": ["mark_drawdown", "giveback_atr", "mark_per_day"],
}
ALL = BASE + sum(GROUPS.values(), [])
MODELS = {"ridge-base": BASE, **{f"ridge-{name}": BASE + cols for name, cols in GROUPS.items()},
          "ridge-full": ALL, **{f"ridge-without-{name}": [c for c in ALL if c not in cols] for name, cols in GROUPS.items()},
          "tree-base": BASE, "tree-full": ALL}


def market_features(bars):
    close, high, low, volume = (bars[c].astype(float) for c in ("Close", "High", "Low", "Volume"))
    ret = close.pct_change()
    tr_cash = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
    atr = tr_cash.rolling(20).mean()
    ma5, ma20 = close.rolling(5).mean(), close.rolling(20).mean()
    ratio = volume.rolling(5).mean() / volume.rolling(20).mean()
    span = (high - low).replace(0, np.nan)
    # A flat day's location carries no directional information.
    location = ((2 * close - high - low) / span).fillna(0.)
    denominator = volume.rolling(5).sum()
    result = pd.DataFrame({
        "ret1": ret, "ret5": close.pct_change(5), "ret20": close.pct_change(20),
        "tr": tr_cash / close.shift(), "volume_ratio": ratio,
        "distance_ma20": close / ma20 - 1, "ma_alignment": ma5 / ma20 - 1,
        "ma_slope": ma20 / ma20.shift(5) - 1,
        "support_distance": (close - close.shift().rolling(5).min()) / atr,
        "volume_location": (location * volume).rolling(5).sum() / denominator,
        "signed_volume": (np.sign(ret) * volume).rolling(5).sum() / denominator,
        "volume_momentum": ratio * close.pct_change(5),
        "trend_preserved": (close >= ma20) & (ma5 >= ma20),
        "support_intact": close >= close.shift().rolling(5).min(),
        "atr": atr,
    })
    return result


def holding_features(close, entry, decision, buy, quantity, atr):
    marks = quantity * (close[entry:decision + 1] * .999 - buy * 1.001) / 100000
    current = float(marks[-1])
    peak = max(0., float(marks.max()))
    scale = quantity * atr / 100000
    if not scale > 0:
        raise ValueError("Positive observed ATR required")
    return {"mark": current, "mark_drawdown": peak - current,
            "giveback_atr": (peak - current) / scale,
            "mark_per_day": current / (decision - entry + 1)}


def fit_predict(task):
    name, left, right, target = task
    left, right, target = (np.asarray(x, dtype=float) for x in (left, right, target))
    if not all(np.isfinite(x).all() for x in (left, right, target)):
        raise ValueError("Nonfinite features or targets")
    if name.startswith("tree"):
        model = DecisionTreeRegressor(max_depth=3, min_samples_leaf=40, random_state=13)
        model.fit(left, target)
        return model.predict(right)
    mean, scale = left.mean(axis=0), left.std(axis=0)
    scale[scale < 1e-12] = 1.
    left, right = (left - mean) / scale, (right - mean) / scale
    center = float(target.mean())
    coefficient = np.linalg.solve(left.T @ left + 10 * np.eye(left.shape[1]), left.T @ (target - center))
    return right @ coefficient + center
