"""Synthetic endpoint, availability and invalid-input checks only."""

from pathlib import Path
from hashlib import sha256
import json
import numpy as np
import pandas as pd
import pressure_component as c


def run():
    checks, refusals = [], []

    def check(name, value):
        assert value, name
        checks.append(name)

    def refuse(name, frame):
        try:
            c.build_features(frame)
        except ValueError:
            refusals.append(name)
        else:
            raise AssertionError(name)

    index = pd.bdate_range("2019-11-01", periods=60)
    change = np.tile([0.01, -0.02, 0.03, -0.01, 0.02], 12)
    close = 100.0 * np.exp(np.cumsum(change))
    opening = np.r_[100.0, close[:-1]] * np.exp(np.tile([-0.02, 0.01, -0.01], 20))
    bars = pd.DataFrame({"Open": opening, "Close": close}, index=index)
    result = c.build_features(bars)
    i = 35
    vol = np.std(close[i - 19 : i + 1] / close[i - 20 : i] - 1.0, ddof=1)
    check(
        "stretch_exact_four_session_endpoint",
        np.isclose(
            result.short_stretch4.iloc[i], np.log(close[i] / close[i - 4]) / (vol * 2.0), atol=1e-12
        ),
    )
    overnight = sum(max(-np.log(opening[j] / close[j - 1]), 0.0) for j in range(i - 3, i + 1))
    intraday = sum(max(-np.log(close[j] / opening[j]), 0.0) for j in range(i - 3, i + 1))
    check(
        "pressure_exact_four_complete_sessions",
        np.allclose(
            result.iloc[i][["overnight_down4", "intraday_down4"]].astype(float),
            [overnight, intraday],
            atol=1e-13,
        ),
    )
    check(
        "pressure_ratio",
        np.isclose(result.overnight_down_share4.iloc[i], overnight / (overnight + intraday)),
    )
    changed_outside = bars.copy()
    changed_outside.iloc[i - 4, changed_outside.columns.get_loc("Open")] *= 0.3
    check(
        "exclude_Tminus4_Open_from_pressure",
        c.build_features(changed_outside).overnight_down_share4.iloc[i]
        == result.overnight_down_share4.iloc[i],
    )
    check(
        "initial_missing_explicit",
        result.short_stretch4.iloc[:20].isna().all()
        and result.short_stretch_reason.iloc[:20].eq("INSUFFICIENT_HISTORY").all(),
    )
    check("initial_pressure_missing", result.overnight_down_share4.iloc[:4].isna().all())
    for size in (21, 35, 50):
        pd.testing.assert_frame_equal(
            c.build_features(bars.iloc[:size]), result.iloc[:size], check_exact=True
        )
        checks.append("prefix_" + str(size))
    future = bars.copy()
    future.iloc[40:] *= np.linspace(0.5, 2.0, 20)[:, None]
    pd.testing.assert_frame_equal(
        c.build_features(future).iloc[:40], result.iloc[:40], check_exact=True
    )
    checks.append("future_mutation_invariant")
    scaled = c.build_features(bars * 19.0)
    check(
        "scale_invariance",
        np.allclose(
            scaled.drop(columns="short_stretch_reason"),
            result.drop(columns="short_stretch_reason"),
            equal_nan=True,
            atol=1e-10,
            rtol=1e-10,
        ),
    )
    flat = pd.DataFrame({"Open": 100.0, "Close": 100.0}, index=index)
    observed = c.build_features(flat)
    check(
        "zero_vol_unavailable_without_epsilon",
        observed.short_stretch4.iloc[20:].isna().all()
        and observed.short_stretch_reason.iloc[20:].eq("ZERO_VOLATILITY").all(),
    )
    check(
        "no_down_zero_retained",
        observed.overnight_down_share4.iloc[4:].eq(0.0).all() and len(observed) == len(flat),
    )
    down_overnight = bars.copy()
    down_overnight["Open"] = down_overnight.Close / 1.1
    # Four terminal sessions with negative overnight but nonnegative intraday.
    down_overnight.iloc[-5:] = [
        [200.0, 210.0],
        [190.0, 200.0],
        [180.0, 190.0],
        [170.0, 180.0],
        [160.0, 170.0],
    ]
    check(
        "overnight_only_down_share_one",
        c.build_features(down_overnight).overnight_down_share4.iloc[-1] == 1.0,
    )
    intraday_only = bars.copy()
    intraday_only.iloc[-5:] = [
        [210.0, 200.0],
        [201.0, 190.0],
        [191.0, 180.0],
        [181.0, 170.0],
        [171.0, 160.0],
    ]
    check(
        "intraday_only_down_share_zero",
        c.build_features(intraday_only).overnight_down_share4.iloc[-1] == 0.0,
    )
    ignored = bars.assign(High=np.nan, Low=-99.0, future_return=999.0)
    pd.testing.assert_frame_equal(c.build_features(ignored), result, check_exact=True)
    checks.append("unused_High_Low_labels")
    refuse("empty", bars.iloc[:0])
    refuse("reversed", bars.iloc[::-1])
    refuse("duplicate_index", pd.concat([bars.iloc[:1], bars]))
    refuse("non_datetime", bars.reset_index(drop=True))
    refuse("missing_Open", bars.drop(columns="Open"))
    refuse("duplicate_column", pd.concat([bars, bars[["Close"]]], axis=1))
    refuse("not_dataframe", None)
    zoned = bars.copy()
    zoned.index = zoned.index.tz_localize("Asia/Shanghai")
    refuse("timezone", zoned)
    offclock = bars.copy()
    offclock.index += pd.Timedelta(hours=1)
    refuse("not_midnight", offclock)
    missing = bars.copy()
    dates = list(missing.index)
    dates[0] = pd.NaT
    missing.index = pd.DatetimeIndex(dates)
    refuse("NaT", missing)
    for column in ("Open", "Close"):
        for name, value in (("zero", 0.0), ("negative", -1.0), ("NaN", np.nan), ("inf", np.inf)):
            invalid = bars.copy()
            invalid.iloc[0, invalid.columns.get_loc(column)] = value
            refuse(column + "_" + name, invalid)
    return {
        "status": "PASS",
        "synthetic_only": True,
        "checks": checks,
        "refusals": refusals,
        "market_reads": 0,
        "accounts": 0,
        "source_sha256": sha256(Path(c.__file__).read_bytes()).hexdigest(),
        "check_source_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    }


if __name__ == "__main__":
    proof = run()
    Path(__file__).with_name("focused_checks.json").write_text(json.dumps(proof, indent=2), "utf-8")
    c.write_method(Path(__file__).with_name("method.json"))
    print({"status": "PASS", "checks": len(proof["checks"]), "refusals": len(proof["refusals"])})
