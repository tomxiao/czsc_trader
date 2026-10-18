"""Offline, hash-bound CZCE methanol providers; no vendor client or network path.

EvidenceParameters identifies a successful acquisition receipt. The receipt binds
the source request, retrieval time and original Tushare table bytes. Explicit
bindings replace defaults: the returned calendar binding is CZCE-only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .contract import DataRequest, Dataset, EvidenceParameters, ProviderBinding
from .errors import DataContractError, EmptyDataError, IncompleteDataError
from . import _czce_calendar_patch


AVAILABILITY_POLICY = "NEXT_CZCE_SESSION_CLOSE_V1"
_DAILY = Dataset.FUTURES_CZCE_METHANOL_DAILY
_MAPPING = Dataset.FUTURES_CZCE_METHANOL_MAPPING
_CONTRACT = r"MA\d{2}(?:0[1-9]|1[0-2])\.ZCE"


def _read_bound(evidence: EvidenceParameters) -> bytes:
    root = evidence.repository_root.resolve()
    path = (root / evidence.source_path).resolve()
    if not path.is_relative_to(root):
        raise DataContractError("evidence path escapes its repository")
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise DataContractError("evidence file is unavailable", path=evidence.source_path) from exc
    if hashlib.sha256(payload).hexdigest() != evidence.source_sha256:
        raise DataContractError("evidence hash differs", path=evidence.source_path)
    return payload


def _receipt(evidence: EvidenceParameters, api: str) -> tuple[pd.DataFrame, dict, dict]:
    receipt = json.loads(_read_bound(evidence))
    if (receipt.get("status") != "RECEIVED" or receipt.get("http_status") != 200
            or receipt.get("vendor_code") != 0 or receipt.get("api") != api):
        raise DataContractError("evidence is not a successful receipt for the requested endpoint", api=api)
    retrieved = pd.Timestamp(receipt["finished_utc"])
    if pd.isna(retrieved) or retrieved.tzinfo is None:
        raise DataContractError("receipt retrieval time must include a timezone")
    response = EvidenceParameters(evidence.repository_root, receipt["response_path"], receipt["response_sha256"])
    table = json.loads(_read_bound(response))
    columns = table["fields"]
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns) or len(set(columns)) != len(columns):
        raise DataContractError("source table fields are invalid")
    if columns != receipt["columns"] or len(table["items"]) != receipt["rows"]:
        raise DataContractError("source table differs from acquisition receipt")
    frame = pd.DataFrame(table["items"], columns=columns)
    if frame.empty:
        raise EmptyDataError("source evidence contains no observations")
    params = receipt["params"]
    if not isinstance(params, dict):
        raise DataContractError("source request parameters are invalid")
    lineage = {
        "receipt_path": evidence.source_path, "receipt_sha256": evidence.source_sha256,
        "response_path": response.source_path, "response_sha256": response.source_sha256,
        "api": api, "params": params, "retrieved_at": retrieved.isoformat(),
    }
    return frame, params, lineage


def _dates(values: pd.Series) -> pd.Series:
    # Vendor dates are eight digits; accepting epoch integers would invent dates.
    strings = values.astype(str)
    if not strings.str.fullmatch(r"\d{8}").all():
        raise DataContractError("source dates must be YYYYMMDD")
    return pd.to_datetime(strings, format="%Y%m%d", errors="raise")


def _source_bounds(params: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    values = _dates(pd.Series([params["start_date"], params["end_date"]]))
    if values.iloc[0] > values.iloc[1]:
        raise DataContractError("source request range is reversed")
    return values.iloc[0], values.iloc[1]


def _range(request: DataRequest, params: dict) -> None:
    start, end = _source_bounds(params)
    if pd.Timestamp(request.start) < start or pd.Timestamp(request.end) > end:
        raise IncompleteDataError("request exceeds the explicitly acquired source range")


def _directory(evidence: EvidenceParameters) -> tuple[pd.DataFrame, dict]:
    raw, params, lineage = _receipt(evidence, "fut_basic")
    if params.get("exchange") != "CZCE" or params.get("fut_code") != "MA":
        raise DataContractError("methanol directory source identity differs")
    if not raw.exchange.eq("CZCE").all() or not raw.fut_code.eq("MA").all():
        raise DataContractError("directory contains a different exchange or product")
    if raw.ts_code.duplicated().any():
        raise DataContractError("directory contains duplicate contracts")
    if not raw.ts_code.str.fullmatch(_CONTRACT + r"|MA\.ZCE|MAL\.ZCE").all():
        raise DataContractError("directory contains an invalid methanol symbol")
    raw = raw.loc[raw.ts_code.str.fullmatch(_CONTRACT)].copy()
    raw["ListDate"] = _dates(raw.list_date)
    raw["MaturityDate"] = _dates(raw.delist_date)
    if (raw.ListDate > raw.MaturityDate).any():
        raise DataContractError("directory contract validity is reversed")
    return raw.set_index("ts_code"), lineage


def _calendar(evidence: EvidenceParameters) -> tuple[pd.DataFrame, dict, dict]:
    raw, params, lineage = _receipt(evidence, "trade_cal")
    if params.get("exchange") != "CZCE" or not raw.exchange.eq("CZCE").all():
        raise DataContractError("calendar source is not CZCE")
    start, end = _source_bounds(params)
    frame = pd.DataFrame({"Date": _dates(raw.cal_date), "IsOpen": pd.to_numeric(raw.is_open)})
    frame["PreviousTradingDate"] = _dates(raw.pretrade_date)
    frame = frame.sort_values("Date").reset_index(drop=True)
    frame, repairs = _czce_calendar_patch.apply_czce_calendar_patch(
        frame, exchange="CZCE", start_date=str(start.date()), end_date=str(end.date()),
    )
    if frame.Date.duplicated().any() or not frame.IsOpen.isin([0, 1]).all():
        raise DataContractError("calendar has duplicate dates or invalid open flags")
    expected = pd.date_range(start, end)
    if not pd.DatetimeIndex(frame.Date).equals(expected):
        raise IncompleteDataError("CZCE calendar does not cover every acquired calendar date",
                                  missing_dates=expected.difference(frame.Date).strftime("%Y-%m-%d").tolist())
    opens = frame.loc[frame.IsOpen.eq(1), "Date"]
    closed_previous_differences = []
    for row in frame.itertuples():
        prior = opens[opens < row.Date]
        if not prior.empty and row.PreviousTradingDate != prior.iloc[-1]:
            if row.IsOpen == 1:
                raise DataContractError("open-day previous trading day disagrees with open sessions")
            closed_previous_differences.append(row.Date.strftime("%Y-%m-%d"))
    # pretrade_date on closed dates is retained as supplier information. It is
    # not the authority for P/Q or availability; those use the exact open flags.
    lineage["closed_day_previous_date_differences"] = closed_previous_differences
    lineage["previous_date_policy"] = "verify open-day predecessor; preserve closed-day source value; use open flags for session lookup"
    lineage.update(repairs)
    return frame, params, lineage


def _available(dates: pd.Series, opens: pd.DatetimeIndex) -> pd.Series:
    positions = opens.searchsorted(pd.DatetimeIndex(dates), side="right")
    if (positions >= len(opens)).any():
        raise IncompleteDataError("calendar lacks the next CZCE session for availability")
    return pd.Series(opens[positions] + pd.Timedelta(hours=15), index=dates.index)


def validate_methanol_output(frame: pd.DataFrame, request: DataRequest, metadata: dict) -> None:
    """Facade-owned invariants, also applied to explicitly injected providers."""
    expected_metadata = {
        "source_calendar": "CZCE", "source_time_field": "Date",
        "availability_time_field": "AvailableDate", "availability_timezone": "Asia/Shanghai",
        "available_at": AVAILABILITY_POLICY, "availability_basis": "DECLARED_POLICY",
        "historical_publication_verified": False, "historical_revision_history_verified": False,
    }
    if any(key not in metadata or metadata[key] != value for key, value in expected_metadata.items()):
        raise DataContractError("methanol requires the explicit declared availability policy")
    coverage = metadata.get("czce_calendar", {})
    opens = pd.DatetimeIndex(pd.to_datetime(coverage.get("open_dates", []), errors="raise"))
    if (opens.empty or opens.has_duplicates or not opens.is_monotonic_increasing
            or opens.tz is not None or not opens.equals(opens.normalize())):
        raise DataContractError("methanol requires ordered, unique CZCE source sessions")
    start, end = pd.Timestamp(request.start), pd.Timestamp(request.end)
    if pd.Timestamp(coverage["start"]) > start or pd.Timestamp(coverage["end"]) < end:
        raise IncompleteDataError("CZCE calendar does not span the request")
    dates = pd.to_datetime(frame.Date, errors="raise")
    expected = opens[(opens >= start) & (opens <= end)]
    if not pd.DatetimeIndex(dates).equals(expected):
        raise IncompleteDataError("methanol does not cover every requested CZCE session",
                                  missing_dates=expected.difference(dates).strftime("%Y-%m-%d").tolist())
    available = pd.to_datetime(frame.AvailableDate, errors="raise")
    if not available.equals(_available(dates, opens)):
        raise DataContractError("methanol AvailableDate differs from next CZCE session close")
    if not frame.Contract.str.fullmatch(_CONTRACT).all():
        raise DataContractError("methanol output has invalid contract identities")
    directory = metadata.get("contract_directory", {})
    for row in frame.itertuples():
        item = directory.get(row.Contract)
        if item is None or not pd.Timestamp(item["listed"]) <= row.Date <= pd.Timestamp(item["maturity"]):
            raise DataContractError("methanol observation falls outside verified contract validity")
    if request.dataset is _DAILY:
        if not frame.Contract.eq(request.symbol).all():
            raise DataContractError("daily output differs from the explicit requested contract")
        numeric = frame[["Close", "Settle", "Volume", "Amount", "OpenInterest"]].apply(pd.to_numeric)
        if (not np.isfinite(numeric.to_numpy(dtype=float)).all()
                or numeric[["Close", "Settle"]].le(0).any().any()
                or numeric[["Volume", "Amount", "OpenInterest"]].lt(0).any().any()):
            raise DataContractError("invalid methanol prices or trading quantities")
        item = directory[request.symbol]
        if start < pd.Timestamp(item["listed"]) or end > pd.Timestamp(item["maturity"]):
            raise DataContractError("daily request exceeds contract validity")
        if (not pd.to_datetime(frame.ListDate).eq(pd.Timestamp(item["listed"])).all()
                or not pd.to_datetime(frame.MaturityDate).eq(pd.Timestamp(item["maturity"])).all()):
            raise DataContractError("daily contract validity fields differ from directory")
    elif not frame.ContinuousSymbol.eq("MA.ZCE").all():
        raise DataContractError("mapping output is not MA.ZCE")


def methanol_evidence_bindings(
    *, directory: EvidenceParameters, calendar: EvidenceParameters,
    mapping: EvidenceParameters, daily: tuple[EvidenceParameters, ...],
) -> dict[Dataset, ProviderBinding]:
    """Bind existing acquisition receipts to two MA datasets and the CZCE calendar.

    No reads occur until prepare requests a dataset. Receipts and response bytes
    are verified each acquisition; prepared fetch remains independent of sources.
    Source Date and AvailableDate are naive Asia/Shanghai wall times, matching
    DFLS session timestamps. AvailableDate is a declared policy, not a release log.
    """
    if (not all(isinstance(item, EvidenceParameters) for item in (directory, calendar, mapping))
            or not isinstance(daily, tuple) or not all(isinstance(item, EvidenceParameters) for item in daily)):
        raise TypeError("methanol sources must be EvidenceParameters and a tuple of daily receipts")
    identities = [(item.source_path, item.source_sha256) for item in (directory, calendar, mapping, *daily)]
    if len(set(identities)) != len(identities):
        raise ValueError("methanol receipt bindings must be distinct")
    evidence_hash = hashlib.sha256(json.dumps(identities, separators=(",", ":")).encode()).hexdigest()
    revision = hashlib.sha256(
        Path(__file__).read_bytes() + Path(_czce_calendar_patch.__file__).read_bytes()
        + json.dumps([_czce_calendar_patch.PATCH_ID, _czce_calendar_patch.PATCH_VERSION,
                      _czce_calendar_patch.PATCH_SOURCE_HASHES]).encode()
    ).hexdigest()

    def provide(request: DataRequest) -> tuple[pd.DataFrame, dict[str, Any]]:
        if request.dataset not in {_DAILY, _MAPPING, Dataset.TRADING_CALENDAR}:
            raise DataContractError("unsupported methanol evidence request")
        cal, cal_params, cal_lineage = _calendar(calendar)
        _range(request, cal_params)
        if request.dataset is Dataset.TRADING_CALENDAR:
            if request.symbol != "CZCE":
                raise DataContractError("offline methanol calendar only supports CZCE")
            return cal.loc[cal.Date.between(request.start, request.end)].reset_index(drop=True), {
                "vendor": "tushare", "vendor_symbol": "CZCE", "source_calendar": "CZCE",
                "exchange": "CZCE", "primary_key": ["Date"], "source_evidence": [cal_lineage],
                "calendar_repairs": cal_lineage.get("calendar_repairs", []),
            }
        contracts, directory_lineage = _directory(directory)
        if request.dataset is _MAPPING:
            raw, params, lineage = _receipt(mapping, "fut_mapping")
            if params.get("ts_code") != "MA.ZCE" or not raw.ts_code.eq("MA.ZCE").all():
                raise DataContractError("mapping source identity differs")
            raw = raw.rename(columns={"mapping_ts_code": "Contract", "ts_code": "ContinuousSymbol"})
        else:
            # Read only small receipts to find the explicitly requested contract;
            # never enumerate/acquire other raw contract tables or call a client.
            matching = []
            for item in daily:
                record = json.loads(_read_bound(item))
                if record.get("api") == "fut_daily" and record.get("params", {}).get("ts_code") == request.symbol:
                    matching.append(item)
            if len(matching) != 1:
                raise IncompleteDataError("expected exactly one daily receipt for the requested contract",
                                          symbol=request.symbol, matching_receipts=len(matching))
            raw, params, lineage = _receipt(matching[0], "fut_daily")
            if not raw.ts_code.eq(request.symbol).all():
                raise DataContractError("daily source contains a different contract")
            raw = raw.rename(columns={"ts_code": "Contract", "close": "Close", "settle": "Settle",
                                      "vol": "Volume", "amount": "Amount", "oi": "OpenInterest"})
        _range(request, params)
        raw["Date"] = _dates(raw.trade_date)
        source_start, source_end = _source_bounds(params)
        if not raw.Date.between(source_start, source_end).all() or raw.Date.duplicated().any():
            raise DataContractError("source contains duplicate or out-of-request dates")
        frame = raw.loc[raw.Date.between(request.start, request.end)].sort_values("Date").reset_index(drop=True)
        if frame.empty:
            raise EmptyDataError("source evidence has no observations in requested window")
        selected_directory = {}
        for symbol in frame.Contract.unique():
            if symbol not in contracts.index:
                raise DataContractError("contract is absent from verified directory", symbol=symbol)
            item = contracts.loc[symbol]
            selected_directory[symbol] = {"listed": item.ListDate.strftime("%Y-%m-%d"),
                                           "maturity": item.MaturityDate.strftime("%Y-%m-%d")}
        opens = pd.DatetimeIndex(cal.loc[cal.IsOpen.eq(1), "Date"])
        frame["AvailableDate"] = _available(frame.Date, opens)
        if request.dataset is _DAILY:
            item = contracts.loc[request.symbol]
            frame["ListDate"], frame["MaturityDate"] = item.ListDate, item.MaturityDate
            columns = ["Date", "Contract", "ListDate", "MaturityDate", "Close", "Settle",
                       "Volume", "Amount", "OpenInterest", "AvailableDate"]
            for name in ["Close", "Settle", "Volume", "Amount", "OpenInterest"]:
                frame[name] = pd.to_numeric(frame[name], errors="raise")
        else:
            columns = ["Date", "ContinuousSymbol", "Contract", "AvailableDate"]
        metadata = {
            "vendor": "tushare", "vendor_symbol": request.symbol, "exchange": "CZCE",
            "primary_key": ["Date", "Contract"] if request.dataset is _DAILY else ["Date", "ContinuousSymbol"],
            "source_time_field": "Date", "availability_time_field": "AvailableDate",
            "source_calendar": "CZCE", "availability_timezone": "Asia/Shanghai",
            "available_at": AVAILABILITY_POLICY, "availability_basis": "DECLARED_POLICY",
            "historical_publication_verified": False, "historical_revision_history_verified": False,
            "price_basis": "RAW_CONTRACT", "zero_volume_semantics": "retained source observation; not a traded return endpoint",
            "czce_calendar": {"start": str(cal.Date.iloc[0].date()), "end": str(cal.Date.iloc[-1].date()),
                              "open_dates": opens.strftime("%Y-%m-%d").tolist()},
            "contract_directory": selected_directory,
            "source_evidence": [lineage, directory_lineage, cal_lineage],
            "calendar_repairs": cal_lineage.get("calendar_repairs", []),
            "evidence_bundle_sha256": evidence_hash,
        }
        return frame[columns], metadata

    # prepare(REUSE) keys include the binding name, not its revision. Pin both
    # evidence and conversion code so changed semantics cannot reuse old assets.
    return {dataset: ProviderBinding("methanol-offline-" + evidence_hash + "-" + revision, revision, provide)
            for dataset in (_DAILY, _MAPPING, Dataset.TRADING_CALENDAR)}


__all__ = ["methanol_evidence_bindings"]
