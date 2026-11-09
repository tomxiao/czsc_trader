"""OHLCV window acceptance through public prepare and pinned fetch operations."""

from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from dataflows import DataRequest, DataStatus, Dataset, PreparePolicy
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence


# A declared synthetic exchange calendar, independent of source response rows.
SESSIONS = tuple(pd.bdate_range("2024-01-02", periods=100).strftime("%Y-%m-%d"))
# Five sessions include an internal gap and the intervening closed weekend.
FAULT_SESSIONS = SESSIONS[:5]
CLOSES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")


def _request(frequency="daily", *, sessions=SESSIONS):
    return DataRequest(
        Dataset.ETF_OHLCV,
        "510500.SH",
        sessions[0],
        sessions[-1],
        required_cutoff=None,
        frequency=frequency,
    )


def _source(*, bad_daily=(), bad_minute=(), sessions=SESSIONS):
    daily = pd.DataFrame(
        {
            "Date": pd.to_datetime(sessions),
            "Open": 10.0,
            "High": 10.0,
            "Low": 10.0,
            "Close": 10.0,
            "Volume": 800.0,
            "Amount": 8000.0,
        }
    )
    daily.loc[list(bad_daily), "Amount"] = 8800.0
    minute = pd.DataFrame(
        {
            "Date": pd.to_datetime([f"{day} {clock}" for day in sessions for clock in CLOSES]),
            "Open": 10.0,
            "High": 10.0,
            "Low": 10.0,
            "Close": 10.0,
            "Volume": 100.0,
            "Amount": 1000.0,
        }
    )
    minute.loc[[day * 8 for day in bad_minute], "Volume"] = 101.0
    return daily, minute


def _metadata(daily, minute=None, *, sessions=SESSIONS):
    frequency = "daily" if minute is None else "30m"
    calendar = pd.DataFrame({"Date": pd.date_range(sessions[0], sessions[-1]).strftime("%Y-%m-%d")})
    calendar["is_open"] = calendar.Date.isin(sessions).astype(int)
    return {
        "vendor": "synthetic-calendar-fixture",
        "vendor_symbol": "510500.SH",
        "asset_type": "etf",
        "period": frequency,
        "adjustment": "none",
        "daily_session_coverage": {
            "source": "independent-test-calendar",
            "exchange": "SSE",
            "start_date": sessions[0],
            "end_date": sessions[-1],
            "listing_date": "2013-03-15",
            "listing_source": "synthetic-lifecycle",
            "calendar": calendar.to_dict("records"),
            "calendar_sha256": frame_content_sha256(calendar),
            "expected_dates": list(sessions),
            "verified_sessions": len(sessions),
        },
        "ohlcv_quality_evidence": build_quality_evidence(
            daily,
            intraday=minute,
            frequency=frequency,
            expected_dates=sessions,
        ),
    }


def _provider(frame, metadata, calls):
    def supply(request):
        calls.append(request)
        return frame.copy(), deepcopy(metadata)

    return supply


@pytest.mark.parametrize(
    "inaccurate, ready",
    [
        (1, True),
        (2, False),
    ],
    ids=["DFLS-QG-C01", "DFLS-QG-C02"],
)
def test_daily_accuracy_accepts_99_percent_including_equality(flow_factory, inaccurate, ready):
    daily, _ = _source(bad_daily=range(inaccurate))
    metadata, calls = _metadata(daily), []
    daily.attrs = deepcopy(metadata)
    source = daily.copy()
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, calls)})
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready is ready, prepared.items
    assert len(calls) == 1
    pd.testing.assert_frame_equal(daily, source, check_exact=True)
    assert daily.attrs == source.attrs
    if ready:
        fetched = flows.fetch(_request(), prepared=prepared.reference)
        assert fetched.ready and len(fetched.dataframe) == 100
        assert fetched.dataframe.attrs == source.attrs
        assert not fetched.identity.metadata["ohlcv_quality_evidence"]["sessions"][SESSIONS[0]][
            "daily_accurate"
        ]
    else:
        assert prepared.reference is None and prepared.items[0].status is DataStatus.FAILED
        assert "accuracy" in prepared.items[0].error.message.lower()


