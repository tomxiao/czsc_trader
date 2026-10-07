"""OHLCV window acceptance through public prepare and pinned fetch operations."""

from copy import deepcopy
from dataclasses import replace

import pandas as pd
import pytest

from dataflows import Dataflows, DataRequest, DataSpace, DataStatus, Dataset, PreparePolicy, ProviderConfig
from dataflows import facade
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence


# A declared synthetic exchange calendar, independent of source response rows.
SESSIONS = tuple(pd.bdate_range("2024-01-02", periods=100).strftime("%Y-%m-%d"))
# Five sessions include an internal gap and the intervening closed weekend.
FAULT_SESSIONS = SESSIONS[:5]
CLOSES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")


def _request(frequency="daily", *, sessions=SESSIONS):
    return DataRequest(Dataset.ETF_OHLCV, "510500.SH", sessions[0], sessions[-1],
                       required_cutoff=None, frequency=frequency)


def _source(*, bad_daily=(), bad_minute=(), sessions=SESSIONS):
    daily = pd.DataFrame({"Date": pd.to_datetime(sessions), "Open": 10., "High": 10.,
                          "Low": 10., "Close": 10., "Volume": 800., "Amount": 8000.})
    daily.loc[list(bad_daily), "Amount"] = 8800.
    minute = pd.DataFrame({
        "Date": pd.to_datetime([f"{day} {clock}" for day in sessions for clock in CLOSES]),
        "Open": 10., "High": 10., "Low": 10., "Close": 10.,
        "Volume": 100., "Amount": 1000.,
    })
    minute.loc[[day * 8 for day in bad_minute], "Volume"] = 101.
    return daily, minute


def _metadata(daily, minute=None, *, sessions=SESSIONS):
    frequency = "daily" if minute is None else "30m"
    calendar = pd.DataFrame({"Date": pd.date_range(sessions[0], sessions[-1]).strftime("%Y-%m-%d")})
    calendar["is_open"] = calendar.Date.isin(sessions).astype(int)
    return {
        "vendor": "synthetic-calendar-fixture", "vendor_symbol": "510500.SH",
        "asset_type": "etf", "period": frequency, "adjustment": "none",
        "daily_session_coverage": {
            "source": "independent-test-calendar", "exchange": "SSE",
            "start_date": sessions[0], "end_date": sessions[-1],
            "listing_date": "2013-03-15", "listing_source": "synthetic-lifecycle",
            "calendar": calendar.to_dict("records"),
            "calendar_sha256": frame_content_sha256(calendar),
            "expected_dates": list(sessions), "verified_sessions": len(sessions),
        },
        "ohlcv_quality_evidence": build_quality_evidence(
            daily, intraday=minute, frequency=frequency, expected_dates=sessions,
        ),
    }


def _provider(frame, metadata, calls):
    def supply(request):
        calls.append(request)
        return frame.copy(), deepcopy(metadata)
    return supply


@pytest.mark.parametrize("inaccurate, ready", [(1, True), (2, False)])
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
        assert not fetched.identity.metadata["ohlcv_quality_evidence"]["sessions"][SESSIONS[0]]["daily_accurate"]
    else:
        assert prepared.reference is None and prepared.items[0].status is DataStatus.FAILED
        assert "accuracy" in prepared.items[0].error.message.lower()


@pytest.mark.parametrize("bad_daily, bad_minute, ready", [(1, 5, True), (2, 0, False), (0, 6, False)])
def test_minute_acceptance_requires_both_99_and_95_percent(flow_factory, bad_daily, bad_minute, ready):
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


