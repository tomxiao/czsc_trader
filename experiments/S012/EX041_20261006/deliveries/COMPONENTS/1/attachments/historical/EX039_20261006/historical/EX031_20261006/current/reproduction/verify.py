"""Independent source/time/signal and numerical audit; never imports experiment code."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd

ROOT = Path.cwd()
EXP = ROOT / "experiments/S012/EX031_20261006"
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
pd.testing.assert_frame_equal(f[list(raw["baseline"].columns)], raw["baseline"])
for key in ("gvz", "usdollar"):
    raw[key] = pd.read_parquet(P / f"data/{key}.parquet")
    raw[key].attrs = {}
    raw[key] = raw[key].set_index(pd.to_datetime(raw[key].Date)).sort_index()
g = raw["gvz"]
u = raw["usdollar"]
expected_available = pd.concat(
    [pd.Series(g.index, index=g.index), pd.to_datetime(g.InitialReleaseDate)], axis=1
).max(axis=1) + pd.Timedelta(days=1, hours=16)
pd.testing.assert_series_equal(
    pd.to_datetime(g.AvailableDate), expected_available, check_names=False
)
assert (pd.to_datetime(u.AvailableDate).to_numpy() == u.index + pd.Timedelta(days=2, hours=8)).all()
assert g.index.max() == pd.Timestamp("2026-09-30") and u.index.max() == pd.Timestamp("2023-06-01")
vx = raw["vix"].set_index(pd.to_datetime(raw["vix"].Date)).sort_index()
pair = vx.Close.rename("vix").to_frame().join(g[["Close", "AvailableDate"]], how="inner")
ratio = pair.vix / pair.Close
native = {
    "gvz": {"gvz5": g.Close - g.Close.shift(5), "gvz_level": g.Close},
    "usdollar": {"usd5": u.BidClose / u.BidClose.shift(5) - 1},
    "vix_level": {"vix_level": vx.Close},
    "relative_risk": {
        "risk_ratio": ratio,
        "ratio_median": ratio.rolling(126, min_periods=63).median().shift(1),
    },
}
native_available = {
    "gvz": pd.to_datetime(g.AvailableDate),
    "usdollar": pd.to_datetime(u.AvailableDate),
    "vix_level": pd.Series(vx.index + pd.Timedelta(days=1, hours=8, minutes=30), index=vx.index),
    "relative_risk": pd.concat(
        [
            pd.to_datetime(pair.AvailableDate),
            pd.Series(pair.index + pd.Timedelta(days=1, hours=8, minutes=30), index=pair.index),
        ],
        axis=1,
    ).max(axis=1),
}
for prefix, columns in native.items():
    availability = native_available[prefix].sort_values(kind="stable")
    ids = availability.index.to_numpy()
    times = availability.to_numpy()
    for j, day in enumerate(d.index):
        decision = day + pd.Timedelta(hours=17)
        pos = np.searchsorted(times, decision.to_datetime64(), side="right") - 1
        found = pos >= 0 and decision - pd.Timestamp(times[pos]) <= pd.Timedelta(days=7)
        found = found and (prefix != "usdollar" or day <= pd.Timestamp("2023-06-01"))
        observed = a[prefix + "_SourceDate"].iloc[j]
        assert (pd.Timestamp(observed) == pd.Timestamp(ids[pos])) if found else pd.isna(observed), (
            prefix,
            str(day),
            str(observed),
            str(ids[pos]),
            str(times[pos]),
            found,
        )
        if found:
            assert pd.Timestamp(times[pos]) <= decision and pd.Timestamp(ids[pos]) < day
            assert a[prefix + "_AvailableDate"].iloc[j] == pd.Timestamp(times[pos])
        for key, series in columns.items():
            eq(f[key].iloc[j], series.loc[pd.Timestamp(ids[pos])] if found else np.nan)
        count += 3
# Derive each signal independently, directly from the audited features.
safe = (f.vix5 > 0) & (f.xau5 > 0)
m05 = safe & (f.gold_vix_corr60 > 0)
high = f.risk_ratio > f.ratio_median
requirements = {
    "C_GOLD": ["xau20"],
    "C_SAFE": ["vix5", "xau5"],
    "C_M05": ["vix5", "xau5", "gold_vix_corr60"],
    "C_USD": ["usd5"],
    "U01": ["usd5", "xau20"],
    "U02": ["usd5", "vix5", "xau5"],
    "U03": ["usd5", "vix5", "xau5"],
    "U04": ["usd5", "risk_ratio", "ratio_median", "vix5", "xau5"],
    "V01": ["risk_ratio", "ratio_median", "vix5", "xau5"],
    "V02": ["risk_ratio", "ratio_median", "vix5", "xau5"],
    "V03": ["gvz5", "xau20"],
    "V04": ["gvz5", "xau20"],
    "V05": ["risk_ratio", "ratio_median", "vix5", "xau5", "gold_vix_corr60"],
}
conditions = {
    "C_GOLD": f.xau20 > 0,
    "C_SAFE": safe,
    "C_M05": m05,
    "C_USD": f.usd5 < 0,
    "U01": (f.usd5 < 0) & (f.xau20 > 0),
    "U02": (f.usd5 < 0) & safe,
    "U03": (f.usd5 >= 0) & safe,
    "U04": (f.usd5 < 0) & high & safe,
    "V01": high & safe,
    "V02": (f.risk_ratio <= f.ratio_median) & safe,
    "V03": (f.gvz5 < 0) & (f.xau20 > 0),
    "V04": (f.gvz5 >= 0) & (f.xau20 > 0),
    "V05": high & m05,
}
for key, cols in requirements.items():
    valid = f[cols].notna().all(axis=1)
    np.testing.assert_array_equal(v[key], valid)
    np.testing.assert_array_equal(s[key], valid & conditions[key])
    count += 2 * len(d)
assert not s.loc[s.index > "2023-06-01", ["C_USD", "U01", "U02", "U03", "U04"]].any().any()

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
                xx = f.loc[mask, ["etf5", "etf20", "vol20", "xau20", "fx5", "vix_level"]].to_numpy()
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
                values["ols_increment"] = (
                    np.linalg.pinv(design).dot(net[mask])[1]
                    if len(xx) >= 20
                    and len(set(s[key].to_numpy()[mask])) == 2
                    and np.linalg.matrix_rank(design) == design.shape[1]
                    else np.nan
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
    len(specs) == 9
    and len(s.columns) == 13
    and len(metrics) == 260
    and len(annual) == 1820
    and len(inference) == 9
)
out = {
    "status": "PASS",
    "scope": "独立前驱SHA、源可得政策、原生变化、比值配对、全部特征/信号有效位、20标签场景、260路径、1820年度、BH9；不复现bootstrap/循环移位抽样，不证明历史逐条发布时间或账户绩效。",
    "numerical_fields_checked": count,
    "sessions": len(d),
    "hypotheses": 9,
    "paths": 260,
    "annual_rows": 1820,
    "bh_family": len(ps),
}
(EXP / "artifacts/verification").mkdir(parents=True, exist_ok=True)
(EXP / "artifacts/verification/independent.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps(out, ensure_ascii=False))
