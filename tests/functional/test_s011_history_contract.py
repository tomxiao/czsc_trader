"""S011 warmup admission through real runtime/DFLS contracts, with synthetic prices.

The exchange closure fixture deliberately includes Chinese New Year. Coverage
is measured in trading sessions, not weekdays. All checks use the installed
S011-v1 release; no signal calculator or feature function is mocked.
"""

from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from dataflows import Dataflows, DataSpace, DataStatus, Dataset, PreparePolicy, ProviderBinding, ProviderConfig
from dataflows.history_repair import frame_content_sha256
from dataflows.ohlcv_quality import bind_quality_frame, build_quality_evidence
from strategy_runtime import (
    RuntimeExecutionError, StrategyInit, StrategyRelease, StrategyRuntime, TradableWindow,
)


ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.release_acceptance
CLOCKS = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
CN_CLOSED = pd.DatetimeIndex(["2025-01-01", *pd.date_range("2025-01-28", "2025-02-04")])
US_CLOSED = pd.DatetimeIndex(["2024-12-25", "2025-01-01", "2025-01-09", "2025-01-20"])
WINDOW = TradableWindow(date(2025, 2, 6), date(2025, 2, 6))


def _sessions(start, end, closed=CN_CLOSED):
    days = pd.date_range(start, end)
    return days[(days.weekday < 5) & ~days.isin(closed)]


@pytest.fixture(scope="module")
def release():
    raw = json.loads((ROOT / "strategies/S011/versions/v1.json").read_text(encoding="utf-8"))
    installed = StrategyRelease.from_mapping(raw)
    assert installed.release_id == "S011-v1"
    return installed


def _ohlcv(dates, volume):
    return pd.DataFrame({"Date": dates, "Open": 1., "High": 1., "Low": 1.,
                         "Close": 1., "Volume": float(volume), "Amount": float(volume)})


def _flows(root, *, defect=None):
    def provider(request):
        days = pd.date_range(request.start, request.end)
        sessions = _sessions(request.start, request.end)
        metadata = {"vendor": "synthetic-price-real-holiday-fixture", "maximum_start_lag_days": 10}
        if request.dataset == Dataset.TRADING_CALENDAR:
            return pd.DataFrame({"Date": days, "IsOpen": days.isin(sessions).astype(int)}), metadata
        if request.dataset == Dataset.GLOBAL_INDEX_DAILY:
            dates = _sessions(request.start, request.end, US_CLOSED)
            return pd.DataFrame({"Date": dates, "PercentChange": np.sin(np.arange(len(dates))) * .01}), metadata
        if request.dataset == Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY:
            frame = pd.DataFrame({"Date": sessions, "Close": 1., "Volume": 800., "Amount": 800.})
            metadata.update(price_scope="CLOSE_AND_INDEX_TURNOVER", volume_unit="hand",
                            amount_unit="thousand_cny", frequency="daily",
                            available_at="current session after market close",
                            vendor_update_window="trading day 15:00-17:00 Asia/Shanghai",
                            source_publication_timestamp_verified=False,
                            historical_revision_history_verified=False)
            if defect == "nonfinite_market":
                frame.loc[frame.index[-1], "Close"] = np.inf
            return frame, metadata
        daily = _ohlcv(sessions, 800)
        minute = _ohlcv(pd.to_datetime([f"{d.date()} {clock}" for d in sessions for clock in CLOCKS]), 100)
        if defect == "incomplete_bars" and request.frequency == "30m":
            minute = minute.iloc[:-1].copy()
        frame = minute if request.frequency == "30m" else daily
        calendar = pd.DataFrame({"Date": days.strftime("%Y-%m-%d"), "is_open": days.isin(sessions).astype(int)})
        expected = sessions.strftime("%Y-%m-%d").tolist()
        metadata.update(adjustment="none" if request.dataset == Dataset.ETF_UNADJUSTED_DAILY else "hfq",
            daily_session_coverage={
                "source": "explicit-2024-2025-A-share-holiday-fixture", "exchange": "SZSE",
                "start_date": request.start, "end_date": request.end,
                "listing_date": "2024-09-09", "listing_source": "declared-fixture-lifecycle",
                "calendar": calendar.to_dict("records"), "calendar_sha256": frame_content_sha256(calendar),
                "expected_dates": expected, "verified_sessions": len(expected),
            })
        quality = build_quality_evidence(daily, intraday=minute if request.frequency == "30m" else None,
                                        frequency=request.frequency, expected_dates=expected)
        metadata["ohlcv_quality_evidence"] = bind_quality_frame(quality, frame, adjustment=metadata["adjustment"])
        frame.attrs = {key: metadata[key] for key in ("daily_session_coverage", "ohlcv_quality_evidence")}
        return frame, metadata

    datasets = (Dataset.TRADING_CALENDAR, Dataset.ETF_OHLCV, Dataset.ETF_UNADJUSTED_DAILY,
                Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY, Dataset.GLOBAL_INDEX_DAILY)
    return Dataflows(base_dir=root, space=DataSpace(Path("data")), providers=ProviderConfig({
        dataset: ProviderBinding("s011-boundary-fixture", "1", provider) for dataset in datasets
    }))