@pytest.mark.parametrize("missing", [0, 2, 4], ids=["first", "internal", "last"])
def test_independent_calendar_detects_missing_daily_session(flow_factory, missing):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    daily = daily.drop(index=missing).reset_index(drop=True)
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, _metadata(daily, sessions=FAULT_SESSIONS), [])})
    prepared = flows.prepare((_request(sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.INCOMPLETE


@pytest.mark.parametrize("whole_day", [False, True], ids=["missing-bar", "missing-day"])
def test_minute_completeness_requires_every_session_and_bar(flow_factory, whole_day):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    missing = range(2 * 8, 3 * 8) if whole_day else [2 * 8 + 3]
    minute = minute.drop(index=missing).reset_index(drop=True)
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(minute, _metadata(daily, minute, sessions=FAULT_SESSIONS), [])})
    prepared = flows.prepare((_request("30m", sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.INCOMPLETE


def test_complete_minutes_cannot_compensate_for_missing_daily_anchor(flow_factory):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    daily = daily.drop(index=2).reset_index(drop=True)
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(minute, _metadata(daily, minute, sessions=FAULT_SESSIONS), [])})
    prepared = flows.prepare((_request("30m", sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.INCOMPLETE


def test_prepare_and_fetch_use_post_correction_source_evidence(flow_factory):
    daily, minute = _source(bad_minute=range(6))
    corrected = minute.copy()
    corrected.loc[0, "Volume"] = 100.
    metadata = _metadata(daily, corrected)
    # This is an explicit provider transformation, not a fabricated DFLS repair receipt.
    metadata["fixture_transformation"] = {"field": "Volume", "old": 101., "new": 100.}
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(corrected, metadata, [])})
    request = _request("30m")
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    fetched = flows.fetch(request, prepared=prepared.reference)
    assert fetched.ready and fetched.dataframe.iloc[0].Volume == 100.
    sessions = fetched.identity.metadata["ohlcv_quality_evidence"]["sessions"]
    assert sessions[SESSIONS[0]]["minute_accurate"]
    assert sum(row["minute_accurate"] for row in sessions.values()) == 95


def test_reuse_is_offline_and_fetch_reads_certified_window_quality(flow_factory, monkeypatch):
    daily, _ = _source(bad_daily=[49])
    metadata, calls = _metadata(daily), []
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, calls)})
    request = _request()
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items

    def must_not_revalidate(*args, **kwargs):
        raise AssertionError("published assets must reuse validated quality facts")

    monkeypatch.setattr(facade, "_validate_provider_output", must_not_revalidate)
    reused = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert reused.ready and reused.reference == prepared.reference and len(calls) == 1
    good = replace(request, start=SESSIONS[0], end=SESSIONS[48])
    fetched = flows.fetch(good, prepared=reused.reference)
    assert fetched.ready
    fetched.identity.metadata["ohlcv_quality_evidence"]["sessions"][SESSIONS[49]]["daily_accurate"] = True
    bad = replace(request, start=SESSIONS[49], end=SESSIONS[49])
    selected = flows.fetch(bad, prepared=reused.reference)
    assert selected.ready and len(selected.dataframe) == 1
    assert selected.identity.metadata["ohlcv_quality"]["daily"]["accuracy"] == .99
    assert not selected.identity.metadata["ohlcv_quality_evidence"]["sessions"][SESSIONS[49]]["daily_accurate"]
    assert len(calls) == 1


@pytest.mark.parametrize("revision", [None, "0" * 64], ids=["unvalidated", "stale"])
def test_fetch_requires_current_publication_validation(flow_factory, revision):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    calls = []
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, _metadata(daily, sessions=FAULT_SESSIONS), calls)})
    request = _request(sessions=FAULT_SESSIONS)
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready
    entries = flows._store.load_preparation(prepared.reference)
    for entry in entries:
        if revision is None:
            del entry["validated_revision"]
        else:
            entry["validated_revision"] = revision
    # Simulate an older immutable publication; do not alter the original manifest.
    with flows._store.transaction() as connection:
        older = flows._store.publish(connection, entries)
    rejected = flows.fetch(request, prepared=older)
    assert rejected.status is DataStatus.FAILED
    assert rejected.error.code == "PREPARATION_VALIDATION_REQUIRED"
    assert len(calls) == 1
    assert flows.fetch(request, prepared=prepared.reference).ready


