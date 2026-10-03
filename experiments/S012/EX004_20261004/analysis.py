"""Preregistered causal features and development-pool component diagnostics."""
import numpy as np
import pandas as pd
from scipy.stats import rankdata
from tsfresh import extract_features

HORIZONS = (3, 5, 10, 20)
FRESH = {"mean": None, "standard_deviation": None, "skewness": None,
         "kurtosis": None, "absolute_sum_of_changes": None,
         "autocorrelation": [{"lag": 1}, {"lag": 2}],
         "quantile": [{"q": .1}, {"q": .9}], "linear_trend": [{"attr": "slope"}]}


def causal_align(frame, index, max_age=7):
    """External source day must be strictly before ETF decision day."""
    source = frame.sort_index().copy()
    source.index = pd.DatetimeIndex(source.index).normalize()
    assert source.index.is_unique
    merged = pd.merge_asof(pd.DataFrame({"decision": index}),
        source.reset_index(names="source_date"), left_on="decision", right_on="source_date",
        direction="backward", allow_exact_matches=False, tolerance=pd.Timedelta(days=max_age))
    good = merged.source_date.notna()
    assert (merged.loc[good, "source_date"] < merged.loc[good, "decision"]).all()
    return merged.set_index("decision").drop(columns="source_date")


def fresh_features(returns, window, workers):
    values = returns.to_numpy(copy=True)
    rows = np.lib.stride_tricks.sliding_window_view(values, window)
    valid = np.isfinite(rows).all(axis=1)
    positions = np.arange(window - 1, len(values))[valid]
    long = pd.DataFrame({"id": np.repeat(positions, window),
                         "time": np.tile(np.arange(window), len(positions)), "return": rows[valid].ravel()})
    extracted = extract_features(long, column_id="id", column_sort="time",
        default_fc_parameters=FRESH, n_jobs=workers, disable_progressbar=True)
    extracted.index = returns.index[extracted.index.astype(int)]
    extracted.columns = [f"fresh{window}_{c}" for c in extracted.columns]
    return extracted.reindex(returns.index)


def build_features(frames, workers=1):
    frames = {k: v.assign(Date=pd.to_datetime(v.Date)) for k, v in frames.items()}
    p = frames["raw"].set_index("Date").sort_index()
    p.index = pd.DatetimeIndex(p.index)
    r = p.Close.pct_change(fill_method=None)
    f, families = {}, {}
    def add(name, value, family):
        f[name], families[name] = value, family
    for w in (3, 5, 10, 20, 60):
        add(f"momentum_{w}", p.Close.pct_change(w, fill_method=None), "price_path")
    for w in (5, 20, 60):
        add(f"volatility_{w}", r.rolling(w).std(), "risk_state")
        add(f"drawdown_{w}", p.Close / p.Close.rolling(w).max() - 1, "risk_state")
    add("reversal_1", -r, "price_path")
    add("close_location", (p.Close - p.Low) / (p.High - p.Low).replace(0, np.nan), "microstructure")
    add("intraday_return", p.Close / p.Open - 1, "microstructure")
    add("opening_gap", p.Open / p.Close.shift() - 1, "microstructure")
    add("volume_ratio", p.Volume / p.Volume.rolling(20).mean(), "liquidity")
    add("amihud_20", (r.abs() / p.Amount.replace(0, np.nan)).rolling(20).mean(), "liquidity")
    add("range_5", ((p.High - p.Low) / p.Close).rolling(5).mean(), "risk_state")
    for name in ("real_yield", "nominal_yield", "fx", "shares", "vix", "shibor"):
        if name not in frames:
            continue
        src = frames[name].set_index("Date").sort_index()
        column = {"real_yield": "RealYield10YPercent", "nominal_yield": "NominalYield10YPercent",
                  "fx": "BidClose", "shares": "TotalShare", "vix": "Close", "shibor": "OvernightRate"}[name]
        x = src[column]
        native = pd.DataFrame({f"{name}_level": x})
        for w in (5, 20):
            native[f"{name}_change_{w}"] = x.pct_change(w, fill_method=None) if name in ("fx", "shares") else x.diff(w)
        aligned = causal_align(native, p.index)
        for c in aligned:
            add(c, aligned[c], "flows" if name == "shares" else "macro")
    sge = frames["sge"].set_index("Date").sort_index()
    # Relative price uses both legs from the same completed date. It is not NAV premium.
    relative = pd.DataFrame({"etf_sge_ratio": p.Close / sge.Close})
    relative["etf_sge_deviation_20"] = relative.etf_sge_ratio / relative.etf_sge_ratio.rolling(20).mean() - 1
    relative["etf_sge_deviation_60"] = relative.etf_sge_ratio / relative.etf_sge_ratio.rolling(60).mean() - 1
    relative["sge_momentum_5"] = sge.Close.pct_change(5, fill_method=None)
    relative["sge_momentum_20"] = sge.Close.pct_change(20, fill_method=None)
    for c, values in causal_align(relative.drop(columns="etf_sge_ratio"), p.index).items():
        add(c, values, "relative_price")
    fut = frames["futures"].copy()
    fut["maturity_days"] = (pd.to_datetime(fut.MaturityDate) - pd.to_datetime(fut.Date)).dt.days
    liquid = fut.loc[(fut.Volume > 0) & (fut.maturity_days >= 20)].sort_values(["Date", "OpenInterest", "Contract"])
    dominant = liquid.groupby("Date").tail(1).set_index("Date")
    basis = pd.DataFrame({"futures_spot_basis": dominant.Settle / sge.Close - 1})
    basis["basis_change_5"] = basis.futures_spot_basis.diff(5)
    # Same-day cross-contract slope; no spliced continuous-price return at contract rolls.
    by_maturity = liquid.sort_values(["Date", "MaturityDate"])
    near = by_maturity.groupby("Date").head(1).set_index("Date")
    far = by_maturity.groupby("Date").tail(1).set_index("Date")
    maturity_gap = (pd.to_datetime(far.MaturityDate) - pd.to_datetime(near.MaturityDate)).dt.days
    basis["futures_curve"] = (far.Settle / near.Settle - 1) * 365 / maturity_gap.replace(0, np.nan)
    for c, values in causal_align(basis, p.index).items():
        add(c, values, "relative_price")
    feature_frame = pd.DataFrame(f, index=p.index)
    for window in (20, 60):
        fresh = fresh_features(r, window, workers)
        for c in fresh:
            families[c] = "tsfresh_price_path"
        feature_frame = pd.concat([feature_frame, fresh], axis=1)
    return feature_frame.replace([np.inf, -np.inf], np.nan), families


