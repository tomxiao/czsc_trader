"""Independent raw-input arithmetic audit; imports no formal experiment code."""

from hashlib import sha256
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "experiments/S012"
CURRENT = "EX018_20261005"
sources, receipts = {}, {}
counts = {"numeric_fields": 0, "boolean_cells": 0, "array_numeric_cells": 0}
maximum = 0.0


def read(eid, name):
    folder = FAMILY / eid / "artifacts/rex"
    receipt = json.loads((folder / "execution_receipt.json").read_text(encoding="utf-8"))
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    assert sha256(canonical.encode("utf-8")).hexdigest() == receipt["receipt_sha256"]
    receipts[eid] = receipt["receipt_sha256"]
    path = folder / name
    digest = sha256(path.read_bytes()).hexdigest()
    assert digest == receipt["artifact_sha256"][name], (eid, name)
    sources[f"{eid}/{name}"] = digest
    if name.endswith(".parquet"):
        result = pd.read_parquet(path)
        result.attrs = {}
        return result
    return json.loads(path.read_text(encoding="utf-8"))


def array_check(actual, expected, boolean=False):
    global maximum
    a, b = np.asarray(actual), np.asarray(expected)
    assert a.shape == b.shape
    if boolean:
        assert np.array_equal(a, b)
        counts["boolean_cells"] += a.size
    else:
        np.testing.assert_allclose(a, b, atol=1e-12, rtol=1e-12, equal_nan=True)
        good = np.isfinite(a) & np.isfinite(b)
        if good.any():
            maximum = max(maximum, float(np.max(np.abs(a[good] - b[good]))))
        counts["array_numeric_cells"] += a.size


raw = read("EX015_20261005", "data/daily.parquet")
dates = pd.DatetimeIndex(pd.to_datetime(raw.Date))
daily = raw.set_index(dates)
peer = read("EX015_20261005", "data/peer.parquet")
peer = peer.set_index(pd.DatetimeIndex(pd.to_datetime(peer.Date))).reindex(dates)
minutes = read("EX015_20261005", "data/minute.parquet")
coverage = read("EX015_20261005", "coverage.json")
features = read("EX017_20261005", "features.parquet")
signals = read("EX017_20261005", "signals.parquet")
valids = read("EX017_20261005", "valids.parquet")
rows = read(CURRENT, "confirmation.json")
annual = read(CURRENT, "annual.json")
risks = read(CURRENT, "risk_context.json")
history = read(CURRENT, "selection_history.json")
recorded_gates = read(CURRENT, "gates.parquet")
recorded_valid = read(CURRENT, "gate_valids.parquet")
recorded_labels = read(CURRENT, "labels.parquet")
inference = read(CURRENT, "inference.json")
assert all(frame.index.equals(dates) for frame in (features, signals, valids, peer))
for eid, receipt_hash in history["predecessor_receipts"].items():
    assert receipt_hash == receipts[eid]
for name, digest in history["source_hashes"].items():
    assert sources[name] == digest

n = len(dates)
years = dates.year.to_numpy()
opens, lows, closes = (daily[c].to_numpy() for c in ("Open", "Low", "Close"))
positions = np.arange(n)
bad = np.array([str(date.date()) in set(coverage["bad_dates"]) for date in dates])
intraday = pd.DataFrame(np.nan, index=dates, columns=["afternoon", "last_hour", "recovery"])
minutes.Date = pd.to_datetime(minutes.Date)
minutes.AvailableDate = pd.to_datetime(minutes.AvailableDate)
for day, chunk in minutes.groupby(minutes.Date.dt.normalize()):
    chunk = chunk.sort_values("Date")
    if pd.isna(features.loc[day, "sell_pressure"]):
        continue
    assert len(chunk) == 48 and chunk.AvailableDate.le(day + pd.Timedelta(hours=17)).all()
    p = chunk.Close.to_numpy()
    shock = int(np.argmin(np.diff(np.log(p)))) + 1
    intraday.loc[day] = [np.log(p[-1] / p[23]), np.log(p[-1] / p[35]), np.log(p[-1] / p[shock])]
