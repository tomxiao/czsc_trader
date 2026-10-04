"""Stable DFLS facade over vendor-specific data adapters."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import fields, is_dataclass, replace
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from .asset_store import AssetStore, StoreError

from .contract import (
    ETF_INTRADAY_OBSERVATION_RULE,
    FXCM_AVAILABILITY_RULE,
    DataError,
    DataIdentity,
    DataRequest,
    DataResult,
    Dataset,
    DataStatus,
    RequestRangePolicy,
    DataSpace, PreparePolicy, PrepareStatus, PreparedDataRef,
    PrepareResult, ItemPrepareResult, ProviderConfig, ProviderBinding,
    PcfParameters, MoneyflowParameters,
)
from .errors import (
    DataContractError,
    DataflowError,
    EmptyDataError,
    IncompleteDataError,
    SourceNotReadyError,
)
from .history_validation import inspect_ohlcv_frame
from .market_resolver import MARKET_A_SHARE, detect_market

Provider = Callable[[DataRequest], tuple[pd.DataFrame, Mapping[str, Any]]]


_SOURCE_CALENDAR_BY_DATASET = {
    Dataset.ETF_CREATION_REDEMPTION_BASKET.value: "SZSE",
    Dataset.FXCM_DAILY.value: "FXCM_24X5",
    Dataset.USDCNH_DAILY.value: "FXCM_24X5",
    Dataset.US_REAL_YIELD_DAILY.value: "US_GOVERNMENT",
    Dataset.US_NOMINAL_YIELD_DAILY.value: "US_GOVERNMENT",
    Dataset.US_POLICY_UNCERTAINTY_DAILY.value: "FRED_CALENDAR_DAY",
    Dataset.GLOBAL_INDEX_DAILY.value: "US_MARKET",
    Dataset.VIX_DAILY.value: "US_MARKET",
    Dataset.CN_CPI_MONTHLY.value: "CHINA_CALENDAR_MONTH",
    Dataset.US_CPI_RELEASE.value: "US_BLS_EASTERN",
    Dataset.US_ISM_PMI_RELEASE.value: "TUSHARE_ECO_CAL_DATE",
    Dataset.US_FEDERAL_BUDGET_RELEASE.value: "TUSHARE_ECO_CAL_DATE",
    Dataset.CN_PPI_MONTHLY.value: "CHINA_CALENDAR_MONTH",
    Dataset.CN_MONEY_MONTHLY.value: "CHINA_CALENDAR_MONTH",
    Dataset.SGE_GOLD_DAILY.value: "SGE",
    Dataset.FUTURES_SHFE_GOLD_DAILY.value: "SHFE",
    Dataset.FUTURES_SHFE_GOLD_MAPPING.value: "SHFE",
    Dataset.FUTURES_SHFE_GOLD_HOLDING.value: "SHFE",
    Dataset.SELL_SIDE_FORECAST.value: "SSE",
    Dataset.STRATEGY_FEATURE_EVIDENCE.value: "REPOSITORY",
}

_CALENDAR_MONTH_DATASETS = {
    Dataset.CN_CPI_MONTHLY.value,
    Dataset.CN_PPI_MONTHLY.value,
    Dataset.CN_MONEY_MONTHLY.value,
}


def _lineage_metadata(
    request: DataRequest,
    dataframe: pd.DataFrame,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Add and validate stable source-time semantics to every READY publication."""

    result = dict(metadata)
    source_time_field = str(result.get("source_time_field", "Date")).strip()
    if not source_time_field or source_time_field not in dataframe.columns:
        raise DataContractError(
            "provider source time field is unavailable",
            source_time_field=source_time_field,
        )
    source_calendar = str(result.get("source_calendar", "")).strip()
    if not source_calendar:
        source_calendar = _SOURCE_CALENDAR_BY_DATASET.get(str(request.dataset), "")
    if not source_calendar:
        source_calendar = str(result.get("exchange") or "SOURCE_NATIVE").strip()
    available_at = str(result.get("available_at", "")).strip()
    if not available_at:
        available_at = str(result.get("availability_rule") or "SOURCE_PERIOD_CLOSE").strip()
    if not source_calendar or not available_at:
        raise DataContractError("provider source-time metadata is incomplete")
    availability_time_field = str(
        result.get(
            "availability_time_field",
            "AvailableDate" if "AvailableDate" in dataframe.columns else source_time_field,
        )
    ).strip()
    if not availability_time_field or availability_time_field not in dataframe.columns:
        raise DataContractError(
            "provider availability time field is unavailable",
            availability_time_field=availability_time_field,
        )
    default_range_policy = (
        RequestRangePolicy.CALENDAR_MONTH
        if str(request.dataset) in _CALENDAR_MONTH_DATASETS
        else RequestRangePolicy.EXACT
    )
    try:
        request_range_policy = RequestRangePolicy(
            result.get("request_range_policy", default_range_policy)
        )
    except ValueError as exc:
        raise DataContractError("provider request range policy is invalid") from exc
    result.update(
        source_time_field=source_time_field,
        availability_time_field=availability_time_field,
        source_calendar=source_calendar,
        available_at=available_at,
        request_range_policy=request_range_policy.value,
    )
    return result


_OHLCV_DATASETS = {
    Dataset.ETF_UNADJUSTED_INTRADAY.value,
    Dataset.ETF_OHLCV.value,
    Dataset.ETF_UNADJUSTED_DAILY.value,
    Dataset.STOCK_OHLCV.value,
    Dataset.STOCK_UNADJUSTED_DAILY.value,
    Dataset.STOCK_UNADJUSTED_INTRADAY.value,
}