def _instance(source, flows, root):
    return StrategyRuntime(ROOT / "strategies", dataflows=flows).create(StrategyInit(source, WINDOW, root / "runtime"))


def _plan(instance, flows):
    request = instance.calendar_request()
    calendar = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert calendar.ready, calendar.items
    return instance.plan_inputs(flows.fetch(request, prepared=calendar.reference))


def test_installed_v1_computes_at_real_holiday_boundary(release, tmp_path):
    assert len(_sessions("2024-12-26", "2025-02-05")) == 23
    assert len(pd.bdate_range("2024-12-26", "2025-02-05")) == 30
    flows = _flows(tmp_path)
    installed = _instance(release, flows, tmp_path)
    installed.prepare_data(policy=PreparePolicy.REUSE)
    history = installed.inspect_signals()
    assert history.index.tolist() == [pd.Timestamp("2025-02-05")]
    assert np.isfinite(history[["tail", "market", "spx", "risk5", "score"]].to_numpy()).all()
    assert installed.input_binding.plan.requests["daily"].start == "2024-12-26"
    assert installed.input_binding.plan.requests["spx"].start == "2024-12-16"


@pytest.mark.parametrize("name,minimum", [("daily", 20), ("bars", 20), ("market", 21), ("spx", 30)])
@pytest.mark.parametrize("deficit", [0, 1])
def test_declared_coverage_accepts_exact_minimum_and_rejects_one_less(release, tmp_path, name, minimum, deficit):
    flows = _flows(tmp_path)
    instance = _instance(release, flows, tmp_path)
    request = _plan(instance, flows).requests[name]
    assert request.coverage.minimum_observations == request.coverage.minimum_sessions == minimum
    # Slice the requested interval, retaining its actual runtime-declared coverage.
    # For bars this has 8 observations per session, so row count alone is insufficient.
    dates = _sessions(request.start, request.end, US_CLOSED if name == "spx" else CN_CLOSED)
    selected = dates[-(minimum - deficit):]
    request = replace(request, start=selected[0].date().isoformat())
    result = flows.prepare((request,), policy=PreparePolicy.REUSE)
    assert result.ready is (deficit == 0), result.items
    if deficit:
        item = result.items[0]
        assert item.status is DataStatus.INCOMPLETE
        key = "actual_sessions" if name == "bars" else "actual_observations"
        assert item.error.context[key] == minimum - 1


@pytest.mark.parametrize("defect", ["incomplete_bars", "nonfinite_market"])
def test_declared_coverage_does_not_admit_invalid_inputs(release, tmp_path, defect):
    flows = _flows(tmp_path, defect=defect)
    instance = _instance(release, flows, tmp_path)
    plan = _plan(instance, flows)
    result = flows.prepare(tuple(plan.requests.values()), policy=PreparePolicy.REUSE)
    assert not result.ready
    failed = [item for item in result.items if not item.ready]
    expected = Dataset.ETF_OHLCV if defect == "incomplete_bars" else Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY
    assert len(failed) == 1 and failed[0].request.dataset == expected, failed
    assert "incomplete" in failed[0].error.message if defect == "incomplete_bars" else "invalid numeric" in failed[0].error.message
    with pytest.raises(RuntimeExecutionError, match="incomplete|invalid numeric"):
        instance.prepare_data(policy=PreparePolicy.REUSE)
