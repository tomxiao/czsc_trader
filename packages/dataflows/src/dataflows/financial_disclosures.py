"""Observed company filings; no vintage selection or financial signal inference.

The event clock is the later disclosed announcement date. AvailableDate is a
conservative research assumption: first later SSE session at 15:00 Shanghai,
with execution left to the next session by the caller. Neither clock certifies
historical vendor arrival, original filings, or complete revision history.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from .contract import DataRequest, FinancialDisclosureParameters, FinancialReportKind
from .errors import DataContractError, EmptyDataError, IncompleteDataError
from .tushare_common import get_tushare_pro


_VALUES = {
    FinancialReportKind.INCOME: (
        "revenue", "oper_cost", "operate_profit", "total_profit", "n_income",
        "n_income_attr_p", "minority_gain", "income_tax", "non_oper_income", "non_oper_exp",
    ),
    FinancialReportKind.BALANCE_SHEET: (
        "total_assets", "total_liab", "total_hldr_eqy_exc_min_int", "total_hldr_eqy_inc_min_int",
        "money_cap", "accounts_receiv", "notes_receiv", "inventories", "contract_assets", "fix_assets", "cip",
    ),
    FinancialReportKind.CASH_FLOW: (
        "net_profit", "n_cashflow_act", "c_fr_sale_sg", "c_paid_goods_s", "c_pay_acq_const_fiolta",
    ),
    FinancialReportKind.FINANCIAL_INDICATOR: (
        "profit_dedt", "extra_item", "grossprofit_margin", "ocfps", "roe", "q_dtprofit",
        "q_gsprofit_margin", "q_sales_yoy", "q_netprofit_yoy", "dt_netprofit_yoy",
    ),
}
_COMMON = ("ts_code", "ann_date", "end_date", "update_flag")
_STATEMENT = ("f_ann_date", "report_type", "comp_type")
_OBSERVED_LIMIT = 100
_AVAILABILITY = "first SSE session strictly after max(ann_date, f_ann_date), 15:00 Asia/Shanghai"
_LIMITATIONS = {
    "point_in_time_mode": "CURRENT_VENDOR_SNAPSHOT",
    "historical_revision_history_verified": False,
    "original_disclosure_version_verified": False,
    "historical_vendor_arrival_verified": False,
    "version_selection": "ALL_OBSERVED_ROWS_NO_VINTAGE_SELECTION",
    "record_identity_basis": "RAW_RECORD_HASH_PLUS_DUPLICATE_ORDINAL_NOT_HISTORICAL_REVISION_ID",
    "source_response_hash_basis": "CANONICAL_SDK_FIELDS_ITEMS_JSON_NOT_TRANSPORT_BYTES",
    "coverage_scope": "OBSERVED_RECORDS_AND_EXPLICIT_EXPECTED_PERIODS_ONLY",
    "execution_rule": "next trading session after decision; caller responsibility",
}


def _fields(parameters: FinancialDisclosureParameters) -> tuple[str, ...]:
    statement = () if parameters.report_kind is FinancialReportKind.FINANCIAL_INDICATOR else _STATEMENT
    return (*_COMMON, *statement, *_VALUES[parameters.report_kind])


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _scalar(value: Any) -> Any:
    if pd.isna(value):
        return None
    return value.item() if isinstance(value, np.generic) else value


def _source_dates(values: pd.Series, name: str, *, nullable: bool = False) -> pd.Series:
    present = values.notna()
    if (not nullable and not present.all()) or not values.loc[present].map(
        lambda value: isinstance(value, str) and re.fullmatch(r"\d{8}", value) is not None
    ).all():
        raise DataContractError("financial disclosure has invalid source dates", field=name)
    dates = pd.to_datetime(values, format="%Y%m%d", errors="coerce")
    if dates.loc[present].isna().any():
        raise DataContractError("financial disclosure has invalid source dates", field=name)
    return dates


def _canonicalize(raw: pd.DataFrame, request: DataRequest) -> pd.DataFrame:
    parameters = request.parameters
    columns = _fields(parameters)
    missing = sorted(set(columns).difference(raw.columns))
    if missing or raw.columns.duplicated().any():
        raise DataContractError("financial disclosure fields are missing or duplicated", missing_fields=missing)
    frame = raw.loc[:, columns].copy().reset_index(drop=True)
    if not frame.ts_code.eq(request.symbol).all():
        raise DataContractError("financial disclosure symbol differs from request")
    if not frame.update_flag.astype("string").isin(["0", "1"]).all():
        raise DataContractError("financial disclosure update_flag is invalid")
    is_indicator = parameters.report_kind is FinancialReportKind.FINANCIAL_INDICATOR
    if not is_indicator:
        if not frame.report_type.astype("string").eq(parameters.report_type.value).all():
            raise DataContractError("financial disclosure report_type differs from request")
        if not frame.comp_type.astype("string").isin(["1", "2", "3", "4"]).all():
            raise DataContractError("financial disclosure company type is invalid")
    period = _source_dates(frame.end_date, "end_date")
    ann = _source_dates(frame.ann_date, "ann_date", nullable=not is_indicator)
    actual = (pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]") if is_indicator
              else _source_dates(frame.f_ann_date, "f_ann_date", nullable=True))
    effective = pd.concat([ann, actual], axis=1).max(axis=1)
    if effective.isna().any() or ((ann.notna() & ann.lt(period)) | (actual.notna() & actual.lt(period))).any():
        raise DataContractError("financial disclosure date precedes report period or is missing")
    for column in _VALUES[parameters.report_kind]:
        # No parsing, rounding, unit conversion, imputation or cumulative differencing.
        if not frame[column].map(
            lambda value: pd.isna(value) or (
                not isinstance(value, (bool, np.bool_)) and isinstance(value, (int, float, np.number))
                and np.isfinite(value)
            )
        ).all():
            raise DataContractError("financial disclosure contains invalid raw numeric values", field=column)
    raw_records = [_json({column: _scalar(value) for column, value in zip(columns, row)})
                   for row in frame.itertuples(index=False, name=None)]
    counts: Counter[str] = Counter()
    record_ids = []
    for record in raw_records:
        digest = _digest(record)
        record_ids.append(f"{digest}:{counts[digest]}")
        counts[digest] += 1
    frame.insert(0, "Date", effective)
    frame["ReportKind"] = parameters.report_kind.value
    frame["RawRecord"] = raw_records
    frame["RecordId"] = record_ids  # observation identity, never a historical revision ID
    return frame.sort_values(["Date", "RecordId"], kind="stable").reset_index(drop=True)


def _calendar(raw: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    if raw.empty or not {"cal_date", "is_open"}.issubset(raw.columns):
        raise IncompleteDataError("SSE financial-disclosure calendar is missing")
    dates = _source_dates(raw.cal_date, "cal_date")
    flags = raw.is_open
    if not flags.map(lambda value: type(value) in (int, str) and str(value) in ("0", "1")).all():
        raise DataContractError("SSE financial-disclosure calendar has invalid open flags")
    result = pd.DataFrame({"cal_date": dates.dt.strftime("%Y%m%d"), "is_open": flags.astype(int)})
    result = result.sort_values("cal_date").reset_index(drop=True)
    if not result.cal_date.tolist() == pd.date_range(start, end).strftime("%Y%m%d").tolist():
        raise IncompleteDataError("SSE financial-disclosure calendar is incomplete or duplicated")
    open_days = pd.to_datetime(result.loc[result.is_open.eq(1), "cal_date"], format="%Y%m%d").tolist()
    return result, open_days


def _available(dates: pd.Series, open_days: list[pd.Timestamp]) -> list[pd.Timestamp]:
    result = []
    for day in dates:
        position = bisect_right(open_days, day)
        if position == len(open_days):
            raise IncompleteDataError("no later SSE session for financial disclosure")
        result.append(open_days[position] + pd.Timedelta(hours=15))
    return result


def _accounting(parameters: FinancialDisclosureParameters) -> dict[str, str]:
    if parameters.report_kind is FinancialReportKind.FINANCIAL_INDICATOR:
        return {"statement_scope": "VENDOR_DEFINED_PER_FIELD", "period_basis": "MIXED_CUMULATIVE_AND_SINGLE_QUARTER"}
    return {"statement_scope": "CONSOLIDATED", "period_basis": (
        "PERIOD_END_SNAPSHOT" if parameters.report_kind is FinancialReportKind.BALANCE_SHEET else "YEAR_TO_DATE_CUMULATIVE"
    )}


def validate_financial_disclosures(frame: pd.DataFrame, request: DataRequest, metadata: Mapping[str, Any]) -> None:
    """Enforce the observed-record schema at the DFLS publication boundary."""
    parameters = request.parameters
    if not isinstance(parameters, FinancialDisclosureParameters):
        raise DataContractError("financial disclosure parameters are required")
    required = {
        **_LIMITATIONS, **_accounting(parameters), "vendor": "tushare",
        "vendor_interface": parameters.report_kind.value, "vendor_symbol": request.symbol,
        "source_time_field": "Date", "availability_time_field": "AvailableDate",
        "source_calendar": "SSE", "availability_timezone": "Asia/Shanghai", "available_at": _AVAILABILITY,
        "primary_key": ["Date", "RecordId"], "request_range_policy": "EXACT",
    }
    if any(metadata.get(key) != value for key, value in required.items()):
        raise DataContractError("financial disclosure lineage or accounting contract differs")
    if not {"Date", "AvailableDate", "RawRecord", "RecordId", "ReportKind"}.issubset(frame.columns):
        raise DataContractError("financial disclosure schema is incomplete")
    try:
        retrieved = pd.Timestamp(metadata["retrieved_at"])
        if pd.isna(retrieved) or retrieved.tzinfo is None:
            raise ValueError("retrieved_at requires a timezone")
        source_digest = metadata["source_response_sha256"]
        if not isinstance(source_digest, str) or re.fullmatch(r"[0-9a-f]{64}", source_digest) is None:
            raise ValueError("source response hash is invalid")
        raw = pd.DataFrame([json.loads(value) for value in frame.RawRecord], dtype=object)
        canonical = _canonicalize(raw, request)
    except (KeyError, TypeError, ValueError) as exc:
        raise DataContractError("financial disclosure evidence identity is invalid") from exc
    expected_columns = list(canonical.columns) + ["AvailableDate"]
    if list(frame.columns) != expected_columns:
        raise DataContractError("financial disclosure columns differ from schema")
    # Compare values, including nulls, without rewriting source dtypes or values.
    for column in canonical:
        left, right = frame[column].reset_index(drop=True), canonical[column]
        if not (left.eq(right) | (left.isna() & right.isna())).all():
            raise DataContractError("financial disclosure differs from raw evidence", field=column)
    periods = pd.to_datetime(frame.end_date, format="%Y%m%d")
    if not periods.between(parameters.report_period_start, parameters.report_period_end).all():
        raise DataContractError("financial disclosure exceeds report-period bounds")
    missing = set(parameters.expected_periods).difference(periods.dt.strftime("%Y-%m-%d"))
    if missing:
        raise IncompleteDataError("financial disclosure expected periods are missing", missing_periods=sorted(missing))
    start = pd.to_datetime(frame.Date).min() + pd.Timedelta(days=1)
    end = pd.to_datetime(frame.Date).max() + pd.Timedelta(days=40)
    calendar, open_days = _calendar(pd.DataFrame(metadata.get("availability_calendar", [])), start, end)
    if _digest(_json(calendar.to_dict("records"))) != metadata.get("calendar_sha256"):
        raise DataContractError("financial disclosure calendar identity differs")
    if not pd.to_datetime(frame.AvailableDate).reset_index(drop=True).equals(
        pd.Series(_available(frame.Date, open_days), dtype="datetime64[ns]")
    ):
        raise DataContractError("financial disclosure availability differs from next-session policy")


def fetch_company_financial_disclosures(
    request: DataRequest, *, env_file: str | Path | None = None, pro: object | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Acquire a bounded current snapshot once; no retries or version collapse.

    Statements are queried by ann_date from the earliest requested report end,
    including earlier ann_date rows with a later f_ann_date. Indicators are
    queried by report period. Both are then bounded by effective disclosure date.
    A limit-sized response is INCOMPLETE rather than assumed exhaustive.
    """
    parameters = request.parameters
    if not isinstance(parameters, FinancialDisclosureParameters):
        raise DataContractError("financial disclosure parameters are required")
    indicator = parameters.report_kind is FinancialReportKind.FINANCIAL_INDICATOR
    query = {
        "ts_code": request.symbol,
        "start_date": parameters.report_period_start.replace("-", ""),
        "end_date": (parameters.report_period_end if indicator else request.end).replace("-", ""),
        "limit": _OBSERVED_LIMIT,
    }
    if not indicator:
        query["report_type"] = parameters.report_type.value
    client = pro if pro is not None else get_tushare_pro(env_file)
    value = getattr(client, parameters.report_kind.value)(fields=",".join(_fields(parameters)), **query)
    retrieved = pd.Timestamp.now(tz="UTC").isoformat()
    raw = pd.DataFrame(value)
    if raw.empty:
        raise EmptyDataError("no company financial disclosures returned")
    if len(raw) >= _OBSERVED_LIMIT:
        raise IncompleteDataError("financial response may be truncated; use a narrower report-period window",
                                  observed_rows=len(raw), limit=_OBSERVED_LIMIT)
    frame = _canonicalize(raw, request)
    periods = pd.to_datetime(frame.end_date, format="%Y%m%d")
    selected = periods.between(parameters.report_period_start, parameters.report_period_end)
    selected &= frame.Date.between(pd.Timestamp(request.start), pd.Timestamp(request.end))
    frame = frame.loc[selected].reset_index(drop=True)
    if frame.empty:
        raise EmptyDataError("no observed financial disclosures within the requested disclosure and period windows")
    calendar_start = frame.Date.min() + pd.Timedelta(days=1)
    calendar_end = frame.Date.max() + pd.Timedelta(days=40)
    calendar_raw = client.trade_cal(exchange="SSE", start_date=calendar_start.strftime("%Y%m%d"),
                                    end_date=calendar_end.strftime("%Y%m%d"), fields="cal_date,is_open")
    calendar, open_days = _calendar(pd.DataFrame(calendar_raw), calendar_start, calendar_end)
    frame["AvailableDate"] = pd.Series(_available(frame.Date, open_days), dtype="datetime64[ns]")
    evidence = {"fields": list(raw.columns), "items": [[_scalar(value) for value in row]
                for row in raw.itertuples(index=False, name=None)]}
    versions = frame.groupby("end_date", dropna=False).size()
    metadata = {
        **_LIMITATIONS, **_accounting(parameters),
        "vendor": "tushare", "vendor_interface": parameters.report_kind.value, "vendor_symbol": request.symbol,
        "query": query, "query_range_basis": "REPORT_PERIOD" if indicator else "ANNOUNCEMENT_DATE",
        "source_time_field": "Date", "availability_time_field": "AvailableDate", "source_calendar": "SSE",
        "availability_timezone": "Asia/Shanghai", "available_at": _AVAILABILITY, "request_range_policy": "EXACT",
        "primary_key": ["Date", "RecordId"], "retrieved_at": retrieved,
        "source_response_sha256": _digest(_json(evidence)), "raw_response_rows": len(raw),
        "excluded_rows": len(raw) - len(frame), "observed_rows": len(frame),
        "version_status": "MULTIPLE_OBSERVED_ROWS" if versions.gt(1).any() else "SINGLE_OBSERVED_ROW_PER_PERIOD",
        "ambiguous_report_periods": sorted(versions.loc[versions.gt(1)].index.tolist()),
        "availability_calendar": calendar.to_dict("records"), "calendar_sha256": _digest(_json(calendar.to_dict("records"))),
        "numeric_units": "SOURCE_NATIVE_NO_SCALING; statements CNY; indicators per-field CNY/percent/CNY_PER_SHARE",
        "indicator_single_quarter_fields": [field for field in _VALUES[parameters.report_kind] if field.startswith("q_")],
        "report_type": None if indicator else parameters.report_type.value,
    }
    validate_financial_disclosures(frame, request, metadata)
    return frame, metadata