@pytest.mark.parametrize(
    "bad_daily, bad_minute, ready",
    [
        (1, 5, True),
        (2, 0, False),
        (0, 6, False),
    ],
    ids=["DFLS-QG-C03", "DFLS-QG-C04", "DFLS-QG-C05"],
)
def test_minute_acceptance_requires_both_99_and_95_percent(
    flow_factory, bad_daily, bad_minute, ready
):
    # A daily amount error also causes one minute mismatch, counted once per day.
    daily, minute = _source(bad_daily=range(bad_daily), bad_minute=range(bad_minute))
    metadata = _metadata(daily, minute)
    minute.attrs = deepcopy(metadata)
    source = minute.copy()
    calls = []
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(minute, metadata, calls)})
    request = _request("30m")
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready is ready, prepared.items
    pd.testing.assert_frame_equal(minute, source, check_exact=True)
    assert minute.attrs == source.attrs
    if ready:
        fetched = flows.fetch(request, prepared=prepared.reference)
        assert fetched.ready and len(fetched.dataframe) == 800
        assert fetched.dataframe.attrs == source.attrs
        evidence = fetched.identity.metadata["ohlcv_quality_evidence"]["sessions"]
        assert sum(row["minute_accurate"] for row in evidence.values()) == 95
        assert sum(row["daily_accurate"] for row in evidence.values()) == 99
    else:
        assert prepared.reference is None and prepared.items[0].status is DataStatus.FAILED


def _certified_daily(clone_published_flow, calls):
    """One real certified publication; every mutation gets a private database."""
    daily, _ = _source(sessions=FAULT_SESSIONS)
    request = _request(sessions=FAULT_SESSIONS)
    flows, original = clone_published_flow(
        "quality-daily",
        {
            Dataset.ETF_OHLCV: _provider(daily, _metadata(daily, sessions=FAULT_SESSIONS), calls),
        },
        request,
    )
    calls.clear()  # Only this case's refresh/reuse may invoke its current provider.
    return flows, request, original.prepared


def test_DFLS_10_C01_partial_minute_fetch_retains_full_session_quality(flow_factory):
    # One inaccurate session needs twenty sessions to meet the 95% gate.
    # The acceptance threshold matrix above owns the 100-session daily gate.
    sessions = SESSIONS[:20]
    daily, minute = _source(bad_minute=[9], sessions=sessions)
    calls = []
    flows = flow_factory(
        {Dataset.ETF_OHLCV: _provider(minute, _metadata(daily, minute, sessions=sessions), calls)}
    )
    request = _request("30m", sessions=sessions)
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    # Reading a slice retains original window facts without a new acceptance gate.
    bad = replace(request, start=f"{sessions[9]} 13:30", end=f"{sessions[9]} 15:00")
    selected = flows.fetch(bad, prepared=prepared.reference)
    assert selected.ready and len(selected.dataframe) == 4
    assert not selected.identity.metadata["ohlcv_quality_evidence"]["sessions"][sessions[9]][
        "minute_accurate"
    ]
    good = replace(request, start=f"{sessions[8]} 13:30", end=f"{sessions[8]} 15:00")
    fetched = flows.fetch(good, prepared=prepared.reference)
    assert fetched.ready and len(fetched.dataframe) == 4
    assert len(calls) == 1


