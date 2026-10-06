"""Independent source/time/signal and numerical audit; never imports experiment code."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd

ROOT = Path.cwd()
EXP = ROOT / "experiments/S012/EX032_20261006"
P = EXP / "artifacts/rex"


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


d = pd.read_parquet(P / "daily.parquet")
f = pd.read_parquet(P / "features.parquet")
s = pd.read_parquet(P / "signals.parquet")
v = pd.read_parquet(P / "valids.parquet")
a = pd.read_parquet(P / "alignment.parquet")
stored = pd.read_parquet(P / "labels.parquet")
specs = read(P / "hypothesis_definitions.json")
parents = {x["id"]: x["parent"] for x in specs}
metrics = read(P / "opportunities.json")
annual = read(P / "annual.json")
count = 0


def eq(actual, expected):
    global count
    if actual is None:
        assert not np.isfinite(expected), (actual, expected)
    else:
        np.testing.assert_allclose(actual, expected, rtol=2e-9, atol=2e-12)
    count += 1


def mean(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return x.mean() if len(x) else np.nan


def schedule(mask, gap):
    out = []
    for n in range(len(mask)):
        if mask[n] and (not out or n - out[-1] >= gap):
            out.append(n)
    return np.array(out, dtype=int)


raw = {}
for key, ref in read(P / "source_hashes.json").items():
    source = ROOT / "experiments/S012" / ref["experiment_id"] / "artifacts/rex" / ref["artifact"]
    assert sha256(source.read_bytes()).hexdigest() == ref["sha256"]
    raw[key] = pd.read_parquet(source)
    raw[key].attrs = {}
unchanged = [
    c for c in raw["baseline"] if c not in ("usd5", "vix_level", "risk_ratio", "ratio_median")
]
pd.testing.assert_frame_equal(f[unchanged], raw["baseline"][unchanged])
g = raw["gvz"].set_index(pd.to_datetime(raw["gvz"].Date)).sort_index()
u = raw["usdollar"].set_index(pd.to_datetime(raw["usdollar"].Date)).sort_index()
expected_available = pd.concat(
    [pd.Series(g.index, index=g.index), pd.to_datetime(g.InitialReleaseDate)], axis=1
).max(axis=1) + pd.Timedelta(days=1, hours=16)
pd.testing.assert_series_equal(
    pd.to_datetime(g.AvailableDate), expected_available, check_names=False
)
assert (pd.to_datetime(u.AvailableDate).to_numpy() == u.index + pd.Timedelta(days=2, hours=8)).all()
vx = raw["vix"].set_index(pd.to_datetime(raw["vix"].Date)).sort_index()
pair = vx.Close.rename("vix").to_frame().join(g[["Close", "AvailableDate"]], how="inner")
ratio = pair.vix / pair.Close
native = {
    "paired_risk": {
        "pair_vix": pair.vix,
        "pair_gvz": pair.Close,
        "vix_median": pair.vix.rolling(126, min_periods=63).median().shift(1),
        "gvz_median": pair.Close.rolling(126, min_periods=63).median().shift(1),
        "risk_ratio": ratio,
        "ratio_median": ratio.rolling(126, min_periods=63).median().shift(1),
        "pair_gvz5": pair.Close - pair.Close.shift(5),
        "vix_log5": np.log(pair.vix / pair.vix.shift(5)),
        "gvz_log5": np.log(pair.Close / pair.Close.shift(5)),
        "ratio_log5": np.log(ratio / ratio.shift(5)),
    },
    "usdollar": {"usd5": u.BidClose / u.BidClose.shift(5) - 1},
    "vix_level": {"vix_level": vx.Close},
}
native_available = {
    "paired_risk": pd.concat(
        [
            pd.to_datetime(pair.AvailableDate),
            pd.Series(pair.index + pd.Timedelta(days=1, hours=8, minutes=30), index=pair.index),
        ],
        axis=1,
    ).max(axis=1),
    "usdollar": pd.to_datetime(u.AvailableDate),
    "vix_level": pd.Series(vx.index + pd.Timedelta(days=1, hours=8, minutes=30), index=vx.index),
}
for prefix, columns in native.items():
    # Independent latest-release selection: lexicographic (availability, observation).
    table = pd.DataFrame(
        {"date": native_available[prefix].index, "time": native_available[prefix].values}
    ).sort_values(["time", "date"])
    ids, times = table.date.to_numpy(), table.time.to_numpy()
    for j, day in enumerate(d.index):
        decision = day + pd.Timedelta(hours=17)
        pos = np.searchsorted(times, decision.to_datetime64(), side="right") - 1
        found = pos >= 0 and decision - pd.Timestamp(times[pos]) <= pd.Timedelta(days=7)
        found = found and (prefix != "usdollar" or day <= pd.Timestamp("2023-06-01"))
        observed = a[prefix + "_SourceDate"].iloc[j]
        assert (pd.Timestamp(observed) == pd.Timestamp(ids[pos])) if found else pd.isna(observed)
        if found:
            assert pd.Timestamp(times[pos]) <= decision and pd.Timestamp(ids[pos]) < day
            assert a[prefix + "_AvailableDate"].iloc[j] == pd.Timestamp(times[pos])
        for key, series in columns.items():
            eq(f[key].iloc[j], series.loc[pd.Timestamp(ids[pos])] if found else np.nan)
        count += 3
safe = (f.vix5 > 0) & (f.xau5 > 0)
m05 = safe & (f.gold_vix_corr60 > 0)
low = f.risk_ratio <= f.ratio_median
vl = f.pair_vix <= f.vix_median
gl = f.pair_gvz <= f.gvz_median
rise = f.pair_gvz5 >= 0
gold = f.xau20 > 0
usdtrend = (f.usd5 < 0) & gold
sr = ["vix5", "xau5"]
rr = ["risk_ratio", "ratio_median"]
qr = ["pair_vix", "pair_gvz", "vix_median", "gvz_median"]
conditions = {
    "C_SAFE": safe,
    "C_M05": m05,
    "C_GOLD": gold,
    "C_CATCHUP": f.xau5 > 0,
    "C_USDTREND": usdtrend,
    "D01": low & safe,
    "D02": low & m05,
    "D03": vl & gl & safe,
    "D04": vl & ~gl & safe,
    "D05": ~vl & gl & safe,
    "D06": ~vl & ~gl & safe,
    "D07": rise & gold & (f.xau5 > 0),
    "D08": rise & gold & (f.xau5 <= 0),
    "D09": rise & (f.xau5 > 0) & (f.etf5 <= 0),
    "D10": rise & (f.xau5 > 0) & (f.etf5 > 0),
    "D11": low & safe & (f.etf3 <= 0),
    "D12": low & safe & (f.etf3 > 0),
    "D13": usdtrend & rise,
    "D14": usdtrend & (f.pair_gvz5 < 0),
}
requirements = {
    "C_SAFE": sr,
    "C_M05": sr + ["gold_vix_corr60"],
    "C_GOLD": ["xau20"],
    "C_CATCHUP": ["xau5"],
    "C_USDTREND": ["usd5", "xau20"],
    "D01": sr + rr,
    "D02": sr + rr + ["gold_vix_corr60"],
    **{k: sr + qr for k in ("D03", "D04", "D05", "D06")},
    **{k: ["pair_gvz5", "xau20", "xau5"] for k in ("D07", "D08")},
    **{k: ["pair_gvz5", "xau5", "etf5"] for k in ("D09", "D10")},
    **{k: sr + rr + ["etf3"] for k in ("D11", "D12")},
    **{k: ["usd5", "xau20", "pair_gvz5"] for k in ("D13", "D14")},
}
for key, cols in requirements.items():
    valid = f[cols].notna().all(axis=1)
    np.testing.assert_array_equal(v[key], valid)
    np.testing.assert_array_equal(s[key], valid & conditions[key])
    count += 2 * len(d)
assert not s.loc[s.index > "2023-06-01", ["C_USDTREND", "D13", "D14"]].any().any()
np.testing.assert_allclose(f.ratio_log5, f.vix_log5 - f.gvz_log5, equal_nan=True, atol=1e-12)


def residual_for(mask, net):
    cells = f.loc[mask, ["etf5", "vol20", "xau20", "fx5"]].copy()
    cells["year"] = cells.index.year
    cells["bucket"] = cells.vol20.groupby(cells.year).transform(
        lambda x: np.searchsorted(x.quantile([1 / 3, 2 / 3]).to_numpy(), x.to_numpy(), side="right")
    )
    cells["etf_sign"] = cells.etf5 > 0
    cells["gold_sign"] = cells.xau20 > 0
    cells["fx_sign"] = cells.fx5 > 0
    cells["net"] = net[mask]
    baseline = cells.groupby(["year", "etf_sign", "gold_sign", "fx_sign", "bucket"]).net.transform(
        "mean"
    )
    out = np.full(len(d), np.nan)
    out[mask] = cells.net.to_numpy() - baseline.to_numpy()
    return out


def independently_ols(mask, net, key, extra=()):
    columns = ["etf5", "etf20", "vol20", "xau20", "fx5", "vix_level", *extra]
    mask = mask & f[columns].notna().all(axis=1).to_numpy()
    xx = f.loc[mask, columns].to_numpy()
    if len(xx) < 20 or len(set(s[key].to_numpy()[mask])) != 2:
        return np.nan
    yy = d.index[mask].year
    sd = xx.std(axis=0)
    sd[sd == 0] = 1
    design = np.column_stack(
        [
            np.ones(len(xx)),
            s[key].to_numpy()[mask],
            (xx - xx.mean(axis=0)) / sd,
            *[(yy == y).astype(float) for y in sorted(set(yy))[1:]],
        ]
    )
    return (
        np.linalg.pinv(design).dot(net[mask])[1]
        if np.linalg.matrix_rank(design) == design.shape[1]
        else np.nan
    )


for h in (1, 3, 5, 10, 20):
    for delay in (0, 2):
        entry = np.full(len(d), np.nan)
        exitp = entry.copy()
        low = entry.copy()
        offset = 1 + delay
        entry[:-offset] = d.Open.to_numpy()[offset:]
        low[:-offset] = d.Low.to_numpy()[offset:]
        exitp[: -offset - h] = d.Open.to_numpy()[offset + h :]
        gross = exitp / entry - 1
        limit = np.trunc((d.Close.to_numpy() + 1e-10) / 0.001) * 0.001
        price = np.where(entry <= limit, entry, np.where(low <= limit, limit, np.nan))
        idlog = np.full(len(d), np.nan)
        onlog = idlog.copy()
        for t in range(len(d) - offset - h + 1):
            ix = slice(t + offset, t + offset + h)
            idlog[t] = np.log(d.Close.to_numpy()[ix] / d.Open.to_numpy()[ix]).sum()
            if t + offset + h < len(d):
                onlog[t] = np.log(
                    d.Open.to_numpy()[t + offset + 1 : t + offset + h + 1] / d.Close.to_numpy()[ix]
                ).sum()
        for fee in (0.001, 0.002):
            net = (1 + gross) * (1 - fee) / (1 + fee) - 1
            limit_net = exitp / price * (1 - fee) / (1 + fee) - 1
            for col, values in [
                ("net", net),
                ("limit_net", limit_net),
                ("gross", gross),
                ("intraday_log", idlog),
                ("overnight_log", onlog),
            ]:
                np.testing.assert_allclose(
                    stored[f"h{h}_d{delay}_f{fee}__{col}"], values, equal_nan=True, atol=1e-12
                )
                count += len(d)
            for r in (
                r for r in metrics if (r["horizon"], r["delay"], r["fee"]) == (h, delay, fee)
            ):
                key = r["signal"]
                par = parents.get(key)
                mask = (
                    v[key].to_numpy()
                    & np.isfinite(net)
                    & f[["etf5", "etf20", "vol20", "xau20", "fx5", "vix_level"]]
                    .notna()
                    .all(axis=1)
                    .to_numpy()
                )
                if par:
                    mask &= v[par].to_numpy()
                hit = mask & s[key].to_numpy()
                phit = mask & (s[par].to_numpy() if par else True)
                chosen = schedule(hit, h + 1)
                pa = schedule(phit, h + 1)
                filled = chosen[np.isfinite(limit_net[chosen])]
                cells = f.loc[mask, ["etf5", "vol20", "xau20", "fx5"]].copy()
                cells["year"] = cells.index.year
                cuts = cells.vol20.groupby(cells.year).transform(
                    lambda x: np.searchsorted(
                        x.quantile([1 / 3, 2 / 3]).to_numpy(), x.to_numpy(), side="right"
                    )
                )
                cells["etf_sign"] = cells.etf5 > 0
                cells["gold_sign"] = cells.xau20 > 0
                cells["fx_sign"] = cells.fx5 > 0
                cells["bucket"] = cuts
                cells["net"] = net[mask]
                baseline = cells.groupby(
                    ["year", "etf_sign", "gold_sign", "fx_sign", "bucket"]
                ).net.transform("mean")
                residual = np.full(len(d), np.nan)
                residual[mask] = cells.net.to_numpy() - baseline.to_numpy()
                values = {
                    "eligible_days": mask.sum(),
                    "events": hit.sum(),
                    "parent_events": phit.sum(),
                    "net_mean": mean(net[hit]),
                    "unconditional_same_fee": mean(net[mask]),
                    "parent_same_fee": mean(net[phit]),
                    "parent_lift": mean(net[hit]) - mean(net[phit]),
                    "matched_increment": mean(residual[hit]),
                    "nonoverlap_events": len(chosen),
                    "nonoverlap_net": mean(net[chosen]),
                    "limit_potential_fills": len(filled),
                    "limit_potential_net": mean(limit_net[filled]),
                    "potential_per60_original1535": len(filled) * 60 / 1535,
                    "intraday_log_mean": mean(idlog[hit]),
                    "overnight_log_mean": mean(onlog[hit]),
                    "fixed_parent_base_contribution": mean(net[pa]),
                    "fixed_parent_filtered_contribution": mean(net[pa] * s[key].to_numpy()[pa]),
                }
                pr = residual_for(phit, net)
                values.update(
                    {
                        "parent_matched_increment": mean(pr[hit]),
                        "ols_increment": independently_ols(mask, net, key),
                        "parent_ols_increment": independently_ols(phit, net, key),
                        "ols_same_risk_window": independently_ols(
                            mask & f[["pair_vix", "pair_gvz"]].notna().all(axis=1).to_numpy(),
                            net,
                            key,
                        ),
                        "ols_with_both_risks": independently_ols(
                            mask, net, key, ("pair_vix", "pair_gvz")
                        ),
                        "ratio_change_mean": mean(f.ratio_log5[hit]),
                        "vix_change_mean": mean(f.vix_log5[hit]),
                        "gvz_change_mean": mean(f.gvz_log5[hit]),
                    }
                )
                for k, x in values.items():
                    eq(r[k], x)
                for aa in (
                    x
                    for x in annual
                    if (x["signal"], x["horizon"], x["delay"], x["fee"]) == (key, h, delay, fee)
                ):
                    am = mask & (d.index.year == aa["year"])
                    ah = hit & am
                    for k, x in [
                        ("eligible_days", am.sum()),
                        ("events", ah.sum()),
                        ("net_mean", mean(net[ah])),
                        ("matched_increment", mean(residual[ah])),
                        ("parent_matched_increment", mean(pr[ah])),
                    ]:
                        eq(aa[k], x)

inference = read(P / "inference.json")
ps = sorted((x["p"], x["signal"]) for x in inference if x["p"] is not None)
independent_q = {}
last = 1.0
for rank in range(len(ps), 0, -1):
    p, key = ps[rank - 1]
    last = min(last, p * len(ps) / rank)
    independent_q[key] = last
for x in inference:
    eq(x["q"], independent_q[x["signal"]])

assert (
    len(specs) == 14
    and len(s.columns) == 19
    and len(metrics) == 380
    and len(annual) == 2660
    and len(inference) == 14
)
out = {
    "status": "PASS",
    "scope": "独立前驱SHA、源可得政策、原生变化、比值配对、全部特征/信号有效位、20标签场景、380路径、2660年度、父事件内匹配/OLS、双风险同窗口OLS及对数来源分解、BH14；不复现bootstrap/循环移位抽样，不证明历史逐条发布时间或账户绩效。",
    "numerical_fields_checked": count,
    "sessions": len(d),
    "hypotheses": 14,
    "paths": 380,
    "annual_rows": 2660,
    "bh_family": len(ps),
}
(EXP / "artifacts/verification").mkdir(parents=True, exist_ok=True)
(EXP / "artifacts/verification/independent.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps(out, ensure_ascii=False))
