from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from factor_signal_catalog.calculations import (
    SellSideRevisionParameters,
    calculate_chinext_turnover_z20,
    calculate_daily_close_vwap_deviation,
    calculate_daily_intraday_range,
    calculate_earnings_acceleration_breadth,
    calculate_etf_nav_premium,
    calculate_etf_share_change,
    calculate_etf_share_change_5d_lag1,
    calculate_external_industry_moneyflow,
    calculate_sell_side_revision_breadth,
    calculate_prior_us_spx_return,
    calculate_shibor_on_change_5d,
)


def test_share_change_is_per_symbol_and_requires_consecutive_sessions():
    calendar = pd.date_range("2026-01-05", periods=3, freq="B")
    shares = pd.DataFrame({
        "ts_code": ["A", "B", "A", "B", "A", "B"],
        "trade_date": list(calendar.repeat(2)), "total_share": [100, 50, 110, 40, 121, 40],
    })
    original = shares.copy(deep=True)
    result = calculate_etf_share_change(shares.iloc[::-1], calendar)
    assert result["share_change"].tolist() == pytest.approx(
        [np.nan, 0.1, 0.1, np.nan, -0.2, 0], nan_ok=True,
    )
    pd.testing.assert_frame_equal(shares, original)
    with pytest.raises(ValueError, match="consecutive"):
        calculate_etf_share_change(shares.drop(index=2), calendar)


@pytest.mark.parametrize("column,value", [
    ("total_share", 0), ("total_share", -1), ("total_share", np.inf),
    ("total_share", np.nan), ("total_share", True), ("trade_date", "2026-01-05T01:00:00"),
])
def test_share_change_rejects_invalid_values(column, value):
    shares = pd.DataFrame({"ts_code": ["A"], "trade_date": ["2026-01-05"], "total_share": [1]})
    shares[column] = value
    with pytest.raises(ValueError):
        calculate_etf_share_change(shares, pd.DatetimeIndex(["2026-01-05"]))


def test_nav_premium_and_invalid_identity():
    values = pd.DataFrame({
        "ts_code": ["A", "B"], "trade_date": ["2026-01-05"] * 2,
        "close": [105, 90], "nav": [100, 100],
    })
    assert calculate_etf_nav_premium(values)["nav_premium"].tolist() == pytest.approx([0.05, -0.1])
    with pytest.raises(ValueError, match="duplicate"):
        calculate_etf_nav_premium(pd.concat([values, values]))
    with pytest.raises(ValueError, match="missing columns"):
        calculate_etf_nav_premium(values.drop(columns="nav"))
    with pytest.raises(ValueError, match="positive"):
        calculate_etf_nav_premium(values.assign(nav=0))


def _earnings():
    disclosures = pd.DataFrame([
        ["A", "2025-01-02", "2024-12-31", "forecast", 10],
        ["A", "2026-01-05", "2025-12-31", "express", -10],
        ["A", "2026-01-05", "2025-12-31", "forecast", 20],
        ["B", "2025-01-02", "2024-12-31", "forecast", 10],
        ["B", "2026-01-05", "2025-12-31", "forecast", 5],
    ], columns=["ts_code", "ann_date", "end_date", "source", "profit_growth_yoy"])
    membership = pd.DataFrame([
        ["2026-01-06", "A", 30], ["2026-01-06", "B", 10],
    ], columns=["dt", "con_code", "weight"])
    calendar = pd.date_range("2026-01-05", periods=3, freq="B")
    return disclosures, membership, calendar


def test_earnings_source_priority_and_next_session_weights():
    disclosures, membership, calendar = _earnings()
    result = calculate_earnings_acceleration_breadth(
        disclosures, membership, calendar, source_priority=("forecast", "express"),
    )
    row = result.iloc[0]
    assert row["eligible_session"] == pd.Timestamp("2026-01-06")
    assert row["positive_weight"] == 30
    assert row["negative_weight"] == 10
    assert row["net_breadth"] == 20
    future = pd.concat([disclosures, pd.DataFrame([
        ["A", "2026-01-07", "2025-12-31", "forecast", -100],
    ], columns=disclosures.columns)])
    pd.testing.assert_frame_equal(result, calculate_earnings_acceleration_breadth(
        future, membership, calendar, source_priority=("forecast", "express"),
    ))


