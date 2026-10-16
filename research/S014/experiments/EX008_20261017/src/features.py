"""Daily price-constraint events and overnight/intraday decomposition."""
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

BASE = ["ret1", "ret5", "ret20", "range", "volume_ratio"]
CONSTRAINTS = ["upper_close", "upper_failure", "lower_recovery", "lower_close", "previous_upper_close"]
SESSION = ["gap", "gap5", "gap_session_product", "gap_down_repair", "gap_up_fade"]
MODELS = {"ridge-base": BASE, "ridge-constraints": BASE + CONSTRAINTS,
          "ridge-session": BASE + SESSION, "ridge-both": BASE + CONSTRAINTS + SESSION,
          "tree-base": BASE, "tree-both": BASE + CONSTRAINTS + SESSION}


def features(data):
    bars, raw, limits = (data[k] for k in ("stock.ohlcv", "stock.unadjusted_daily", "security.price_limits"))
    c, o = bars.Close.astype(float), bars.Open.astype(float)
    gap = np.log(o / c.shift())
    intraday = np.log(c / o)
    upper_close = (raw.Close - limits.UpLimit).abs().le(.005)
    lower_close = (raw.Close - limits.DownLimit).abs().le(.005)
    upper_touch = raw.High.ge(limits.UpLimit - .005)
    lower_touch = raw.Low.le(limits.DownLimit + .005)
    return pd.DataFrame({
        "ret1": c.pct_change(), "ret5": c.pct_change(5), "ret20": c.pct_change(20),
        "range": (bars.High - bars.Low) / c,
        "volume_ratio": bars.Volume.rolling(5).mean() / bars.Volume.rolling(20).mean(),
        "upper_close": upper_close.astype(float), "upper_failure": (upper_touch & ~upper_close).astype(float),
        "lower_recovery": (lower_touch & ~lower_close).astype(float), "lower_close": lower_close.astype(float),
        "previous_upper_close": upper_close.shift(1, fill_value=False).astype(float),
        "gap": gap, "intraday": intraday, "gap5": gap.rolling(5).sum(),
        "intraday5": intraday.rolling(5).sum(), "gap_session_product": gap * intraday,
        "gap_down_repair": (gap.lt(0) & intraday.gt(0)).astype(float),
        "gap_up_fade": (gap.gt(0) & intraday.lt(0)).astype(float),
        "lower_touch": lower_touch.astype(float),
    })


def predict(task):
    name, left, right, y = task
    left, right, y = (np.asarray(v, dtype=float) for v in (left, right, y))
    assert all(np.isfinite(v).all() for v in (left, right, y))
    if name.startswith("tree"):
        model = DecisionTreeRegressor(max_depth=3, min_samples_leaf=40, random_state=13)
        model.fit(left, y)
        return model.predict(left), model.predict(right)
    mean, scale = left.mean(axis=0), left.std(axis=0)
    scale[scale < 1e-12] = 1.
    left, right = (left - mean) / scale, (right - mean) / scale
    center = float(y.mean())
    coef = np.linalg.solve(left.T @ left + 10 * np.eye(left.shape[1]), left.T @ (y - center))
    return left @ coef + center, right @ coef + center


def event_masks(frame, q10, q90):
    return {
        "upper-close": (frame.upper_close.eq(1).to_numpy(), (frame.ret1.ge(q90) & frame.upper_close.eq(0)).to_numpy(), 1.),
        "lower-recovery": (frame.lower_recovery.eq(1).to_numpy(), (frame.ret1.le(q10) & frame.lower_touch.eq(0)).to_numpy(), 1.),
        "gap-down-repair": (frame.gap_down_repair.eq(1).to_numpy(), (frame.gap.lt(0) & frame.intraday.le(0)).to_numpy(), 1.),
        "gap-up-fade": (frame.gap_up_fade.eq(1).to_numpy(), (frame.gap.gt(0) & frame.intraday.ge(0)).to_numpy(), -1.),
    }