for name in intraday:
    array_check(intraday[name], features[name])
location = (daily.Close - daily.Low) / (daily.High - daily.Low).replace(0, np.nan)
volume_ratio = np.full(n, np.nan)
for i in range(20, n):
    volume_ratio[i] = daily.Volume.iloc[i] / np.mean(daily.Volume.iloc[i - 20 : i])
array_check(location, features.location)
array_check(volume_ratio, features.volume_ratio)
inputs = {
    "afternoon_positive": intraday.afternoon.to_numpy(),
    "last_hour_positive": intraday.last_hour.to_numpy(),
    "close_upper_half": location.to_numpy() - 0.5,
    "recovered_after_shock": intraday.recovery.to_numpy(),
    "peer_positive": (peer.Close / peer.Open - 1).to_numpy(),
    "volume_participation": volume_ratio - 1,
}
gates, gate_valid = {}, {}
for name, values in inputs.items():
    gate_valid[name] = np.isfinite(values)
    gates[name] = (
        (values >= 0) if name in ("close_upper_half", "volume_participation") else (values > 0)
    ) & gate_valid[name]
    array_check(recorded_gates[name], gates[name], True)
    array_check(recorded_valid[name], gate_valid[name], True)

return3 = np.full(n, np.nan)
return3[3:] = closes[3:] / closes[:-3] - 1
gap = closes / (daily.Amount.to_numpy() / daily.Volume.to_numpy()) - 1
quartiles = np.full((n, 2), np.nan)
for year in np.unique(years):
    past = gap[(years < year) & np.isfinite(gap)]
    if len(past) >= 252:
        quartiles[years == year] = np.quantile(past, [0.25, 0.75])
mid_valid = np.isfinite(gap) & np.isfinite(quartiles).all(axis=1) & np.isfinite(return3)
n09 = mid_valid & (gap >= quartiles[:, 0]) & (gap <= quartiles[:, 1]) & (return3 > 0)
array_check(signals.mid_momentum_positive, n09, True)
array_check(valids.mid_momentum_positive, mid_valid, True)

values = pd.DataFrame(index=dates)
r1 = daily.Close.pct_change(fill_method=None)
values["volatility20"] = r1.rolling(20).std()
values["momentum20"] = daily.Close.pct_change(20, fill_method=None)
values["kurtosis60"] = r1.rolling(60).kurt()
thresholds = pd.DataFrame(np.nan, index=dates, columns=values.columns)
for year in np.unique(years):
    for name in values:
        past = values.loc[years < year, name].dropna().to_numpy()
        if len(past) >= 252:
            thresholds.loc[years == year, name] = np.median(past)
risk_valid = np.isfinite(values) & thresholds.notna()
high = (values > thresholds) & risk_valid
array_check(read(CURRENT, "risk_values.parquet"), values)
array_check(read(CURRENT, "risk_thresholds.parquet"), thresholds)
array_check(read(CURRENT, "risk_valids.parquet"), risk_valid, True)
array_check(read(CURRENT, "risk_high.parquet"), high, True)


def average(z):
    a = np.asarray(z, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.mean(a)) if a.size else None


def difference(a, b):
    return None if a is None or b is None else a - b


def schedule(mask, horizon):
    selected = []
    for i in np.where(mask)[0].tolist():
        if not selected or i - selected[-1] >= horizon + 1:
            selected.append(i)
    return np.asarray(selected, dtype=int)


cache = {}