_DATASET_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    Dataset.ETF_CREATION_REDEMPTION_BASKET.value: (
        {
            "Date", "AvailableDate", "ConstituentSymbol", "Quantity",
            "CashSubstitutionFlag", "CreationSubstitutionRatePercent",
            "RedemptionSubstitutionRatePercent", "CreationSubstitutionAmountYuan",
            "RedemptionSubstitutionAmountYuan", "Exchange",
        },
        {
            "Quantity", "CreationSubstitutionRatePercent",
            "RedemptionSubstitutionRatePercent", "CreationSubstitutionAmountYuan",
            "RedemptionSubstitutionAmountYuan",
        },
    ),
    Dataset.SHIBOR_DAILY.value: ({"Date", "OvernightRate"}, {"OvernightRate"}),
    Dataset.US_REAL_YIELD_DAILY.value: (
        {"Date", "RealYield5YPercent", "RealYield10YPercent"},
        {"RealYield5YPercent", "RealYield10YPercent"},
    ),
    Dataset.US_NOMINAL_YIELD_DAILY.value: (
        {"Date", "NominalYield10YPercent"},
        {"NominalYield10YPercent"},
    ),
    Dataset.US_POLICY_UNCERTAINTY_DAILY.value: (
        {"Date", "AvailableDate", "PolicyUncertaintyIndex"},
        {"PolicyUncertaintyIndex"},
    ),
    Dataset.USDCNH_DAILY.value: (
        {
            "Date",
            "BidOpen",
            "BidHigh",
            "BidLow",
            "BidClose",
            "AskOpen",
            "AskHigh",
            "AskLow",
            "AskClose",
            "TickQuantity",
        },
        {
            "BidOpen",
            "BidHigh",
            "BidLow",
            "BidClose",
            "AskOpen",
            "AskHigh",
            "AskLow",
            "AskClose",
            "TickQuantity",
        },
    ),
    Dataset.FXCM_DAILY.value: (
        {
            "Date",
            "BidOpen",
            "BidHigh",
            "BidLow",
            "BidClose",
            "AskOpen",
            "AskHigh",
            "AskLow",
            "AskClose",
            "TickQuantity",
        },
        {
            "BidOpen",
            "BidHigh",
            "BidLow",
            "BidClose",
            "AskOpen",
            "AskHigh",
            "AskLow",
            "AskClose",
            "TickQuantity",
        },
    ),
    Dataset.SGE_GOLD_DAILY.value: (
        {"Date", "Open", "High", "Low", "Close", "Volume", "Amount"},
        {"Open", "High", "Low", "Close", "Volume", "Amount"},
    ),
    Dataset.FUTURES_SHFE_GOLD_DAILY.value: (
        {
            "Date",
            "Contract",
            "MaturityDate",
            "Close",
            "Settle",
            "Volume",
            "Amount",
            "OpenInterest",
        },
        {
            "Close",
            "Settle",
            "Volume",
            "Amount",
            "OpenInterest",
        },
    ),
    Dataset.FUTURES_SHFE_GOLD_MAPPING.value: (
        {"Date", "ContinuousSymbol", "Contract"},
        set(),
    ),
    Dataset.FUTURES_SHFE_GOLD_HOLDING.value: (
        {
            "Date",
            "Contract",
            "Broker",
            "Volume",
            "VolumeChange",
            "LongHolding",
            "LongChange",
            "ShortHolding",
            "ShortChange",
        },
        set(),
    ),
    Dataset.DOMESTIC_INDEX_DAILY.value: (
        {"Date", "Open", "High", "Low", "Close", "Volume", "Amount"},
        {"Open", "High", "Low", "Close", "Volume", "Amount"},
    ),
    Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: ({"Date", "Close"}, {"Close"}),
    Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: (
        {"Date", "Close", "Volume", "Amount"}, {"Close", "Volume", "Amount"},
    ),
    Dataset.CN_CPI_MONTHLY.value: (
        {"Date", "AvailableDate", "NationalYoYPercent", "NationalMoMPercent"},
        {"NationalYoYPercent", "NationalMoMPercent"},
    ),
    Dataset.US_CPI_RELEASE.value: (
        {"Date", "ReleaseAt", "AvailableDate", "YoYPercent"},
        {"YoYPercent"},
    ),
    Dataset.US_ISM_PMI_RELEASE.value: (
        {"Date", "AvailableDate", "PmiIndex", "SourceClock", "SourceEvent"},
        {"PmiIndex"},
    ),
    Dataset.US_FEDERAL_BUDGET_RELEASE.value: (
        {"Date", "AvailableDate", "BudgetBalanceBillionUSD", "SourceClock", "SourceEvent"},
        {"BudgetBalanceBillionUSD"},
    ),
    Dataset.CN_PPI_MONTHLY.value: (
        {"Date", "AvailableDate", "ProducerYoYPercent", "ProducerMoMPercent"},
        {"ProducerYoYPercent", "ProducerMoMPercent"},
    ),
    Dataset.CN_MONEY_MONTHLY.value: (
        {"Date", "AvailableDate", "M1YoYPercent", "M2YoYPercent"},
        {"M1YoYPercent", "M2YoYPercent"},
    ),
    Dataset.INDEX_DAILY_BASIC.value: (
        {"Date", "TurnoverRateFreeFloat"},
        {"TurnoverRateFreeFloat"},
    ),
    Dataset.ETF_SHARE_SIZE.value: ({"Date", "TotalShare"}, {"TotalShare"}),
    Dataset.GLOBAL_INDEX_DAILY.value: ({"Date", "PercentChange"}, {"PercentChange"}),
    Dataset.VIX_DAILY.value: (
        {"Date", "Open", "High", "Low", "Close", "PercentChange"},
        {"Open", "High", "Low", "Close", "PercentChange"},
    ),
    Dataset.INDEX_CONSTITUENT_WEIGHT.value: (
        {"Date", "ConstituentSymbol", "Weight"},
        {"Weight"},
    ),
    Dataset.SELL_SIDE_FORECAST.value: (
        {
            "Date",
            "AvailableDate",
            "VendorCreatedAt",
            "Symbol",
            "ReportTitle",
            "Institution",
            "ForecastPeriod",
            "NetProfitForecast",
            "EarningsPerShareForecast",
            "Rating",
        },
        set(),
    ),
    Dataset.STOCK_MONEYFLOW.value: (
        {"Date", "Symbol", "NetMoneyflowAmount"},
        {"NetMoneyflowAmount"},
    ),
    Dataset.TRADING_CALENDAR.value: ({"Date", "IsOpen"}, {"IsOpen"}),
}


def canonical_frame_sha256(dataframe: pd.DataFrame) -> str:
    """Hash dataframe content, column order, dtypes and index deterministically."""

    digest = hashlib.sha256()
    def dtype_schema(dtype):
        if isinstance(dtype, pd.CategoricalDtype):
            return {"dtype": "category", "ordered": dtype.ordered,
                    "categories_dtype": str(dtype.categories.dtype),
                    "categories_hash": hashlib.sha256(
                        pd.util.hash_pandas_object(dtype.categories, index=True).values.tobytes()
                    ).hexdigest()}
        return {"dtype": str(dtype)}

    schema = {
        "version": 2,
        "columns": [(str(column), dtype_schema(dtype)) for column, dtype in dataframe.dtypes.items()],
        "index": {"type": type(dataframe.index).__name__, "names": repr(dataframe.index.names),
                  "dtypes": [dtype_schema(level.dtype) for level in dataframe.index.levels]
                  if isinstance(dataframe.index, pd.MultiIndex)
                  else [dtype_schema(dataframe.index.dtype)]},
    }
    digest.update(json.dumps(schema, separators=(",", ":")).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(dataframe, index=True).values.tobytes())
    return digest.hexdigest()


