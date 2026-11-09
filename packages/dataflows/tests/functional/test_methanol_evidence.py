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
    Dataflows,
    Dataset,
    EvidenceParameters,
    PreparePolicy,
    ProviderConfig,
)
from dataflows.methanol_evidence import methanol_evidence_bindings, validate_methanol_output
from dataflows.errors import DataContractError, IncompleteDataError


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


@pytest.fixture
def methanol_flow(tmp_path, empty_space_factory):
    """Private named stores; every evidence acquisition/publication remains real."""
    def create(evidence, *, space="published", bindings=None):
        return Dataflows(
            base_dir=tmp_path, space=empty_space_factory(space),
            providers=ProviderConfig(bindings=_bindings(evidence) if bindings is None else bindings),
        )
    return create


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("methanol evidence publication must make zero network calls")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)








def test_DFLS_36_C01_conversion_revision_prevents_reuse_of_prior_preparation(tmp_path, methanol_flow, monkeypatch):
    from dataflows import methanol_evidence

    evidence = _write_evidence(tmp_path)
    requests = (_request(), _request(MAPPING, "MA.ZCE"))
    original_bindings = _bindings(evidence)
    original_flow = methanol_flow(evidence, bindings=original_bindings)
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
    changed_flow = methanol_flow(evidence, bindings=changed_bindings)
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






def _assert_source_rejected(evidence, request=None):
    # Source evidence/conversion failures belong to the binding and validator;
    # the facade rejection path is exercised once below, without one SQLite
    # publication store per malformed receipt or source row.
    request = request or _request()
    with pytest.raises((DataContractError, IncompleteDataError)):
        frame, metadata = _bindings(evidence)[request.dataset].fetch(request)
        validate_methanol_output(frame, request, metadata)


@pytest.mark.parametrize("mutation", [
    "response_hash",
], ids=['DFLS-35-C06'])
def test_evidence_failures_reject_at_source_without_fallback(tmp_path, mutation):
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
    if mutation == "relative_escape":
        # The typed path contract rejects traversal while decoding the receipt,
        # before any provider output or publication validation exists.
        with pytest.raises(ValueError, match=r"^source_path must be a non-empty relative path without '\.\.'$"):
            _bindings(evidence)[DAILY].fetch(_request())
    else:
        _assert_source_rejected(evidence)




def test_DFLS_35_C05_zero_volume_is_preserved_and_calendar_tail_cannot_invent_next_session(tmp_path, methanol_flow):
    records = _records()
    records["daily"][3][0][4] = 0.
    evidence = _write_evidence(tmp_path, records)
    flow = methanol_flow(evidence)
    prepared = flow.prepare((_request(),), policy=PreparePolicy.REFRESH)
    assert prepared.ready, prepared.items
    result = flow.fetch(_request(), prepared=prepared.reference)
    assert result.dataframe.Volume.tolist() == [0., 110.]
    # Authorize an actual last-day row; lack of the NEXT calendar session must fail.
    records["daily"][1]["end_date"] = "20260929"
    records["daily"][3].append(["MA2611.ZCE", "20260929", 12., 12., 100., 1200., 210.])
    evidence = _write_evidence(tmp_path, records)
    _assert_source_rejected(evidence, _request(end="2026-09-29"))




@pytest.mark.parametrize("mutation", [
    "missing_session",
    "unknown_month_contract",
], ids=['DFLS-35-C03', 'DFLS-35-C04'])
def test_mapping_requires_exact_sessions_and_verified_original_contracts(tmp_path, mutation):
    records = _records()
    if mutation == "missing_session":
        records["mapping"][3].pop(0)
    elif mutation == "wrong_series":
        records["mapping"][3][0][0] = "MAL.ZCE"
    else:
        records["mapping"][3][0][2] = "MA2612.ZCE"
    _assert_source_rejected(_write_evidence(tmp_path, records), _request(MAPPING, "MA.ZCE"))