def labels(h, delay, fee):
    key = (h, delay, fee)
    if key not in cache:
        net, limit_net, downside = (np.full(n, np.nan) for _ in range(3))
        clean = np.ones(n, dtype=bool)
        for i in range(n):
            clean[i] = not bad[i : min(n, i + h + delay + 2)].any()
            entry, exit_index = i + delay + 1, i + delay + h + 1
            if exit_index <= n:
                downside[i] = max(0, 1 - np.min(lows[entry:exit_index]) / opens[entry])
            if exit_index >= n:
                continue
            net[i] = opens[exit_index] / opens[entry] * (1 - fee) / (1 + fee) - 1
            limit = np.floor((closes[i] + 1e-10) / 0.001) * 0.001
            fill = (
                opens[entry] if opens[entry] <= limit else limit if lows[entry] <= limit else np.nan
            )
            limit_net[i] = opens[exit_index] / fill * (1 - fee) / (1 + fee) - 1
        frame = pd.DataFrame(
            {"net": net, "limit_net": limit_net, "clean": clean, "downside": downside}, index=dates
        )
        array_check(
            recorded_labels[f"h{h}_delay{delay}_fee{fee}"][["net", "limit_net", "downside"]],
            frame[["net", "limit_net", "downside"]],
        )
        array_check(recorded_labels[f"h{h}_delay{delay}_fee{fee}"].clean, clean, True)
        cache[key] = (net, limit_net, downside, clean)
    return cache[key]


def recompute(parent, gate, h, delay, fee):
    y, ly, downside, _ = labels(h, delay, fee)
    passed, rejected = parent & gate, parent & ~gate
    anchors = schedule(parent, h)
    kept, dropped = anchors[gate[anchors]], anchors[~gate[anchors]]
    changed = schedule(passed, h)
    lost = y[dropped]
    known = np.isfinite(ly[anchors])
    pass_known = known & gate[anchors]
    zero_limit = np.where(np.isfinite(ly[anchors]), ly[anchors], 0)
    parent_mean, pass_mean, reject_mean = (
        average(y[parent]),
        average(y[passed]),
        average(y[rejected]),
    )
    parent_c, pass_c = average(y[anchors]), average(np.where(gate[anchors], y[anchors], 0))
    parent_lc, pass_lc = average(zero_limit), average(np.where(gate[anchors], zero_limit, 0))
    return {
        "parent_events": int(parent.sum()),
        "passed_events": int(passed.sum()),
        "rejected_events": int(rejected.sum()),
        "retention": int(passed.sum()) / max(1, int(parent.sum())),
        "parent_net": parent_mean,
        "passed_net": pass_mean,
        "rejected_net": reject_mean,
        "conditional_lift": difference(pass_mean, parent_mean),
        "pass_minus_reject": difference(pass_mean, reject_mean),
        "parent_downside": average(downside[parent]),
        "passed_downside": average(downside[passed]),
        "rejected_downside": average(downside[rejected]),
        "parent_anchors": len(anchors),
        "kept_anchors": len(kept),
        "dropped_anchors": len(dropped),
        "parent_anchor_net": parent_c,
        "kept_anchor_net": average(y[kept]),
        "fixed_parent_contribution": parent_c,
        "fixed_filter_contribution": pass_c,
        "fixed_contribution_delta": difference(pass_c, parent_c),
        "lost_profitable_events": int((lost > 0).sum()),
        "lost_profit_sum": float(lost[lost > 0].sum()),
        "avoided_loss_events": int((lost < 0).sum()),
        "avoided_loss_sum": float(-lost[lost < 0].sum()),
        "parent_limit_fills": int(known.sum()),
        "kept_limit_fills": int(pass_known.sum()),
        "parent_limit_per60": int(known.sum()) * 60 / n,
        "kept_limit_per60": int(pass_known.sum()) * 60 / n,
        "parent_limit_net": average(ly[anchors]),
        "kept_limit_net": average(ly[kept]),
        "fixed_limit_parent_contribution": parent_lc,
        "fixed_limit_filter_contribution": pass_lc,
        "fixed_limit_contribution_delta": difference(pass_lc, parent_lc),
        "rescheduled_events": len(changed),
        "rescheduled_limit_fills": int(np.isfinite(ly[changed]).sum()),
        "rescheduled_limit_per60": int(np.isfinite(ly[changed]).sum()) * 60 / n,
        "rescheduled_limit_net": average(ly[changed]),
        "without_best5_passed_net": average(sorted(y[passed])[:-5]) if passed.sum() > 5 else None,
        "without_2025_lift": difference(
            average(y[passed & (years != 2025)]), average(y[parent & (years != 2025)])
        ),
    }


