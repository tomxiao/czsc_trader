"""Independent S012 result arithmetic, without importing experiment functions."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd

root = Path(__file__).resolve().parents[3]
source = root / "experiments/S012/EX015_20261005/artifacts/rex"
receipt = json.loads((source / "execution_receipt.json").read_text(encoding="utf-8"))
names = (
    "data/daily.parquet",
    "features.parquet",
    "signals.parquet",
    "valids.parquet",
    "coverage.json",
    "opportunities.json",
)
for name in names:
    assert sha256((source / name).read_bytes()).hexdigest() == receipt["artifact_sha256"][name]
d = pd.read_parquet(source / names[0])
d.attrs = {}
dates = pd.DatetimeIndex(pd.to_datetime(d.Date))
years = dates.year.to_numpy()
f = pd.read_parquet(source / "features.parquet")
f.attrs = {}
s = pd.read_parquet(source / "signals.parquet")
s.attrs = {}
v = pd.read_parquet(source / "valids.parquet")
v.attrs = {}
assert f.index.equals(dates) and s.index.equals(dates) and v.index.equals(dates)
coverage = json.loads((source / "coverage.json").read_text(encoding="utf-8"))
rows = json.loads((source / "opportunities.json").read_text(encoding="utf-8"))
N = len(d)
o = d.Open.to_numpy()
low = d.Low.to_numpy()
close = d.Close.to_numpy()
volume = d.Volume.to_numpy()
positions = np.arange(N)
raw_controls = np.full((N, 3), np.nan)
raw_controls[1:, 0] = close[1:] / close[:-1] - 1
raw_controls[3:, 1] = close[3:] / close[:-3] - 1
for i in range(20, N):
    raw_controls[i, 2] = volume[i] / np.mean(volume[i - 20 : i])
bins = np.full((N, 3), -1, dtype=int)
for year in np.unique(years):
    for j in range(3):
        ids = np.flatnonzero((years == year) & np.isfinite(raw_controls[:, j]))
        order = np.argsort(raw_controls[ids, j], kind="stable")
        ranks = np.empty(len(ids), dtype=float)
        ranks[order] = np.arange(1, len(ids) + 1)
        edges = np.array([1 + (len(ids) - 1) / 3, 1 + 2 * (len(ids) - 1) / 3])
        bins[ids, j] = np.searchsorted(edges, ranks, side="left")
cells = [(int(y), *(int(x) for x in b)) for y, b in zip(years, bins)]
bad = np.array([str(t.date()) in set(coverage["bad_dates"]) for t in dates])
minute_valid = f.sell_pressure.notna().to_numpy()
limit = np.floor((close + 1e-10) / 0.001) * 0.001
errors = []
maximum = 0.0
numeric_checks = 0
samples = []
window_counts = {}


def mean(a):
    a = np.asarray(a, dtype=float)
    a = a[np.isfinite(a)]
    return float(np.mean(a)) if len(a) else None


for row in rows:
    h, delay, fee = row["horizon"], row["delay"], row["fee"]
    en = positions + delay + 1
    ex = en + h
    eligible = (years >= 2022) & minute_valid & (ex < N) & v[row["signal"]].to_numpy()
    clean = np.array([not bad[i : min(N, i + h + delay + 2)].any() for i in positions])
    window_counts[f"h{h}_delay{delay}"] = int(
        ((years >= 2022) & minute_valid & (ex < N) & ~clean).sum()
    )
    if row["sensitivity"] == "quality_clean":
        eligible &= clean
    mask = eligible & s[row["signal"]].to_numpy()
    good = np.flatnonzero(ex < N)
    gross = np.full(N, np.nan)
    net = np.full(N, np.nan)
    gross[good] = o[ex[good]] / o[en[good]] - 1
    net[good] = (1 + gross[good]) * (1 - fee) / (1 + fee) - 1
    grouped = {}
    for i in np.flatnonzero(eligible):
        grouped.setdefault(cells[i], []).append(gross[i])
    base = {k: np.mean(z) for k, z in grouped.items()}
    event_ids = np.flatnonzero(mask)
    matched = [net[i] - base[cells[i]] for i in event_ids]
    chosen = []
    next_allowed = 0
    for i in event_ids:
        if i >= next_allowed:
            chosen.append(i)
            next_allowed = i + h + 1
    filled_net = []
    for i in chosen:
        px = o[en[i]] if o[en[i]] <= limit[i] else limit[i] if low[en[i]] <= limit[i] else None
        if px is not None:
            filled_net.append(o[ex[i]] / px * (1 - fee) / (1 + fee) - 1)
    observed = {
        "events": len(event_ids),
        "eligible": int(eligible.sum()),
        "net_mean": mean(net[mask]),
        "increment": mean(matched),
        "nonoverlap_events": len(chosen),
        "nonoverlap_net": mean(net[chosen]),
        "limit_fills": len(filled_net),
        "limit_per60": len(filled_net) * 60 / N,
        "limit_net": mean(filled_net),
    }
    for key, value in observed.items():
        expected = row[key]
        if value is None or expected is None:
            difference = 0 if value is None and expected is None else float("inf")
        else:
            difference = abs(value - expected)
        maximum = max(maximum, difference)
        numeric_checks += 1
        if difference > 2e-12:
            errors.append(
                {
                    "row": {
                        k: row[k] for k in ("signal", "horizon", "delay", "fee", "sensitivity")
                    },
                    "field": key,
                    "actual": value,
                    "reported": expected,
                }
            )
    if row["signal"] == "pre_long_closure" and fee == 0.001 and row["sensitivity"] == "all":
        samples.append({**{k: row[k] for k in ("signal", "horizon", "delay", "fee")}, **observed})

output = {
    "status": "PASS" if not errors else "FAIL",
    "experiment": "EX015_20261005",
    "receipt_sha256": receipt["receipt_sha256"],
    "rows_checked": len(rows),
    "numeric_fields_checked": numeric_checks,
    "maximum_abs_difference": maximum,
    "source_hashes_verified": list(names),
    "calendar_recomputed": samples,
    "bad_dates_count": int(bad.sum()),
    "quality_window_exclusions": window_counts,
    "errors": errors,
}
calendar_ids = np.flatnonzero(s.pre_long_closure.to_numpy() & (years >= 2022) & (positions + 6 < N))
output["calendar_date_examples"] = [
    {
        "decision": str(dates[i].date()),
        "entry_T1": str(dates[i + 1].date()),
        "exit_h1_T2": str(dates[i + 2].date()),
        "exit_h5_T6": str(dates[i + 6].date()),
        "calendar_gap_days": int((dates[i + 2] - dates[i + 1]).days),
    }
    for i in calendar_ids[:3]
]
output["calendar_timing"] = (
    "T+1 Open is the final trading day before the long closure; h1 exit is first post-closure Open."
)
successor = source.parents[2] / "EX016_20261005/artifacts/rex"
if successor.exists():
    r16 = json.loads((successor / "execution_receipt.json").read_text(encoding="utf-8"))
    for name in ("signals.parquet", "valids.parquet", "confirmation.json"):
        assert sha256((successor / name).read_bytes()).hexdigest() == r16["artifact_sha256"][name]
    s16 = pd.read_parquet(successor / "signals.parquet")
    s16.attrs = {}
    v16 = pd.read_parquet(successor / "valids.parquet")
    v16.attrs = {}
    confirmation = json.loads((successor / "confirmation.json").read_text(encoding="utf-8"))
    candidates = [c for c in s16.columns if c != "o01"]
    label = np.full(N, np.nan)
    label[:-6] = o[6:] / o[1:-5] * 0.999 / 1.001 - 1
    complete = (years >= 2022) & np.isfinite(label)
    exit_date = np.full(N, np.datetime64("NaT", "ns"), dtype="datetime64[ns]")
    exit_date[:-6] = dates.to_numpy(dtype="datetime64[ns]")[6:]
    verified = []
    for reported in confirmation["walkforward"]:
        year = reported["year"]
        cutoff = np.datetime64(f"{year}-01-01", "ns")
        training = complete & (exit_date < cutoff)
        scores = {}
        for name in candidates:
            valid_rows = training & v16[name].to_numpy()
            events = valid_rows & s16[name].to_numpy()
            scores[name] = mean(label[events]) - mean(label[valid_rows]) if events.any() else None
        finite = {k: x for k, x in scores.items() if x is not None}
        selected = max(finite, key=finite.get) if finite else None
        assert selected == reported["selected"]
        for name, score in scores.items():
            assert (
                score is None
                and reported["training_scores"][name] is None
                or score is not None
                and abs(score - reported["training_scores"][name]) < 2e-12
            )
        test = complete & (years == year)
        events = test & s16[selected].to_numpy() & v16[selected].to_numpy()
        assert int(events.sum()) == reported["events"]
        test_mean = mean(label[events])
        test_increment = test_mean - mean(label[test]) if test_mean is not None else None
        assert (
            test_mean is None
            and reported["net_mean"] is None
            or test_mean is not None
            and abs(test_mean - reported["net_mean"]) < 2e-12
        )
        assert (
            test_increment is None
            and reported["unconditional_increment"] is None
            or test_increment is not None
            and abs(test_increment - reported["unconditional_increment"]) < 2e-12
        )
        assert (exit_date[training] < cutoff).all()
        verified.append(
            {
                "year": year,
                "selected": selected,
                "latest_training_exit": str(np.max(exit_date[training]))[:10],
                "events": int(events.sum()),
                "net_mean": mean(label[events]),
                "unconditional_increment": test_increment,
            }
        )
    output["successor_walkforward"] = {
        "status": "PASS",
        "receipt_sha256": r16["receipt_sha256"],
        "years": verified,
        "candidate_selection_bias_disclosed": True,
    }
out = root / ".tmp/s012-opportunity-20261005/recomputed_independent_verification.json"
out.write_text(
    json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {
            "status": output["status"],
            "rows": len(rows),
            "checks": numeric_checks,
            "max_difference": maximum,
            "errors": errors[:2],
            "calendar": samples,
        },
        ensure_ascii=False,
    )
)
