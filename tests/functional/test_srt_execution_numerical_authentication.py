"""Numerical authentication keeps pricing and tamper checks, without attrs copying."""

from copy import deepcopy
from dataclasses import replace
from datetime import date

from dataflows import DataIdentity, DataResult, DataStatus, canonical_frame_sha256
import pandas as pd
import pytest
from strategy_runtime import ExecutionPriceBasis, ExecutionPricing, RuntimeContractError

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


@pytest.mark.parametrize("basis", [ExecutionPriceBasis.UNADJUSTED, ExecutionPriceBasis.HFQ_RESEARCH])
def test_numeric_authentication_matches_normal_preparation_without_changing_metadata(basis):
    results = _inputs()
    originals = {key: (deepcopy(item.dataframe.attrs), canonical_frame_sha256(item.dataframe))
                 for key, item in results.items()}
    pricing = (ExecutionPricing() if basis is ExecutionPriceBasis.UNADJUSTED else
               ExecutionPricing(basis, date(2026, 9, 14), 2.0))
    normal = _execution_frames(results, pricing)
    numerical = _execution_frames_for_authentication(results, pricing)
    assert normal.keys() == numerical.keys()
    for key in normal:
        pd.testing.assert_frame_equal(normal[key], numerical[key])
        assert canonical_frame_sha256(normal[key]) == canonical_frame_sha256(numerical[key])
        assert numerical[key].attrs == {}
    for key, item in results.items():
        assert item.dataframe.attrs == originals[key][0]
        assert canonical_frame_sha256(item.dataframe) == originals[key][1]
    normal["execution_daily"].attrs["quality"]["sessions"].append({"date": "changed"})
    assert results["execution_daily"].dataframe.attrs == originals["execution_daily"][0]
    numerical["raw_execution_daily"].loc[0, "close"] += 1
    assert canonical_frame_sha256(results["execution_daily"].dataframe) == originals["execution_daily"][1]


def test_numeric_authentication_never_deepcopies_source_attrs():
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


def test_every_authentication_still_fetches_all_inputs_and_detects_changed_actual_frame(fresh_bound_inputs, monkeypatch):
    request, flows = fresh_bound_inputs
    execution = request.execution_data
    calls = []
    original = flows.fetch

    def tracked(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(flows, "fetch", tracked)
    _validate_execution_binding(flows, execution, execution.prepared)
    _validate_execution_binding(flows, execution, execution.prepared)
    assert len(calls) == 2 * len(execution.requests)
    assert all(calls.count(value) == 2 for value in execution.requests.values())
    changed = execution.execution_daily.copy()
    changed.loc[0, "close"] += 1
    with pytest.raises(RuntimeContractError, match="dataframe differs.*execution_daily"):
        _validate_execution_binding(flows, replace(execution, execution_daily=changed), execution.prepared)


def test_changed_source_identity_and_fingerprint_still_fail(fresh_bound_inputs, monkeypatch):
    request, flows = fresh_bound_inputs
    execution = request.execution_data
    with pytest.raises(RuntimeContractError, match="fingerprint differs"):
        _validate_execution_binding(flows, replace(execution, fingerprint="0" * 64), execution.prepared)
    original = flows.fetch

    def tampered(*args, **kwargs):
        result = original(*args, **kwargs)
        return replace(result, identity=replace(result.identity, content_sha256="0" * 64))

    monkeypatch.setattr(flows, "fetch", tampered)
    with pytest.raises(RuntimeContractError, match="input differs"):
        _validate_execution_binding(flows, execution, execution.prepared)
