# Risk ownership: TDR-05
"""Numerical authentication keeps pricing and tamper checks, without attrs copying."""

from dataclasses import replace

from dataflows import DataIdentity, DataResult, DataStatus
import pandas as pd
import pytest
from strategy_runtime import ExecutionPricing, RuntimeContractError

from czsc_trader.backtesting.execution_data import _execution_frames
from czsc_trader.backtesting.srt_bridge import (
    _execution_frames_for_authentication,
    _validate_execution_binding,
)
from test_input_binding_integrity import fresh_bound_inputs as fresh_bound_inputs


def _result(frame):
    return DataResult(DataStatus.READY, frame, DataIdentity(
        dataset="etf.ohlcv", source="synthetic", symbol="588080.SH",
        data_start="2026-09-14", data_cutoff="2026-09-16", content_sha256="a" * 64,
        metadata={"source_time_field": "Date", "availability_time_field": "Date",
                  "source_calendar": "SSE", "available_at": "MARKET_CLOSE",
                  "request_range_policy": "EXACT"},
    ))


def _inputs():
    dates = pd.bdate_range("2026-09-14", periods=3)
    raw = pd.DataFrame({"Date": dates, "Open": [10., 11., 12.],
        "High": [11., 12., 13.], "Low": [9., 10., 11.], "Close": [10.5, 11.5, 12.5],
        "Volume": [100., 200., 300.], "Amount": [1050., 2300., 3750.]})
    adjusted = raw.copy()
    for column in ("Open", "High", "Low", "Close"):
        adjusted[column] *= [2., 4., 4.]
    adjusted["Volume"] /= [2., 4., 4.]
    minute = raw.copy()
    minute["Date"] += pd.Timedelta(hours=10)
    for frame in (raw, adjusted, minute):
        frame.attrs = {"quality": {"sessions": [{"date": str(day)} for day in dates]}}
    return {"adjusted_daily": _result(adjusted), "execution_daily": _result(raw),
            "execution_30m": _result(minute), "execution_5m": _result(minute.copy())}


def test_TDR_05_C06_numeric_authentication_never_deepcopies_source_attrs():
    class NoCopy:
        def __deepcopy__(self, memo):
            raise AssertionError("quality metadata must not be copied for numerical authentication")

    results = _inputs()
    for item in results.values():
        item.dataframe.attrs["copy_sentinel"] = NoCopy()
    frames = _execution_frames_for_authentication(results, ExecutionPricing())
    assert all(frame.attrs == {} for frame in frames.values())
    with pytest.raises(AssertionError, match="quality metadata"):
        _execution_frames(results, ExecutionPricing())


def test_TDR_05_C04_changed_source_identity_and_fingerprint_still_fail(fresh_bound_inputs, monkeypatch):
    request, flows = fresh_bound_inputs
    execution = request.execution_data
    original = flows.fetch

    def tampered(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(result, identity=replace(result.identity, content_sha256="0" * 64))

    monkeypatch.setattr(flows, "fetch", tampered)
    with pytest.raises(RuntimeContractError, match="input differs"):
        _validate_execution_binding(flows, execution, execution.prepared)