def test_earnings_cannot_use_future_baseline_or_nonmembers():
    disclosures, membership, calendar = _earnings()
    disclosures.loc[0, "ann_date"] = "2026-01-07"
    result = calculate_earnings_acceleration_breadth(
        disclosures, membership, calendar, source_priority=("forecast", "express"),
    )
    assert result.iloc[0]["net_breadth"] == -10
    membership.loc[0, "con_code"] = "OTHER"
    assert calculate_earnings_acceleration_breadth(
        disclosures, membership, calendar, source_priority=("forecast", "express"),
    ).iloc[0]["disclosures"] == 1
    with pytest.raises(ValueError, match="duplicate"):
        calculate_earnings_acceleration_breadth(
            disclosures, pd.concat([membership, membership]), calendar,
            source_priority=("forecast", "express"),
        )


def test_earnings_unpaired_periods_produce_no_events():
    disclosures, membership, calendar = _earnings()
    result = calculate_earnings_acceleration_breadth(
        disclosures.loc[disclosures["end_date"].eq("2025-12-31")], membership, calendar,
        source_priority=("forecast", "express"),
    )
    assert result.empty
    assert list(result.columns) == [
        "eligible_session", "disclosures", "positive_weight", "negative_weight", "net_breadth",
    ]


def _flows():
    data = pd.DataFrame({
        "trade_date": ["2026-01-05", "2026-01-05", "2026-01-06", "2026-01-06"],
        "ts_code": ["A", "B", "A", "B"], "net_mf_amount": [8, -4, 8, -4],
    })
    for size in ("sm", "md", "lg", "elg"):
        for side in ("buy", "sell"):
            data[f"{side}_{size}_amount"] = 2.0
    members = pd.DataFrame({
        "trade_date": ["2026-01-05", "2026-01-06"], "ts_code": ["A", "B"],
    })
    return data, members


def test_industry_excludes_current_index_members_and_zero_gross_is_undefined():
    data, members = _flows()
    result = calculate_external_industry_moneyflow(data, members)
    assert result["active_members"].tolist() == [1, 1]
    assert result["positive_member_ratio"].tolist() == [0, 1]
    assert result["net_flow_ratio"].tolist() == [-0.25, 0.5]
    for column in data.columns:
        if column.endswith("_amount") and column != "net_mf_amount":
            data[column] = 0.0
    assert calculate_external_industry_moneyflow(data, members)["net_flow_ratio"].isna().all()
    with pytest.raises(ValueError, match="nonnegative"):
        calculate_external_industry_moneyflow(data.assign(buy_sm_amount=-1), members)
    with pytest.raises(ValueError, match="finite"):
        calculate_external_industry_moneyflow(data.assign(net_mf_amount=np.nan), members)
    with pytest.raises(ValueError, match="lacks"):
        calculate_external_industry_moneyflow(data, members.iloc[:1])


def test_industry_no_external_members_does_not_report_zero_flow():
    data, _ = _flows()
    result = calculate_external_industry_moneyflow(data, data[["trade_date", "ts_code"]])
    assert result["active_members"].eq(0).all()
    assert result[["positive_member_ratio", "net_mf_amount", "net_flow_ratio"]].isna().all().all()


def _reports():
    return pd.DataFrame([
        ["A", "2026-01-01", "2026-01-02", "X", "2026Q4", 100, 1.0, 20],
        ["A", "2026-01-04", "2026-01-05", "X", "2026Q4", 120, 0.5, 20],
        ["A", "2026-01-01", "2026-01-02", "Y", "2026Q4", np.nan, 1.0, 20],
        ["A", "2026-01-04", "2026-01-05", "Y", "2026Q4", np.nan, 0.8, 20],
        ["B", "2026-01-01", "2026-01-02", "X", "2026Q4", 100, 1.0, 10],
        ["B", "2026-01-04", "2026-01-05", "X", "2026Q4", 101, 1.5, 10],
    ], columns=["ts_code", "report_date", "available_session", "org_name", "quarter", "np", "eps", "weight"])


