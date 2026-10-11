"""Pure synthetic checks; never loads market data or executes accounts."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from component_definitions import (
    intraday_downside_energy,
    mature_training_mask,
    overnight_downside_risk,
    short_horizon_labels,
)


def expect_refusal(call):
    try:
        call()
    except ValueError:
        return
    raise AssertionError("invalid input not refused")


def main():
    rng = np.random.default_rng(13)
    dates = pd.bdate_range("2023-11-01", periods=80)
    opening = 100 * np.exp(np.cumsum(rng.normal(0, .01, len(dates))))
    closing = opening * np.exp(rng.normal(0, .005, len(dates)))
    daily = pd.DataFrame({"Date": dates, "Open": opening, "Close": closing, "Low": np.minimum(opening, closing) * .99})
    rows = []
    for day, start in zip(dates, opening, strict=True):
        closes = start * np.exp(np.cumsum(rng.normal(0, .002, 8)))
        for number in range(8):
            rows.append((day + pd.Timedelta(hours=10, minutes=30 * number), start if number == 0 else closes[number - 1], closes[number]))
    bars = pd.DataFrame(rows, columns=["Date", "Open", "Close"])
    h1 = intraday_downside_energy(bars)
    h2 = overnight_downside_risk(daily)
    labels = short_horizon_labels(daily)
    checks = []
    for length in (25, 40, 60):
        assert_frame_equal(intraday_downside_energy(bars.iloc[:length * 8]), h1.iloc[:length])
        assert_frame_equal(overnight_downside_risk(daily.iloc[:length]), h2.iloc[:length])
        checks.append(f"feature_prefix_{length}")
        prefix_labels = short_horizon_labels(daily.iloc[:length])
        assert_frame_equal(prefix_labels.iloc[:length - 6], labels.iloc[:length - 6])
        checks.append(f"mature_label_prefix_{length}")
    future_daily = daily.copy()
    future_daily.loc[40:, ["Open", "Close", "Low"]] *= 4
    future_bars = bars.copy()
    future_bars.loc[40 * 8:, ["Open", "Close"]] *= 4
    assert_frame_equal(overnight_downside_risk(future_daily).iloc[:40], h2.iloc[:40])
    assert_frame_equal(intraday_downside_energy(future_bars).iloc[:40], h1.iloc[:40])
    assert_frame_equal(short_horizon_labels(future_daily).iloc[:34], labels.iloc[:34])
    checks.append("future_modification_invariance")
    scaled_daily = daily.copy()
    scaled_daily[["Open", "Close", "Low"]] *= 7.3
    scaled_bars = bars.copy()
    scaled_bars[["Open", "Close"]] *= 7.3
    assert_frame_equal(overnight_downside_risk(scaled_daily), h2, atol=1e-14, rtol=1e-12)
    assert_frame_equal(intraday_downside_energy(scaled_bars), h1, atol=1e-14, rtol=1e-12)
    assert_frame_equal(short_horizon_labels(scaled_daily), labels, atol=1e-14, rtol=1e-12)
    checks.append("positive_price_scale_invariance")
    path1 = np.array([.01, .01, -.005, -.005, .001, .001, .001, -.004])
    path2 = np.array([.001, .001, .001, .001, .001, .001, .001, .002])
    assert np.isclose(path1.sum(), path2.sum())
    def energy(path):
        closes = 100 * np.exp(path.cumsum())
        stamp = np.concatenate([(day + pd.to_timedelta(np.arange(8) * 30 + 600, unit="min")).to_numpy() for day in dates[:20]])
        return intraday_downside_energy(pd.DataFrame({"Date": stamp, "Open": np.tile(np.r_[100, closes[:-1]], 20), "Close": np.tile(closes, 20)}))
    a, b = energy(path1), energy(path2)
    assert np.isclose(a.intraday_net_logreturn.iloc[0], b.intraday_net_logreturn.iloc[0])
    assert a.feature_intraday_down_energy20.iloc[-1] > b.feature_intraday_down_energy20.iloc[-1]
    checks.append("same_net_return_different_path_information")
    fixture = pd.DataFrame({"Date": pd.bdate_range("2024-01-01", periods=8), "Open": [100., 100., 110., 120., 130., 140., 150., 160.], "Low": [99., 90., 105., 115., 1., 130., 140., 150.]})
    fixture_labels = short_horizon_labels(fixture)
    assert np.isclose(fixture_labels.return_h3.iloc[0], .3)
    assert fixture_labels.risk_h3.iloc[0] == .1 or np.isclose(fixture_labels.risk_h3.iloc[0], .1)
    assert fixture_labels.label_entry_h3.iloc[0] == fixture.Date.iloc[1]
    assert fixture_labels.label_exit_h3.iloc[0] == fixture.Date.iloc[4]
    assert fixture_labels.risk_h5.iloc[0] == .99
    assert fixture_labels.iloc[-6:][["return_h5", "risk_h5", "label_entry_h5", "label_exit_h5"]].isna().all().all()
    checks.append("full_holding_horizon_entry_low_included_exit_low_excluded_and_tail_missing")
    first_test = fixture.Date.iloc[4]
    mask = mature_training_mask(fixture_labels, 3, first_test)
    assert not mask.any()
    later_mask = mature_training_mask(fixture_labels, 3, fixture.Date.iloc[5])
    assert later_mask.sum() == 1 and later_mask.iloc[0]
    checks.append("strict_label_maturity_before_test_signal")
    flat = bars.iloc[:20 * 8].copy()
    flat[["Open", "Close"]] = 100.
    invalid_price = daily.copy()
    invalid_price.loc[4, "Open"] = 0.
    missing_price = bars.copy()
    missing_price.loc[4, "Close"] = np.nan
    duplicate = bars.copy()
    duplicate.loc[1, "Date"] = duplicate.loc[0, "Date"]
    for name, call in (
        ("zero_energy", lambda: intraday_downside_energy(flat)),
        ("missing_bar", lambda: intraday_downside_energy(bars.iloc[:-1])),
        ("duplicate_bar", lambda: intraday_downside_energy(duplicate)),
        ("missing_price", lambda: intraday_downside_energy(missing_price)),
        ("zero_price", lambda: overnight_downside_risk(invalid_price)),
        ("wrong_horizon", lambda: mature_training_mask(labels, 4, dates[40])),
    ):
        expect_refusal(call)
        checks.append(f"refuse_{name}")
    result = {"status": "PASS", "checks": checks, "count": len(checks), "seed": 13, "real_asset_read": False, "financial_account_execution": False}
    path = Path(__file__).with_name("component_checks.json")
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
