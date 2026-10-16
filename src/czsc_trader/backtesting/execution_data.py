"""TDR-owned market data used only for historical execution and reporting."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from dataflows import (DataRequest, DataStatus, Dataflows, Dataset,
                       PreparePolicy, PreparedDataRef, DataResult)
from strategy_runtime import (canonical_sha256, StrategyInputBinding,
                              ExecutionPriceBasis, ExecutionPricing)
from trading_execution_engine import MarketExecutionRules, SessionPriceLimits


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
    pricing: ExecutionPricing = field(default_factory=ExecutionPricing)
    raw_execution_daily: pd.DataFrame | None = None
    market_rules: MarketExecutionRules | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.pricing, ExecutionPricing):
            raise TypeError("execution data pricing requires ExecutionPricing")

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
    # Transform numerical columns without copying quality evidence at each step.
    value = pd.DataFrame(frame, copy=False).rename(
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
    value = value[["dt", "open", "high", "low", "close", "vol", "amount"]]
    value.attrs = deepcopy(frame.attrs)
    return value


def _empty_prices() -> pd.DataFrame:
    return pd.DataFrame({
        "dt": pd.Series(dtype="datetime64[ns]"),
        **{name: pd.Series(dtype=float) for name in ("open", "high", "low", "close", "vol", "amount")},
    })


def _execution_frames(results, pricing: ExecutionPricing) -> dict[str, pd.DataFrame]:
    adjusted = _prices(results["adjusted_daily"].dataframe)
    raw = _prices(results["execution_daily"].dataframe)
    frames = {"adjusted_daily": adjusted, "raw_execution_daily": raw,
              "execution_daily": pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted),
              "execution_intraday": _empty_prices()}
    for key, field_name in (("execution_30m", "execution_intraday"),
                            ("execution_5m", "execution_five_minute")):
        if key in results:
            frames[field_name] = pricing.apply(_prices(results[key].dataframe),
                                              raw_daily=raw, adjusted_daily=adjusted)
    return frames


def _market_execution_rules(results, pricing: ExecutionPricing, symbol: str) -> MarketExecutionRules:
    """Translate authenticated raw limits into the account's explicit price units."""
    limits = results["price_limits"].dataframe
    # DFLS already authenticated metadata; unit conversion needs numerical data only.
    raw = _prices(pd.DataFrame(results["execution_daily"].dataframe, copy=False))
    adjusted = _prices(pd.DataFrame(results["adjusted_daily"].dataframe, copy=False))
    execution = pricing.apply(raw, raw_daily=raw, adjusted_daily=adjusted)
    scales = pd.Series(execution["close"].to_numpy() / raw["close"].to_numpy(),
                       index=pd.DatetimeIndex(raw["dt"]).normalize())
    dates = pd.to_datetime(limits["Date"], errors="raise").dt.normalize()
    if dates.duplicated().any() or not dates.is_monotonic_increasing:
        raise ValueError("execution price limits require unique increasing sessions")
    factors = dates.map(scales)
    if factors.isna().any():
        raise ValueError("execution price limits have no authenticated price scale")
    return MarketExecutionRules(symbol, tuple(
        SessionPriceLimits(day.date(), float(lower) * float(scale), float(upper) * float(scale))
        for day, lower, upper, scale in zip(dates, limits["DownLimit"], limits["UpLimit"], factors, strict=True)
    ))


def _require_market_rules(data: BacktestExecutionData) -> MarketExecutionRules:
    """Formal TDR replay always has a complete, explicit market contract."""
    if not isinstance(data.market_rules, MarketExecutionRules) or data.market_rules.symbol != data.symbol:
        raise ValueError("formal replay requires matching market execution rules")
    if "price_limits" not in data.requests or "price_limits" not in data.input_identities:
        raise ValueError("formal replay requires authenticated price-limit inputs")
    for session in data.evaluation_sessions:
        data.market_rules.for_session(pd.Timestamp(session).date())
    return data.market_rules


def _require_execution_frequencies(
    data: BacktestExecutionData, frequencies: tuple[str, ...],
) -> None:
    for frequency in frequencies:
        frame = data.execution_intraday if frequency == "30m" else data.execution_five_minute
        if frame is None or frame.empty:
            raise ValueError(f"execution data has no required {frequency} prices")
        observed = pd.DatetimeIndex(pd.to_datetime(pd.DataFrame(frame, copy=False)["dt"])).normalize()
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
    price_basis: ExecutionPriceBasis = ExecutionPriceBasis.UNADJUSTED,
) -> BacktestExecutionData:
    """Bind execution prices for declared frequencies and daily benchmark history.

    Strategy calculation history is independently planned by SRT. Minute prices
    cover only the execution interval; daily prices include prior signal sessions.
    """
    if type(prior_sessions) is not int or prior_sessions < 1:
        raise ValueError("prior_sessions must be a positive integer")
    if not isinstance(price_basis, ExecutionPriceBasis):
        raise TypeError("price_basis requires ExecutionPriceBasis")
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
    try:
        exchange = {"SH": "SSE", "SZ": "SZSE"}[normalized_symbol.rsplit(".", 1)[-1]]
    except KeyError as exc:
        raise ValueError("historical market execution currently supports SH/SZ securities") from exc
    flows = dataflows
    calendar_request = DataRequest(
            Dataset.TRADING_CALENDAR,
            exchange,
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
        "price_limits": DataRequest(
            Dataset.SECURITY_PRICE_LIMITS, normalized_symbol,
            actual_start.isoformat(), actual_end.isoformat(), actual_end.isoformat(),
        ),
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
    pricing = ExecutionPricing.from_daily(
        price_basis, _prices(results["execution_daily"].dataframe),
        _prices(results["adjusted_daily"].dataframe), signal_start,
    )
    frames = _execution_frames(results, pricing)
    adjusted_daily = frames["adjusted_daily"]
    adjusted_daily.insert(1, "symbol", normalized_symbol)
    execution_daily = frames["execution_daily"]
    execution_intraday = frames["execution_intraday"]
    execution_five_minute = frames.get("execution_five_minute")
    adjusted_sessions = pd.DatetimeIndex(pd.DataFrame(adjusted_daily, copy=False)["dt"].dt.normalize())
    if not prior[-prior_sessions:].isin(adjusted_sessions).all():
        raise ValueError("adjusted daily prices do not cover declared prior sessions")
    execution_sessions = pd.DatetimeIndex(pd.DataFrame(execution_daily, copy=False)["dt"].dt.normalize())
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
    market_rules = _market_execution_rules(results, pricing, normalized_symbol)
    if tuple(item.session for item in market_rules.sessions) != tuple(item.date() for item in sessions):
        raise ValueError("execution price limits do not cover evaluation sessions exactly")
    fingerprint = canonical_sha256(
        {
            "symbol": normalized_symbol,
            "asset_type": normalized_asset,
            "evaluation_start": actual_start.isoformat(),
            "evaluation_end": actual_end.isoformat(),
            "inputs": identities,
            "pricing": pricing.to_dict(),
            "market_rules": market_rules.to_dict(),
        }
    )
    return BacktestExecutionData(
        root=Path(repository_root).resolve() / ".tmp" / "evaluation-contexts" / str(flows.binding.space_id),
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
        pricing=pricing,
        raw_execution_daily=frames["raw_execution_daily"],
        market_rules=market_rules,
    )
