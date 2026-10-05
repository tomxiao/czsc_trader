"""Causal intraday opportunity census; all selection remains development research."""

from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from tsfresh import extract_features
from expr_codegen import codegen_exec

FRESH = {
    "kurtosis": None,
    "autocorrelation": [{"lag": 1}],
    "linear_trend": [{"attr": "slope"}],
    "absolute_sum_of_changes": None,
}
EXPRESSIONS = "intraday = Close / Open - 1\nvwap_gap = Close / VWAP - 1\npeer_gap = Close * PeerOpen / (Open * PeerClose) - 1"


def build_features(daily, minutes, peer, workers, generated=None):
    d = daily.copy()
    d.attrs = {}
    d["Date"] = pd.to_datetime(d.Date).dt.normalize()
    d = d.set_index("Date").sort_index()
    m = minutes.copy()
    m.attrs = {}
    m["Date"] = pd.to_datetime(m.Date)
    m["AvailableDate"] = pd.to_datetime(m.AvailableDate)
    m["day"] = m.Date.dt.normalize()
    if m.Date.duplicated().any() or d.index.duplicated().any():
        raise ValueError("duplicate market observations")
    p = peer.copy()
    p.attrs = {}
    p["Date"] = pd.to_datetime(p.Date).dt.normalize()
    p = p.set_index("Date").reindex(d.index)
    data, long, invalid = [], [], []
    expected_times = [
        f"{h:02d}:{v:02d}"
        for h, start, end in (
            (9, 35, 60),
            (10, 0, 60),
            (11, 0, 35),
            (13, 5, 60),
            (14, 0, 60),
            (15, 0, 5),
        )
        for v in range(start, end, 5)
    ]
    for day, g in m.groupby("day", sort=True):
        g = g.sort_values("Date")
        if (
            g.Date.dt.strftime("%H:%M").tolist() != expected_times
            or not g.AvailableDate.le(day + pd.Timedelta(hours=17)).all()
            or not np.isfinite(g[["Close", "Volume"]].to_numpy()).all()
            or not g.Close.gt(0).all()
            or not g.Volume.ge(0).all()
            or g.Volume.iloc[1:].sum() <= 0
        ):
            invalid.append(str(day.date()))
            continue
        prices = g.Close.to_numpy()
        volumes = g.Volume.to_numpy()
        r = np.diff(np.log(prices))
        weights = volumes[1:] / volumes[1:].sum()
        worst = int(np.argmin(r)) + 1
        row = {
            "Date": day,
            "sell_pressure": float(np.sum(weights * r)),
            "late_volume": float(volumes[-12:].sum() / volumes.sum()),
            "volume_concentration": float(np.sum((volumes / volumes.sum()) ** 2)),
            "efficiency": float(np.log(prices[-1] / prices[0]) / (np.abs(r).sum() + 1e-12)),
            "shock": float(r[worst - 1]),
            "recovery": float(np.log(prices[-1] / prices[worst])),
            "shock_time": float(worst / 47),
            "thin_impact": float(
                np.abs(r)[volumes[1:] < np.median(volumes[1:])].sum() / (np.abs(r).sum() + 1e-12)
            ),
            "morning": float(np.log(prices[23] / prices[0])),
            "afternoon": float(np.log(prices[-1] / prices[23])),
            "last_hour": float(np.log(prices[-1] / prices[35])),
            "vwap_close_proxy_gap": float(prices[-1] / np.average(prices, weights=volumes) - 1),
        }
        data.append(row)
        long.extend({"id": day.value, "time": i, "return": v} for i, v in enumerate(r))
    f = pd.DataFrame(data).set_index("Date").reindex(d.index)
    fresh = extract_features(
        pd.DataFrame(long),
        column_id="id",
        column_sort="time",
        default_fc_parameters=FRESH,
        n_jobs=workers,
        disable_progressbar=True,
    )
    fresh.index = pd.to_datetime(fresh.index)
    fresh.columns = ["fresh_" + c for c in fresh.columns]
    f = f.join(fresh)
    inputs = pd.DataFrame(
        {
            "date": d.index,
            "asset": "518850.SH",
            "Close": d.Close.to_numpy(),
            "Open": d.Open.to_numpy(),
            "VWAP": (d.Amount / d.Volume).to_numpy(),
            "PeerClose": p.Close.to_numpy(),
            "PeerOpen": p.Open.to_numpy(),
        }
    )
    computed = codegen_exec(
        inputs, EXPRESSIONS, over_null=None, style="pandas", output_file=generated
    )
    reference = {
        "intraday": d.Close / d.Open - 1,
        "vwap_gap": d.Close / (d.Amount / d.Volume) - 1,
        "peer_gap": d.Close * p.Open / (d.Open * p.Close) - 1,
    }
    for key, value in reference.items():
        np.testing.assert_allclose(computed[key], value, equal_nan=True, atol=1e-12, rtol=1e-12)
        f[key] = computed[key].to_numpy()
    f["day_return"] = d.Close.pct_change(fill_method=None)
    f["return3"] = d.Close.pct_change(3, fill_method=None)
    f["volume_ratio"] = d.Volume / d.Volume.shift(1).rolling(20).mean()
    f["range"] = (d.High - d.Low) / d.Close
    f["location"] = (d.Close - d.Low) / (d.High - d.Low).replace(0, np.nan)
    f["momentum20"] = d.Close.pct_change(20, fill_method=None)
    f["volatility20"] = f.day_return.rolling(20).std()
    # Next two historical trading dates are calendar metadata, not future prices.
    f["closure_days"] = (
        pd.Series(d.index, index=d.index)
        .shift(-2)
        .sub(pd.Series(d.index, index=d.index).shift(-1))
        .dt.days
    )
    # Same-day complete path at 17:00, never a pre-close executable signal.
    return d, f, invalid


