"""Review acquired snapshots without supplier access or imputations."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd

root = Path(__file__).resolve().parent
review_path = root / "data_review.json"
review = json.loads(review_path.read_text(encoding="utf-8"))
axis_path = Path("research/S013/assets/evidence/EX079_20261012/8f555f2eaac04c28c588bde3122e3ee1a248cc2326d77c33a45bb6057f669c75.csv")
source = pd.read_csv(axis_path)
axis = pd.DatetimeIndex(pd.to_datetime(source.signal_date))
assert len(axis) == 1635 and axis.is_unique and axis.is_monotonic_increasing
assert axis[0] == pd.Timestamp("2020-01-02") and axis[-1] == pd.Timestamp("2026-09-29")
axis = axis.append(pd.DatetimeIndex([pd.Timestamp("2026-09-30")]))
review["coverage_reference"] = {"source": axis_path.as_posix(),
    "sha256": hashlib.sha256(axis_path.read_bytes()).hexdigest(),
    "source_signal_dates": 1635, "explicit_final_execution_date_added": "2026-09-30",
    "pool_sessions": len(axis), "warmup_count_reference": 60}
docs = {
    "verified_at": "2026-10-13", "historical_versions_obtained": False,
    "G1": {"url": "https://tushare.pro/document/2?doc_id=128",
           "summary": "Current public documentation names Zhongzheng500 support, community-computed daily metrics, history from Jan2004, minimum2000points and3000rows/request. It does not expose historical per-row publication/revision timestamps.",
           "unit": "turnover_rate_f is turnover based on freely circulating shares; supplier raw scale preserved"},
    "G2": {"url": "https://tushare.pro/document/2?doc_id=408",
           "summary": "Current public documentation defines total_share in10000units; updates are ingested in batches, prior-session values usually around08:30nextday, overseasETFs later; minimum8000points, maximum5000rows/request. It does not expose actual historical release/revision timestamps.",
           "unit": "10000 fund units (wan fen), preserved unchanged"},
}
review["public_documentation"] = docs
frames = {}
for group in ("G1", "G2"):
    path = root / f"{group}_ordered.csv"
    frame = pd.read_csv(path)
    dates = pd.DatetimeIndex(pd.to_datetime(frame.trade_date))
    values = pd.to_numeric(frame[review["series"][group]["value_field"]])
    frames[group] = dates
    item = review["series"][group]
    missing = axis.difference(dates)
    outside = dates[(dates >= axis[0]) & (dates <= axis[-1])].difference(axis)
    item.update({"pool_date_missing_count": len(missing),
                 "pool_date_missing": [d.strftime("%Y-%m-%d") for d in missing],
                 "unexpected_pool_date_count": len(outside),
                 "pool_date_coverage": (len(axis)-len(missing))/len(axis),
                 "nonfinite_values": int((~np.isfinite(values)).sum()),
                 "observed_zero_values": int((values == 0).sum()),
                 "consecutive_identical_pairs": int((values.diff() == 0).sum()),
                 "current_snapshot_cross_source_values_verified": False})
    change = values.pct_change(fill_method=None)
    ranking = change.abs().nlargest(10).index
    item["largest_daily_relative_changes_descriptive_only"] = [
        {"date": frame.trade_date.iloc[i], "previous_value": float(values.iloc[i-1]),
         "value": float(values.iloc[i]), "relative_change": float(change.iloc[i])}
        for i in ranking]
    item["anomaly_policy"] = "Large changes are retained and disclosed, not excluded or repaired; no external authoritative reconciliation in authorized two-series scope"
review["series_date_axes_identical"] = frames["G1"].equals(frames["G2"])
review["availability_limitation"] = "Snapshot row completeness does not establish historical point-in-time availability. Neither response has release/revision times; fixed one-trading-day lag is an explicit exploratory assumption, not proof of historical publish timing. Do not use T share data at T17:00. No claims of strict reconstructed historical availability."
review["artifacts"] = {p.name: {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                "bytes": p.stat().st_size}
                       for p in sorted(root.iterdir()) if p.is_file() and p != review_path}
review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"pool_sessions": len(axis), "requests": review["actual_requests"],
                  "axes_identical": review["series_date_axes_identical"],
                  "coverage": {g: review["series"][g]["pool_date_coverage"] for g in frames},
                  "max_daily_absolute_relative_change": {g: review["series"][g]["largest_daily_relative_changes_descriptive_only"][0] for g in frames}}, ensure_ascii=False))
