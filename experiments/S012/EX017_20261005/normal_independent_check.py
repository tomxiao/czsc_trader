"""Independent EX017 masks and arithmetic; no formal experiment imports."""

from pathlib import Path
from hashlib import sha256
import json
import runpy
import numpy as np
import pandas as pd

root = Path(__file__).resolve().parents[3]
b = runpy.run_path(str(Path(__file__).with_name("independent_check.py")))
families = root / "experiments/S012"
sources = {}
sources["EX015_20261005/data/daily.parquet"] = b["receipt"]["artifact_sha256"]["data/daily.parquet"]
sources["EX015_20261005/coverage.json"] = b["receipt"]["artifact_sha256"]["coverage.json"]


def read(eid, name):
    folder = families / eid / "artifacts/rex"
    receipt = json.loads((folder / "execution_receipt.json").read_text(encoding="utf-8"))
    path = folder / name
    digest = sha256(path.read_bytes()).hexdigest()
    assert digest == receipt["artifact_sha256"][name]
    sources[f"{eid}/{name}"] = digest
    if name.endswith(".parquet"):
        frame = pd.read_parquet(path)
        frame.attrs = {}
        return frame
    return json.loads(path.read_text(encoding="utf-8"))


f = read("EX016_20261005", "features.parquet")
t = read("EX016_20261005", "thresholds.parquet")
old = read("EX016_20261005", "signals.parquet")
oldv = read("EX016_20261005", "valids.parquet")
s = read("EX017_20261005", "signals.parquet")
v = read("EX017_20261005", "valids.parquet")
rows = read("EX017_20261005", "opportunities.json")
confirmation = read("EX017_20261005", "confirmation.json")
dates, years, close, d, N = (b[k] for k in ("dates", "years", "close", "d", "N"))
o, low, limit, positions, bad, cells = (
    b[k] for k in ("o", "low", "limit", "positions", "bad", "cells")
)
assert all(x.index.equals(dates) for x in (f, t, old, oldv, s, v))
gap = close / (d.Amount.to_numpy() / d.Volume.to_numpy()) - 1
np.testing.assert_allclose(gap, f.actual_vwap_gap, atol=1e-12, rtol=1e-12)
np.testing.assert_allclose(
    f.return3, b["raw_controls"][:, 1], equal_nan=True, atol=1e-12, rtol=1e-12
)
for name in ("actual_vwap_low", "actual_vwap_high", "o01"):
    assert np.array_equal(s[name].to_numpy(), old[name].to_numpy())
    assert np.array_equal(v[name].to_numpy(), oldv[name].to_numpy())
quartiles = np.full((N, 2), np.nan)
for year in np.unique(years):
    history = gap[(years < year) & np.isfinite(gap)]
    if len(history) >= 252:
        quartiles[years == year] = np.quantile(history, [0.25, 0.75])
np.testing.assert_allclose(quartiles, t.to_numpy(), equal_nan=True, atol=1e-12, rtol=1e-12)
lo, hi = quartiles.T
bounded = np.isfinite(gap) & np.isfinite(lo) & np.isfinite(hi)
mid = (gap >= lo) & (gap <= hi)
expected_signals = {
    "actual_vwap_mid": mid,
    "mid_nonnegative": mid & (gap >= 0),
    "mid_negative": mid & (gap < 0),
    "vwap_near_zero": np.abs(gap) <= 0.002,
    "mid_late_thin": mid & old.late_volume_low.to_numpy(),
    "mid_momentum_positive": mid & (f.return3.to_numpy() > 0),
    "o01_mid": mid & old.o01.to_numpy(),
}
checks = 0
for name, mask in expected_signals.items():
    defined = np.isfinite(gap) if name == "vwap_near_zero" else bounded.copy()
    if name == "mid_late_thin":
        defined &= oldv.late_volume_low.to_numpy()
    if name == "mid_momentum_positive":
        defined &= np.isfinite(f.return3.to_numpy())
    if name == "o01_mid":
        defined &= oldv.o01.to_numpy()
    assert np.array_equal(defined, v[name].to_numpy())
    assert np.array_equal(mask & defined, s[name].to_numpy())
    checks += N * 2
# Perturb all 2026 values: earlier-year thresholds cannot change.
changed = gap.copy()
changed[years >= 2026] = 10.0
for year in np.unique(years[years <= 2026]):
    history = changed[(years < year) & np.isfinite(changed)]
    if len(history) >= 252:
        np.testing.assert_allclose(
            quartiles[years == year],
            np.broadcast_to(np.quantile(history, [0.25, 0.75]), quartiles[years == year].shape),
        )

maximum = 0.0
summaries = []
count = 0


def mean(z):
    z = np.asarray(z)
    z = z[np.isfinite(z)]
    return float(z.mean()) if len(z) else None