def test_revision_np_preference_eps_pair_broker_aggregation_and_strict_threshold():
    calendar = pd.date_range("2026-01-02", periods=4, freq="B")
    reports = _reports()
    result = calculate_sell_side_revision_breadth(
        reports.iloc[::-1], calendar, SellSideRevisionParameters(rolling_sessions=2),
    )
    assert result["revision_score"].tolist() == pytest.approx(
        [np.nan, 0, 0, np.nan], nan_ok=True,
    )
    assert result.iloc[1]["observed_weight"] == 30
    # Add a second forecast period for broker X: +1 and -1 median to zero,
    # then brokers X=0 and Y=-1 average to -0.5 for A.
    other = reports.iloc[:2].copy().assign(quarter="2027Q4")
    other.loc[other.index[1], "np"] = 80
    combined = pd.concat([reports, other])
    revised = calculate_sell_side_revision_breadth(
        combined, calendar, SellSideRevisionParameters(rolling_sessions=2),
    )
    assert revised.iloc[1]["revision_score"] == pytest.approx(-1 / 3)
    future = pd.concat([combined, reports.iloc[[1]].assign(
        report_date="2026-01-06", available_session="2026-01-07", np=200,
    )])
    extended = calculate_sell_side_revision_breadth(
        future, calendar, SellSideRevisionParameters(rolling_sessions=2),
    )
    pd.testing.assert_frame_equal(revised.iloc[:3], extended.iloc[:3])


def test_revision_age_boundary_zero_baseline_and_unavailable_previous_report():
    reports = _reports().iloc[:2].copy()
    reports.loc[0, "report_date"] = "2025-01-04"
    calendar = pd.date_range("2026-01-02", periods=4, freq="B")
    assert calculate_sell_side_revision_breadth(
        reports, calendar, SellSideRevisionParameters(rolling_sessions=1),
    ).iloc[1]["revision_score"] == 1
    reports.loc[0, "report_date"] = "2025-01-03"
    assert calculate_sell_side_revision_breadth(
        reports, calendar, SellSideRevisionParameters(rolling_sessions=1),
    )["revision_score"].isna().all()
    reports.loc[0, "report_date"] = "2026-01-01"
    reports.loc[0, "np"] = 0
    assert calculate_sell_side_revision_breadth(
        reports, calendar, SellSideRevisionParameters(rolling_sessions=1),
    )["revision_score"].isna().all()
    reports.loc[0, "np"] = 100
    reports.loc[0, "available_session"] = "2026-01-06"
    assert calculate_sell_side_revision_breadth(
        reports, calendar, SellSideRevisionParameters(rolling_sessions=1),
    )["revision_score"].isna().all()


@pytest.mark.parametrize("kwargs", [
    {"rolling_sessions": 0}, {"rolling_sessions": True},
    {"maximum_previous_age_days": -1}, {"minimum_relative_revision": np.inf},
    {"minimum_relative_revision": -0.1},
])
def test_revision_parameters_reject_invalid_values(kwargs):
    with pytest.raises(ValueError):
        SellSideRevisionParameters(**kwargs)


def test_revision_rejects_duplicate_reports_and_inconsistent_weights():
    reports = _reports()
    calendar = pd.date_range("2026-01-02", periods=4, freq="B")
    with pytest.raises(ValueError, match="duplicate"):
        calculate_sell_side_revision_breadth(
            pd.concat([reports, reports]), calendar, SellSideRevisionParameters(),
        )
    reports.loc[3, "weight"] = 21
    with pytest.raises(ValueError, match="weight must agree"):
        calculate_sell_side_revision_breadth(reports, calendar, SellSideRevisionParameters())


def test_five_session_share_change_is_lagged_per_symbol_and_causal():
    calendar = pd.date_range("2026-01-05", periods=8, freq="B")
    data = pd.DataFrame({
        "ts_code": ["A"] * 8 + ["B"] * 8,
        "trade_date": list(calendar) * 2,
        "total_share": list(range(100, 108)) + [200] * 8,
    })
    result = calculate_etf_share_change_5d_lag1(data, calendar)
    assert result.iloc[:6]["share_change_5d_lag1"].isna().all()
    assert result.iloc[6]["share_change_5d_lag1"] == pytest.approx(0.05)
    assert result.iloc[7]["share_change_5d_lag1"] == pytest.approx(106 / 101 - 1)
    assert result.iloc[14:]["share_change_5d_lag1"].eq(0).all()
    data.loc[6, "total_share"] = 300
    assert calculate_etf_share_change_5d_lag1(data, calendar).iloc[6][
        "share_change_5d_lag1"
    ] == result.iloc[6]["share_change_5d_lag1"]


def test_daily_vwap_units_and_zero_volume_failure():
    data = pd.DataFrame({
        "ts_code": ["A"], "trade_date": ["2026-01-05"],
        "close": [12], "amount": [1000], "volume": [100],
    })
    assert calculate_daily_close_vwap_deviation(data).iloc[0][
        "daily_close_vwap_deviation"
    ] == pytest.approx(0.2)
    with pytest.raises(ValueError, match="positive"):
        calculate_daily_close_vwap_deviation(data.assign(volume=0))


