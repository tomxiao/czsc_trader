"""Regression checks for batch consistency and typed subset reads."""

from dataclasses import replace

import pandas as pd
import pytest

from dataflows import (
    DataCoverageRequirement,
    DataRequest,
    DataStatus,
    Dataset,
    MoneyflowParameters,
    PreparePolicy,
    PrepareStatus,
    canonical_frame_sha256,
)


def _request():
    return DataRequest(Dataset.SHIBOR_DAILY, None, "2026-09-14", "2026-09-16", None)


def _rates():
    return pd.DataFrame({
        "Date": pd.date_range("2026-09-14", periods=3),
        "OvernightRate": [1.0, 1.1, 1.2],
    })


def test_refresh_deduplicates_acquisition_but_checks_each_coverage(flow_factory):
    calls = []

    def provider(request):
        calls.append(request)
        return _rates(), {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    first = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=2))
    second = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=3))
    prepared = flows.prepare((first, second), policy=PreparePolicy.REFRESH)
    assert prepared.ready and len(calls) == 1
    assert flows.fetch(first, prepared=prepared.reference).ready
    assert flows.fetch(second, prepared=prepared.reference).ready

    excessive = replace(second, coverage=DataCoverageRequirement(minimum_observations=4))
    rejected = flows.prepare((first, excessive), policy=PreparePolicy.REFRESH)
    assert len(calls) == 2
    assert rejected.status is PrepareStatus.PARTIAL and rejected.reference is None
    assert [item.status for item in rejected.items] == [DataStatus.READY, DataStatus.INCOMPLETE]


def test_conflicting_overlap_prevents_batch_publication(flow_factory):
    calls = []

    def provider(request):
        calls.append(request)
        frame = _rates()
        frame = frame.loc[frame.Date.between(request.start, request.end)].copy()
        if request.start == "2026-09-15":
            frame.loc[frame.Date.eq("2026-09-15"), "OvernightRate"] = 9.9
        return frame, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    result = flows.prepare(
        (_request(), replace(_request(), start="2026-09-15")), policy=PreparePolicy.REFRESH,
    )
    assert len(calls) == 2
    assert result.status is PrepareStatus.FAILED and result.reference is None
    assert all(item.error.code == "INCONSISTENT_PREPARATION" for item in result.items)


def test_moneyflow_fetch_filters_explicit_date_subset_without_supplier_call(flow_factory):
    calls = []
    dates = ("2026-09-14", "2026-09-15", "2026-09-16")

    def provider(request):
        calls.append(request)
        return pd.DataFrame({
            "Date": pd.to_datetime(dates),
            "Symbol": ["600000.SH"] * 3,
            "NetMoneyflowAmount": [1.0, 2.0, 3.0],
        }), {"vendor": "fixture", "primary_key": ["Date", "Symbol"]}

    flows = flow_factory({Dataset.STOCK_MONEYFLOW: provider})
    request = DataRequest(
        Dataset.STOCK_MONEYFLOW, None, dates[0], dates[-1], None,
        parameters=MoneyflowParameters(dates),
    )
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    subset = replace(request, parameters=MoneyflowParameters((dates[0], dates[2])))
    result = flows.fetch(subset, prepared=prepared.reference)
    assert result.ready and len(calls) == 1
    assert result.dataframe.Date.dt.strftime("%Y-%m-%d").tolist() == [dates[0], dates[2]]
    assert result.dataframe.NetMoneyflowAmount.tolist() == [1.0, 3.0]


@pytest.mark.parametrize("categories, ordered", [
    (["a", "b", "unused"], False),
    (["b", "a"], False),
    (["a", "b"], True),
])
def test_categorical_domain_and_order_are_part_of_content_identity(categories, ordered):
    original = pd.DataFrame({"Class": pd.Categorical(["a", "b"], categories=["a", "b"])})
    changed = pd.DataFrame({
        "Class": pd.Categorical(["a", "b"], categories=categories, ordered=ordered),
    })
    assert original.Class.astype(str).tolist() == changed.Class.astype(str).tolist()
    assert canonical_frame_sha256(original) != canonical_frame_sha256(changed)


def test_intraday_fetch_can_read_partial_session_from_complete_preparation(flow_factory):
    calls = []
    times = pd.to_datetime([
        f"2026-09-14 {clock}" for clock in
        ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
    ])

    def provider(request):
        calls.append(request)
        return pd.DataFrame({
            "Date": times, "Open": 1.0, "High": 1.0, "Low": 1.0,
            "Close": 1.0, "Volume": 100.0, "Amount": 100.0,
        }), {"vendor": "fixture"}

    flows = flow_factory({Dataset.ETF_OHLCV: provider})
    request = DataRequest(
        Dataset.ETF_OHLCV, "518850.SH", "2026-09-14", "2026-09-14", None, "30m",
    )
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    subset = replace(request, start="2026-09-14 10:30", end="2026-09-14 11:30")
    result = flows.fetch(subset, prepared=prepared.reference)
    assert result.ready and len(calls) == 1
    assert result.dataframe.Date.tolist() == times[1:4].tolist()


@pytest.mark.parametrize("missing_bar", [False, True])
def test_partial_intraday_prepare_checks_only_requested_session_bars(flow_factory, missing_bar):
    times = pd.to_datetime(["2026-09-14 10:30", "2026-09-14 11:00", "2026-09-14 11:30"])
    if missing_bar:
        times = times.delete(1)
    frame = pd.DataFrame({
        "Date": times, "Open": 1.0, "High": 1.0, "Low": 1.0,
        "Close": 1.0, "Volume": 100.0, "Amount": 100.0,
    })
    flows = flow_factory({Dataset.ETF_OHLCV: lambda request: (frame, {"vendor": "fixture"})})
    request = DataRequest(
        Dataset.ETF_OHLCV, "518850.SH", "2026-09-14 10:30", "2026-09-14 11:30", None, "30m",
    )
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready is not missing_bar
    if missing_bar:
        assert "INCOMPLETE_TRADING_SESSION" in prepared.items[0].error.message
    else:
        result = flows.fetch(request, prepared=prepared.reference)
        assert result.ready and result.dataframe.Date.tolist() == times.tolist()