def labels(prices, horizon):
    p = prices.assign(Date=pd.to_datetime(prices.Date)).set_index("Date").sort_index()
    entry = p.Open.shift(-1)
    gross = p.Open.shift(-horizon - 1) / entry - 1
    lows = pd.concat([p.Low.shift(-k) for k in range(1, horizon + 1)], axis=1)
    downside = (1 - lows.min(axis=1, skipna=False) / entry).clip(lower=0)
    return pd.DataFrame({"return": gross, "net_return": (1 + gross) * .999 / 1.001 - 1,
                         "downside": downside}, index=p.index)


def residual_rank(x, controls, years):
    rank = rankdata(x).astype(float)
    columns = [np.ones(len(x))]
    for year in np.unique(years)[1:]:
        columns.append((years == year).astype(float))
    for c in controls.T:
        columns.append(rankdata(c) / len(x))
    design = np.column_stack(columns)
    out = rank - design @ np.linalg.lstsq(design, rank, rcond=None)[0]
    norm = np.linalg.norm(out)
    return out / norm if norm > 1e-10 else np.zeros(len(x))


def circular_p(x, y, gap=60):
    corr = float(x @ y)
    offsets = np.arange(gap, len(x) - gap)
    cross = np.fft.ifft(np.conj(np.fft.fft(x)) * np.fft.fft(y)).real
    p = float((1 + (np.abs(cross[offsets]) >= abs(corr)).sum()) / (1 + len(offsets)))
    return corr, p


def bh_adjust(values):
    p = np.asarray(values)
    order = np.argsort(p)
    corrected = np.minimum.accumulate((p[order] * len(p) / np.arange(1, len(p) + 1))[::-1])[::-1]
    out = np.empty(len(p)); out[order] = np.minimum(corrected, 1)
    return out


def evaluate(features, families, raw):
    records, folds = [], []
    control_cols = ["momentum_20", "volatility_20"]
    for h in HORIZONS:
        targets = labels(raw, h)
        for feature in features:
            for role in ("return", "downside"):
                frame = pd.concat([features[[feature]], targets, features[control_cols].add_prefix("control_")], axis=1).dropna()
                if len(frame) < 300 or frame[feature].nunique() < 10:
                    continue
                controls = frame[["control_" + c for c in control_cols if c != feature]].to_numpy(copy=True)
                years = frame.index.year.to_numpy(copy=True)
                x = residual_rank(frame[feature].to_numpy(copy=True), controls, years)
                y = residual_rank(frame[role].to_numpy(copy=True), controls, years)
                corr, p = circular_p(x, y)
                year_corr = {}
                for year, part in frame.groupby(frame.index.year):
                    if len(part) >= 80:
                        year_corr[str(year)] = float(part[feature].corr(part[role], method="spearman"))
                # Expanding fit, purge h+1 decision rows before test; all slices remain development evidence.
                oof_differences, directions = [], []
                for year in sorted(set(years)):
                    first = pd.Timestamp(year, 1, 1)
                    train = frame.loc[frame.index < first].iloc[:-(h + 1)]
                    test = frame.loc[frame.index.year == year]
                    if len(train) < 400 or len(test) < 80:
                        continue
                    train_corr = train[feature].corr(train[role], method="spearman")
                    direction = 1 if train_corr >= 0 else -1
                    q1, q3 = train[feature].quantile([.25, .75])
                    high, low = test.loc[test[feature] >= q3], test.loc[test[feature] <= q1]
                    if min(len(high), len(low)) < 10:
                        continue
                    spread = float((high[role].mean() - low[role].mean()) * direction)
                    oof_differences.append(spread); directions.append(direction)
                    folds.append({"feature": feature, "role": role, "horizon": h, "year": int(year),
                        "train_rows": len(train), "high_n": len(high), "low_n": len(low), "direction": direction,
                        "signed_spread": spread, "high_mean": float(high[role].mean()), "low_mean": float(low[role].mean()),
                        "high_net_event": float(high.net_return.mean()), "low_net_event": float(low.net_return.mean())})
                records.append({"feature": feature, "family": families[feature], "role": role, "horizon": h,
                    "n": len(frame), "partial_ic": corr, "circular_p": p,
                    "year_ic": year_corr, "folds": len(oof_differences),
                    "positive_folds": int(sum(d > 0 for d in oof_differences)),
                    "mean_fold_spread": float(np.mean(oof_differences)) if oof_differences else None,
                    "directions": directions})
    qvalues = bh_adjust([x["circular_p"] for x in records])
    for record, q in zip(records, qvalues, strict=True):
        record["fdr_q"] = float(q)
    return records, folds