def make_signals(f):
    signals, thresholds, valids = {}, {}, {}
    feature_cols = [
        c
        for c in f
        if c
        not in (
            "day_return",
            "return3",
            "volume_ratio",
            "intraday",
            "vwap_gap",
            "range",
            "location",
            "momentum20",
            "volatility20",
            "closure_days",
        )
    ]
    for col in feature_cols:
        lo, hi = pd.Series(np.nan, index=f.index), pd.Series(np.nan, index=f.index)
        for year in sorted(set(f.index.year)):
            history = f.loc[f.index.year < year, col].dropna()
            if len(history) >= 252:
                lo.loc[f.index.year == year] = history.quantile(0.25)
                hi.loc[f.index.year == year] = history.quantile(0.75)
        signals[col + "_low"] = f[col].lt(lo)
        signals[col + "_high"] = f[col].gt(hi)
        valids[col + "_low"] = f[col].notna() & lo.notna()
        valids[col + "_high"] = f[col].notna() & hi.notna()
        thresholds[col] = {"low": lo, "high": hi}
    s = pd.DataFrame(signals, index=f.index)
    s["selling_absorbed"] = s.sell_pressure_low & s.recovery_high & f.shock_time.lt(0.75)
    s["unrecovered_late_shock"] = s.shock_low & s.recovery_low & f.shock_time.ge(0.75)
    s["afternoon_repair"] = f.morning.lt(0) & f.afternoon.gt(0) & s.late_volume_high
    s["afternoon_continuation"] = f.morning.gt(0) & f.afternoon.gt(0) & s.late_volume_high
    s["dry_pullback"] = f.afternoon.lt(0) & s.late_volume_low & f.return3.gt(0)
    s["flow_divergence"] = s.sell_pressure_high & f.day_return.lt(0)
    s["efficient_advance"] = s.efficiency_high & s.volume_concentration_low & f.day_return.gt(0)
    s["peer_lag_absorbed"] = s.peer_gap_low & s.recovery_high
    s["thin_shock_recovered"] = s.thin_impact_high & s.recovery_high & f.day_return.lt(0)
    s["pre_long_closure"] = f.closure_days.ge(4)
    s["pre_weekend"] = f.closure_days.eq(3)
    s["daily_reversal_control"] = f.day_return.lt(0)
    s["daily_momentum_control"] = f.return3.gt(0)
    dependencies = {
        "selling_absorbed": ["sell_pressure", "recovery", "shock_time"],
        "unrecovered_late_shock": ["shock", "recovery", "shock_time"],
        "afternoon_repair": ["morning", "afternoon", "late_volume"],
        "afternoon_continuation": ["morning", "afternoon", "late_volume"],
        "dry_pullback": ["afternoon", "late_volume", "return3"],
        "flow_divergence": ["sell_pressure", "day_return"],
        "efficient_advance": ["efficiency", "volume_concentration", "day_return"],
        "peer_lag_absorbed": ["peer_gap", "recovery"],
        "thin_shock_recovered": ["thin_impact", "recovery", "day_return"],
        "pre_long_closure": ["closure_days"],
        "pre_weekend": ["closure_days"],
        "daily_reversal_control": ["day_return"],
        "daily_momentum_control": ["return3"],
    }
    for name, cols in dependencies.items():
        valids[name] = f[cols].notna().all(axis=1)
        for col in cols:
            if col in thresholds:
                valids[name] &= thresholds[col]["low"].notna()
    return (
        s,
        pd.concat({c: pd.DataFrame(v) for c, v in thresholds.items()}, axis=1),
        pd.DataFrame(valids, index=f.index),
    )


