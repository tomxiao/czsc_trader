"""Default ETF routes authenticate repairs before publishing a pinned asset."""

from pathlib import Path

import pandas as pd
import pytest

from dataflows import (
    Dataflows,
    DataRequest,
    DataSpace,
    DataStatus,
    Dataset,
    PreparePolicy,
    PrepareStatus,
    ProviderConfig,
    canonical_frame_sha256,
)
from dataflows import tushare_etf
from dataflows.history_repair import frame_content_sha256


@pytest.fixture
def repair_root(tmp_path, empty_space_factory):
    # Initialization/concurrency are covered by test_data_space.
    empty_space_factory("assets")
    return tmp_path


def _bars(day, minutes, price=10.0):
    date = pd.Timestamp(day)
    times = pd.date_range(
        date + pd.Timedelta(hours=9, minutes=30 + minutes),
        periods=120 // minutes,
        freq=f"{minutes}min",
    ).append(
        pd.date_range(
            date + pd.Timedelta(hours=13, minutes=minutes),
            periods=120 // minutes,
            freq=f"{minutes}min",
        )
    )
    return pd.DataFrame(
        {
            "Date": times,
            "Open": price,
            "High": price,
            "Low": price,
            "Close": price,
            "Volume": float(minutes),
            "Amount": float(minutes * price),
        }
    )


def _daily(days, price=10.0):
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(days),
            "Open": price,
            "High": price,
            "Low": price,
            "Close": price,
            "Volume": 240.0,
            "Amount": 240.0 * price,
        }
    )


class _Vendor:
    """Only the client transport is replaced; DFLS normalization remains real."""

    def __init__(self, daily, coarse=None, minute=None):
        self.daily = daily.copy(deep=True)
        self.coarse = None if coarse is None else coarse.copy(deep=True)
        self.minute = None if minute is None else minute.copy(deep=True)
        self.calls = []

    def fund_basic(self, *, ts_code, fields):
        self.calls.append(("fund_basic", {"ts_code": ts_code, "fields": fields}))
        assert fields == "ts_code,list_date"
        return pd.DataFrame({"ts_code": [ts_code], "list_date": ["20130101"]})

    def fund_daily(self, **kwargs):
        self.calls.append(("fund_daily", kwargs))
        frame = self.daily.copy(deep=True)
        frame["Date"] = frame.Date.dt.strftime("%Y%m%d")
        frame["Volume"] /= 100.0  # fund_daily reports shares in hundreds.
        frame["Amount"] /= 1000.0
        return frame.rename(
            columns={
                "Date": "trade_date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "vol",
                "Amount": "amount",
            }
        )

    def etf_mins(self, **kwargs):
        self.calls.append(("etf_mins", kwargs))
        source = self.minute if kwargs["freq"] == "1min" else self.coarse
        assert source is not None, "this repair must not acquire undeclared minute evidence"
        frame = source.loc[
            source.Date.between(
                pd.Timestamp(kwargs["start_date"]),
                pd.Timestamp(kwargs["end_date"]),
            )
        ].copy(deep=True)
        return frame.rename(
            columns={
                "Date": "trade_time",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "vol",
                "Amount": "amount",
            }
        )

    def trade_cal(self, **kwargs):
        self.calls.append(("trade_cal", kwargs))
        assert kwargs["exchange"] == "SSE"
        dates = pd.date_range(kwargs["start_date"], kwargs["end_date"])
        return pd.DataFrame(
            {
                "cal_date": dates.strftime("%Y%m%d"),
                "is_open": (dates.dayofweek < 5).astype(int),
            }
        )

    def fund_adj(self, **kwargs):
        pytest.fail("unadjusted executable prices must not acquire adjustment factors")


def _flow(repair_root, vendor, monkeypatch):
    monkeypatch.setattr(tushare_etf, "get_tushare_pro", lambda _: vendor)
    return Dataflows(
        base_dir=repair_root, space=DataSpace(Path("assets")), providers=ProviderConfig()
    )


def _publish(flow, request):
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.status is PrepareStatus.READY, prepared.items
    assert prepared.reference is not None and prepared.items[0].status is DataStatus.READY
    result = flow.fetch(request, prepared=prepared.reference)
    assert result.ready, result.error
    assert result.prepared == prepared.reference
    return prepared, result


def _assert_repair_identity(result, patch_id, affected_dates):
    metadata = result.identity.metadata
    assert metadata["vendor"] == "tushare"
    assert metadata["vendor_symbol"] == result.identity.symbol
    assert metadata["adjustment"] == "none"
    assert metadata["validation"]["status"] == "PASS"
    assert len(metadata["reference_daily_sha256"]) == 64
    (record,) = metadata["repair_records"]
    assert record["patch_id"] == patch_id
    assert record["affected_dates"] == affected_dates
    assert record["affected_date_count"] == len(affected_dates)
    assert record["raw_content_sha256"] != record["repaired_content_sha256"]
    assert len(record["raw_content_sha256"]) == len(record["repaired_content_sha256"]) == 64
    assert record["repaired_content_sha256"] == frame_content_sha256(
        result.dataframe.drop(columns="AvailableDate", errors="ignore"),
    )
    assert result.identity.content_sha256 == canonical_frame_sha256(result.dataframe)
    return record


def _raw_hash(frame, *, intraday):
    normalized = frame.copy(deep=True)
    normalized["Date"] = normalized.Date.dt.strftime(
        "%Y-%m-%d %H:%M:%S" if intraday else "%Y-%m-%d"
    )
    return frame_content_sha256(normalized)