def test_changed_revision_requires_prepare_before_fetch(flow_factory, monkeypatch):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    calls = []
    providers = {Dataset.ETF_OHLCV: _provider(daily, _metadata(daily, sessions=FAULT_SESSIONS), calls)}
    flows = flow_factory(providers)
    request = _request(sessions=FAULT_SESSIONS)
    original = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    monkeypatch.setattr(facade, "_implementation_revision", lambda: "0" * 64)
    upgraded = Dataflows(
        base_dir=flows._store.base_dir,
        space=DataSpace(flows._store.root.relative_to(flows._store.base_dir)),
        providers=ProviderConfig(bindings={Dataset(key): value for key, value in flows._providers.items()}),
    )
    rejected = upgraded.fetch(request, prepared=original.reference)
    assert rejected.error.code == "PREPARATION_VALIDATION_REQUIRED" and len(calls) == 1
    current = upgraded.prepare((request,), policy=PreparePolicy.REUSE)
    assert current.ready and upgraded.fetch(request, prepared=current.reference).ready
    assert len(calls) == 2
    assert flows.fetch(request, prepared=original.reference).ready


def test_partial_minute_fetch_retains_full_session_quality(flow_factory):
    daily, minute = _source(bad_minute=[49])
    calls = []
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(minute, _metadata(daily, minute), calls)})
    request = _request("30m")
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    # Reading a slice retains original window facts without a new acceptance gate.
    bad = replace(request, start=f"{SESSIONS[49]} 13:30", end=f"{SESSIONS[49]} 15:00")
    selected = flows.fetch(bad, prepared=prepared.reference)
    assert selected.ready and len(selected.dataframe) == 4
    assert not selected.identity.metadata["ohlcv_quality_evidence"]["sessions"][SESSIONS[49]]["minute_accurate"]
    good = replace(request, start=f"{SESSIONS[48]} 13:30", end=f"{SESSIONS[48]} 15:00")
    fetched = flows.fetch(good, prepared=prepared.reference)
    assert fetched.ready and len(fetched.dataframe) == 4
    assert len(calls) == 1