def summary(d, f, s, valids, bad, workers):
    records, annual, panels = [], [], []
    valid = f.sell_pressure.notna() & (f.index.year >= 2022)
    badmask = pd.Series([str(t.date()) in bad for t in d.index], index=d.index)
    for h in (1, 3, 5):
        for delay in (0, 2):
            ratio = d.Open.shift(-h - delay - 1) / d.Open.shift(-delay - 1)
            gross = ratio - 1
            clean = ~pd.concat(
                [badmask.shift(-k, fill_value=False) for k in range(h + delay + 2)], axis=1
            ).any(axis=1)
            limit = np.floor((d.Close + 1e-10) / 0.001) * 0.001
            entry = d.Open.shift(-delay - 1)
            fill = entry.where(entry.le(limit), limit.where(d.Low.shift(-delay - 1).le(limit)))
            limitnet = d.Open.shift(-h - delay - 1) / fill * 0.999 / 1.001 - 1
            for fee in (0.001, 0.002):
                net = ratio * (1 - fee) / (1 + fee) - 1
                eligible = valid & net.notna()
                controls = pd.DataFrame(
                    {
                        "year": d.index.year,
                        "r1": f.day_return,
                        "r3": f.return3,
                        "v": f.volume_ratio,
                    },
                    index=d.index,
                )
                # Price/volume rank cells are retrospective matched diagnostics, not inputs.
                cells = controls.groupby("year", group_keys=False)[["r1", "r3", "v"]].transform(
                    lambda x: pd.qcut(x.rank(method="first"), 3, labels=False, duplicates="drop")
                )
                key = pd.Series(
                    [
                        f"{y}_{a}_{b}_{c}"
                        for y, a, b, c in zip(d.index.year, cells.r1, cells.r3, cells.v)
                    ],
                    index=d.index,
                )
                X = f[
                    [
                        "day_return",
                        "return3",
                        "volume_ratio",
                        "range",
                        "location",
                        "momentum20",
                        "volatility20",
                    ]
                ].copy()
                X = X.join(
                    pd.get_dummies(
                        pd.Series(d.index.year, index=d.index), dtype=float, prefix="year"
                    )
                )
                X.insert(0, "constant", 1.0)

                def calc(name):
                    out = []
                    for sensitivity in ("all", "quality_clean"):
                        owneligible = eligible & valids[name]
                        mask = owneligible & s[name]
                        if sensitivity != "all":
                            mask &= clean
                        # Use exactly the same eligibility for retrospective controls.
                        controlmask = owneligible & (clean if sensitivity != "all" else True)
                        base = gross[controlmask].groupby(key[controlmask]).mean()
                        diff = net - key.map(base)
                        fitmask = controlmask & X.notna().all(axis=1)
                        beta = np.linalg.lstsq(
                            X.loc[fitmask].to_numpy(), gross[fitmask].to_numpy(), rcond=None
                        )[0]
                        residual = net - pd.Series(X.to_numpy() @ beta, index=d.index)
                        ids = np.flatnonzero(mask.to_numpy())
                        chosen = []
                        nxt = 0
                        for i in ids:
                            if i >= nxt:
                                chosen.append(int(i))
                                nxt = int(i) + h + 1
                        values = net[mask]
                        yearly = [
                            {
                                "signal": name,
                                "horizon": h,
                                "delay": delay,
                                "fee": fee,
                                "sensitivity": sensitivity,
                                "year": int(y),
                                "events": int((mask & (d.index.year == y)).sum()),
                                "net_mean": number(net[mask & (d.index.year == y)].mean()),
                                "increment": number(diff[mask & (d.index.year == y)].mean()),
                            }
                            for y in sorted(set(d.index.year))
                        ]
                        limitvalues = (
                            (d.Open.shift(-h - delay - 1) / fill * (1 - fee) / (1 + fee) - 1)
                            .iloc[chosen]
                            .dropna()
                        )
                        out.append(
                            (
                                {
                                    "signal": name,
                                    "horizon": h,
                                    "delay": delay,
                                    "fee": fee,
                                    "sensitivity": sensitivity,
                                    "events": len(values),
                                    "net_mean": number(values.mean()),
                                    "increment": number(diff[mask].mean()),
                                    "price_volume_control_increment": number(residual[mask].mean()),
                                    "nonoverlap_events": len(chosen),
                                    "nonoverlap_net": number(net.iloc[chosen].mean()),
                                    "limit_fills": len(limitvalues),
                                    "limit_per60": len(limitvalues) * 60 / len(d),
                                    "limit_net": number(limitvalues.mean()),
                                    "eligible": int(controlmask.sum()),
                                    "without_best5": number(values.sort_values().iloc[:-5].mean())
                                    if len(values) > 5
                                    else None,
                                    "without_2025": number(
                                        net[mask & (d.index.year != 2025)].mean()
                                    ),
                                    "positive_years": sum(
                                        x["increment"] is not None and x["increment"] > 0
                                        for x in yearly
                                    ),
                                },
                                yearly,
                            )
                        )
                    return out

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    for results in pool.map(calc, s.columns):
                        for row, years in results:
                            records.append(row)
                            annual.extend(years)
            panel = pd.DataFrame(
                {
                    "net": ratio * 0.999 / 1.001 - 1,
                    "limit_net": limitnet,
                    "clean": clean,
                    "valid": eligible,
                },
                index=d.index,
            )
            panels.append((f"h{h}_delay{delay}", panel))
    # Dependent block permutation of primary-horizon association; adjustment across all signals.
    rng = np.random.default_rng(12015)
    y = panels[4][1]["net"]  # horizon5 delay0
    ic = []
    for name in s:
        mask = valid & y.notna() & valids[name]
        a = s.loc[mask, name].to_numpy(dtype=float)
        b = y[mask].to_numpy()
        observed = abs(spearmanr(a, b).statistic) if a.std() > 0 else 0.0
        years = d.index[mask].year.to_numpy()
        count = 0
        for _ in range(199):
            shuffled = b.copy()
            for year in np.unique(years):
                ids = np.flatnonzero(years == year)
                part = b[ids]
                blocks = [part[i : i + 20] for i in range(0, len(part), 20)]
                shuffled[ids] = np.concatenate([blocks[i] for i in rng.permutation(len(blocks))])
            value = abs(spearmanr(a, shuffled).statistic) if a.std() > 0 else 0.0
            count += value >= observed
        ic.append(
            {
                "signal": name,
                "ic": number(spearmanr(a, b).statistic) if a.std() > 0 else None,
                "p": (count + 1) / 200,
            }
        )
    order = sorted(range(len(ic)), key=lambda i: ic[i]["p"])
    q = 1.0
    for rank, i in reversed(list(enumerate(order, 1))):
        q = min(q, ic[i]["p"] * len(ic) / rank)
        ic[i]["q"] = q
    return records, annual, ic, pd.concat(dict(panels), axis=1)


def number(value):
    return float(value) if pd.notna(value) and np.isfinite(value) else None