def check_fields(row, expected):
    global maximum
    for name, value in expected.items():
        actual = row[name]
        if value is None:
            assert actual is None, (name, actual, value)
        elif isinstance(value, (int, np.integer)):
            assert actual == value, (name, actual, value)
        else:
            assert actual is not None and np.isclose(actual, value, rtol=1e-10, atol=1e-12), (
                name,
                actual,
                value,
                row,
            )
            maximum = max(maximum, abs(actual - value))
        counts["numeric_fields"] += 1


for row in rows + annual:
    h, delay, fee = row["horizon"], row["delay"], row["fee"]
    y, _, _, clean = labels(h, delay, fee)
    parent_raw = (
        (years >= 2022)
        & np.isfinite(y)
        & features.sell_pressure.notna().to_numpy()
        & signals[row["base"]].to_numpy()
        & valids[row["base"]].to_numpy()
    )
    if row["quality"] == "quality_clean":
        parent_raw &= clean
    parent = parent_raw & gate_valid[row["gate"]]
    if "year" in row:
        parent &= years == row["year"]
    expected = recompute(parent, gates[row["gate"]], h, delay, fee)
    if "unknown_confirmation_events" in row:
        expected["unknown_confirmation_events"] = int((parent_raw & ~gate_valid[row["gate"]]).sum())
    check_fields(row, expected)
for row in risks:
    y, _, _, clean = labels(5, 0, 0.001)
    parent = (
        (years >= 2022)
        & np.isfinite(y)
        & features.sell_pressure.notna().to_numpy()
        & signals[row["base"]].to_numpy()
        & valids[row["base"]].to_numpy()
        & risk_valid[row["risk"]].to_numpy()
    )
    if row["quality"] == "quality_clean":
        parent &= clean
    check_fields(row, recompute(parent, ~high[row["risk"]].to_numpy(), 5, 0, 0.001))

primary = [
    r
    for r in rows
    if r["horizon"] == 5 and r["delay"] == 0 and r["fee"] == 0.001 and r["quality"] == "all"
]
inferred = []
for i, base in enumerate(("o01", "mid_momentum_positive")):
    for j, gate_name in enumerate(gates):
        y, _, _, _ = labels(5, 0, 0.001)
        parent = (
            (years >= 2022)
            & np.isfinite(y)
            & features.sell_pressure.notna().to_numpy()
            & signals[base].to_numpy()
            & valids[base].to_numpy()
            & gate_valid[gate_name]
        )
        ids = np.where(parent)[0]
        anchors = schedule(parent, 5)
        gate = gates[gate_name]
        expected = {
            name: None
            for name in (
                "p",
                "q",
                "lift_ci_low",
                "lift_ci_high",
                "contribution_ci_low",
                "contribution_ci_high",
            )
        }
        if int(gate[anchors].sum()) >= 6 and int((~gate[anchors]).sum()) >= 6:
            rng = np.random.default_rng(12018 + i * 100 + j)
            pattern = gate[ids]
            observed = average(y[ids][pattern]) - average(y[ids][~pattern])
            extreme = 0
            groups = [np.where(years[ids] == year)[0] for year in np.unique(years[ids])]
            for _ in range(399):
                permuted = pattern.copy()
                for group in groups:
                    shift = int(rng.integers(len(group)))
                    permuted[group] = pattern[group][(np.arange(len(group)) - shift) % len(group)]
                effect = average(y[ids][permuted]) - average(y[ids][~permuted])
                extreme += abs(effect) >= abs(observed)
            expected["p"] = (extreme + 1) / 400
            block_ids = np.zeros(n, dtype=int)
            pools, offset = [], 0
            for year in np.unique(years):
                year_ids = np.where(years == year)[0]
                local_ids = np.arange(len(year_ids)) // 20
                block_ids[year_ids] = local_ids + offset
                pools.append(np.arange(offset, offset + int(local_ids.max()) + 1))
                offset += int(local_ids.max()) + 1
            sampled_pools = [rng.choice(pool, size=(999, len(pool))) for pool in pools]
            lifts, contributions = [], []
            for sample in range(999):
                draws = np.concatenate([pool[sample] for pool in sampled_pools])
                weights = np.bincount(draws, minlength=offset)
                opportunity_weights = weights[block_ids[ids]]
                passing_weights = opportunity_weights * pattern
                if passing_weights.sum() > 0:
                    lifts.append(
                        float(
                            np.average(y[ids], weights=passing_weights)
                            - np.average(y[ids], weights=opportunity_weights)
                        )
                    )
                anchor_weights = weights[block_ids[anchors]]
                if anchor_weights.sum() > 0:
                    contributions.append(
                        float(
                            np.average(
                                np.where(gate[anchors], 0, -y[anchors]), weights=anchor_weights
                            )
                        )
                    )
            expected["lift_ci_low"], expected["lift_ci_high"] = np.quantile(
                lifts, [0.025, 0.975]
            ).tolist()
            expected["contribution_ci_low"], expected["contribution_ci_high"] = np.quantile(
                contributions, [0.025, 0.975]
            ).tolist()
        inferred.append(expected)