def test_DFLS_21_C01_calendar_prevents_source_and_denominator_from_jointly_hiding_missing_day(
    flow_factory,
):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    metadata = _metadata(daily, sessions=FAULT_SESSIONS)
    daily = daily.drop(index=2).reset_index(drop=True)
    del metadata["ohlcv_quality_evidence"]["sessions"][FAULT_SESSIONS[2]]
    metadata["daily_session_coverage"]["expected_dates"].remove(FAULT_SESSIONS[2])
    metadata["daily_session_coverage"]["verified_sessions"] -= 1
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, [])})
    prepared = flows.prepare((_request(sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status in {DataStatus.FAILED, DataStatus.INCOMPLETE}


@pytest.mark.parametrize(
    "frequency",
    [
        "daily",
    ],
    ids=["DFLS-22-C03"],
)
def test_rebinding_changed_amount_cannot_reuse_healthy_quality_facts(flow_factory, frequency):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    frame = daily if frequency == "daily" else minute
    metadata = _metadata(daily, None if frequency == "daily" else minute, sessions=FAULT_SESSIONS)
    frame.loc[2 if frequency == "daily" else 2 * 8, "Amount"] += 800.0

    def provider(request):
        rebound = deepcopy(metadata)
        rebound["ohlcv_quality_evidence"] = bind_quality_frame(
            rebound["ohlcv_quality_evidence"],
            frame,
        )
        return frame.copy(), rebound

    flows = flow_factory({Dataset.ETF_OHLCV: provider})
    prepared = flows.prepare(
        (_request(frequency, sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH
    )
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED
    assert (
        prepared.items[0].error.message == "OHLCV publication differs from quality numeric evidence"
    )
    assert prepared.items[0].error.context["field"] == "Amount"


def test_DFLS_22_C04_quality_evidence_must_use_the_instrument_market(flow_factory):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    metadata = _metadata(daily, sessions=FAULT_SESSIONS)
    metadata["ohlcv_quality_evidence"]["market"] = "hk"
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, [])})
    prepared = flows.prepare((_request(sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED


def test_DFLS_22_C02_existing_tolerances_accept_small_price_volume_and_amount_differences(
    flow_factory,
):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    daily.loc[0, "Amount"] = 8004.0  # VWAP is exactly High + 0.005.
    minute.loc[minute.index[:8], "Amount"] = 1000.5
    minute.loc[0, "Volume"] += 0.004  # Relative difference 5e-6, below 1e-5.
    minute.loc[minute.index[8:], ["Open", "High", "Low", "Close"]] += 0.004
    minute.loc[8, "Amount"] += 0.04  # Relative difference 5e-6, below 1e-5.
    metadata = _metadata(daily, minute, sessions=FAULT_SESSIONS)
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(minute, metadata, [])})
    request = _request("30m", sessions=FAULT_SESSIONS)
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    fetched = flows.fetch(request, prepared=prepared.reference)
    assert fetched.ready
    quality = fetched.identity.metadata["ohlcv_quality"]
    assert quality["daily"]["accuracy"] == 1.0
    assert quality["minute"]["accuracy"] == 1.0


def test_DFLS_21_C02_structurally_invalid_row_is_not_diluted_by_99_percent_threshold(flow_factory):
    daily, _ = _source()
    metadata = _metadata(daily)
    daily.loc[49, "Close"] = 11.0
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, [])})
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED


def test_DFLS_21_C03_nanosecond_duplicate_close_cannot_publish_as_complete_minute_session(
    flow_factory,
):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    extra = minute.iloc[[2 * 8]].copy()
    extra["Date"] += pd.Timedelta(nanoseconds=1)
    minute = pd.concat([minute, extra]).sort_values("Date").reset_index(drop=True)

    def provider(request):
        return minute.copy(), _metadata(daily, minute, sessions=FAULT_SESSIONS)

    flows = flow_factory({Dataset.ETF_OHLCV: provider})
    prepared = flows.prepare(
        (_request("30m", sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH
    )
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED


def test_DFLS_21_C04_lunch_bar_is_rejected():
    from dataflows.history_validation import inspect_ohlcv_frame
    from dataflows.errors import DataContractError

    _, minute = _source(sessions=FAULT_SESSIONS[:1])
    minute.loc[0, "Date"] = pd.Timestamp(FAULT_SESSIONS[0] + " 12:00")
    with pytest.raises(DataContractError):
        inspect_ohlcv_frame(minute, "30m").require_pass()