def _assert_failed_refresh_preserves_ref(
    flow,
    request,
    prepared,
    original,
    repair_root,
    code,
    *,
    item_status=DataStatus.FAILED,
):
    failed = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert failed.status is PrepareStatus.FAILED and failed.reference is None
    (item,) = failed.items
    assert item.status is item_status and item.identity is None
    assert item.error.code == code
    # Reopen without any supplier: neither failed refresh nor fetch may replace
    # the original immutable published object.
    offline = Dataflows(
        base_dir=repair_root, space=DataSpace(Path("assets")), providers=ProviderConfig(bindings={})
    )
    restored = offline.fetch(request, prepared=prepared.reference)
    assert restored.ready and restored.prepared == prepared.reference
    assert restored.identity == original.identity
    pd.testing.assert_frame_equal(restored.dataframe, original.dataframe)
    return item.error


def test_DFLS_24_C01_registered_repair_publishes_offline(repair_root, monkeypatch):
    daily = _daily(["2020-03-09", "2020-03-10"], price=3.659)
    daily.loc[0, ["Open", "High", "Low"]] = [3.716, 3.728, 3.317]
    vendor = _Vendor(daily)
    flow = _flow(repair_root, vendor, monkeypatch)
    request = DataRequest(
        Dataset.ETF_UNADJUSTED_DAILY, "518880.SH", "2020-03-09", "2020-03-10", "2020-03-10"
    )
    prepared, result = _publish(flow, request)
    record = _assert_repair_identity(result, "TUSHARE_518880_V2", ["2020-03-09"])
    assert record["raw_content_sha256"] == _raw_hash(daily, intraday=False)
    assert record["patch_version"] == 2
    assert record["findings_before"] == ["KNOWN_SOURCE_ANOMALY"]
    assert result.dataframe.Low.tolist() == [3.548, 3.659]
    assert result.dataframe.Open.tolist() == daily.Open.tolist()
    assert result.dataframe.High.tolist() == daily.High.tolist()
    assert result.dataframe.Close.tolist() == daily.Close.tolist()
    assert result.dataframe.Volume.tolist() == [240.0, 240.0]
    assert result.dataframe.Amount.tolist() == daily.Amount.tolist()
    assert vendor.daily.Low.iloc[0] == 3.317
    assert [endpoint for endpoint, _ in vendor.calls] == ["fund_daily", "fund_basic", "trade_cal"]
    offline = Dataflows(
        base_dir=repair_root, space=DataSpace(Path("assets")), providers=ProviderConfig({})
    )
    restored = offline.fetch(request, prepared=prepared.reference)
    assert restored.ready and restored.identity == result.identity
    pd.testing.assert_frame_equal(restored.dataframe, result.dataframe)


def test_DFLS_24_C02_failed_repair_keeps_previous_reference(repair_root, monkeypatch):
    days = ["2020-09-11", "2020-09-14"]
    daily = _daily(days, price=6.9)
    daily.loc[0, "Low"] = 6.829
    coarse = pd.concat([_bars(day, 5, 6.9) for day in days], ignore_index=True)
    coarse.loc[coarse.Date.eq(pd.Timestamp("2020-09-11 09:40")), "Low"] = 6.837
    minute = _bars(days[0], 1, 6.9)
    minute.loc[minute.Date.eq(pd.Timestamp("2020-09-11 09:37")), "Low"] = 6.829
    vendor = _Vendor(daily, coarse, minute)
    flow = _flow(repair_root, vendor, monkeypatch)
    request = DataRequest(
        Dataset.ETF_UNADJUSTED_INTRADAY, "510500.SH", days[0], days[-1], days[-1], frequency="5m"
    )
    prepared, result = _publish(flow, request)
    record = _assert_repair_identity(result, "TUSHARE_510500_V2", [days[0]])
    assert record["raw_content_sha256"] == _raw_hash(coarse, intraday=True)
    assert record["patch_version"] == 2
    assert record["findings_before"] == ["CROSS_FREQUENCY_MISMATCH"]
    assert result.dataframe.Low.min() == 6.829
    assert len(result.dataframe) == 96
    actual = result.dataframe.drop(columns="AvailableDate").copy()
    actual["Date"] = pd.to_datetime(actual.Date)
    expected = coarse.copy(deep=True)
    expected.loc[expected.Date.eq(pd.Timestamp("2020-09-11 09:40")), "Low"] = 6.829
    pd.testing.assert_frame_equal(actual, expected)
    minute_calls = [
        call for endpoint, call in vendor.calls if endpoint == "etf_mins" and call["freq"] == "1min"
    ]
    assert minute_calls == [
        {
            "ts_code": "510500.SH",
            "start_date": "2020-09-11 00:00:00",
            "end_date": "2020-09-11 23:59:59",
            "freq": "1min",
        }
    ]
    assert result.identity.metadata["source_publication_timestamp_verified"] is False
    assert result.identity.metadata["live_feed_latency_verified"] is False
    vendor.minute = vendor.minute.loc[vendor.minute.Date.ne(pd.Timestamp("2020-09-11 09:37"))]
    expected_message = "expected 240 complete 1m repair bars, found 239"
    error = _assert_failed_refresh_preserves_ref(
        flow,
        request,
        prepared,
        result,
        repair_root,
        "DATA_REPAIR_FAILED",
    )
    assert expected_message in error.message