ordered = sorted(
    [i for i, item in enumerate(inferred) if item["p"] is not None], key=lambda i: inferred[i]["p"]
)
previous = 1.0
for rank in range(len(ordered), 0, -1):
    i = ordered[rank - 1]
    previous = min(previous, inferred[i]["p"] * len(inferred) / rank)
    inferred[i]["q"] = previous
for actual, expected in zip(inference, inferred):
    check_fields(actual, expected)
correlations = []
for base in ("o01", "mid_momentum_positive"):
    y, _, _, _ = labels(5, 0, 0.001)
    parent = (years >= 2022) & np.isfinite(y) & signals[base].to_numpy() & valids[base].to_numpy()
    for i, a in enumerate(gates):
        for b in list(gates)[i + 1 :]:
            common = parent & gate_valid[a] & gate_valid[b]
            x, z = gates[a][common], gates[b][common]
            phi = (
                float(np.corrcoef(x.astype(float), z.astype(float))[0, 1])
                if np.std(x) and np.std(z)
                else None
            )
            correlations.append(
                {
                    "base": base,
                    "a": a,
                    "b": b,
                    "events": int(common.sum()),
                    "correlation": phi,
                    "identical": bool(np.array_equal(x, z)),
                }
            )
report = {
    "status": "PASS",
    "experiment_id": CURRENT,
    "independent_imports": ["numpy", "pandas"],
    "formal_module_imports": [],
    "source_hashes": sources,
    "receipt_hashes": receipts,
    "rows_verified": len(rows),
    "annual_rows_verified": len(annual),
    "risk_rows_verified": len(risks),
    **counts,
    "maximum_absolute_difference": maximum,
    "primary_results": primary,
    "gate_correlations": correlations,
    "verification_scope": "全部确认/年度/风险数值字段、12套标签、原始5分钟路径派生、6门及有效掩码、N09定义、3风险历史中位阈值、399次循环移位/BH及999次描述区间。O01沿用哈希绑定的父信号，不重建其汇率数据。",
    "inference_rows_verified": len(inference),
    "boundaries": [
        "开发池结果，非独立样本外",
        "日线Low触价代理",
        "年度分项在年内重建父事件去重序列，不与全年去重计数直接可加",
        "风险视图非历史组件定义替代",
    ],
}
output = ROOT / "research/S012/materials/confirmation_independent_verification_20261005.json"
output.write_text(
    json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {
            "status": report["status"],
            "rows": len(rows),
            "annual": len(annual),
            "risks": len(risks),
            **counts,
            "maximum": maximum,
        },
        ensure_ascii=False,
    )
)