@pytest.mark.parametrize("invalid", [None, "gap", "market", "time"])
def test_hk_intraday_uses_requested_market_session(flow_factory, invalid):
    times = pd.to_datetime([
        f"2026-09-14 {clock}" for clock in
        ("10:00", "10:30", "11:00", "11:30", "12:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00")
    ])
    if invalid == "gap":
        times = times.delete(4)
    elif invalid == "time":
        times = times.append(pd.DatetimeIndex(["2026-09-14 16:30"]))
    frame = pd.DataFrame({
        "Date": times, "Open": 1.0, "High": 1.0, "Low": 1.0,
        "Close": 1.0, "Volume": 100.0, "Amount": 100.0,
    })
    metadata = {"vendor": "fixture", "market": "a_share" if invalid == "market" else "hk"}
    flows = flow_factory({Dataset.STOCK_OHLCV: lambda request: (frame, metadata)})
    request = DataRequest(Dataset.STOCK_OHLCV, "00700.HK", "2026-09-14", "2026-09-14", None, "30m")
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready is (invalid is None)
    if prepared.ready:
        result = flows.fetch(request, prepared=prepared.reference)
        assert result.ready and len(result.dataframe) == 11


@pytest.mark.parametrize("dataset", [
    Dataset.SHIBOR_DAILY, Dataset.US_REAL_YIELD_DAILY, Dataset.US_NOMINAL_YIELD_DAILY,
    Dataset.US_POLICY_UNCERTAINTY_DAILY, Dataset.USDCNH_DAILY, Dataset.CN_CPI_MONTHLY,
    Dataset.CN_PPI_MONTHLY, Dataset.CN_MONEY_MONTHLY, Dataset.US_CPI_RELEASE,
    Dataset.US_ISM_PMI_RELEASE, Dataset.US_FEDERAL_BUDGET_RELEASE,
])
def test_fixed_series_rejects_symbol_before_provider_selection(dataset):
    with pytest.raises(ValueError, match="fixed series and accepts no symbol"):
        DataRequest(dataset, "EURUSD", "2026-09-14", "2026-09-14", None)


@pytest.mark.parametrize("strict_first", [False, True])
def test_reuse_refreshes_once_for_all_requirements_independent_of_order(flow_factory, strict_first):
    calls = []
    source = _rates().iloc[:1].copy()

    def provider(request):
        calls.append(request)
        return source, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    original = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert original.ready and len(calls) == 1
    source = _rates().iloc[:2].copy()
    strict = replace(_request(), coverage=DataCoverageRequirement(minimum_observations=2))
    requests = (strict, _request()) if strict_first else (_request(), strict)
    prepared = flows.prepare(requests, policy=PreparePolicy.REUSE)
    assert prepared.ready and len(calls) == 2
    assert all(item.status is DataStatus.READY for item in prepared.items)
    for request in requests:
        result = flows.fetch(request, prepared=prepared.reference)
        assert result.ready and len(result.dataframe) == 2


def test_mixed_naive_and_aware_series_returns_structured_batch_failure(flow_factory):
    def provider(request):
        frame = _rates()
        if pd.Timestamp(request.start).tzinfo is not None:
            frame.Date = frame.Date.dt.tz_localize("Asia/Shanghai")
        return frame, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    aware = replace(
        _request(), start="2026-09-14T00:00:00+08:00", end="2026-09-16T00:00:00+08:00",
    )
    result = flows.prepare((_request(), aware), policy=PreparePolicy.REFRESH)
    assert result.status is PrepareStatus.FAILED and result.reference is None
    assert all(item.error.code == "INCONSISTENT_PREPARATION" for item in result.items)


@pytest.mark.parametrize("requirement", ["coverage", "cutoff"])
def test_refresh_failing_all_acceptance_preserves_previous_reusable_data(flow_factory, requirement):
    calls = []
    source = _rates()

    def provider(request):
        calls.append(request)
        return source, {"vendor": "fixture"}

    flows = flow_factory({Dataset.SHIBOR_DAILY: provider})
    original = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert original.ready
    source = _rates().iloc[:1].assign(OvernightRate=9.0)
    strict = (
        replace(_request(), coverage=DataCoverageRequirement(minimum_observations=3))
        if requirement == "coverage" else replace(_request(), required_cutoff="2026-09-16")
    )
    rejected = flows.prepare((strict,), policy=PreparePolicy.REFRESH)
    assert rejected.status is PrepareStatus.FAILED and rejected.reference is None
    assert [item.status for item in rejected.items] == [DataStatus.INCOMPLETE]
    old = flows.fetch(_request(), prepared=original.reference)
    assert old.ready and old.dataframe.OvernightRate.tolist() == [1.0, 1.1, 1.2]
    reused = flows.prepare((_request(),), policy=PreparePolicy.REUSE)
    assert reused.ready and len(calls) == 2
    current = flows.fetch(_request(), prepared=reused.reference)
    assert current.ready and current.dataframe.OvernightRate.tolist() == [1.0, 1.1, 1.2]


def test_date_only_end_accepts_cutoff_later_on_same_day():
    request = DataRequest(
        Dataset.ETF_OHLCV, "518850.SH", "2026-09-14", "2026-09-14",
        "2026-09-14T15:00:00", "30m",
    )
    assert request.required_cutoff == "2026-09-14T15:00:00"