def test_spx_maps_explicit_completed_times_before_open_in_decimal_units():
    data = pd.DataFrame({
        "ts_code": ["SPX"] * 3,
        "trade_date": ["2026-01-02", "2026-01-05", "2026-01-06"],
        "pct_chg": [2, -3, 5],
        "available_at": ["2026-01-03T05:00:00Z", "2026-01-06T01:30:00Z",
                         "2026-01-07T05:00:00Z"],
    })
    opens = pd.DatetimeIndex(["2026-01-05T09:30:00+08:00", "2026-01-06T09:30:00+08:00"])
    result = calculate_prior_us_spx_return(data, opens)
    # Same-timestamp availability is excluded, and future availability is unused.
    assert result["prior_us_spx_return"].tolist() == [0.02, 0.02]
    later_open = pd.DatetimeIndex(["2026-01-06T01:30:01Z"])
    assert calculate_prior_us_spx_return(data, later_open).iloc[0]["prior_us_spx_return"] == -0.03
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_prior_us_spx_return(data, opens.tz_localize(None))
    with pytest.raises(ValueError, match="lacks"):
        calculate_prior_us_spx_return(data, pd.DatetimeIndex(["2026-01-02T01:30:00Z"]))
    with pytest.raises(ValueError, match="duplicate"):
        calculate_prior_us_spx_return(pd.concat([data, data.iloc[:1]]), opens)


def test_chinext_z20_uses_population_std_and_constant_window_is_undefined():
    calendar = pd.date_range("2026-01-05", periods=22, freq="B")
    data = pd.DataFrame({
        "ts_code": ["399006.SZ"] * 22, "trade_date": calendar,
        "turnover_rate_f": np.arange(1, 23),
    })
    result = calculate_chinext_turnover_z20(data, calendar)
    assert result.iloc[:19]["chinext_turnover_z20"].isna().all()
    assert result.iloc[19]["chinext_turnover_z20"] == pytest.approx(
        (20 - np.mean(np.arange(1, 21))) / np.std(np.arange(1, 21), ddof=0),
    )
    data.loc[21, "turnover_rate_f"] = 99
    pd.testing.assert_series_equal(
        result.iloc[:21]["chinext_turnover_z20"],
        calculate_chinext_turnover_z20(data, calendar).iloc[:21]["chinext_turnover_z20"],
    )
    assert calculate_chinext_turnover_z20(data.assign(turnover_rate_f=1), calendar)[
        "chinext_turnover_z20"
    ].isna().all()
    with pytest.raises(ValueError, match="consecutive"):
        calculate_chinext_turnover_z20(data.drop(index=10), calendar)
    with pytest.raises(ValueError, match="399006"):
        calculate_chinext_turnover_z20(data.assign(ts_code="OTHER"), calendar)


def test_shibor_absolute_change_retains_percentage_point_units():
    calendar = pd.date_range("2026-01-05", periods=7, freq="B")
    data = pd.DataFrame({"trade_date": calendar, "on": [2, 2, 2, 2, 2, 2.5, 1.5]})
    result = calculate_shibor_on_change_5d(data, calendar)
    assert result.iloc[:5]["shibor_on_change_5d"].isna().all()
    assert result.iloc[5:]["shibor_on_change_5d"].tolist() == [0.5, -0.5]
    with pytest.raises(ValueError, match="consecutive"):
        calculate_shibor_on_change_5d(data.drop(index=2), calendar)
    with pytest.raises(ValueError, match="finite"):
        calculate_shibor_on_change_5d(data.assign(on=np.inf), calendar)


def test_daily_range_decimal_units_and_consistent_price_bounds():
    data = pd.DataFrame({
        "ts_code": ["A"], "trade_date": ["2026-01-05"], "high": [12], "low": [8], "close": [10],
    })
    assert calculate_daily_intraday_range(data).iloc[0]["daily_intraday_range"] == 0.4
    assert calculate_daily_intraday_range(data.assign(high=10, low=10)).iloc[0][
        "daily_intraday_range"
    ] == 0
    with pytest.raises(ValueError, match="low <= close <= high"):
        calculate_daily_intraday_range(data.assign(close=15))
    with pytest.raises(ValueError, match="positive"):
        calculate_daily_intraday_range(data.assign(low=-1))
