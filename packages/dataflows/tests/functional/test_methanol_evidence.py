"""Offline methanol publication: source identity, exact sessions and delayed use."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket

import pandas as pd
import pytest

from dataflows import (
    DataRequest,
    DataStatus,
    DataTemporalRequirement,
    Dataflows,
    DataSpace,
    Dataset,
    EvidenceParameters,
    PreparePolicy,
    ProviderBinding,
    ProviderConfig,
    TemporalAlignment,
    align_temporal_frame,
)
from dataflows.methanol_evidence import methanol_evidence_bindings


DAILY = Dataset.FUTURES_CZCE_METHANOL_DAILY
MAPPING = Dataset.FUTURES_CZCE_METHANOL_MAPPING


def _request(dataset=DAILY, symbol="MA2611.ZCE", start="2026-09-24", end="2026-09-28"):
    return DataRequest(dataset, symbol, start, end, end)


def _records():
    """Synthetic holiday and roll; September 25 is deliberately closed."""
    dates = pd.date_range("2026-09-24", "2026-09-29")
    calendar = []
    previous = "20260923"
    for date in dates:
        key = date.strftime("%Y%m%d")
        opened = key in {"20260924", "20260928", "20260929"}
        calendar.append(["CZCE", key, int(opened), previous])
        if opened:
            previous = key
    return {
        "directory": (
            "fut_basic", {"exchange": "CZCE", "fut_code": "MA"},
            ["ts_code", "symbol", "exchange", "fut_code", "list_date", "delist_date"],
            [["MA2610.ZCE", "MA2610", "CZCE", "MA", "20251001", "20261015"],
             ["MA2611.ZCE", "MA2611", "CZCE", "MA", "20251101", "20261115"]],
        ),
        "calendar": (
            "trade_cal", {"exchange": "CZCE", "start_date": "20260924", "end_date": "20260929"},
            ["exchange", "cal_date", "is_open", "pretrade_date"], calendar,
        ),
        "mapping": (
            "fut_mapping", {"ts_code": "MA.ZCE", "start_date": "20260924", "end_date": "20260928"},
            ["ts_code", "trade_date", "mapping_ts_code"],
            [["MA.ZCE", "20260924", "MA2610.ZCE"], ["MA.ZCE", "20260928", "MA2611.ZCE"]],
        ),
        "daily": (
            "fut_daily", {"ts_code": "MA2611.ZCE", "start_date": "20260924", "end_date": "20260928"},
            ["ts_code", "trade_date", "close", "settle", "vol", "amount", "oi"],
            [["MA2611.ZCE", "20260924", 10., 10., 100., 1000., 200.],
             ["MA2611.ZCE", "20260928", 11., 11., 110., 1210., 210.]],
        ),
    }


def _write_evidence(root, records=None):
    evidence = {}
    for name, (api, params, fields, items) in (records or _records()).items():
        response = root / f"{name}-response.json"
        response.write_text(json.dumps({"fields": fields, "items": items}), encoding="utf-8")
        receipt = root / f"{name}-receipt.json"
        receipt.write_text(json.dumps({
            "api": api, "params": params, "fields": ",".join(fields),
            "status": "RECEIVED", "http_status": 200, "vendor_code": 0,
            "finished_utc": "2026-10-18T05:00:00+00:00",
            "response_path": response.name,
            "response_sha256": hashlib.sha256(response.read_bytes()).hexdigest(),
            "rows": len(items), "columns": fields,
        }), encoding="utf-8")
        evidence[name] = EvidenceParameters(
            root, receipt.name, hashlib.sha256(receipt.read_bytes()).hexdigest(),
        )
    return evidence


def _bindings(evidence):
    return methanol_evidence_bindings(
        directory=evidence["directory"], calendar=evidence["calendar"],
        mapping=evidence["mapping"], daily=(evidence["daily"],),
    )


def _flow(root, evidence, *, space="published", bindings=None):
    return Dataflows(
        base_dir=root, space=DataSpace(Path(space)),
        providers=ProviderConfig(bindings=_bindings(evidence) if bindings is None else bindings),
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("methanol evidence publication must make zero network calls")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def test_offline_publication_preserves_pre_roll_contract_and_pinned_reload(tmp_path):
    evidence = _write_evidence(tmp_path)
    requests = (_request(), _request(MAPPING, "MA.ZCE"))
    flow = _flow(tmp_path, evidence)
    prepared = flow.prepare(requests, policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    daily, mapping = [flow.fetch(request, prepared=prepared.reference) for request in requests]
    assert daily.ready and mapping.ready
    assert daily.dataframe.Contract.tolist() == ["MA2611.ZCE", "MA2611.ZCE"]
    assert mapping.dataframe.Contract.tolist() == ["MA2610.ZCE", "MA2611.ZCE"]
    assert daily.dataframe.Close.tolist() == [10., 11.]
    assert daily.dataframe.AvailableDate.tolist() == [
        pd.Timestamp("2026-09-28 15:00"), pd.Timestamp("2026-09-29 15:00"),
    ]
    pd.testing.assert_series_equal(daily.dataframe.AvailableDate, mapping.dataframe.AvailableDate)
    for result in (daily, mapping):
        metadata = result.identity.metadata
        assert metadata["source_calendar"] == "CZCE"
        assert metadata["availability_time_field"] == "AvailableDate"
        assert metadata["available_at"] == "NEXT_CZCE_SESSION_CLOSE_V1"
        assert metadata["historical_publication_verified"] is False
        assert metadata["historical_revision_history_verified"] is False
    # A pinned asset is independent of later source-file loss or caller mutations.
    daily.dataframe.loc[0, "Close"] = -999.
    for path in tmp_path.glob("*-response.json"):
        path.unlink()
    reopened = Dataflows(base_dir=tmp_path, space=DataSpace(Path("published")),
                        providers=ProviderConfig(bindings={}))
    again = reopened.fetch(requests[0], prepared=prepared.reference)
    assert again.ready and again.dataframe.Close.tolist() == [10., 11.]
    reused = flow.prepare(requests, policy=PreparePolicy.REUSE)
    assert reused.ready and reused.reference == prepared.reference


def test_available_date_excludes_same_source_day_and_before_close(tmp_path):
    evidence = _write_evidence(tmp_path)
    flow = _flow(tmp_path, evidence)
    request = _request()
    prepared = flow.prepare((request,), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(request, prepared=prepared.reference)
    aligned = align_temporal_frame(
        result.dataframe,
        ["2026-09-24 15:00", "2026-09-28 14:59", "2026-09-28 15:00", "2026-09-29 15:00"],
        contract=result.identity.temporal_contract,
        requirement=DataTemporalRequirement(
            TemporalAlignment.EXACT_SESSION, decision_time="Asia/Shanghai 15:00", warmup_sessions=2,
        ),
    )
    assert aligned.unmatched_prefix_rows == 2
    assert aligned.dataframe.Close.iloc[:2].isna().all()
    assert aligned.dataframe.Close.iloc[2:].tolist() == [10., 11.]


def test_closed_day_previous_date_is_preserved_but_open_day_predecessor_is_required(tmp_path):
    records = _records()
    # Closed-day vendor values may use a different convention from the latest open date.
    records["calendar"][3][1][3] = "20260923"
    evidence = _write_evidence(tmp_path, records)
    calendar_request = _request(Dataset.TRADING_CALENDAR, "CZCE", end="2026-09-29")
    flow = _flow(tmp_path, evidence)
    prepared = flow.prepare((_request(), calendar_request), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    calendar = flow.fetch(calendar_request, prepared=prepared.reference)
    closed = calendar.dataframe.loc[calendar.dataframe.Date.eq(pd.Timestamp("2026-09-25"))].iloc[0]
    assert closed.IsOpen == 0
    assert closed.PreviousTradingDate == pd.Timestamp("2026-09-23")
    lineage = calendar.identity.metadata["source_evidence"][0]
    assert lineage["closed_day_previous_date_differences"] == ["2026-09-25"]
    daily = flow.fetch(_request(), prepared=prepared.reference)
    assert daily.dataframe.AvailableDate.tolist() == [
        pd.Timestamp("2026-09-28 15:00"), pd.Timestamp("2026-09-29 15:00"),
    ]
    daily_calendar = next(item for item in daily.identity.metadata["source_evidence"]
                          if item["api"] == "trade_cal")
    assert daily_calendar["closed_day_previous_date_differences"] == ["2026-09-25"]

    # The same discrepancy on an OPEN date is a contradiction, not a retained convention.
    records["calendar"][3][4][3] = "20260923"
    evidence = _write_evidence(tmp_path, records)
    rejected = _flow(tmp_path, evidence, space="invalid-open-predecessor").prepare(
        (_request(),), policy=PreparePolicy.REFRESH,
    )
    assert not rejected.ready and rejected.reference is None
    assert rejected.items[0].status is DataStatus.FAILED
    assert rejected.items[0].error.code == "DATA_CONTRACT_MISMATCH"
    assert "open-day previous trading day" in rejected.items[0].error.message


def test_conversion_revision_prevents_reuse_of_prior_preparation(tmp_path, monkeypatch):
    from dataflows import methanol_evidence

    evidence = _write_evidence(tmp_path)
    requests = (_request(), _request(MAPPING, "MA.ZCE"))
    original_bindings = _bindings(evidence)
    original_flow = _flow(tmp_path, evidence, bindings=original_bindings)
    original = original_flow.prepare(requests, policy=PreparePolicy.REFRESH)
    assert original.ready, original.items

    source = Path(methanol_evidence.__file__).resolve()
    read_bytes = Path.read_bytes

    def revised_source(path):
        payload = read_bytes(path)
        return payload + b"\n# synthetic conversion revision\n" if path.resolve() == source else payload

    monkeypatch.setattr(Path, "read_bytes", revised_source)
    changed_bindings = _bindings(evidence)
    for dataset in (DAILY, MAPPING):
        assert changed_bindings[dataset].revision != original_bindings[dataset].revision
        assert changed_bindings[dataset].name != original_bindings[dataset].name
    changed_flow = _flow(tmp_path, evidence, bindings=changed_bindings)
    changed = changed_flow.prepare(requests, policy=PreparePolicy.REUSE)
    assert changed.ready, changed.items
    assert changed.reference != original.reference
    for request in requests:
        result = changed_flow.fetch(request, prepared=changed.reference)
        earlier = changed_flow.fetch(request, prepared=original.reference)
        assert result.ready and earlier.ready
        assert result.identity.metadata["provider_revision"] == changed_bindings[request.dataset].revision
        assert earlier.identity.metadata["provider_revision"] == original_bindings[request.dataset].revision
        pd.testing.assert_frame_equal(result.dataframe, earlier.dataframe)


@pytest.mark.parametrize("dataset,symbol", [
    (DAILY, "MA.ZCE"), (DAILY, "MA2613.ZCE"), (DAILY, "MA2600.ZCE"),
    (DAILY, "MA611.ZCE"), (DAILY, "MA2611.CZCE"), (DAILY, "ma2611.ZCE"),
    (MAPPING, "MA2611.ZCE"), (MAPPING, "MAL.ZCE"),
])
def test_contract_rejects_ambiguous_or_invalid_symbols(dataset, symbol):
    with pytest.raises(ValueError):
        _request(dataset, symbol)


@pytest.mark.parametrize("changes", [
    {"start": "2026-09-24T00:00:00"}, {"frequency": "weekly"},
    {"parameters": EvidenceParameters(Path.cwd(), "receipt.json", "0" * 64)},
])
def test_request_rejects_implicit_time_or_wrong_parameters(changes):
    with pytest.raises((ValueError, TypeError)):
        replace(_request(), **changes)


def _assert_rejected(root, evidence, request=None, *, space="rejected"):
    flow = _flow(root, evidence, space=space)
    prepared = flow.prepare((request or _request(),), policy=PreparePolicy.REFRESH)
    assert not prepared.ready
    assert prepared.reference is None
    assert prepared.items[0].status in {DataStatus.FAILED, DataStatus.INCOMPLETE}
    assert prepared.items[0].error is not None


@pytest.mark.parametrize("mutation", [
    "response_hash", "receipt_hash", "relative_escape", "wrong_api", "wrong_exchange",
    "failed_receipt", "missing_session", "duplicate_session", "wrong_contract",
    "unlisted_contract", "zero_close", "negative_volume", "calendar_hole",
])
def test_evidence_failures_block_publication_without_fallback(tmp_path, mutation):
    records = _records()
    if mutation == "missing_session":
        records["daily"][3].pop(0)
    elif mutation == "duplicate_session":
        records["daily"][3].append(records["daily"][3][0].copy())
    elif mutation == "wrong_contract":
        records["daily"][3][0][0] = "MA2610.ZCE"
    elif mutation == "unlisted_contract":
        records["directory"][3][1][4] = "20260928"
    elif mutation == "zero_close":
        records["daily"][3][0][2] = 0.
    elif mutation == "negative_volume":
        records["daily"][3][0][4] = -1.
    elif mutation == "calendar_hole":
        records["calendar"][3].pop(2)  # Missing closed Saturday still violates natural-day coverage.
    evidence = _write_evidence(tmp_path, records)
    if mutation == "response_hash":
        (tmp_path / "daily-response.json").write_text("{}", encoding="utf-8")
    elif mutation == "receipt_hash":
        (tmp_path / "daily-receipt.json").write_text("{}", encoding="utf-8")
    elif mutation in {"relative_escape", "wrong_api", "wrong_exchange", "failed_receipt"}:
        name = "calendar" if mutation == "wrong_exchange" else "daily"
        path = tmp_path / f"{name}-receipt.json"
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "relative_escape":
            receipt["response_path"] = "../daily-response.json"
        elif mutation == "wrong_api":
            receipt["api"] = "daily"
        elif mutation == "wrong_exchange":
            receipt["params"]["exchange"] = "SSE"
        else:
            receipt["status"] = "FAILED"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        evidence[name] = replace(evidence[name], source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    _assert_rejected(tmp_path, evidence)


@pytest.mark.parametrize("data_request", [
    _request(start="2026-09-23"), _request(end="2026-09-29"),
    _request(symbol="MA2610.ZCE"),
])
def test_unprovided_contract_or_range_never_triggers_acquisition(tmp_path, data_request):
    _assert_rejected(tmp_path, _write_evidence(tmp_path), data_request)


def test_zero_volume_is_preserved_and_calendar_tail_cannot_invent_next_session(tmp_path):
    records = _records()
    records["daily"][3][0][4] = 0.
    evidence = _write_evidence(tmp_path, records)
    flow = _flow(tmp_path, evidence)
    prepared = flow.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(_request(), prepared=prepared.reference)
    assert result.dataframe.Volume.tolist() == [0., 110.]
    # Authorize an actual last-day row; lack of the NEXT calendar session must fail.
    records["daily"][1]["end_date"] = "20260929"
    records["daily"][3].append(["MA2611.ZCE", "20260929", 12., 12., 100., 1200., 210.])
    evidence = _write_evidence(tmp_path, records)
    _assert_rejected(tmp_path, evidence, _request(end="2026-09-29"))


def test_single_contract_request_never_reads_other_contract_response(tmp_path):
    records = _records()
    records["unselected"] = (
        "fut_daily", {"ts_code": "MA2610.ZCE", "start_date": "20260924", "end_date": "20260928"},
        records["daily"][2].copy(),
        [["MA2610.ZCE", "20260924", 20., 20., 100., 2000., 200.]],
    )
    evidence = _write_evidence(tmp_path, records)
    (tmp_path / "unselected-response.json").unlink()
    bindings = methanol_evidence_bindings(
        directory=evidence["directory"], calendar=evidence["calendar"], mapping=evidence["mapping"],
        daily=(evidence["daily"], evidence["unselected"]),
    )
    flow = _flow(tmp_path, evidence, bindings=bindings)
    prepared = flow.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    assert flow.fetch(_request(), prepared=prepared.reference).dataframe.Contract.eq("MA2611.ZCE").all()


@pytest.mark.parametrize("mutation", ["missing_session", "wrong_series", "unknown_month_contract"])
def test_mapping_requires_exact_sessions_and_verified_original_contracts(tmp_path, mutation):
    records = _records()
    if mutation == "missing_session":
        records["mapping"][3].pop(0)
    elif mutation == "wrong_series":
        records["mapping"][3][0][0] = "MAL.ZCE"
    else:
        records["mapping"][3][0][2] = "MA2612.ZCE"
    _assert_rejected(tmp_path, _write_evidence(tmp_path, records), _request(MAPPING, "MA.ZCE"))


@pytest.mark.parametrize("mutation", ["missing_availability", "same_day_availability", "wrong_contract"])
def test_facade_rechecks_provider_time_and_identity(tmp_path, mutation):
    evidence = _write_evidence(tmp_path)
    bindings = _bindings(evidence)
    original = bindings[DAILY]

    def invalid(request):
        frame, metadata = original.fetch(request)
        frame = frame.copy()
        if mutation == "missing_availability":
            frame = frame.drop(columns="AvailableDate")
        elif mutation == "same_day_availability":
            frame["AvailableDate"] = pd.to_datetime(frame["Date"]) + pd.Timedelta(hours=15)
        else:
            frame.loc[0, "Contract"] = "MA2610.ZCE"
        return frame, metadata

    bindings[DAILY] = ProviderBinding("invalid-evidence-fixture", "v1", invalid)
    prepared = _flow(tmp_path, evidence, bindings=bindings).prepare(
        (_request(),), policy=PreparePolicy.REFRESH,
    )
    assert not prepared.ready and prepared.reference is None
    assert prepared.items[0].status is DataStatus.FAILED
    assert prepared.items[0].error.code == "DATA_CONTRACT_MISMATCH"