def _validate_provider_output(
    dataframe: pd.DataFrame,
    request: DataRequest,
    metadata: Mapping[str, Any],
    *, complete_sessions: bool = True,
) -> None:
    """Apply the final DFLS-owned contract before READY can cross the facade."""

    dataset = str(request.dataset)
    vendor_symbol = metadata.get("vendor_symbol")
    if vendor_symbol is not None and request.symbol is not None:
        if str(vendor_symbol).upper() != request.symbol.upper():
            raise DataContractError(
                "provider symbol differs from request",
                requested_symbol=request.symbol,
                provider_symbol=str(vendor_symbol),
            )

    if dataset in _OHLCV_DATASETS:
        frequency = (
            "daily"
            if dataset in {Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.STOCK_UNADJUSTED_DAILY.value}
            else request.frequency
        )
        declared_period = metadata.get("period")
        if declared_period is not None and str(declared_period) != frequency:
            raise DataContractError(
                "provider frequency differs from request",
                requested_frequency=frequency,
                provider_frequency=str(declared_period),
            )
        expected_asset = "etf" if dataset.startswith("etf.") else "stock"
        declared_asset = metadata.get("asset_type")
        if declared_asset is not None and str(declared_asset) != expected_asset:
            raise DataContractError(
                "provider asset type differs from dataset",
                expected_asset_type=expected_asset,
                provider_asset_type=str(declared_asset),
            )
        if (
            dataset
            in {
                Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.ETF_UNADJUSTED_INTRADAY.value,
                Dataset.STOCK_UNADJUSTED_DAILY.value,
                Dataset.STOCK_UNADJUSTED_INTRADAY.value,
            }
            and metadata.get("adjustment") != "none"
        ):
            raise DataContractError(
                "unadjusted dataset provider did not declare adjustment=none",
                dataset=dataset,
            )
        if dataset in {Dataset.ETF_UNADJUSTED_INTRADAY.value, Dataset.STOCK_UNADJUSTED_INTRADAY.value}:
            available = pd.to_datetime(dataframe.get("AvailableDate"), errors="coerce")
            source_dates = pd.to_datetime(dataframe["Date"], errors="coerce")
            if (
                frequency not in {"1m", "5m", "15m", "30m"}
                or metadata.get("availability_time_field") != "AvailableDate"
                or metadata.get("available_at") != ETF_INTRADAY_OBSERVATION_RULE
                or metadata.get("availability_basis") != "MARKET_BAR_CLOSE_ASSUMPTION"
                or metadata.get("source_publication_timestamp_verified") is not False
                or metadata.get("historical_revision_history_verified") is not False
                or metadata.get("live_feed_latency_verified") is not False
                or not isinstance(available, pd.Series)
                or not available.equals(source_dates)
            ):
                raise DataContractError("unadjusted intraday observation contract differs")
        if metadata.get("vendor") == "tushare" and dataset in {
            Dataset.ETF_OHLCV.value, Dataset.STOCK_OHLCV.value,
        } and (dataset == Dataset.ETF_OHLCV.value or metadata.get("market") == MARKET_A_SHARE):
            factor_source = "fund_adj" if dataset == Dataset.ETF_OHLCV.value else "adj_factor"
            expected_schedule = (
                "daily 17:00 Asia/Shanghai" if factor_source == "fund_adj"
                else "trade day 09:15-09:20 Asia/Shanghai"
            )
            expected_availability = (
                "scheduled fund_adj daily 17:00 Asia/Shanghai; historical publication unverified"
                if factor_source == "fund_adj" else
                "intraday bar close or daily 17:00 Asia/Shanghai conservative; "
                "historical publication unverified"
            )
            if (
                metadata.get("adjustment") != "hfq"
                or metadata.get("adjustment_factor_source") != factor_source
                or not isinstance(metadata.get("adjustment_factor_sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", metadata["adjustment_factor_sha256"]) is None
                or metadata.get("adjustment_factor_publication_schedule") != expected_schedule
                or metadata.get("adjustment_factor_publication_timestamp_verified") is not False
                or metadata.get("adjustment_factor_revision_history_verified") is not False
                or metadata.get("availability_time_field") != "AvailableDate"
                or metadata.get("available_at") != expected_availability
            ):
                raise DataContractError("HFQ source or availability evidence contract differs")
            available = pd.to_datetime(dataframe.get("AvailableDate"), errors="coerce")
            source_dates = pd.to_datetime(dataframe["Date"], errors="coerce")
            if not isinstance(available, pd.Series) or available.isna().any():
                raise DataContractError("HFQ scheduled availability is missing")
            if factor_source == "fund_adj" or frequency not in {"1m", "5m", "15m", "30m"}:
                expected_available = source_dates.dt.normalize() + pd.Timedelta(hours=17)
            else:
                expected_available = source_dates
            if not available.equals(expected_available):
                raise DataContractError("HFQ scheduled availability differs from bar and factor timing")
        market = detect_market(_required_symbol(request))
        if metadata.get("market") is not None and metadata["market"] != market:
            raise DataContractError("provider market differs from requested symbol")
        inspect_ohlcv_frame(
            dataframe,
            frequency,
            require_complete_days=complete_sessions and frequency in {"1m", "5m", "15m", "30m"},
            market=market,
            request_start=request.start,
            request_end=request.end,
        ).require_pass()
        return

    specification = _DATASET_FIELDS.get(dataset)
    if specification is None:
        return
    required, numeric = specification
    missing = sorted(required.difference(dataframe.columns))
    if missing:
        raise DataContractError(
            "provider output is missing required dataset fields",
            dataset=dataset,
            missing_fields=missing,
        )
    for column in numeric:
        values = pd.to_numeric(dataframe[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise DataContractError(
                "provider output contains invalid numeric values",
                dataset=dataset,
                field=column,
            )
    if dataset == Dataset.ETF_CREATION_REDEMPTION_BASKET.value:
        source_dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        available_dates = pd.to_datetime(dataframe["AvailableDate"], errors="coerce")
        if (
            source_dates.isna().any()
            or available_dates.isna().any()
            or (available_dates.dt.normalize() <= source_dates.dt.normalize()).any()
            or available_dates.dt.strftime("%H:%M:%S").ne("09:30:00").any()
            or (pd.to_numeric(dataframe["Quantity"]) < 0).any()
            or dataframe[["ConstituentSymbol", "CashSubstitutionFlag", "Exchange"]]
            .astype(str).apply(lambda column: column.str.strip().eq("")).any().any()
            or metadata.get("source_time_field") != "Date"
            or metadata.get("availability_time_field") != "AvailableDate"
            or metadata.get("source_calendar") != "SZSE"
            or metadata.get("available_at")
            != "conservative next SZSE trading session 09:30 Asia/Shanghai"
            or metadata.get("availability_basis") != "CONSERVATIVE_NEXT_SESSION"
            or metadata.get("source_disclosure_schedule")
            != "trade-date premarket; exact timestamp unavailable"
            or metadata.get("source_publication_timestamp_verified") is not False
            or metadata.get("historical_revision_history_verified") is not False
        ):
            raise DataContractError("ETF creation/redemption basket contract differs")
        official_claim = metadata.get("official_pcf_code_quantity_verified")
        if official_claim is not None and (
            official_claim is not True
            or request.symbol != "159326.SZ"
            or request.start != request.end
            or metadata.get("official_pcf_source") != "ChinaAMC historical PCF XML"
            or metadata.get("official_pcf_file_name")
            != f"pcf_159326_{request.start.replace('-', '')}.xml"
            or not isinstance(metadata.get("official_pcf_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", metadata["official_pcf_sha256"]) is None
            or metadata.get("official_pcf_component_count") != len(dataframe)
            or metadata.get("official_pcf_publication_timestamp_verified") is not False
            or metadata.get("official_pcf_historical_revisions_verified") is not False
        ):
            raise DataContractError("official PCF component verification claim differs")
    if dataset == Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value:
        if set(dataframe.columns) != {"Date", "Close"} or metadata.get("price_scope") != "CLOSE_ONLY":
            raise DataContractError("domestic index close-only contract differs")
        dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        if dates.isna().any() or dates.duplicated().any() or dataframe["Close"].le(0).any():
            raise DataContractError("domestic index close-only dates or prices are invalid")
    if dataset == Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value:
        if (
            set(dataframe.columns) != {"Date", "Close", "Volume", "Amount"}
            or metadata.get("price_scope") != "CLOSE_AND_INDEX_TURNOVER"
            or metadata.get("volume_unit") != "hand"
            or metadata.get("amount_unit") != "thousand_cny"
            or metadata.get("frequency") != "daily"
            or metadata.get("available_at") != "current session after market close"
            or metadata.get("vendor_update_window")
            != "trading day 15:00-17:00 Asia/Shanghai"
            or metadata.get("source_publication_timestamp_verified") is not False
            or metadata.get("historical_revision_history_verified") is not False
        ):
            raise DataContractError("domestic index close-turnover contract differs")
        dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        if (
            dates.isna().any() or dates.duplicated().any()
            or dataframe["Close"].le(0).any()
            or dataframe[["Volume", "Amount"]].lt(0).any().any()
        ):
            raise DataContractError("domestic index close-turnover values are invalid")
    if dataset == Dataset.US_CPI_RELEASE.value:
        if (
            metadata.get("source_time_field") != "ReleaseAt"
            or metadata.get("source_calendar") != "US_BLS_EASTERN"
            or metadata.get("available_at")
            != "first SSE open day strictly after Shanghai release date"
        ):
            raise DataContractError("US CPI release lineage contract is incomplete")
        release_at = dataframe["ReleaseAt"]
        if (
            not isinstance(release_at.dtype, pd.DatetimeTZDtype)
            or str(release_at.dt.tz) != "Asia/Shanghai"
        ):
            raise DataContractError("US CPI release time must use Asia/Shanghai timezone")
        dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        available = pd.to_datetime(dataframe["AvailableDate"], errors="coerce")
        eastern = release_at.dt.tz_convert("America/New_York")
        invalid = (
            dates.isna()
            | available.isna()
            | dates.ne(release_at.dt.tz_localize(None).dt.normalize())
            | available.le(dates)
            | eastern.dt.strftime("%H:%M").ne("08:30")
            | eastern.dt.date.ne(release_at.dt.date)
        )
        if invalid.any():
            raise DataContractError("US CPI release timing is causally invalid")
    if dataset in {
        Dataset.US_ISM_PMI_RELEASE.value,
        Dataset.US_FEDERAL_BUDGET_RELEASE.value,
    }:
        if (
            metadata.get("source_time_field") != "Date"
            or metadata.get("source_calendar") != "TUSHARE_ECO_CAL_DATE"
            or metadata.get("available_at")
            != "first SSE open day strictly after source calendar date"
        ):
            raise DataContractError("US monthly release lineage contract is incomplete")
        dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        available = pd.to_datetime(dataframe["AvailableDate"], errors="coerce")
        if dates.isna().any() or available.isna().any() or available.le(dates).any():
            raise DataContractError("US monthly release timing is causally invalid")
    if dataset == Dataset.US_POLICY_UNCERTAINTY_DAILY.value:
        if (
            metadata.get("series_id") != "USEPUINDXD"
            or metadata.get("vintage_mode") != "INITIAL_RELEASE_ONLY"
            or metadata.get("fred_output_type") != 4
            or metadata.get("source_time_field") != "Date"
            or metadata.get("availability_time_field") != "AvailableDate"
            or metadata.get("source_calendar") != "FRED_CALENDAR_DAY"
            or metadata.get("available_at") != "initial release date reported by ALFRED"
        ):
            raise DataContractError("FRED policy-uncertainty lineage contract is incomplete")
        dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        available = pd.to_datetime(dataframe["AvailableDate"], errors="coerce")
        values = pd.to_numeric(dataframe["PolicyUncertaintyIndex"], errors="coerce")
        invalid = dates.isna() | available.isna() | available.lt(dates) | values.le(0)
        if invalid.any():
            raise DataContractError(
                "FRED policy-uncertainty observations are causally invalid",
                invalid_rows=int(invalid.sum()),
            )
    if dataset == Dataset.SELL_SIDE_FORECAST.value:
        if (
            metadata.get("vendor_interface") != "report_rc"
            or metadata.get("source_time_field") != "Date"
            or metadata.get("availability_time_field") != "AvailableDate"
            or metadata.get("source_calendar") != "SSE"
            or metadata.get("available_at")
            != "first SSE open day strictly after report date and vendor create date"
            or metadata.get("point_in_time_mode") != "CURRENT_VENDOR_SNAPSHOT"
            or metadata.get("historical_revision_identity") != "unavailable_from_vendor"
        ):
            raise DataContractError("sell-side forecast lineage contract is incomplete")
        dates = pd.to_datetime(dataframe["Date"], errors="coerce")
        available = pd.to_datetime(dataframe["AvailableDate"], errors="coerce")
        vendor_created = pd.to_datetime(dataframe["VendorCreatedAt"], errors="coerce")
        symbols = dataframe["Symbol"].astype("string")
        availability_anchor = pd.concat(
            [dates, vendor_created.dt.normalize()], axis=1
        ).max(axis=1)
        if (
            dates.isna().any()
            or available.isna().any()
            or vendor_created.isna().any()
            or available.le(availability_anchor).any()
            or request.symbol is None
            or symbols.isna().any()
            or not symbols.eq(request.symbol).all()
        ):
            raise DataContractError("sell-side forecast identity or timing is invalid")
        forecast_fields = (
            "OperatingRevenueForecast",
            "OperatingProfitForecast",
            "TotalProfitForecast",
            "NetProfitForecast",
            "EarningsPerShareForecast",
            "PriceEarningsRatio",
            "DividendYieldPercent",
            "ReturnOnEquityPercent",
            "EnterpriseValueToEbitda",
            "TargetPriceMax",
            "TargetPriceMin",
        )
        for field in forecast_fields:
            if field not in dataframe.columns:
                raise DataContractError(
                    "sell-side forecast field is missing", field=field
                )
            numeric = pd.to_numeric(dataframe[field], errors="coerce")
            present = dataframe[field].notna()
            if (present & numeric.isna()).any() or np.isinf(
                numeric.dropna().to_numpy(dtype=float)
            ).any():
                raise DataContractError(
                    "sell-side forecast field contains invalid values", field=field
                )
    if dataset in {Dataset.SGE_GOLD_DAILY.value, Dataset.DOMESTIC_INDEX_DAILY.value}:
        open_values = pd.to_numeric(dataframe["Open"])
        high_values = pd.to_numeric(dataframe["High"])
        low_values = pd.to_numeric(dataframe["Low"])
        close_values = pd.to_numeric(dataframe["Close"])
        volume_values = pd.to_numeric(dataframe["Volume"])
        amount_values = pd.to_numeric(dataframe["Amount"])
        price_tolerance = 0.011 if dataset == Dataset.SGE_GOLD_DAILY.value else 0.0
        invalid = (
            (low_values <= 0)
            | (high_values + price_tolerance < open_values)
            | (high_values + price_tolerance < close_values)
            | (low_values - price_tolerance > open_values)
            | (low_values - price_tolerance > close_values)
            | (volume_values < 0)
            | (amount_values < 0)
        )
        if invalid.any():
            raise DataContractError(
                "provider output contains invalid daily price bars",
                dataset=dataset,
                invalid_rows=int(invalid.sum()),
            )
    if dataset == Dataset.FUTURES_SHFE_GOLD_DAILY.value:
        close_values = pd.to_numeric(dataframe["Close"])
        settle_values = pd.to_numeric(dataframe["Settle"])
        volume_values = pd.to_numeric(dataframe["Volume"])
        amount_values = pd.to_numeric(dataframe["Amount"])
        interest_values = pd.to_numeric(dataframe["OpenInterest"])
        maturity = pd.to_datetime(dataframe["MaturityDate"], errors="coerce")
        source_date = pd.to_datetime(dataframe["Date"], errors="coerce")
        invalid = (
            (close_values <= 0)
            | (settle_values <= 0)
            | (volume_values < 0)
            | (amount_values < 0)
            | (interest_values < 0)
            | maturity.isna()
            | source_date.isna()
            | (maturity < source_date)
        )
        if invalid.any():
            raise DataContractError(
                "provider output contains invalid SHFE gold futures bars",
                invalid_rows=int(invalid.sum()),
            )
    if dataset == Dataset.FUTURES_SHFE_GOLD_MAPPING.value:
        if (
            dataframe["ContinuousSymbol"].astype(str).str.strip().eq("").any()
            or dataframe["Contract"].astype(str).str.strip().eq("").any()
        ):
            raise DataContractError("futures mapping contains an empty symbol")
    if dataset == Dataset.FUTURES_SHFE_GOLD_HOLDING.value:
        numeric_columns = (
            "Volume",
            "VolumeChange",
            "LongHolding",
            "LongChange",
            "ShortHolding",
            "ShortChange",
        )
        numeric = dataframe.loc[:, numeric_columns].apply(pd.to_numeric, errors="coerce")
        invalid_text = dataframe["Contract"].astype(str).str.strip().eq("") | dataframe[
            "Broker"
        ].astype(str).str.strip().eq("")
        missing_all_rankings = numeric[["Volume", "LongHolding", "ShortHolding"]].isna().all(axis=1)
        negative_rankings = (numeric[["Volume", "LongHolding", "ShortHolding"]] < 0).any(axis=1)
        invalid_numeric = pd.Series(False, index=dataframe.index)
        for column in numeric_columns:
            original_present = dataframe[column].notna()
            invalid_numeric |= original_present & numeric[column].isna()
        invalid = invalid_text | missing_all_rankings | negative_rankings | invalid_numeric
        if invalid.any():
            raise DataContractError(
                "provider output contains invalid SHFE gold holding rankings",
                invalid_rows=int(invalid.sum()),
            )
    if dataset == Dataset.VIX_DAILY.value:
        open_values = pd.to_numeric(dataframe["Open"])
        high_values = pd.to_numeric(dataframe["High"])
        low_values = pd.to_numeric(dataframe["Low"])
        close_values = pd.to_numeric(dataframe["Close"])
        # The official VIX close is a separate calculation and can fall just outside
        # the intraday high-low range; only the traded open must remain inside it.
        invalid = (
            (low_values <= 0)
            | (close_values <= 0)
            | (high_values < open_values)
            | (low_values > open_values)
        )
        if invalid.any():
            raise DataContractError(
                "provider output contains invalid VIX price bars",
                invalid_rows=int(invalid.sum()),
            )
    if dataset in {Dataset.USDCNH_DAILY.value, Dataset.FXCM_DAILY.value}:
        if (
            "AvailableDate" not in dataframe.columns
            or metadata.get("availability_time_field") != "AvailableDate"
            or metadata.get("availability_timezone") != "Asia/Shanghai"
            or metadata.get("available_at") != FXCM_AVAILABILITY_RULE
        ):
            raise DataContractError("FXCM daily publication requires conservative availability timestamps")
        available = pd.to_datetime(dataframe["AvailableDate"], errors="coerce")
        expected = pd.to_datetime(dataframe["Date"]).dt.normalize() + pd.Timedelta(days=2, hours=8)
        if not available.equals(expected):
            raise DataContractError("FXCM daily availability differs from the conservative session policy")
        bid_close = pd.to_numeric(dataframe["BidClose"])
        ask_close = pd.to_numeric(dataframe["AskClose"])
        if (bid_close <= 0).any() or (ask_close <= 0).any() or (bid_close > ask_close).any():
            raise DataContractError("provider output contains invalid FXCM quotes")
    if dataset == Dataset.TRADING_CALENDAR.value:
        flags = pd.to_numeric(dataframe["IsOpen"], errors="coerce")
        if not flags.isin([0, 1]).all():
            raise DataContractError("trading calendar contains invalid open flags")
        observed_dates = pd.DatetimeIndex(
            pd.to_datetime(dataframe["Date"], errors="coerce").dt.normalize()
        )
        expected_dates = pd.date_range(
            pd.Timestamp(request.start).normalize(),
            pd.Timestamp(request.end).normalize(),
            freq="D",
        )
        if not observed_dates.equals(expected_dates):
            raise DataContractError(
                "trading calendar does not cover every requested calendar date",
                missing_dates=[
                    item.date().isoformat() for item in expected_dates.difference(observed_dates)
                ],
                unexpected_dates=[
                    item.date().isoformat() for item in observed_dates.difference(expected_dates)
                ],
            )


def _date_bounds(
    dataframe: pd.DataFrame,
    request: DataRequest,
    metadata: Mapping[str, Any],
) -> tuple[str, str]:
    if "Date" not in dataframe.columns:
        raise DataContractError("published dataframe is missing Date column")
    timestamps = pd.to_datetime(dataframe["Date"], errors="coerce")
    if timestamps.isna().any():
        raise DataContractError("published dataframe contains invalid Date values")
    primary_key = list(metadata.get("primary_key", ["Date"]))
    missing_key = sorted(set(primary_key).difference(dataframe.columns))
    if missing_key:
        raise DataContractError(
            "published dataframe is missing primary-key columns",
            missing_fields=missing_key,
        )
    if dataframe.duplicated(primary_key).any():
        raise DataContractError(
            "published dataframe contains duplicate primary keys",
            primary_key=primary_key,
        )
    if not timestamps.is_monotonic_increasing:
        raise DataContractError("published dataframe must be ordered by Date")

    requested_start = pd.Timestamp(request.start)
    requested_end = pd.Timestamp(request.end)
    if " " not in request.end and "T" not in request.end:
        requested_end += pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
    actual_start = timestamps.iloc[0]
    actual_end = timestamps.iloc[-1]
    if actual_start < requested_start or actual_end > requested_end:
        raise DataContractError(
            "published dataframe exceeds the requested time boundary",
            requested_start=str(requested_start),
            requested_end=str(requested_end),
            actual_start=str(actual_start),
            actual_end=str(actual_end),
        )
    maximum_start_lag_days = (
        request.coverage.maximum_start_lag_days
        if request.coverage is not None and request.coverage.maximum_start_lag_days is not None
        else metadata.get("maximum_start_lag_days")
    )
    if maximum_start_lag_days is not None:
        try:
            maximum_start_lag_days = int(maximum_start_lag_days)
        except (TypeError, ValueError) as exc:
            raise DataContractError(
                "provider maximum start lag must be an integer",
                maximum_start_lag_days=maximum_start_lag_days,
            ) from exc
        if maximum_start_lag_days < 0:
            raise DataContractError(
                "provider maximum start lag must not be negative",
                maximum_start_lag_days=maximum_start_lag_days,
            )
        latest_acceptable_start = requested_start.normalize() + pd.Timedelta(
            days=maximum_start_lag_days
        )
        if actual_start.normalize() > latest_acceptable_start:
            raise IncompleteDataError(
                "published dataframe does not cover the requested history start",
                requested_start=str(requested_start),
                actual_start=str(actual_start),
                maximum_start_lag_days=maximum_start_lag_days,
            )
    if request.required_cutoff is not None:
        required_cutoff = pd.Timestamp(request.required_cutoff)
        if " " not in request.required_cutoff and "T" not in request.required_cutoff:
            actual_comparable = actual_end.normalize()
            required_comparable = required_cutoff.normalize()
        else:
            actual_comparable = actual_end
            required_comparable = required_cutoff
        if actual_comparable < required_comparable:
            raise IncompleteDataError(
                "published dataframe does not reach the required cutoff",
                required_cutoff=str(required_cutoff),
                actual_cutoff=str(actual_end),
            )
    return actual_start.isoformat(), actual_end.isoformat()


def _json_contract(value: Any) -> Any:
    if is_dataclass(value):
        return {item.name: _json_contract(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _json_contract(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_contract(item) for item in value]
    if isinstance(value, Path):
        return str(value.resolve())
    return value


def _request_record(request: DataRequest) -> dict[str, Any]:
    return _json_contract(request)


def _selection(record: Mapping[str, Any]) -> dict[str, Any]:
    return {key: record[key] for key in ("dataset", "symbol", "frequency", "parameters")}


def _selection_contains(stored: Mapping[str, Any], requested: Mapping[str, Any]) -> bool:
    left, right = _selection(stored), _selection(requested)
    if left["dataset"] == Dataset.STOCK_MONEYFLOW and "trading_dates" in left["parameters"]:
        if "trading_dates" not in right["parameters"]:
            return False
        if not set(right["parameters"]["trading_dates"]).issubset(left["parameters"]["trading_dates"]):
            return False
        left = {**left, "parameters": {}}
        right = {**right, "parameters": {}}
    return left == right


def _end_timestamp(value: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    return (timestamp + pd.Timedelta(days=1) - pd.Timedelta(nanoseconds=1)
            if " " not in value and "T" not in value else timestamp)


def _validate_coverage(frame: pd.DataFrame, request: DataRequest) -> None:
    coverage = request.coverage
    if coverage is None:
        return
    if coverage.observations_through is not None:
        frame = frame.loc[
            pd.to_datetime(frame["Date"], errors="raise")
            <= _end_timestamp(coverage.observations_through)
        ]
    if len(frame) < coverage.minimum_observations:
        raise IncompleteDataError(
            "published dataframe has fewer observations than required",
            minimum_observations=coverage.minimum_observations, actual_observations=len(frame),
            observations_through=coverage.observations_through,
        )
    sessions = pd.to_datetime(frame["Date"], errors="raise").dt.normalize().nunique()
    if sessions < coverage.minimum_sessions:
        raise IncompleteDataError(
            "published dataframe has fewer sessions than required",
            minimum_sessions=coverage.minimum_sessions, actual_sessions=int(sessions),
            observations_through=coverage.observations_through,
        )


def _implementation_revision() -> str:
    """Invalidate REUSE when adapter, validation or repair implementation changes."""
    digest = hashlib.sha256()
    root = Path(__file__).parent
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()


class Dataflows:
    """Prepare managed data assets, then read explicitly bound preparations."""

    def __init__(
        self, *, base_dir: Path, space: DataSpace, providers: ProviderConfig,
    ) -> None:
        if not isinstance(providers, ProviderConfig):
            raise TypeError("providers must be ProviderConfig")
        self._store = AssetStore(base_dir, space)
        self._revision = _implementation_revision()
        if providers.bindings is None:
            self._providers = {
                str(dataset): ProviderBinding(str(dataset), self._revision, provider)
                for dataset, provider in _default_providers(providers.env_file).items()
            }
        else:
            self._providers = {str(dataset): binding for dataset, binding in providers.bindings.items()}

    @property
    def datasets(self) -> tuple[str, ...]:
        """Return the registered dataset names in stable lexical order."""

        return tuple(sorted(self._providers))

    def prepare(
        self, requests: tuple[DataRequest, ...], *, policy: PreparePolicy,
    ) -> PrepareResult:
        if not isinstance(requests, tuple) or not requests or not all(
            isinstance(request, DataRequest) for request in requests
        ):
            raise TypeError("requests must be a non-empty tuple of DataRequest")
        if not isinstance(policy, PreparePolicy):
            raise TypeError("policy must be PreparePolicy")
        items = []
        entries = []
        reference = None
        acquired: dict[str, tuple[str | None, DataResult]] = {}
        planned = []
        requirements: dict[str, list[DataRequest]] = {}
        for request in requests:
            binding = self._providers.get(str(request.dataset))
            record = _request_record(request)
            selector = {key: value for key, value in record.items()
                        if key not in {"coverage", "required_cutoff"}}
            key = hashlib.sha256(json.dumps({
                "request": selector,
                "provider": binding.name if binding else None,
                "provider_revision": binding.revision if binding else None,
                "dfls_revision": self._revision,
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            planned.append((request, binding, record, key))
            requirements.setdefault(key, []).append(request)
        try:
            with self._store.transaction() as connection:
                for request, binding, record, key in planned:
                    asset_id = None
                    if binding is None:
                        result = self._failure(DataStatus.FAILED, "UNSUPPORTED_DATASET",
                                               "no provider configured for dataset", request)
                    else:
                        if key in acquired:
                            asset_id, previous = acquired[key]
                            result = self._checked_result(previous, request) if previous.ready else previous
                        elif policy is PreparePolicy.REUSE:
                            asset_id = self._store.lookup_asset(connection, key)
                        if key not in acquired and asset_id is None:
                            # Fetch one asset independently of the consumer's acceptance thresholds.
                            result = self._fetch_source(replace(request, required_cutoff=None, coverage=None))
                            if result.ready and any(self._checked_result(result, requirement).ready
                                                    for requirement in requirements[key]):
                                asset_id = self._store.put_asset(
                                    connection, key=key, dataframe=result.dataframe,
                                    identity=result.identity, warnings=result.warnings,
                                )
                            acquired[key] = (asset_id, result)
                            result = self._checked_result(result, request) if result.ready else result
                        elif key not in acquired:
                            stored_result = self._store.read_asset(connection, asset_id)
                            result = self._checked_result(
                                stored_result, request,
                            )
                            # A previously complete but now insufficient source may have advanced.
                            if any(self._checked_result(stored_result, requirement).status
                                   is DataStatus.INCOMPLETE for requirement in requirements[key]):
                                stored_result = self._fetch_source(
                                    replace(request, required_cutoff=None, coverage=None)
                                )
                                if stored_result.ready and any(
                                    self._checked_result(stored_result, requirement).ready
                                    for requirement in requirements[key]
                                ):
                                    asset_id = self._store.put_asset(
                                        connection, key=key, dataframe=stored_result.dataframe,
                                        identity=stored_result.identity, warnings=stored_result.warnings,
                                    )
                                result = (self._checked_result(stored_result, request)
                                          if stored_result.ready else stored_result)
                            acquired[key] = (asset_id, stored_result)
                    items.append(ItemPrepareResult(
                        request=request, status=result.status,
                        identity=result.identity, error=result.error,
                    ))
                    if result.ready:
                        entries.append({"request": record, "asset_id": asset_id})
                if all(item.status is DataStatus.READY for item in items):
                    self._assert_consistent(connection, entries)
                    reference = self._store.publish(connection, entries)
        except StoreError as exc:
            items = [ItemPrepareResult(
                request=request, status=DataStatus.FAILED, identity=None,
                error=DataError(exc.code, str(exc)),
            ) for request in requests]
            reference = None
        status = (PrepareStatus.READY if reference is not None else
                  PrepareStatus.PARTIAL if any(item.status is DataStatus.READY for item in items)
                  else PrepareStatus.FAILED)
        return PrepareResult(status=status, items=tuple(items), reference=reference)

    def _assert_consistent(self, connection, entries: list[dict]) -> None:
        """A READY preparation must not contain conflicting views of the same series."""
        seen: dict[str, list[DataResult]] = {}
        visited = set()
        for entry in entries:
            if entry["asset_id"] in visited:
                continue
            visited.add(entry["asset_id"])
            selection = _selection(entry["request"])
            moneyflow = selection["dataset"] == Dataset.STOCK_MONEYFLOW
            if moneyflow:
                selection = {**selection, "parameters": {}}
            key = json.dumps(selection, sort_keys=True)
            current = self._store.read_asset(connection, entry["asset_id"])
            for previous in seen.get(key, []):
                if ((pd.Timestamp(previous.identity.data_start).tzinfo is None)
                        != (pd.Timestamp(current.identity.data_start).tzinfo is None)):
                    raise StoreError("INCONSISTENT_PREPARATION", "overlapping series use incompatible timezones")
                start = max(pd.Timestamp(previous.identity.data_start), pd.Timestamp(current.identity.data_start))
                end = min(pd.Timestamp(previous.identity.data_cutoff), pd.Timestamp(current.identity.data_cutoff))
                if start > end:
                    continue
                hashes = []
                common_dates = (set(pd.to_datetime(previous.dataframe["Date"]))
                                & set(pd.to_datetime(current.dataframe["Date"])))
                for result in (previous, current):
                    dates = pd.to_datetime(result.dataframe["Date"])
                    selected = dates.between(start, end)
                    if moneyflow:
                        selected &= dates.isin(common_dates)
                    overlap = result.dataframe.loc[selected].reset_index(drop=True)
                    hashes.append(canonical_frame_sha256(overlap))
                if hashes[0] != hashes[1]:
                    raise StoreError("INCONSISTENT_PREPARATION", "overlapping source data disagree")
            seen.setdefault(key, []).append(current)

    def fetch(self, request: DataRequest, *, prepared: PreparedDataRef) -> DataResult:
        if not isinstance(request, DataRequest):
            raise TypeError("request must be DataRequest")
        if not isinstance(prepared, PreparedDataRef):
            raise TypeError("prepared must be PreparedDataRef")
        try:
            entries = self._store.load_preparation(prepared)
            record = _request_record(request)
            matching = [entry for entry in entries
                        if _selection_contains(entry["request"], record)
                        and pd.Timestamp(entry["request"]["start"]) <= pd.Timestamp(request.start)
                        and _end_timestamp(entry["request"]["end"]) >= _end_timestamp(request.end)]
            if not matching:
                return self._failure(DataStatus.FAILED, "REQUEST_NOT_PREPARED",
                                     "request is outside this preparation", request)
            results = []
            for asset_id in sorted({entry["asset_id"] for entry in matching}):
                stored = self._store.read(asset_id)
                dates = pd.to_datetime(stored.dataframe["Date"], errors="raise")
                selected = dates.between(pd.Timestamp(request.start), _end_timestamp(request.end))
                if isinstance(request.parameters, MoneyflowParameters):
                    selected &= dates.dt.strftime("%Y-%m-%d").isin(request.parameters.trading_dates)
                frame = stored.dataframe.loc[selected].copy().reset_index(drop=True)
                if frame.empty:
                    return self._failure(DataStatus.EMPTY, "EMPTY_DATA",
                                         "prepared asset has no observations in this range", request)
                identity = replace(stored.identity, content_sha256=canonical_frame_sha256(frame))
                result = self._checked_result(
                    DataResult(DataStatus.READY, frame, identity, warnings=stored.warnings), request,
                )
                if not result.ready:
                    return result
                results.append(result)
            if len({result.identity.content_sha256 for result in results}) != 1:
                return self._failure(DataStatus.FAILED, "AMBIGUOUS_PREPARED_DATA",
                                     "overlapping prepared assets disagree", request)
            result = results[0]
            return replace(result, prepared=prepared)
        except StoreError as exc:
            return self._failure(DataStatus.FAILED, exc.code, str(exc), request)
        except (TypeError, ValueError, KeyError) as exc:
            return self._failure(DataStatus.FAILED, "PREPARED_DATA_INVALID", str(exc), request)

    def _checked_result(self, result: DataResult, request: DataRequest, *, complete_sessions: bool = True) -> DataResult:
        try:
            if result.identity.dataset != str(request.dataset) or result.identity.symbol != request.symbol:
                raise DataContractError("prepared asset identity differs from request")
            if canonical_frame_sha256(result.dataframe) != result.identity.content_sha256:
                raise DataContractError("prepared asset content hash differs")
            _validate_coverage(result.dataframe, request)
            _validate_provider_output(result.dataframe, request, result.identity.metadata,
                                      complete_sessions=complete_sessions)
            start, end = _date_bounds(result.dataframe, request, result.identity.metadata)
            return replace(result, identity=replace(result.identity, data_start=start, data_cutoff=end))
        except IncompleteDataError as exc:
            return self._expected_failure(DataStatus.INCOMPLETE, exc, request)
        except DataflowError as exc:
            return self._expected_failure(DataStatus.FAILED, exc, request)

        except (TypeError, ValueError, KeyError) as exc:
            return self._failure(DataStatus.FAILED, "DATA_CONTRACT_INVALID", str(exc), request)

    def _fetch_source(self, request: DataRequest) -> DataResult:
        provider = self._providers.get(str(request.dataset))
        if provider is None:
            return self._failure(
                DataStatus.FAILED,
                "UNSUPPORTED_DATASET",
                f"unsupported dataset: {request.dataset}",
                request,
            )
        try:
            dataframe, metadata = provider.fetch(request)
            if dataframe is None or dataframe.empty:
                raise EmptyDataError("provider returned no rows")
            frame = dataframe.copy().reset_index(drop=True)
            _validate_coverage(frame, request)
            metadata = _lineage_metadata(request, frame, metadata)
            metadata.update(provider_binding=provider.name, provider_revision=provider.revision,
                            dfls_revision=self._revision)
            _validate_provider_output(frame, request, metadata)
            data_start, data_cutoff = _date_bounds(frame, request, metadata)
            source = str(metadata.get("vendor", "unknown"))
            identity = DataIdentity(
                dataset=str(request.dataset),
                source=source,
                symbol=request.symbol,
                data_start=data_start,
                data_cutoff=data_cutoff,
                content_sha256=canonical_frame_sha256(frame),
                metadata=metadata,
            )
            return DataResult(DataStatus.READY, frame, identity)
        except SourceNotReadyError as exc:
            return self._expected_failure(DataStatus.WAITING_SOURCE, exc, request)
        except EmptyDataError as exc:
            return self._expected_failure(DataStatus.EMPTY, exc, request)
        except IncompleteDataError as exc:
            return self._expected_failure(DataStatus.INCOMPLETE, exc, request)
        except DataflowError as exc:
            return self._expected_failure(DataStatus.FAILED, exc, request)
        except Exception as exc:  # vendor SDK failures cross this boundary as structured errors
            return self._failure(
                DataStatus.FAILED,
                "PROVIDER_EXCEPTION",
                str(exc),
                request,
                exception_type=type(exc).__name__,
            )

    @staticmethod
    def _expected_failure(
        status: DataStatus, exc: DataflowError, request: DataRequest
    ) -> DataResult:
        return Dataflows._failure(
            status,
            exc.code,
            str(exc),
            request,
            retryable=exc.retryable,
            **exc.context,
        )

    @staticmethod
    def _failure(
        status: DataStatus,
        code: str,
        message: str,
        request: DataRequest,
        *,
        retryable: bool = False,
        **context: Any,
    ) -> DataResult:
        details = {
            "dataset": str(request.dataset),
            "symbol": request.symbol,
            "start": request.start,
            "end": request.end,
            **context,
        }
        return DataResult(
            status=status,
            error=DataError(code, message, retryable=retryable, context=details),
        )


def _default_providers(env_file: Path | None) -> dict[str, Provider]:
    from .chinaamc_pcf import verify_chinaamc_pcf_components
    from .fred_policy_uncertainty import fetch_us_policy_uncertainty_daily
    from .local_strategy_data import fetch_strategy_feature_evidence
    from .tushare_etf import fetch_etf_ohlcv, fetch_etf_unadjusted_daily
    from .tushare_pcf import fetch_etf_creation_redemption_basket
    from .tushare_futures import (
        fetch_shfe_gold_daily,
        fetch_shfe_gold_holding,
        fetch_shfe_gold_mapping,
    )
    from .tushare_strategy_data import (
        fetch_cn_cpi_monthly,
        fetch_us_federal_budget_release,
        fetch_us_ism_pmi_release,
        fetch_us_nominal_yield_daily,
        fetch_us_cpi_release,
        fetch_cn_money_monthly,
        fetch_cn_ppi_monthly,
        fetch_domestic_index_daily,
        fetch_domestic_index_close_daily,
        fetch_domestic_index_close_turnover_daily,
        fetch_etf_share_size,
        fetch_fxcm_daily,
        fetch_global_index_daily,
        fetch_index_constituent_weight,
        fetch_index_daily_basic,
        fetch_sge_gold_daily,
        fetch_shibor_daily,
        fetch_stock_moneyflow,
        fetch_stock_moneyflow_sessions,
        fetch_trading_calendar,
        fetch_us_real_yield_daily,
        fetch_usdcnh_daily,
        fetch_vix_daily,
    )
    from .tushare_stock import fetch_stock_ohlcv, fetch_stock_unadjusted_daily
    from .tushare_sell_side import fetch_sell_side_forecast

    def etf_ohlcv(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_etf_ohlcv(
            _required_symbol(request),
            request.start,
            request.end,
            request.frequency,
            env_file=env_file,
        )

    def etf_unadjusted(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_etf_unadjusted_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def etf_unadjusted_intraday(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        from .tushare_etf import fetch_etf_unadjusted_intraday

        return fetch_etf_unadjusted_intraday(
            _required_symbol(request), request.start, request.end,
            request.frequency, env_file=env_file,
        )

    def etf_creation_redemption_basket(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        if request.frequency != "daily":
            raise DataContractError("ETF creation/redemption basket requires daily frequency")
        verify = (request.parameters.verify_official_pcf_components
                  if isinstance(request.parameters, PcfParameters) else False)
        if type(verify) is not bool:
            raise DataContractError("verify_official_pcf_components must be a boolean")
        if verify and (request.symbol != "159326.SZ" or request.start != request.end):
            raise DataContractError("official PCF check requires one 159326.SZ trade date")
        frame, metadata = fetch_etf_creation_redemption_basket(
            _required_symbol(request), request.start, request.end,
            env_file=env_file,
        )
        if verify:
            metadata.update(verify_chinaamc_pcf_components(
                request.symbol, request.start, frame,
            ))
        return frame, metadata

    def stock_ohlcv(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_stock_ohlcv(
            _required_symbol(request),
            request.start,
            request.end,
            request.frequency,
            env_file=env_file,
        )

    def stock_unadjusted(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_stock_unadjusted_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def stock_unadjusted_intraday(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        from .tushare_stock import fetch_stock_unadjusted_intraday

        return fetch_stock_unadjusted_intraday(
            _required_symbol(request), request.start, request.end,
            request.frequency, env_file=env_file,
        )

    def shibor(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shibor_daily(request.start, request.end, env_file=env_file)

    def us_real_yield(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_real_yield_daily(request.start, request.end, env_file=env_file)

    def us_nominal_yield(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_nominal_yield_daily(request.start, request.end, env_file=env_file)

    def us_policy_uncertainty(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_policy_uncertainty_daily(
            request.start,
            request.end,
            env_file=env_file,
        )

    def usdcnh(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_usdcnh_daily(request.start, request.end, env_file=env_file)

    def fxcm(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_fxcm_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def sge_gold(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_sge_gold_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def domestic_index(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_domestic_index_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def domestic_index_close(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_domestic_index_close_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def domestic_index_close_turnover(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_domestic_index_close_turnover_daily(
            _required_symbol(request), request.start, request.end,
            env_file=env_file,
        )

    def shfe_gold_daily(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shfe_gold_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def shfe_gold_mapping(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shfe_gold_mapping(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def shfe_gold_holding(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shfe_gold_holding(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def cn_cpi(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_cn_cpi_monthly(request.start, request.end, env_file=env_file)

    def us_cpi_release(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_cpi_release(request.start, request.end, env_file=env_file)

    def us_ism_pmi_release(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_ism_pmi_release(request.start, request.end, env_file=env_file)

    def us_federal_budget_release(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_federal_budget_release(
            request.start, request.end, env_file=env_file
        )

    def cn_ppi(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_cn_ppi_monthly(request.start, request.end, env_file=env_file)

    def cn_money(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_cn_money_monthly(request.start, request.end, env_file=env_file)

    def index_basic(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_index_daily_basic(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def etf_shares(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_etf_share_size(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def global_index(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_global_index_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def vix(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_vix_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def index_weights(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_index_constituent_weight(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def stock_moneyflow(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        trading_dates = (request.parameters.trading_dates
                         if isinstance(request.parameters, MoneyflowParameters) else None)
        if trading_dates is not None:
            if request.symbol is not None:
                raise DataContractError(
                    "explicit-session stock moneyflow requests must be all-market"
                )
            if not isinstance(trading_dates, list | tuple):
                raise DataContractError("trading_dates must be a list or tuple")
            return fetch_stock_moneyflow_sessions(
                tuple(str(item) for item in trading_dates),
                env_file=env_file,
            )
        return fetch_stock_moneyflow(
            request.start,
            request.end,
            symbol=request.symbol,
            env_file=env_file,
        )

    def sell_side_forecast(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_sell_side_forecast(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    def trading_calendar(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_trading_calendar(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=env_file,
        )

    return {
        Dataset.ETF_OHLCV.value: etf_ohlcv,
        Dataset.ETF_UNADJUSTED_DAILY.value: etf_unadjusted,
        Dataset.ETF_UNADJUSTED_INTRADAY.value: etf_unadjusted_intraday,
        Dataset.STOCK_UNADJUSTED_INTRADAY.value: stock_unadjusted_intraday,
        Dataset.ETF_CREATION_REDEMPTION_BASKET.value: etf_creation_redemption_basket,
        Dataset.STOCK_OHLCV.value: stock_ohlcv,
        Dataset.STOCK_UNADJUSTED_DAILY.value: stock_unadjusted,
        Dataset.SHIBOR_DAILY.value: shibor,
        Dataset.US_REAL_YIELD_DAILY.value: us_real_yield,
        Dataset.US_NOMINAL_YIELD_DAILY.value: us_nominal_yield,
        Dataset.US_POLICY_UNCERTAINTY_DAILY.value: us_policy_uncertainty,
        Dataset.USDCNH_DAILY.value: usdcnh,
        Dataset.FXCM_DAILY.value: fxcm,
        Dataset.SGE_GOLD_DAILY.value: sge_gold,
        Dataset.FUTURES_SHFE_GOLD_DAILY.value: shfe_gold_daily,
        Dataset.FUTURES_SHFE_GOLD_MAPPING.value: shfe_gold_mapping,
        Dataset.FUTURES_SHFE_GOLD_HOLDING.value: shfe_gold_holding,
        Dataset.DOMESTIC_INDEX_DAILY.value: domestic_index,
        Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value: domestic_index_close,
        Dataset.DOMESTIC_INDEX_CLOSE_TURNOVER_DAILY.value: domestic_index_close_turnover,
        Dataset.CN_CPI_MONTHLY.value: cn_cpi,
        Dataset.US_CPI_RELEASE.value: us_cpi_release,
        Dataset.US_ISM_PMI_RELEASE.value: us_ism_pmi_release,
        Dataset.US_FEDERAL_BUDGET_RELEASE.value: us_federal_budget_release,
        Dataset.CN_PPI_MONTHLY.value: cn_ppi,
        Dataset.CN_MONEY_MONTHLY.value: cn_money,
        Dataset.INDEX_DAILY_BASIC.value: index_basic,
        Dataset.ETF_SHARE_SIZE.value: etf_shares,
        Dataset.GLOBAL_INDEX_DAILY.value: global_index,
        Dataset.VIX_DAILY.value: vix,
        Dataset.INDEX_CONSTITUENT_WEIGHT.value: index_weights,
        Dataset.SELL_SIDE_FORECAST.value: sell_side_forecast,
        Dataset.STOCK_MONEYFLOW.value: stock_moneyflow,
        Dataset.TRADING_CALENDAR.value: trading_calendar,
        Dataset.STRATEGY_FEATURE_EVIDENCE.value: fetch_strategy_feature_evidence,
    }


def _required_symbol(request: DataRequest) -> str:
    if request.symbol is None:
        raise DataContractError(f"{request.dataset} requires a symbol")
    return request.symbol
