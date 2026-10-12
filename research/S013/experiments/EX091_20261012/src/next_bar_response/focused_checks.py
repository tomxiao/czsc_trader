"""Synthetic-only checks; no real-market reads or experiment allocation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

import features as f


def synthetic(body, volume, days=24):
    axis = pd.bdate_range("2020-01-02", periods=days)
    body = np.broadcast_to(np.asarray(body, float), (days, 8)).copy()
    volume = np.broadcast_to(np.asarray(volume, float), (days, 8)).copy()
    dates = pd.DatetimeIndex(
        np.repeat(axis.to_numpy(), 8)
        + np.tile(pd.to_timedelta([s + ":00" for s in f.CLOCKS]), days)
    )
    bars = pd.DataFrame({
        "Date": dates, "Open": np.full(days * 8, 100.0),
        "Close": 100 * np.exp(body.ravel()), "Volume": volume.ravel(),
    })
    return bars, axis


def old_module(relative, name):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location(name, root / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run():
    checks, refused = [], []
    b = [-.02, .03, -.01, -.04, .05, .02, .01, -.08]
    bars, axis = synthetic(b, np.ones(8))
    out, trace = f.build(bars, axis)
    assert tuple(out.columns) == f.COLUMNS
    np.testing.assert_allclose(out.X, 0, atol=1e-15)
    checks.append("equal source volumes give X zero")
    changed = bars.copy()
    changed.loc[changed.index % 8 == 0, "Volume"] = 10
    alt, _ = f.build(changed, axis)
    assert (alt.X > out.X).all()
    np.testing.assert_allclose(alt.U, out.U, atol=0)
    expected_s = (10 * .03 - .04 + .05) / 12
    np.testing.assert_allclose(alt.S, expected_s, atol=1e-14)
    checks.append("volume emphasis on recovering negative source changes response")
    assert trace.iloc[0].source_indices == [0, 2, 3]
    assert trace.iloc[0].successor_indices == [1, 3, 4]
    next_day = bars.copy()
    next_day.loc[8:15, "Close"] *= 2
    first, _ = f.build(next_day, axis[:1])
    pd.testing.assert_frame_equal(first, out.iloc[:1])
    last_changed = bars.copy()
    last_changed.loc[7, "Close"] = 1
    last, lt = f.build(last_changed, axis[:1])
    np.testing.assert_allclose(last[["X", "S", "U"]], out.iloc[:1][["X", "S", "U"]])
    assert lt.iloc[0].source_indices == [0, 2, 3]
    checks.append("no last-bar source or following-day response")
    for n in (1, 20, 21, 24):
        prefix, pt = f.build(bars.iloc[:n * 8], axis[:n])
        pd.testing.assert_frame_equal(prefix, out.iloc[:n])
        pd.testing.assert_frame_equal(pt, trace.iloc[:n])
    checks.append("all prefixes invariant")
    assert out.past_clock_samebar.iloc[:20].isna().all()
    assert trace.iloc[19].past_clock_samebar_reason == "INSUFFICIENT_PAST20_FULL_SESSIONS"
    assert trace.iloc[20].past_clock_available
    clock_change = bars.copy()
    clock_change.loc[160:167, "Volume"] = [1000, 1, 1, 1, 1, 1, 1, 1]
    co, ct = f.build(clock_change, axis)
    np.testing.assert_allclose(co.past_clock_samebar.iloc[20], out.past_clock_samebar.iloc[20])
    np.testing.assert_allclose(ct.iloc[20].past_clock_weights, np.full(8, 1/8))
    assert not np.allclose(ct.iloc[21].past_clock_weights, np.full(8, 1/8))
    assert all(pd.Timestamp(d) < axis[20] for d in ct.iloc[20].past_window_dates)
    checks.append("past20 excludes current; exact20 histories and next-day adaptation")
    old = old_module("research/S013/experiments/EX075_20261011/src/component_draft.py", "old_volume")
    old_frame, _ = old.features(changed.set_index("Date"))
    np.testing.assert_allclose(alt.negative_body_mean, old_frame.mean_negative_body, atol=0)
    np.testing.assert_allclose(alt.samebar_cov, old_frame.down_volume_cov, atol=0)
    np.testing.assert_allclose(alt.past_clock_samebar, old_frame.past_volume_shape_projection, atol=0, equal_nan=True)
    checks.append("old EX075 same-bar fields exactly match synthetic inputs")
    bare, ba = synthetic(np.zeros(8), np.ones(8))
    no, nt = f.build(bare, ba)
    assert no[["X", "S", "U", "sources_negative_mean"]].isna().all().all()
    assert nt.X_reason.eq("NO_NEGATIVE_SOURCE_PAIR").all()
    zero, za = synthetic([-.02, 0, .01, .01, .01, .01, .01, .01], np.ones(8))
    zo, _ = f.build(zero, za)
    np.testing.assert_array_equal(zo[["X", "S", "U"]], 0)
    checks.append("no sources NA; actual zero successor remains zero")
    source_zero = bars.copy()
    source_zero.loc[source_zero.index % 8 == 0, "Volume"] = 0
    source_zero.loc[source_zero.index % 8 == 2, "Volume"] = 0
    source_zero.loc[source_zero.index % 8 == 3, "Volume"] = 0
    sz, st = f.build(source_zero, axis)
    assert sz[["X", "S"]].isna().all().all() and sz.U.notna().all()
    assert st.X_reason.eq("ZERO_SOURCE_VOLUME").all()
    assert st.iloc[20].past_clock_next_response_reason == "ZERO_PAST_CLOCK_SOURCE_WEIGHT"
    fullzero = bars.copy()
    fullzero.loc[:7, "Volume"] = 0
    zz, zt = f.build(fullzero, axis)
    assert zt.iloc[0].X_reason == "ZERO_SESSION_VOLUME"
    assert np.isnan(zz.samebar_cov.iloc[0]) and np.isfinite(zz.U.iloc[0])
    assert zt.iloc[20].past_clock_samebar_reason == "ZERO_VOLUME_IN_PAST20_PROFILE"
    assert zt.iloc[21].past_clock_available
    checks.append("zero source/session volume explicit; past zero invalidates exact window")
    pd.testing.assert_frame_equal(f.build(bars, axis[20:])[0], out.iloc[20:])
    checks.append("warmup outside selected axis retained without silent filling")
    scaled = bars.copy()
    scales = np.repeat(np.arange(1, len(axis)+1), 8)
    scaled[["Open", "Close"]] = scaled[["Open", "Close"]].mul(scales, axis=0)
    scaled.Volume *= scales
    sc, _ = f.build(scaled, axis)
    np.testing.assert_allclose(sc, out, atol=2e-14, equal_nan=True)
    checks.append("per-session HFQ price/volume scale cancels")
    bads = {}
    bads["missing_bar"] = bars.drop(index=2)
    bads["wrong_clock"] = bars.copy()
    bads["wrong_clock"].loc[0, "Date"] += pd.Timedelta(minutes=1)
    bads["duplicate"] = bars.copy()
    bads["duplicate"].loc[1, "Date"] = bars.Date.iloc[0]
    bads["unordered"] = bars.iloc[::-1]
    bads["nan_price"] = bars.copy()
    bads["nan_price"].loc[0, "Close"] = np.nan
    bads["zero_price"] = bars.copy()
    bads["zero_price"].loc[0, "Open"] = 0
    bads["negative_volume"] = bars.copy()
    bads["negative_volume"].loc[0, "Volume"] = -1
    bads["nan_volume"] = bars.copy()
    bads["nan_volume"].loc[0, "Volume"] = np.nan
    bads["missing_column"] = bars.drop(columns="Volume")
    bads["duplicate_column"] = pd.concat([bars, bars[["Open"]]], axis=1)
    bads["non_datetime"] = bars.assign(Date=bars.Date.astype(str))
    bads["timezone"] = bars.assign(Date=bars.Date.dt.tz_localize("Asia/Shanghai"))
    bads["nat"] = bars.copy()
    bads["nat"].loc[0, "Date"] = pd.NaT
    for name, bad in bads.items():
        try:
            f.build(bad, axis)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("not rejected: " + name)
    for name, bad_axis in {
        "absent_axis": axis.append(pd.DatetimeIndex([axis[-1] + pd.Timedelta(days=10)])),
        "duplicated_axis": axis.insert(1, axis[0]),
        "unordered_axis": axis[::-1],
        "intraday_axis": axis + pd.Timedelta(hours=1),
        "timezone_axis": axis.tz_localize("Asia/Shanghai"),
        "empty_axis": axis[:0],
    }.items():
        try:
            f.build(bars, bad_axis)
        except ValueError:
            refused.append(name)
        else:
            raise AssertionError("not rejected: " + name)
    return {
        "status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
        "accounts": 0, "experiments_allocated": 0,
        "checks": checks, "rejections": refused,
        "check_count": len(checks), "rejection_count": len(refused),
    }


if __name__ == "__main__":
    result = run()
    target = Path(__file__).with_suffix(".json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
