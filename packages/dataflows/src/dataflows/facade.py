"""Stable DFLS facade over vendor-specific data adapters."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pandas as pd
import numpy as np

from .contract import DataError, DataIdentity, DataRequest, DataResult, Dataset, DataStatus
from .errors import (
    DataContractError,
    DataflowError,
    EmptyDataError,
    IncompleteDataError,
    SourceNotReadyError,
)
from .history_validation import inspect_ohlcv_frame

Provider = Callable[[DataRequest], tuple[pd.DataFrame, Mapping[str, Any]]]


_SOURCE_CALENDAR_BY_DATASET = {
    Dataset.FXCM_DAILY.value: "FXCM_24X5",
    Dataset.USDCNH_DAILY.value: "FXCM_24X5",
    Dataset.US_REAL_YIELD_DAILY.value: "US_GOVERNMENT",
    Dataset.US_NOMINAL_YIELD_DAILY.value: "US_GOVERNMENT",
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
    Dataset.STRATEGY_FEATURE_EVIDENCE.value: "REPOSITORY",
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
        available_at = str(
            result.get("availability_rule") or "SOURCE_PERIOD_CLOSE"
        ).strip()
    if not source_calendar or not available_at:
        raise DataContractError("provider source-time metadata is incomplete")
    result.update(
        source_time_field=source_time_field,
        source_calendar=source_calendar,
        available_at=available_at,
    )
    return result


_OHLCV_DATASETS = {
    Dataset.ETF_OHLCV.value,
    Dataset.ETF_UNADJUSTED_DAILY.value,
    Dataset.STOCK_OHLCV.value,
    Dataset.STOCK_UNADJUSTED_DAILY.value,
}

_DATASET_FIELDS: dict[str, tuple[set[str], set[str]]] = {
    Dataset.SHIBOR_DAILY.value: ({"Date", "OvernightRate"}, {"OvernightRate"}),
    Dataset.US_REAL_YIELD_DAILY.value: (
        {"Date", "RealYield5YPercent", "RealYield10YPercent"},
        {"RealYield5YPercent", "RealYield10YPercent"},
    ),
    Dataset.US_NOMINAL_YIELD_DAILY.value: (
        {"Date", "NominalYield10YPercent"}, {"NominalYield10YPercent"}
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
    Dataset.CN_CPI_MONTHLY.value: (
        {"Date", "NationalYoYPercent", "NationalMoMPercent"},
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
        {"Date", "ProducerYoYPercent", "ProducerMoMPercent"},
        {"ProducerYoYPercent", "ProducerMoMPercent"},
    ),
    Dataset.CN_MONEY_MONTHLY.value: (
        {"Date", "M1YoYPercent", "M2YoYPercent"},
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
    Dataset.STOCK_MONEYFLOW.value: (
        {"Date", "Symbol", "NetMoneyflowAmount"},
        {"NetMoneyflowAmount"},
    ),
    Dataset.TRADING_CALENDAR.value: ({"Date", "IsOpen"}, {"IsOpen"}),
}


def canonical_frame_sha256(dataframe: pd.DataFrame) -> str:
    """Hash dataframe content, column order, dtypes and index deterministically."""

    digest = hashlib.sha256()
    schema = [(str(column), str(dtype)) for column, dtype in dataframe.dtypes.items()]
    digest.update(json.dumps(schema, separators=(",", ":")).encode("utf-8"))
    digest.update(pd.util.hash_pandas_object(dataframe, index=True).values.tobytes())
    return digest.hexdigest()


def _validate_provider_output(
    dataframe: pd.DataFrame,
    request: DataRequest,
    metadata: Mapping[str, Any],
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
            if dataset
            in {Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.STOCK_UNADJUSTED_DAILY.value}
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
        if dataset in {
            Dataset.ETF_UNADJUSTED_DAILY.value,
            Dataset.STOCK_UNADJUSTED_DAILY.value,
        } and metadata.get("adjustment") != "none":
            raise DataContractError(
                "unadjusted dataset provider did not declare adjustment=none",
                dataset=dataset,
            )
        inspect_ohlcv_frame(
            dataframe,
            frequency,
            require_complete_days=frequency in {"1m", "5m", "15m", "30m"},
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
    if dataset == Dataset.US_CPI_RELEASE.value:
        if (
            metadata.get("source_time_field") != "ReleaseAt"
            or metadata.get("source_calendar") != "US_BLS_EASTERN"
            or metadata.get("available_at")
            != "first SSE open day strictly after Shanghai release date"
        ):
            raise DataContractError("US CPI release lineage contract is incomplete")
        release_at = dataframe["ReleaseAt"]
        if not isinstance(release_at.dtype, pd.DatetimeTZDtype) or str(release_at.dt.tz) != "Asia/Shanghai":
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
                    item.date().isoformat()
                    for item in expected_dates.difference(observed_dates)
                ],
                unexpected_dates=[
                    item.date().isoformat()
                    for item in observed_dates.difference(expected_dates)
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
    maximum_start_lag_days = metadata.get("maximum_start_lag_days")
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


class Dataflows:
    """Dataset registry and explicit publication-result boundary for DFLS."""

    def __init__(self, providers: Mapping[str, Provider] | None = None) -> None:
        self._providers = dict(providers) if providers is not None else _default_providers()

    @property
    def datasets(self) -> tuple[str, ...]:
        """Return the registered dataset names in stable lexical order."""

        return tuple(sorted(self._providers))

    def fetch(self, request: DataRequest) -> DataResult:
        provider = self._providers.get(str(request.dataset))
        if provider is None:
            return self._failure(
                DataStatus.FAILED,
                "UNSUPPORTED_DATASET",
                f"unsupported dataset: {request.dataset}",
                request,
            )
        try:
            dataframe, metadata = provider(request)
            if dataframe is None or dataframe.empty:
                raise EmptyDataError("provider returned no rows")
            frame = dataframe.copy()
            metadata = _lineage_metadata(request, frame, metadata)
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


def _default_providers() -> dict[str, Provider]:
    from .local_strategy_data import fetch_strategy_feature_evidence
    from .tushare_etf import fetch_etf_ohlcv, fetch_etf_unadjusted_daily
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

    def etf_ohlcv(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_etf_ohlcv(
            _required_symbol(request),
            request.start,
            request.end,
            request.frequency,
            env_file=_env_file(request),
        )

    def etf_unadjusted(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_etf_unadjusted_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def stock_ohlcv(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_stock_ohlcv(
            _required_symbol(request),
            request.start,
            request.end,
            request.frequency,
            env_file=_env_file(request),
        )

    def stock_unadjusted(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_stock_unadjusted_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def shibor(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shibor_daily(request.start, request.end, env_file=_env_file(request))

    def us_real_yield(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_real_yield_daily(
            request.start, request.end, env_file=_env_file(request)
        )

    def us_nominal_yield(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_nominal_yield_daily(
            request.start, request.end, env_file=_env_file(request)
        )

    def usdcnh(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_usdcnh_daily(request.start, request.end, env_file=_env_file(request))

    def fxcm(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_fxcm_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def sge_gold(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_sge_gold_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def domestic_index(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_domestic_index_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def shfe_gold_daily(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shfe_gold_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def shfe_gold_mapping(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shfe_gold_mapping(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def shfe_gold_holding(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_shfe_gold_holding(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def cn_cpi(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_cn_cpi_monthly(
            request.start, request.end, env_file=_env_file(request)
        )

    def us_cpi_release(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_cpi_release(
            request.start, request.end, env_file=_env_file(request)
        )

    def us_ism_pmi_release(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_ism_pmi_release(
            request.start, request.end, env_file=_env_file(request)
        )

    def us_federal_budget_release(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_us_federal_budget_release(
            request.start, request.end, env_file=_env_file(request)
        )

    def cn_ppi(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_cn_ppi_monthly(
            request.start, request.end, env_file=_env_file(request)
        )

    def cn_money(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_cn_money_monthly(
            request.start, request.end, env_file=_env_file(request)
        )

    def index_basic(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_index_daily_basic(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def etf_shares(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_etf_share_size(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def global_index(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_global_index_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def vix(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_vix_daily(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def index_weights(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_index_constituent_weight(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    def stock_moneyflow(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        trading_dates = request.options.get("trading_dates")
        if trading_dates is not None:
            if request.symbol is not None:
                raise DataContractError(
                    "explicit-session stock moneyflow requests must be all-market"
                )
            if not isinstance(trading_dates, list | tuple):
                raise DataContractError("trading_dates must be a list or tuple")
            return fetch_stock_moneyflow_sessions(
                tuple(str(item) for item in trading_dates),
                env_file=_env_file(request),
            )
        return fetch_stock_moneyflow(
            request.start,
            request.end,
            symbol=request.symbol,
            env_file=_env_file(request),
        )

    def trading_calendar(request: DataRequest) -> tuple[pd.DataFrame, Mapping[str, Any]]:
        return fetch_trading_calendar(
            _required_symbol(request),
            request.start,
            request.end,
            env_file=_env_file(request),
        )

    return {
        Dataset.ETF_OHLCV.value: etf_ohlcv,
        Dataset.ETF_UNADJUSTED_DAILY.value: etf_unadjusted,
        Dataset.STOCK_OHLCV.value: stock_ohlcv,
        Dataset.STOCK_UNADJUSTED_DAILY.value: stock_unadjusted,
        Dataset.SHIBOR_DAILY.value: shibor,
        Dataset.US_REAL_YIELD_DAILY.value: us_real_yield,
        Dataset.US_NOMINAL_YIELD_DAILY.value: us_nominal_yield,
        Dataset.USDCNH_DAILY.value: usdcnh,
        Dataset.FXCM_DAILY.value: fxcm,
        Dataset.SGE_GOLD_DAILY.value: sge_gold,
        Dataset.FUTURES_SHFE_GOLD_DAILY.value: shfe_gold_daily,
        Dataset.FUTURES_SHFE_GOLD_MAPPING.value: shfe_gold_mapping,
        Dataset.FUTURES_SHFE_GOLD_HOLDING.value: shfe_gold_holding,
        Dataset.DOMESTIC_INDEX_DAILY.value: domestic_index,
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
        Dataset.STOCK_MONEYFLOW.value: stock_moneyflow,
        Dataset.TRADING_CALENDAR.value: trading_calendar,
        Dataset.STRATEGY_FEATURE_EVIDENCE.value: fetch_strategy_feature_evidence,
    }


def _env_file(request: DataRequest) -> str | Path | None:
    value = request.options.get("env_file")
    return None if value is None else Path(value)


def _required_symbol(request: DataRequest) -> str:
    if request.symbol is None:
        raise DataContractError(f"{request.dataset} requires a symbol")
    return request.symbol
