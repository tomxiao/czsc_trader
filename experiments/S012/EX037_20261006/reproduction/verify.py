"""Independent source/time/signal and numerical audit; never imports experiment code."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd

ROOT = Path.cwd()
EXP = ROOT / "experiments/S012/EX037_20261006"
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
    receipt = (
        read(source.parents[0] / "execution_receipt.json")
        if "/" not in ref["artifact"]
        else read(
            ROOT
            / "experiments/S012"
            / ref["experiment_id"]
            / "artifacts/rex/execution_receipt.json"
        )
    )
    assert receipt["artifact_sha256"][ref["artifact"]] == ref["sha256"]
    raw[key] = pd.read_parquet(source) if source.suffix == ".parquet" else read(source)
    if isinstance(raw[key], pd.DataFrame):
        raw[key].attrs = {}
pd.testing.assert_frame_equal(d, raw["daily"])
pd.testing.assert_frame_equal(f[raw["baseline"].columns], raw["baseline"])
m = raw["minute"]
m["day"] = pd.to_datetime(m.Date).dt.normalize()
m["time"] = pd.to_datetime(m.Date).dt.strftime("%H:%M")
z = m.pivot(index="day", columns="time", values="Close").reindex(d.index)
expected = {
    "morning": z["11:30"] / d.Open - 1,
    "afternoon": z["15:00"] / z["11:30"] - 1,
    "tail": z["15:00"] / z["14:00"] - 1,
    "own_day": d.Close / d.Open - 1,
}
for k, x in expected.items():
    np.testing.assert_allclose(f[k], x, equal_nan=True, atol=1e-12)
    count += len(d)
md = raw["minute_daily"].copy()
md["Date"] = pd.to_datetime(md.Date)
pd.testing.assert_frame_equal(
    d[["Open", "High", "Low", "Close", "Volume", "Amount"]],
    md.set_index("Date")[["Open", "High", "Low", "Close", "Volume", "Amount"]],
    check_freq=False,
)
assert m.groupby("day").size().eq(8).all() and a.structural_valid.all()
assert (a.last_available <= a.decision_time).all()
safe = (f.vix5 > 0) & (f.xau5 > 0) & (f.gold_vix_corr60 > 0)
down = f.own_day <= 0
pull = (f.known_rmb5 > 0) & (f.etf3 < 0)
req = ["vix5", "xau5", "gold_vix_corr60"]
mr = ["morning", "afternoon"]
expressions = {
    "C_MDOWN": (f.morning < 0, mr),
    "C_MUP": (f.morning >= 0, mr),
    "C_DOWN": (down, ["own_day", "tail"]),
    "C_PULL": (pull, ["known_rmb5", "etf3", "tail"]),
    "C_M05": (safe, req),
    "I01": ((f.morning < 0) & (f.afternoon > 0), mr),
    "I02": ((f.morning < 0) & (f.afternoon <= 0), mr),
    "I03": ((f.morning >= 0) & (f.afternoon < 0), mr),
    "I04": ((f.morning >= 0) & (f.afternoon >= 0), mr),
    "I05": (down & (f["tail"] > 0), ["own_day", "tail"]),
    "I06": (down & (f["tail"] <= 0), ["own_day", "tail"]),
    "I07": (pull & (f["tail"] < 0), ["known_rmb5", "etf3", "tail"]),
    "I08": (pull & (f["tail"] >= 0), ["known_rmb5", "etf3", "tail"]),
    "I09": (safe & (f["tail"] < 0), req + ["tail"]),
    "I10": (safe & (f["tail"] >= 0), req + ["tail"]),
    "I11": (safe & (f.afternoon > 0), req + ["afternoon"]),
    "I12": (safe & (f.afternoon <= 0), req + ["afternoon"]),
}
for key, (condition, cols) in expressions.items():
    valid = f[cols].notna().all(axis=1)
    np.testing.assert_array_equal(v[key], valid)
    np.testing.assert_array_equal(s[key], valid & condition)
    count += 2 * len(d)
bad = set(raw["quality"]["target_30m"]["quality"]["minute"]["inaccurate_dates"])
assert len(bad) == 26
raw_bad = np.array([str(x.date()) in bad for x in d.index])
metrics += read(P / "quality_sensitivity.json")


def residual_for(mask, net):
    cells = f.loc[mask, ["etf5", "vol20", "own_day"]].copy()
    cells["year"] = cells.index.year
    cells["bucket"] = cells.vol20.groupby(cells.year).transform(
        lambda x: np.searchsorted(x.quantile([1 / 3, 2 / 3]).to_numpy(), x.to_numpy(), side="right")
    )
    cells["etf_sign"] = cells.etf5 > 0
    cells["day_sign"] = cells.own_day > 0
    cells["net"] = net[mask]
    baseline = cells.groupby(["year", "etf_sign", "bucket", "day_sign"]).net.transform("mean")
    out = np.full(len(d), np.nan)
    out[mask] = cells.net.to_numpy() - baseline.to_numpy()
    return out


def independently_ols(mask, net, key, extra=()):
    columns = ["etf5", "etf20", "vol20", "own_day", *extra]
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


for h in (1, 3, 5):
    for delay in (0, 1, 2):
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
                    & f[["etf5", "etf20", "vol20", "own_day"]].notna().all(axis=1).to_numpy()
                )
                if par:
                    mask &= v[par].to_numpy()
                if r.get("diagnostic_only"):
                    polluted = np.zeros(len(d), dtype=bool)
                    for offset2 in range(h + delay + 2):
                        polluted[: len(d) - offset2] |= raw_bad[offset2:]
                    mask &= ~polluted
                hit = mask & s[key].to_numpy()
                phit = mask & (s[par].to_numpy() if par else True)
                chosen = schedule(hit, h + 1)
                pa = schedule(phit, h + 1)
                filled = chosen[np.isfinite(limit_net[chosen])]
                residual = residual_for(mask, net)
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
                parent_limit = np.nan_to_num(limit_net[pa], nan=0.0)
                keep = s[key].to_numpy()[pa]
                delta = np.where(keep, parent_limit, 0.0) - parent_limit
                values.update(
                    {
                        "fixed_parent_limit_base": mean(parent_limit),
                        "fixed_parent_limit_filtered": mean(np.where(keep, parent_limit, 0.0)),
                        "fixed_parent_limit_delta": mean(delta),
                        "fixed_parent_limit_slots": len(pa),
                        "fixed_parent_limit_base_fills": np.isfinite(limit_net[pa]).sum(),
                        "fixed_parent_limit_kept_fills": (keep & np.isfinite(limit_net[pa])).sum(),
                    }
                )
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
                    }
                )
                for k, x in values.items():
                    eq(r[k], x)
                for aa in (
                    ()
                    if r.get("diagnostic_only")
                    else (
                        x
                        for x in annual
                        if (x["signal"], x["horizon"], x["delay"], x["fee"]) == (key, h, delay, fee)
                    )
                ):
                    am = mask & (d.index.year == aa["year"])
                    ah = hit & am
                    for k, x in [
                        ("eligible_days", am.sum()),
                        ("events", ah.sum()),
                        ("net_mean", mean(net[ah])),
                        ("matched_increment", mean(residual[ah])),
                        ("parent_matched_increment", mean(pr[ah])),
                        ("fixed_parent_limit_delta", mean(delta[d.index[pa].year == aa["year"]])),
                        (
                            "fixed_parent_limit_base",
                            mean(parent_limit[d.index[pa].year == aa["year"]]),
                        ),
                        ("fixed_parent_limit_slots", sum(d.index[pa].year == aa["year"])),
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

for r in read(P / "leave_one_year_out.json"):
    sample = [
        x
        for x in annual
        if (x["signal"], x["horizon"], x["delay"], x["fee"])
        == (r["signal"], 5, r["delay"], r["fee"])
        and x["year"] != r["omitted_year"]
        and x["fixed_parent_limit_slots"] > 0
    ]
    slots = sum(x["fixed_parent_limit_slots"] for x in sample)
    assert r["slots"] == slots
    eq(
        r["limit_delta"],
        sum(x["fixed_parent_limit_delta"] * x["fixed_parent_limit_slots"] for x in sample) / slots
        if slots
        else np.nan,
    )
out = {
    "status": "PASS",
    "scope": "独立前驱SHA/回执、继承信号/新增分钟特征、18费用延迟标签、全部事件/匹配/父OLS/限价贡献和年度/去单年/BH。分钟离线质量子样本或旧集合互补槽另核验；不复现随机区间与循环抽样，不证明实际发布时间或账户目标。",
    "numerical_fields_checked": count,
    "sessions": len(d),
    "hypotheses": len(specs),
    "paths": len(metrics),
    "annual_rows": len(annual),
    "bh_family": len(ps),
}
(EXP / "artifacts/verification").mkdir(parents=True, exist_ok=True)
(EXP / "artifacts/verification/independent.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
)
print(json.dumps(out, ensure_ascii=False))
