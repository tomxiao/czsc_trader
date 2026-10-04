"""TDR-owned market data used only for historical execution and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dataflows import (DataRequest, DataStatus, Dataflows, Dataset,
                       PreparePolicy, PreparedDataRef, DataResult)
from strategy_runtime import canonical_sha256, StrategyInputBinding


@dataclass(frozen=True)
class BacktestExecutionData:
    """Execution-channel facts; never used as SRT calculation input."""

    root: Path
    symbol: str
    asset_type: str
    adjusted_daily: pd.DataFrame
    execution_daily: pd.DataFrame
    execution_intraday: pd.DataFrame
    fingerprint: str
    cutoff: date
    evaluation_sessions: pd.DatetimeIndex
    execution_five_minute: pd.DataFrame | None = None
    requests: dict[str, DataRequest] = field(default_factory=dict)
    prepared: PreparedDataRef | None = None
    input_identities: dict[str, str] = field(default_factory=dict)
    strategy_bindings: dict[str, StrategyInputBinding] = field(default_factory=dict)

    @property
    def evaluation_start(self) -> pd.Timestamp:
        return pd.Timestamp(self.evaluation_sessions[0])

    @property
    def evaluation_end(self) -> pd.Timestamp:
        return pd.Timestamp(self.evaluation_sessions[-1])


class BacktestExecutionDataNotReadyError(ValueError):
    def __init__(
        self,
        *,
        requested_cutoff: date,
        published_cutoff: date,
        first_unpublished_session: date,
    ) -> None:
        self.requested_cutoff = requested_cutoff
        self.published_cutoff = published_cutoff
        self.first_unpublished_session = first_unpublished_session
        super().__init__(
            "backtest data is not ready: "
            f"requested cutoff {requested_cutoff.isoformat()} includes unpublished "
            f"trading session {first_unpublished_session.isoformat()}; "
            f"published cutoff is {published_cutoff.isoformat()}"
        )


def _ready(
    flows: Dataflows,
    request: DataRequest,
    name: str,
    evaluation_sessions: pd.DatetimeIndex | None = None,
    requested_cutoff: date | None = None,
    *,
    prepared: PreparedDataRef,
):
    result = flows.fetch(request, prepared=prepared)
    return _require_ready(result, name, evaluation_sessions, requested_cutoff)


def _require_ready(result, name, evaluation_sessions=None, requested_cutoff=None):
    if result.status is DataStatus.READY and result.identity is not None:
        return result
    if (
        result.status is DataStatus.INCOMPLETE
        and result.error is not None
        and evaluation_sessions is not None
    ):
        actual = pd.Timestamp(str(result.error.context.get("actual_cutoff"))).normalize()
        missing = evaluation_sessions[evaluation_sessions > actual]
        if not missing.empty:
            raise BacktestExecutionDataNotReadyError(
                requested_cutoff=requested_cutoff or evaluation_sessions[-1].date(),
                published_cutoff=actual.date(),
                first_unpublished_session=missing[0].date(),
            )
    detail = result.error.message if result.error is not None else result.status.value
    raise ValueError(f"TDR execution-data preparation failed for {name}: {detail}")


def _prices(frame: pd.DataFrame) -> pd.DataFrame:
    value = frame.rename(
        columns={
            "Date": "dt",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "vol",
            "Amount": "amount",
        }
    ).copy()
    value["dt"] = pd.to_datetime(value["dt"], errors="raise")
    return value[["dt", "open", "high", "low", "close", "vol", "amount"]]


def _unadjust_intraday(
    adjusted_intraday: pd.DataFrame,
    adjusted_daily: pd.DataFrame,
    execution_daily: pd.DataFrame,
) -> pd.DataFrame:
    adjusted = adjusted_daily.set_index(adjusted_daily["dt"].dt.normalize())
    execution = execution_daily.set_index(execution_daily["dt"].dt.normalize())
    common = adjusted.index.intersection(execution.index)
    factors = adjusted.loc[common, "close"].astype(float).div(
        execution.loc[common, "close"].astype(float)
    )
    result = adjusted_intraday.copy()
    row_factors = result["dt"].dt.normalize().map(factors)
    if row_factors.isna().any() or row_factors.le(0).any():
        raise ValueError("TDR intraday prices have no complete positive adjustment factors")
    for column in ("open", "high", "low", "close"):
        result[column] = result[column].astype(float).div(row_factors.to_numpy(dtype=float))
    return result


def _prepare_backtest_execution_data(
    *,
    repository_root: Path,
    symbol: str,
    asset_type: str,
    start: date,
    end: date,
    include_five_minute: bool = False,
    dataflows: Dataflows,
) -> BacktestExecutionData:
    """Prepare TDR/TXE data without inspecting any strategy input contract."""

    if start > end:
        raise ValueError("backtest start must not follow end")
    normalized_asset = asset_type.lower()
    if normalized_asset not in {"stock", "etf"}:
        raise ValueError("backtest asset type must be stock or etf")
    normalized_symbol = symbol.upper()
    flows = dataflows
    calendar_request = DataRequest(
            Dataset.TRADING_CALENDAR,
            "SSE",
            start.isoformat(),
            end.isoformat(),
            end.isoformat(),
            "daily",
    )
    calendar_prepared = flows.prepare((calendar_request,), policy=PreparePolicy.REUSE)
    if not calendar_prepared.ready:
        item = calendar_prepared.items[0]
        _require_ready(DataResult(item.status, error=item.error), "trading_calendar")
    calendar = _ready(flows, calendar_request, "trading_calendar", prepared=calendar_prepared.reference)
    calendar_frame = calendar.dataframe.copy()
    calendar_dates = pd.to_datetime(calendar_frame["Date"], errors="raise").dt.normalize()
    sessions = pd.DatetimeIndex(
        calendar_dates.loc[pd.to_numeric(calendar_frame["IsOpen"], errors="raise").eq(1)],
        name="dt",
    )
    if sessions.empty:
        raise ValueError("backtest interval contains no trading sessions")
    if sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("backtest trading sessions must be unique and increasing")

    actual_start = sessions[0].date()
    actual_end = sessions[-1].date()
    history_start = actual_start - timedelta(days=400)
    adjusted_dataset = Dataset.ETF_OHLCV if normalized_asset == "etf" else Dataset.STOCK_OHLCV
    execution_dataset = (
        Dataset.ETF_UNADJUSTED_DAILY
        if normalized_asset == "etf"
        else Dataset.STOCK_UNADJUSTED_DAILY
    )

    requests = {
        "adjusted_daily": DataRequest(
            adjusted_dataset,
            normalized_symbol,
            history_start.isoformat(),
            actual_end.isoformat(),
            actual_end.isoformat(),
            "daily",
        ),
        "adjusted_30m": DataRequest(
            adjusted_dataset,
            normalized_symbol,
            history_start.isoformat(),
            actual_end.isoformat(),
            actual_end.isoformat(),
            "30m",
        ),
        "execution_daily": DataRequest(
            execution_dataset,
            normalized_symbol,
            history_start.isoformat(),
            actual_end.isoformat(),
            actual_end.isoformat(),
            "daily",
        ),
    }
    if include_five_minute:
        requests["adjusted_5m"] = DataRequest(
            adjusted_dataset,
            normalized_symbol,
            history_start.isoformat(),
            actual_end.isoformat(),
            actual_end.isoformat(),
            "5m",
        )
    requests["trading_calendar"] = calendar_request
    prepared = flows.prepare(tuple(requests.values()), policy=PreparePolicy.REUSE)
    if not prepared.ready:
        for name, item in zip(requests, prepared.items):
            if not item.ready:
                _require_ready(DataResult(item.status, error=item.error), name, sessions, end)
    results = {
        name: _ready(flows, request, name, sessions, end, prepared=prepared.reference)
        for name, request in requests.items()
    }
    if results["trading_calendar"].identity.content_sha256 != calendar.identity.content_sha256:
        raise ValueError("calendar changed while preparing execution inputs")
    adjusted_daily = _prices(results["adjusted_daily"].dataframe)
    adjusted_daily.insert(1, "symbol", normalized_symbol)
    execution_daily = _prices(results["execution_daily"].dataframe)
    adjusted_intraday = _prices(results["adjusted_30m"].dataframe)
    execution_intraday = _unadjust_intraday(
        adjusted_intraday, adjusted_daily, execution_daily
    )
    execution_five_minute = None
    if include_five_minute:
        execution_five_minute = _unadjust_intraday(
            _prices(results["adjusted_5m"].dataframe),
            adjusted_daily,
            execution_daily,
        )
    execution_sessions = pd.DatetimeIndex(execution_daily["dt"].dt.normalize())
    if not sessions.isin(execution_sessions).all():
        missing = sessions[~sessions.isin(execution_sessions)]
        raise ValueError(
            "TDR execution prices do not cover evaluation sessions: "
            f"{[item.date().isoformat() for item in missing]}"
        )
    identities = {
        "trading_calendar": calendar.identity.content_sha256,
        **{
            name: result.identity.content_sha256
            for name, result in sorted(results.items())
        },
    }
    fingerprint = canonical_sha256(
        {
            "symbol": normalized_symbol,
            "asset_type": normalized_asset,
            "evaluation_start": actual_start.isoformat(),
            "evaluation_end": actual_end.isoformat(),
            "inputs": identities,
        }
    )
    return BacktestExecutionData(
        root=Path(repository_root).resolve() / "data" / "backtest",
        symbol=normalized_symbol,
        asset_type=normalized_asset,
        adjusted_daily=adjusted_daily,
        execution_daily=execution_daily,
        execution_intraday=execution_intraday,
        execution_five_minute=execution_five_minute,
        fingerprint=fingerprint,
        cutoff=actual_end,
        evaluation_sessions=sessions,
        requests=requests,
        prepared=prepared.reference,
        input_identities=identities,
    )
