"""TDR-owned market data used only for historical execution and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame({
        "dt": pd.Series(dtype="datetime64[ns]"),
        **{name: pd.Series(dtype=float) for name in ("open", "high", "low", "close", "vol", "amount")},
    })


def _require_execution_frequencies(
    data: BacktestExecutionData, frequencies: tuple[str, ...],
) -> None:
    for frequency in frequencies:
        frame = data.execution_intraday if frequency == "30m" else data.execution_five_minute
        if frame is None or frame.empty:
            raise ValueError(f"execution data has no required {frequency} prices")
        observed = pd.DatetimeIndex(pd.to_datetime(frame["dt"])).normalize()
        if not data.evaluation_sessions.isin(observed).all():
            raise ValueError(f"execution {frequency} prices do not cover evaluation sessions")


def _prepare_backtest_execution_data(
    *,
    repository_root: Path,
    symbol: str,
    asset_type: str,
    start: date,
    end: date,
    intraday_frequencies: tuple[str, ...] = (),
    prior_sessions: int = 1,
    dataflows: Dataflows,
) -> BacktestExecutionData:
    """Bind execution prices for declared frequencies and daily benchmark history.

    Strategy calculation history is independently planned by SRT. Minute prices
    cover only the execution interval; daily prices include prior signal sessions.
    """
    if type(prior_sessions) is not int or prior_sessions < 1:
        raise ValueError("prior_sessions must be a positive integer")
    if (not isinstance(intraday_frequencies, tuple)
            or len(set(intraday_frequencies)) != len(intraday_frequencies)
            or any(value not in {"30m", "5m"} for value in intraday_frequencies)):
        raise ValueError("execution frequencies must be a unique tuple of 30m/5m")

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
    history_calendar_request = replace(
        calendar_request, start=(start - timedelta(days=max(31, prior_sessions * 2))).isoformat(),
    )
    calendar_prepared = flows.prepare((history_calendar_request,), policy=PreparePolicy.REUSE)
    if not calendar_prepared.ready:
        item = calendar_prepared.items[0]
        _require_ready(DataResult(item.status, error=item.error), "trading_calendar")
    calendar = _ready(flows, calendar_request, "trading_calendar", prepared=calendar_prepared.reference)
    history_calendar = _ready(
        flows, history_calendar_request, "history_calendar", prepared=calendar_prepared.reference,
    )
    calendar_frame = history_calendar.dataframe.copy()
    calendar_dates = pd.to_datetime(calendar_frame["Date"], errors="raise").dt.normalize()
    calendar_sessions = pd.DatetimeIndex(
        calendar_dates.loc[pd.to_numeric(calendar_frame["IsOpen"], errors="raise").eq(1)],
        name="dt",
    )
    sessions = calendar_sessions[(calendar_sessions >= pd.Timestamp(start)) & (calendar_sessions <= pd.Timestamp(end))]
    if sessions.empty:
        raise ValueError("backtest interval contains no trading sessions")
    if sessions.has_duplicates or not sessions.is_monotonic_increasing:
        raise ValueError("backtest trading sessions must be unique and increasing")

    actual_start = sessions[0].date()
    actual_end = sessions[-1].date()
    prior = calendar_sessions[calendar_sessions < sessions[0]]
    if len(prior) < prior_sessions:
        raise ValueError(f"trading calendar cannot satisfy {prior_sessions} prior sessions")
    history_start = prior[-prior_sessions].date()
    signal_start = prior[-1].date()
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
        "execution_daily": DataRequest(
            execution_dataset,
            normalized_symbol,
            signal_start.isoformat(),
            actual_end.isoformat(),
            actual_end.isoformat(),
            "daily",
        ),
    }
    intraday_dataset = (
        Dataset.ETF_UNADJUSTED_INTRADAY if normalized_asset == "etf"
        else Dataset.STOCK_UNADJUSTED_INTRADAY
    )
    for frequency in intraday_frequencies:
        requests[f"execution_{frequency}"] = DataRequest(
            intraday_dataset, normalized_symbol, actual_start.isoformat(),
            actual_end.isoformat(), actual_end.isoformat(), frequency,
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
    execution_intraday = (
        _prices(results["execution_30m"].dataframe) if "execution_30m" in results else _empty_prices()
    )
    execution_five_minute = (
        _prices(results["execution_5m"].dataframe) if "execution_5m" in results else None
    )
    adjusted_sessions = pd.DatetimeIndex(adjusted_daily["dt"].dt.normalize())
    if not prior[-prior_sessions:].isin(adjusted_sessions).all():
        raise ValueError("adjusted daily prices do not cover declared prior sessions")
    execution_sessions = pd.DatetimeIndex(execution_daily["dt"].dt.normalize())
    if not prior[-1:].append(sessions).isin(execution_sessions).all():
        required = prior[-1:].append(sessions)
        missing = required[~required.isin(execution_sessions)]
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
