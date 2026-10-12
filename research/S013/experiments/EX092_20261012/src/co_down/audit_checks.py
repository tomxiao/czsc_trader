"""Synthetic-only independent co-down audit checks; never reads real inputs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

import audit_features as audit
import features as primary


def paired(aa, bb, start="2020-12-01"):
    calendar = pd.bdate_range(start, periods=len(aa)+1)
    opening, closing = [100.0], [100.0]
    for a, b in zip(aa, bb):
        opening.append(closing[-1] * np.exp(-a))
        closing.append(opening[-1] * np.exp(-b))
    prices = pd.DataFrame({"open": opening, "close": closing}, index=calendar)
    return prices, calendar


def exercise(prices, axis, calendar):
    result, trace = primary.build(prices, axis, calendar)
    cert = audit.verify(prices, axis, calendar, result, trace)
    return result, trace, cert


def run():
    checks, rejections, cases = [], [], []
    aa = np.tile([.01, .02], 15)
    bb = aa.copy()
    prices, calendar = paired(aa, bb)
    result, trace, cert = exercise(prices, calendar, calendar)
    cases.append(cert)
    anti_prices, _ = paired(aa, bb[::-1])
    anti, _, anti_cert = exercise(anti_prices, calendar, calendar)
    cases.append(anti_cert)
    np.testing.assert_allclose(result.iloc[20, 1:], anti.iloc[20, 1:], atol=1e-14)
    assert result.iloc[20, 0] > 0 and anti.iloc[20, 0] < 0
    checks.append("same six marginals different negative pairing changes X")
    assert result.iloc[:20].isna().all().all()
    assert all(t["reason"] == "INSUFFICIENT_HISTORY" for t in trace[:20])
    assert trace[20]["window_positions"] == list(range(1, 21))
    assert trace[20]["predecessor_position"] == 0
    assert trace[20]["max_observation_date"] == calendar[20].isoformat()
    checks.append("first20 unavailable and every20-gap plus predecessor window exact")
    for count in (1, 20, 21, 27, 31):
        out, pt, pcert = exercise(prices.iloc[:count], calendar[:count], calendar[:count])
        pd.testing.assert_frame_equal(out, result.iloc[:count])
        assert pt == trace[:count]
        cases.append(pcert)
    future = prices.copy()
    future.iloc[22:] *= 4
    prefix, _, _ = exercise(future, calendar[:22], calendar)
    pd.testing.assert_frame_equal(prefix, result.iloc[:22])
    checks.append("prefix invariance and future mutation not consumed")
    scaled, _, sc = exercise(prices * .2803, calendar, calendar)
    np.testing.assert_allclose(scaled, result, atol=1e-12, equal_nan=True)
    cases.append(sc)
    assert calendar[0].year != calendar[-1].year
    assert trace[calendar.get_loc(calendar[calendar.year == 2021][0])]["window_complete"]
    checks.append("HFQ common unit scaling and calendar-year transition no reset")
    for a, b, name in ((np.zeros(30), bb, "gap_zero"),
                       (aa, np.zeros(30), "body_zero"),
                       (np.zeros(30), np.zeros(30), "both_zero")):
        flat, fc = paired(a, b)
        fo, ft, fcert = exercise(flat, fc, fc)
        assert fo.iloc[20:, 0].isna().all() and fo.iloc[20:, 1:].notna().all().all()
        assert all(t["reason"] == "ZERO_NEGATIVE_ENERGY_DENOMINATOR" for t in ft[20:])
        cases.append(fcert)
        checks.append(name + " X unavailable while all six observed marginals retained")
    zero_cov, zc = paired(np.full(30, .01), np.full(30, .02))
    zo, zt, zcert = exercise(zero_cov, zc, zc)
    np.testing.assert_allclose(zo.iloc[20:, 0], 0, atol=1e-12)
    assert all(t["reason"] == "AVAILABLE" for t in zt[20:])
    cases.append(zcert)
    checks.append("zero covariance with positive energies is observed zero not NA")
    mutations = {}
    for name, field, value in (("nan_open", "open", np.nan),
                               ("zero_close", "close", 0),
                               ("negative_open", "open", -1),
                               ("inf_close", "close", np.inf)):
        bad = prices.copy()
        bad.loc[calendar[1], field] = value
        mutations[name] = (bad, calendar, calendar)
    mutations["missing_price_date"] = (prices.drop(index=calendar[3]), calendar, calendar)
    mutations["missing_column"] = (prices.drop(columns="open"), calendar, calendar)
    mutations["duplicate_column"] = (pd.concat([prices, prices[["open"]]], axis=1), calendar, calendar)
    mutations["unordered_calendar"] = (prices, calendar, calendar[::-1])
    mutations["duplicate_calendar"] = (prices, calendar, calendar.insert(2, calendar[1]))
    mutations["signal_gap"] = (prices, calendar.delete(3), calendar)
    mutations["signal_absent"] = (prices, calendar + pd.Timedelta(days=1000), calendar)
    mutations["nonmidnight_signal"] = (prices, calendar + pd.Timedelta(hours=1), calendar)
    mutations["timezone_calendar"] = (prices, calendar, calendar.tz_localize("Asia/Shanghai"))
    mutations["nat_calendar"] = (prices, calendar, calendar.insert(2, pd.NaT))
    bad = prices.copy()
    bad.index = bad.index.insert(2, bad.index[1])[:len(bad)]
    mutations["duplicate_price_date"] = (bad, calendar, calendar)
    for name, (bad, ba, bc) in mutations.items():
        try:
            audit.verify(bad, ba, bc, result, trace)
        except ValueError:
            rejections.append(name)
        else:
            raise AssertionError("failed to reject " + name)
    frauds = []
    for column in audit.COLUMNS:
        bad = result.copy()
        bad.loc[calendar[20], column] += .001
        frauds.append(("feature_" + column, bad, trace))
    bad = result.copy()
    bad.iloc[0, 0] = 0
    frauds.append(("first_NA_filled_zero", bad, trace))
    for key, value in (("window_positions", list(range(2, 22))),
                       ("predecessor_position", 1), ("max_observation_date", calendar[21].isoformat()),
                       ("available", False), ("reason", "INSUFFICIENT_HISTORY"),
                       ("numerator", .123), ("denominator", .321)):
        bad_trace = copy.deepcopy(trace)
        bad_trace[20][key] = value
        frauds.append(("trace_" + key, result, bad_trace))
    for name, bad, bt in frauds:
        try:
            audit.verify(prices, calendar, calendar, bad, bt)
        except ValueError:
            rejections.append(name)
        else:
            raise AssertionError("failed to reject reported mutation " + name)
    checks.append("every numeric column, unavailable cell, and window trace fraud rejected")
    return {
        "status": "PASS", "synthetic_only": True, "real_inputs_read": 0,
        "new_statistics": 0, "accounts": 0, "experiments_allocated": 0,
        "checks": checks, "rejections": rejections, "cases": cases,
        "check_count": len(checks), "rejection_count": len(rejections),
    }


if __name__ == "__main__":
    result = run()
    Path(__file__).with_suffix(".json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({k: result[k] for k in ("status", "check_count", "rejection_count")}, ensure_ascii=False))