@pytest.mark.parametrize("corruption", ["missing-quality", "missing-calendar", "flags", "hidden-fields", "tolerance", "denominator", "float-version", "bool-version", "calendar-gap", "calendar-hash"])
def test_unverifiable_quality_metadata_cannot_publish(flow_factory, corruption):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    metadata = _metadata(daily, sessions=FAULT_SESSIONS)
    if corruption == "missing-quality":
        del metadata["ohlcv_quality_evidence"]
    elif corruption == "missing-calendar":
        del metadata["daily_session_coverage"]
    elif corruption == "flags":
        metadata["ohlcv_quality_evidence"]["sessions"][FAULT_SESSIONS[0]]["daily_accurate"] = "true"
    elif corruption == "hidden-fields":
        metadata["ohlcv_quality_evidence"]["sessions"][FAULT_SESSIONS[0]]["daily_fields"] = ["VWAP_ABOVE_HIGH"]
    elif corruption == "tolerance":
        metadata["ohlcv_quality_evidence"]["price_tolerance"] = 1.
    elif corruption == "denominator":
        metadata["daily_session_coverage"]["expected_dates"] = list(FAULT_SESSIONS[1:])
    elif corruption == "float-version":
        metadata["ohlcv_quality_evidence"]["version"] = 1.
    elif corruption == "bool-version":
        metadata["ohlcv_quality_evidence"]["version"] = True
    elif corruption == "calendar-gap":
        coverage = metadata["daily_session_coverage"]
        coverage["calendar"] = [row for row in coverage["calendar"] if row["Date"] != "2024-01-06"]
        coverage["calendar_sha256"] = frame_content_sha256(pd.DataFrame(coverage["calendar"]))
    else:
        metadata["daily_session_coverage"]["calendar_sha256"] = "0" * 64
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, [])})
    prepared = flows.prepare((_request(sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED


def test_calendar_prevents_source_and_denominator_from_jointly_hiding_missing_day(flow_factory):
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


@pytest.mark.parametrize("frequency", ["daily", "30m"])
def test_source_values_must_match_the_quality_evidence(flow_factory, frequency):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    if frequency == "daily":
        metadata = _metadata(daily, sessions=FAULT_SESSIONS)
        frame = daily
        frame.loc[2, "Amount"] = 8800.
    else:
        metadata = _metadata(daily, minute, sessions=FAULT_SESSIONS)
        frame = minute
        frame.loc[2 * 8, "Volume"] = 101.
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(frame, metadata, [])})
    prepared = flows.prepare((_request(frequency, sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED
    assert prepared.items[0].error.message == "OHLCV observations differ from post-repair quality evidence"


@pytest.mark.parametrize("frequency", ["daily", "30m"])
def test_rebinding_changed_amount_cannot_reuse_healthy_quality_facts(flow_factory, frequency):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    frame = daily if frequency == "daily" else minute
    metadata = _metadata(daily, None if frequency == "daily" else minute, sessions=FAULT_SESSIONS)
    frame.loc[2 if frequency == "daily" else 2 * 8, "Amount"] += 800.

    def provider(request):
        rebound = deepcopy(metadata)
        rebound["ohlcv_quality_evidence"] = bind_quality_frame(
            rebound["ohlcv_quality_evidence"], frame,
        )
        return frame.copy(), rebound

    flows = flow_factory({Dataset.ETF_OHLCV: provider})
    prepared = flows.prepare((_request(frequency, sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED
    assert prepared.items[0].error.message == "OHLCV publication differs from quality numeric evidence"
    assert prepared.items[0].error.context["field"] == "Amount"


def test_quality_evidence_must_use_the_instrument_market(flow_factory):
    daily, _ = _source(sessions=FAULT_SESSIONS)
    metadata = _metadata(daily, sessions=FAULT_SESSIONS)
    metadata["ohlcv_quality_evidence"]["market"] = "hk"
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, [])})
    prepared = flows.prepare((_request(sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED


def test_existing_tolerances_accept_small_price_volume_and_amount_differences(flow_factory):
    daily, minute = _source()
    daily.loc[0, "Amount"] = 8004.  # VWAP is exactly High + 0.005.
    minute.loc[minute.index[:8], "Amount"] = 1000.5
    minute.loc[0, "Volume"] += .004  # Relative difference 5e-6, below 1e-5.
    minute.loc[minute.index[8:], ["Open", "High", "Low", "Close"]] += .004
    minute.loc[8, "Amount"] += .04  # Relative difference 5e-6, below 1e-5.
    metadata = _metadata(daily, minute)
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(minute, metadata, [])})
    request = _request("30m")
    prepared = flows.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    fetched = flows.fetch(request, prepared=prepared.reference)
    assert fetched.ready
    quality = fetched.identity.metadata["ohlcv_quality"]
    assert quality["daily"]["accuracy"] == 1.
    assert quality["minute"]["accuracy"] == 1.


def test_structurally_invalid_row_is_not_diluted_by_99_percent_threshold(flow_factory):
    daily, _ = _source()
    metadata = _metadata(daily)
    daily.loc[49, "Close"] = 11.
    flows = flow_factory({Dataset.ETF_OHLCV: _provider(daily, metadata, [])})
    prepared = flows.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED


def test_nanosecond_duplicate_close_cannot_publish_as_complete_minute_session(flow_factory):
    daily, minute = _source(sessions=FAULT_SESSIONS)
    extra = minute.iloc[[2 * 8]].copy()
    extra["Date"] += pd.Timedelta(nanoseconds=1)
    minute = pd.concat([minute, extra]).sort_values("Date").reset_index(drop=True)

    def provider(request):
        return minute.copy(), _metadata(daily, minute, sessions=FAULT_SESSIONS)

    flows = flow_factory({Dataset.ETF_OHLCV: provider})
    prepared = flows.prepare((_request("30m", sessions=FAULT_SESSIONS),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED
