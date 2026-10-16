"""Fixed, causal phase-two diagnostics; no parameter optimization."""
import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor


def fitted_scores(task):
    model_name, train_x, all_x, y = task
    means = np.nanmean(train_x, axis=0)
    if not np.isfinite(means).all():
        raise ValueError("Training feature is entirely missing")
    train = np.where(np.isfinite(train_x), train_x, means)
    whole = np.where(np.isfinite(all_x), all_x, means)
    if model_name.startswith("tree-"):
        model = DecisionTreeRegressor(max_depth=2, min_samples_leaf=50, random_state=13)
        model.fit(train, y)
        return model.predict(train), model.predict(whole)
    scale = train.std(axis=0)
    scale[scale < 1e-12] = 1
    train, whole = (train - means) / scale, (whole - means) / scale
    center = float(np.mean(y))
    coefficient = np.linalg.solve(train.T @ train + 10 * np.eye(train.shape[1]), train.T @ (y - center))
    return train @ coefficient + center, whole @ coefficient + center


def rolling_threshold(scores, quantile):
    return pd.Series(scores).shift(1).rolling(63, min_periods=63).quantile(quantile).to_numpy()


def extended_features(adjusted):
    close = adjusted.Close.astype(float)
    volume = adjusted.Volume.astype(float)
    returns = close.pct_change()
    return pd.DataFrame({"ret_1": returns, "ret_5": close.pct_change(5), "ret_20": close.pct_change(20),
        "range_1": (adjusted.High - adjusted.Low) / close, "std20": returns.rolling(20).std(),
        "above_ma60": close > close.rolling(60, min_periods=60).mean(),
        "breakout20": close > adjusted.High.shift(1).rolling(20).max(),
        "volume_confirmation": volume > volume.shift(1).rolling(20).mean(),
        "close_location": ((close - adjusted.Low) / (adjusted.High - adjusted.Low).replace(0, np.nan)).fillna(.5),
        "gap_next_open": adjusted.Open.shift(-1) / close - 1})


def association(x, y):
    x, y = pd.Series(np.asarray(x)), pd.Series(np.asarray(y))
    if len(x) < 3 or x.nunique() < 2 or y.nunique() < 2:
        return None
    value = x.corr(y, method="spearman")
    return float(value) if np.isfinite(value) else None


def mean_or_none(values):
    values = np.asarray(values, dtype=float)
    return float(values.mean()) if len(values) else None


def bootstrap_pair(task):
    groups, seed, family_count = task
    random = np.random.default_rng(seed)
    distributions = np.zeros(5000)
    valid = np.ones(5000, dtype=bool)
    total = sum(len(y) for _, y, _, _ in groups)
    years = []
    for year, y, chosen, control in groups:
        n = len(y)
        if not chosen.any() or not control.any():
            return {"status": "INSUFFICIENT_DATA", "reason": "NO_SELECTIONS_IN_A_YEAR", "year": int(year),
                    "difference": None, "interval95": None, "interval_family": None, "valid_draw_fraction": 0.}
        starts = random.integers(0, n, (5000, int(np.ceil(n / 20))))
        indices = ((starts[:, :, None] + np.arange(20)) % n).reshape(5000, -1)[:, :n]
        first, second = chosen[indices], control[indices]
        a_count, b_count = first.sum(axis=1), second.sum(axis=1)
        nonempty = (a_count > 0) & (b_count > 0)
        a_mean = np.divide((y[indices] * first).sum(axis=1), a_count, out=np.full(5000, np.nan), where=a_count > 0)
        b_mean = np.divide((y[indices] * second).sum(axis=1), b_count, out=np.full(5000, np.nan), where=b_count > 0)
        valid &= nonempty
        distributions += (a_mean - b_mean) * n / total
        point = float(y[chosen].mean() - y[control].mean())
        years.append({"year": int(year), "dates": n, "difference": point})
    good = distributions[valid]
    point = sum(row["difference"] * row["dates"] for row in years) / total
    leave = {str(row["year"]): sum(x["difference"] * x["dates"] for x in years if x is not row) / (total - row["dates"]) for row in years}
    return {"status": "COMPUTED", "difference": point,
            "interval95": np.quantile(good, [.025, .975]).tolist() if len(good) else None,
            "interval_family": np.quantile(good, [.05 / (2 * family_count), 1 - .05 / (2 * family_count)]).tolist() if len(good) else None,
            "valid_draw_fraction": float(valid.mean()), "positive_years": sum(x["difference"] > 0 for x in years),
            "leave_one_year_out": leave, "dates": total}


def precheck(pool):
    generator = np.random.default_rng(13)
    task = ("reversal", generator.normal(size=(80, 5)), generator.normal(size=(100, 5)), generator.normal(size=80))
    first, second = fitted_scores(task), pool.submit(fitted_scores, task).result()
    np.testing.assert_allclose(first[1], second[1], atol=1e-12, rtol=0)
    scores = generator.normal(size=100)
    np.testing.assert_allclose(rolling_threshold(scores, .75)[:80], rolling_threshold(scores[:80], .75), equal_nan=True)
    synthetic = pd.DataFrame({"Close": np.exp(generator.normal(0, .02, 100).cumsum()), "Volume": generator.uniform(100, 200, 100)})
    synthetic["Open"], synthetic["High"], synthetic["Low"] = synthetic.Close, synthetic.Close * 1.02, synthetic.Close * .98
    left, right = extended_features(synthetic), extended_features(synthetic.iloc[:80])
    # gap_next_open is an outcome-only diagnostic, never a decision feature.
    pd.testing.assert_frame_equal(left.drop(columns="gap_next_open").iloc[:80], right.drop(columns="gap_next_open"))
    return {"status": "PASS", "serial_spawn": True, "rolling_threshold_excludes_current_score": True,
            "feature_prefix": True, "outcome_only_columns": ["gap_next_open"]}