for row in rows:
    h, delay, fee = row["horizon"], row["delay"], row["fee"]
    entry = positions + delay + 1
    exit_ = entry + h
    eligible = (years >= 2022) & b["minute_valid"] & (exit_ < N) & v[row["signal"]].to_numpy()
    clean = np.array([not bad[i : min(N, i + h + delay + 2)].any() for i in positions])
    if row["sensitivity"] == "quality_clean":
        eligible &= clean
    mask = eligible & s[row["signal"]].to_numpy()
    good = np.flatnonzero(exit_ < N)
    gross = np.full(N, np.nan)
    net = np.full(N, np.nan)
    gross[good] = o[exit_[good]] / o[entry[good]] - 1
    net[good] = (1 + gross[good]) * (1 - fee) / (1 + fee) - 1
    groups = {}
    for i in np.flatnonzero(eligible):
        groups.setdefault(cells[i], []).append(gross[i])
    base = {k: np.mean(z) for k, z in groups.items()}
    event_ids = np.flatnonzero(mask)
    chosen = []
    nxt = 0
    for i in event_ids:
        if i >= nxt:
            chosen.append(i)
            nxt = i + h + 1
    fills = []
    for i in chosen:
        px = (
            o[entry[i]]
            if o[entry[i]] <= limit[i]
            else limit[i]
            if low[entry[i]] <= limit[i]
            else None
        )
        if px is not None:
            fills.append(o[exit_[i]] / px * (1 - fee) / (1 + fee) - 1)
    actual = {
        "events": len(event_ids),
        "eligible": int(eligible.sum()),
        "net_mean": mean(net[mask]),
        "increment": mean([net[i] - base[cells[i]] for i in event_ids]),
        "nonoverlap_events": len(chosen),
        "nonoverlap_net": mean(net[chosen]),
        "limit_fills": len(fills),
        "limit_per60": len(fills) * 60 / N,
        "limit_net": mean(fills),
    }
    for field, value in actual.items():
        reported = row[field]
        difference = 0 if value is None and reported is None else abs(value - reported)
        maximum = max(maximum, difference)
        assert difference < 2e-12
        count += 1
    if row["signal"] == "mid_momentum_positive" and h == 5:
        summaries.append(
            {**{k: row[k] for k in ("signal", "horizon", "delay", "fee", "sensitivity")}, **actual}
        )
primary = (years >= 2022) & b["minute_valid"] & (positions + 6 < N)
filtered = primary & s.o01_mid.to_numpy() & v.o01_mid.to_numpy()
assert int(filtered.sum()) == 35
union = primary & (
    (s.o01.to_numpy() & v.o01.to_numpy())
    | (s.mid_momentum_positive.to_numpy() & v.mid_momentum_positive.to_numpy())
)
chosen = []
nxt = 0
for i in np.flatnonzero(union):
    if i >= nxt:
        chosen.append(i)
        nxt = i + 6
filled = [i for i in chosen if o[i + 1] <= limit[i] or low[i + 1] <= limit[i]]
assert (int(union.sum()), len(chosen), len(filled)) == (377, 132, 79)
actual_union = next(
    row for row in confirmation["unions"] if row["signals"] == ["o01", "mid_momentum_positive"]
)
assert (actual_union["events"], actual_union["nonoverlap_events"], actual_union["limit_fills"]) == (
    377,
    132,
    79,
)
binding = json.loads(
    (families / "EX017_20261005/experiment_binding.json").read_text(encoding="utf-8")
)
r17 = json.loads(
    (families / "EX017_20261005/artifacts/rex/execution_receipt.json").read_text(encoding="utf-8")
)
assert binding["source_sha256"] == r17["source_sha256"]
output = {
    "status": "PASS",
    "experiment": "EX017_20261005",
    "receipt_sha256": r17["receipt_sha256"],
    "source_binding_sha256": binding["source_sha256"],
    "source_hashes_verified": sources,
    "signal_and_mask_boolean_checks": checks,
    "threshold_causal_prefix": "PASS",
    "path_rows_checked": len(rows),
    "numeric_checks": count,
    "maximum_abs_difference": maximum,
    "mid_momentum_primary_and_sensitivities": summaries,
    "o01_mid_events": 35,
    "o01_mid_momentum_union": {
        "events": 377,
        "nonoverlap": 132,
        "limit_fills": 79,
        "limit_per60": 79 * 60 / N,
    },
    "calendar_date_examples": b["output"]["calendar_date_examples"],
}
(root / ".tmp/normal_independent_verification.json").write_text(
    json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
)
print(
    json.dumps(
        {
            "status": "PASS",
            "boolean_checks": checks,
            "path_checks": count,
            "max_difference": maximum,
            "calendar": output["calendar_date_examples"],
            "primary": summaries,
        },
        ensure_ascii=False,
    )
)
