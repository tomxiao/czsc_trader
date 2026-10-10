"""TDR bridge from candidate/frozen SRT strategies to TXE historical execution."""

from __future__ import annotations

from dataflows import Dataflows, DataResult, PreparePolicy, Dataset, canonical_frame_sha256

from hashlib import sha256
from pathlib import Path
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import date
import re

import numpy as np
import pandas as pd
from strategy_runtime import (
    TradableWindow,
    ExecutionPolicy,
    ExecutionPricing,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    StrategyCandidate,
    StrategyInputBinding,
    RuntimeContractError,
    canonical_sha256,
)

from trading_execution_engine import HistoricalExecutor
from .execution_data import BacktestExecutionData, _require_execution_frequencies
from .models import StrategySnapshot
from .result import BacktestResult
from .signal_replay import SignalReplay


def _validate_historical_decisions(
    history: pd.DataFrame,
    required_sessions: pd.DatetimeIndex,
) -> None:
    """Reject incomplete historical outputs before absence becomes HOLD or NO_EVENT."""

    if not isinstance(history.index, pd.DatetimeIndex):
        raise RuntimeContractError("SRT historical decisions must use a DatetimeIndex")
    normalized = pd.DatetimeIndex(pd.to_datetime(history.index).normalize(), name="dt")
    if normalized.has_duplicates or not normalized.is_monotonic_increasing:
        raise RuntimeContractError("SRT historical decision sessions are invalid")
    normalized_history = history.copy()
    normalized_history.index = normalized
    missing = required_sessions.difference(normalized_history.index)
    if not missing.empty:
        raise RuntimeContractError(
            "SRT historical decisions do not cover required sessions: "
            f"missing={[item.date().isoformat() for item in missing]}"
        )
    visible = normalized_history.reindex(required_sessions)
    if "target_position" not in visible:
        raise RuntimeContractError("SRT historical decisions have no target_position")
    target = pd.to_numeric(visible["target_position"], errors="coerce")
    if target.isna().any() or not target.between(0.0, 1.0).all():
        raise RuntimeContractError(
            "SRT historical target_position contains unavailable or invalid values"
        )


def _plain_json(value):
    if is_dataclass(value):
        return {item.name: _plain_json(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain_json(item) for item in value]
    return value


def _decision_id(reference: str, signal_date: pd.Timestamp, target: int) -> str:
    raw = f"{reference}|{signal_date.date()}|{target}".encode()
    return "DEC-" + sha256(raw).hexdigest()[:20].upper()


def _overlay_decision_id(reference: str, signal_date: pd.Timestamp) -> str:
    raw = "|".join(map(str, (reference, signal_date, "INTRADAY_LONG"))).encode()
    return "DEC-" + sha256(raw).hexdigest()[:20].upper()


def _load_release(repository_root: Path, reference: str) -> StrategyRelease:
    from strategy_manager import StrategyRegistry
    family, version = reference.split("-", 1)
    frozen = StrategyRegistry(Path(repository_root) / "strategies").get_version(family, version)
    return StrategyRelease.from_mapping(frozen.to_dict())


def load_srt_strategy(
    repository_root: Path,
    reference: str,
    *,
    deployment_symbol: str | None = None,
):
    """Load a frozen runtime, optionally bound to an explicit backtest symbol."""

    release = _load_release(repository_root, reference)
    definition = StrategyRuntime(Path(repository_root) / "strategies").describe(
        release, symbol=deployment_symbol,
    )
    return release, definition


def describe_snapshot_strategy(
    repository_root: Path,
    snapshot: StrategySnapshot,
    *,
    deployment_symbol: str,
):
    """Authenticate one TDR snapshot and return its SRT source and definition."""

    if snapshot.identity.kind == "CANDIDATE":
        family, separator, candidate_id = snapshot.identity.reference.partition("-")
        if not separator:
            raise RuntimeContractError(
                "candidate replay requires a family-qualified identity"
            )
        source = StrategyCandidate(
            family, candidate_id, snapshot.strategy_payload, snapshot.runtime_root,
        )
        if snapshot.source_hash != source.runtime_identity_sha256:
            raise RuntimeContractError("candidate release hashes differ from the snapshot")
        if snapshot.content_hash != canonical_sha256(snapshot.strategy_payload):
            raise RuntimeContractError("candidate snapshot content hash differs")
        definition = StrategyRuntime(Path(repository_root) / "strategies").describe(source)
    elif snapshot.identity.kind == "REGISTERED":
        source = _load_release(repository_root, snapshot.identity.reference)
        if (
            snapshot.source_hash != source.release_hash
            or canonical_sha256(snapshot.strategy_payload)
            != canonical_sha256(source.payload)
        ):
            raise RuntimeContractError("registered snapshot differs from its frozen release")
        definition = StrategyRuntime(Path(repository_root) / "strategies").describe(
            source, symbol=deployment_symbol,
        )
    else:
        raise RuntimeContractError(
            f"unsupported strategy identity: {snapshot.identity.kind}"
        )
    if definition.release_id != snapshot.identity.reference:
        raise RuntimeContractError("historical runtime differs from the replay identity")
    if strategy_reference_symbol(definition) != deployment_symbol.upper():
        raise RuntimeContractError("historical runtime differs from the replay symbol")
    return source, definition


def strategy_reference_symbol(strategy) -> str:
    """Return the single ETF instrument declared by one frozen runtime."""

    definition = getattr(strategy, "definition", strategy)
    subjects = {
        item.subject.upper()
        for item in definition.inputs.requirements
        if item.subject and item.dataset.startswith("etf.")
    }
    if len(subjects) != 1:
        payload = definition.parameters.values
        rule = payload.get("rule")
        if isinstance(rule, Mapping):
            execution = rule.get("execution")
            if isinstance(execution, Mapping):
                instrument = execution.get("instrument")
                if isinstance(instrument, Mapping) and isinstance(
                    instrument.get("symbol"), str
                ):
                    return str(instrument["symbol"]).upper()
            if isinstance(rule.get("symbol"), str):
                return str(rule["symbol"]).upper()
        if isinstance(payload.get("symbol"), str):
            return str(payload["symbol"]).upper()
        raise ValueError("SRT strategy does not declare exactly one ETF instrument")
    return next(iter(subjects))


def execution_intraday_frequencies(strategy) -> tuple[str, ...]:
    """Map SRT channel checkpoints to TDR execution-price datasets."""

    definition = getattr(strategy, "definition", strategy)
    checkpoints = set(definition.capabilities.checkpoints)
    unsupported = checkpoints - {"OPEN", "11:30_CLOSE"}
    if unsupported:
        raise ValueError(f"unsupported SRT execution checkpoints: {sorted(unsupported)}")
    frequencies = []
    if definition.execution.policy_type == "FROZEN_RULE":
        if any(definition.execution.order_type_for(side) == "LIMIT" for side in ("BUY", "SELL")):
            frequencies.append("30m")
    if "11:30_CLOSE" in checkpoints:
        frequencies.append("5m")
    return tuple(frequencies)


def srt_data_directory(
    root: Path,
    snapshot: StrategySnapshot,
    symbol: str,
    *,
    created_on: date | None = None,
) -> Path:
    """Locate computation context; input versions are selected only by bindings."""

    parent = Path(root).resolve() / "contexts"
    parent.mkdir(parents=True, exist_ok=True)
    reference = re.sub(r"[^A-Za-z0-9]+", "", snapshot.identity.reference)
    instrument = re.sub(r"[^A-Za-z0-9]+", "", symbol.split(".", 1)[0].upper())
    if not reference or not instrument:
        raise RuntimeContractError("SRT data-space identity is not path-safe")
    target = parent / f"{reference}_{instrument}"
    target.mkdir(exist_ok=True)
    return target


def prepare_srt_input_binding(
    *, snapshot: StrategySnapshot, execution_data: BacktestExecutionData,
    start: pd.Timestamp, end: pd.Timestamp, repository_root: Path, dataflows: Dataflows,
) -> StrategyInputBinding:
    """Prepare one input list for strategy calculation and historical execution."""
    if not execution_data.requests or execution_data.prepared is None:
        raise RuntimeContractError("execution data requires an explicit DFLS input binding")
    _validate_execution_binding(dataflows, execution_data, execution_data.prepared)
    source, _ = describe_snapshot_strategy(
        repository_root, snapshot, deployment_symbol=execution_data.symbol,
    )
    instance = StrategyRuntime(Path(repository_root) / "strategies", dataflows=dataflows).create(
        StrategyInit(source, TradableWindow(pd.Timestamp(start).date(), pd.Timestamp(end).date()),
                     srt_data_directory(execution_data.root, snapshot, execution_data.symbol),
                     symbol=execution_data.symbol if snapshot.identity.kind == "REGISTERED" else None,
                     pricing=execution_data.pricing)
    )
    calendar_request = instance.calendar_request()
    calendar_prepared = dataflows.prepare((calendar_request,), policy=PreparePolicy.REUSE)
    if not calendar_prepared.ready:
        raise RuntimeContractError(f"strategy calendar preparation failed: {calendar_prepared.items}")
    calendar = dataflows.fetch(calendar_request, prepared=calendar_prepared.reference)
    if not calendar.ready:
        raise RuntimeContractError(f"strategy calendar read failed: {calendar.error}")
    plan = instance.plan_inputs(calendar)
    prepared = dataflows.prepare(
        (*plan.requests.values(), *execution_data.requests.values()), policy=PreparePolicy.REUSE,
    )
    if not prepared.ready:
        raise RuntimeContractError(f"backtest input preparation failed: {prepared.items}")
    binding = StrategyInputBinding(plan, prepared.reference)
    final_calendar = dataflows.fetch(plan.requests[plan.calendar_name], prepared=prepared.reference)
    if not final_calendar.ready or final_calendar.identity.content_sha256 != plan.calendar_sha256:
        raise RuntimeContractError("calendar changed while preparing the strategy input list")
    _validate_execution_binding(dataflows, execution_data, binding.prepared)
    return binding


def _execution_frames_for_authentication(
    results: Mapping[str, DataResult], pricing: ExecutionPricing,
) -> dict[str, pd.DataFrame]:
    """Rebuild authenticated numerical frames without duplicating quality metadata.

    DFLS identities and coverage were checked on the original results. These detached
    DataFrame containers have empty attrs; the ordinary conversion and public pricing
    algorithm still produce every value that participates in the frame hash.
    """
    from .execution_data import _execution_frames

    numerical = {
        name: replace(result, dataframe=pd.DataFrame(result.dataframe, copy=False))
        for name, result in results.items()
    }
    return _execution_frames(numerical, pricing)


def _validate_execution_binding(flows, execution_data, prepared):
    if not execution_data.requests or not execution_data.input_identities:
        raise RuntimeContractError("execution data has no authenticated input list")
    asset = execution_data.asset_type
    if asset not in {"etf", "stock"} or execution_data.symbol != execution_data.symbol.upper():
        raise RuntimeContractError("execution instrument identity is invalid")
    adjusted_dataset = Dataset.ETF_OHLCV if asset == "etf" else Dataset.STOCK_OHLCV
    daily_dataset = Dataset.ETF_UNADJUSTED_DAILY if asset == "etf" else Dataset.STOCK_UNADJUSTED_DAILY
    expected = {
        "adjusted_daily": (adjusted_dataset, execution_data.symbol, "daily"),
        "execution_daily": (daily_dataset, execution_data.symbol, "daily"),
        "trading_calendar": (Dataset.TRADING_CALENDAR, "SSE", "daily"),
    }
    intraday_dataset = Dataset.ETF_UNADJUSTED_INTRADAY if asset == "etf" else Dataset.STOCK_UNADJUSTED_INTRADAY
    if "execution_30m" in execution_data.requests:
        expected["execution_30m"] = (intraday_dataset, execution_data.symbol, "30m")
    if execution_data.execution_five_minute is not None:
        expected["execution_5m"] = (intraday_dataset, execution_data.symbol, "5m")
    if set(execution_data.requests) != set(expected) or set(execution_data.input_identities) != set(expected):
        raise RuntimeContractError("execution input list differs from its declared tables")
    results = {}
    for name, request in execution_data.requests.items():
        if (request.dataset, request.symbol, request.frequency) != expected[name]:
            raise RuntimeContractError(f"execution input selection differs from instrument: {name}")
        result = flows.fetch(request, prepared=prepared)
        if not result.ready or result.identity.content_sha256 != execution_data.input_identities.get(name):
            raise RuntimeContractError(f"execution input differs from bound preparation: {name}")
        results[name] = result
    calendar = results["trading_calendar"].dataframe
    sessions = pd.DatetimeIndex(
        pd.to_datetime(calendar.loc[pd.to_numeric(calendar["IsOpen"]).eq(1), "Date"]).dt.normalize(),
        name="dt",
    )
    if (sessions.empty or not sessions.equals(execution_data.evaluation_sessions)
            or execution_data.cutoff != sessions[-1].date()):
        raise RuntimeContractError("execution evaluation window differs from bound calendar")
    fingerprint = canonical_sha256({
        "symbol": execution_data.symbol, "asset_type": asset,
        "evaluation_start": sessions[0].date().isoformat(),
        "evaluation_end": sessions[-1].date().isoformat(),
        "inputs": {name: result.identity.content_sha256 for name, result in results.items()},
        "pricing": execution_data.pricing.to_dict(),
    })
    if execution_data.fingerprint != fingerprint:
        raise RuntimeContractError("execution data fingerprint differs from bound inputs")
    frames = _execution_frames_for_authentication(results, execution_data.pricing)
    frames["adjusted_daily"].insert(1, "symbol", execution_data.symbol)
    for name, frame in frames.items():
        actual = getattr(execution_data, name)
        if not isinstance(actual, pd.DataFrame) or canonical_frame_sha256(actual) != canonical_frame_sha256(frame):
            raise RuntimeContractError(f"execution dataframe differs from bound inputs: {name}")


def build_srt_signal_replay(
    *,
    snapshot: StrategySnapshot,
    execution_data: BacktestExecutionData,
    start: pd.Timestamp,
    end: pd.Timestamp,
    repository_root: Path,
    space_created_on: date | None = None,
    dataflows: Dataflows | None = None,
    input_binding: StrategyInputBinding | None = None,
) -> tuple[object, SignalReplay]:
    """Create one SRT instance and calculate its complete historical window."""

    if dataflows is None:
        raise RuntimeContractError("backtest requires host-supplied Dataflows")
    source, definition = describe_snapshot_strategy(
        repository_root,
        snapshot,
        deployment_symbol=execution_data.symbol,
    )
    _require_execution_frequencies(execution_data, execution_intraday_frequencies(definition))
    runtime = StrategyRuntime(Path(repository_root) / "strategies", dataflows=dataflows)
    if end.normalize() > pd.Timestamp(execution_data.cutoff):
        raise RuntimeContractError("backtest window exceeds the published cutoff")
    sessions = pd.DatetimeIndex(
        pd.to_datetime(pd.DataFrame(execution_data.adjusted_daily, copy=False)["dt"]).dt.normalize(), name="dt"
    )
    evaluation = sessions[(sessions >= start.normalize()) & (sessions <= end.normalize())]
    if evaluation.empty:
        raise ValueError("backtest interval contains no trading sessions")
    first_location = int(sessions.get_loc(evaluation[0]))
    visible = sessions[
        max(0, first_location - 1) : int(sessions.get_loc(evaluation[-1]))
    ]
    next_sessions = pd.Series(sessions[1:], index=sessions[:-1])
    data_dir = srt_data_directory(
        execution_data.root,
        snapshot,
        execution_data.symbol,
        created_on=space_created_on,
    )
    strategy = runtime.create(
        StrategyInit(
            source,
            TradableWindow(evaluation[0].date(), evaluation[-1].date()),
            data_dir,
            pricing=execution_data.pricing,
            symbol=(
                execution_data.symbol
                if snapshot.identity.kind == "REGISTERED"
                else None
            ),
        )
    )
    if input_binding is None and execution_data.strategy_bindings:
        key = f"{snapshot.identity.reference}|{evaluation[0].date()}|{evaluation[-1].date()}"
        if key not in execution_data.strategy_bindings:
            raise RuntimeContractError("review data does not bind the requested strategy/window")
        input_binding = execution_data.strategy_bindings[key]
    if input_binding is None:
        input_binding = prepare_srt_input_binding(
            snapshot=snapshot, execution_data=execution_data, start=evaluation[0], end=evaluation[-1],
            repository_root=repository_root, dataflows=dataflows,
        )
    _validate_execution_binding(dataflows, execution_data, execution_data.prepared)
    _validate_execution_binding(dataflows, execution_data, input_binding.prepared)
    prepared = strategy.prepare_data(binding=input_binding)
    history = strategy.inspect_signals()
    _validate_historical_decisions(history, visible)
    rows: list[dict[str, object]] = []
    output_kind = strategy.definition.decision.output_kind
    if output_kind == "INTRADAY_OVERLAY":
        selected = history.loc[history["signal_active"].fillna(False).astype(bool)].copy()
        selected["valid_session"] = selected.index.map(next_sessions)
        selected = selected.loc[selected["valid_session"].isin(evaluation)]
        for signal_date, row in selected.iterrows():
            rows.append(
                {
                    "decision_id": _overlay_decision_id(snapshot.identity.reference, signal_date),
                    "signal_date": signal_date,
                    "valid_session": row["valid_session"],
                    "target_position": 1,
                    "factor_score": float(row["moneyflow_breadth"]),
                    "regime": None,
                    "threshold": float(row["threshold"]),
                    "observed_weight_ratio": float(row["observed_weight_ratio"]),
                    "action": "INTRADAY_LONG_OVERLAY",
                }
            )
    else:
        for signal_date in visible:
            row = history.loc[signal_date]
            if float(row["target_position"]) not in (0.0, 1.0):
                raise RuntimeContractError("TXE target replay requires binary positions; fractional targets are unsupported")
            target = int(row["target_position"])
            record: dict[str, object] = {
                "decision_id": _decision_id(snapshot.identity.reference, signal_date, target),
                "signal_date": signal_date,
                "valid_session": next_sessions.get(signal_date, pd.NaT),
                "target_position": target,
                "factor_score": float(row.get("factor_score", row.get("base_score", target))),
            }
            if "confirmation_score" in history:
                record["confirmation_score"] = float(row["confirmation_score"])
            record["regime"] = row.get("regime")
            rows.append(record)
        rows = [
            row
            for row in rows
            if not pd.isna(row["valid_session"])
            and pd.Timestamp(row["valid_session"]) in evaluation
        ]
    calculations = history.index
    execution = definition.execution
    target_order_types: dict[str, str | None] = {
        "entry_order_type": None,
        "exit_order_type": None,
    }
    if execution.policy_type == "FROZEN_RULE":
        target_order_types = {
            "entry_order_type": execution.order_type_for("BUY"),
            "exit_order_type": execution.order_type_for("SELL"),
        }
    replay = SignalReplay(
        snapshot=snapshot,
        strategy_source=source,
        decisions=pd.DataFrame(rows),
        calculation_start=pd.Timestamp(calculations.min()),
        calculation_end=pd.Timestamp(calculations.max()),
        evaluation_start=evaluation[0],
        evaluation_end=evaluation[-1],
        data_dir=data_dir,
        data_identity=prepared.data_identity,
        support_data={
            "mode": "srt_input_contract",
            "release_id": definition.release_id,
            "runtime_sha256": definition.runtime_sha256,
            "execution_policy": {
                "policy_type": execution.policy_type,
                "settings": _plain_json(execution.settings),
            },
            **target_order_types,
            "available_through": prepared.available_through.isoformat(),
            "prepared_data_identity": prepared.data_identity,
            "input_binding": input_binding.to_dict(),
            "execution_input_identities": dict(execution_data.input_identities),
            "execution_requests": {name: _plain_json(request)
                                   for name, request in execution_data.requests.items()},
        },
    )
    return strategy, replay


def replay_srt_account(
    *,
    strategy,
    signals: SignalReplay,
    execution_data: BacktestExecutionData,
    initial_cash: float,
    fee_rate_override: float | None = None,
    dataflows: Dataflows | None = None,
) -> BacktestResult:
    """Route SRT decisions directly through TXE, then wrap facts for reporting."""

    definition = strategy.definition
    effective_policy = definition.execution
    if fee_rate_override is not None:
        if not np.isfinite(fee_rate_override) or not 0 <= fee_rate_override < 1:
            raise RuntimeContractError("fee_rate_override must be finite and in [0, 1)")
        settings = dict(effective_policy.settings)
        if effective_policy.policy_type == "FROZEN_RULE":
            settings["capital"] = {
                **settings["capital"],
                "fee_rate": float(fee_rate_override),
            }
        else:
            settings["one_way_cost"] = float(fee_rate_override)
        effective_policy = ExecutionPolicy(effective_policy.policy_type, settings)
    strategy_root = Path(signals.snapshot.identity.source)
    input_binding = strategy.input_binding
    strategy = StrategyRuntime(strategy_root, dataflows=dataflows).create(
        StrategyInit(
            signals.strategy_source,
            strategy.tradable_window,
            signals.data_dir,
            symbol=(
                execution_data.symbol
                if signals.snapshot.identity.kind == "REGISTERED"
                else None
            ),
            execution_policy=effective_policy,
            pricing=execution_data.pricing,
        )
    )
    strategy.prepare_data(binding=input_binding)
    channel = HistoricalExecutor(
        strategy_reference=signals.snapshot.identity.reference,
        symbol=execution_data.symbol,
        execution_daily=execution_data.execution_daily,
        execution_intraday=execution_data.execution_intraday,
        execution_five_minute=execution_data.execution_five_minute,
        evaluation_start=signals.evaluation_start,
        evaluation_end=signals.evaluation_end,
        initial_cash=initial_cash,
        execution_policy=effective_policy,
        order_types=definition.capabilities.order_types,
        checkpoints=definition.capabilities.checkpoints,
        pricing=execution_data.pricing,
    )
    from .observation import ObservationExecutor
    observed = ObservationExecutor(strategy.definition, channel)
    ledger = strategy.run_window(executor=observed)
    return BacktestResult(
        identity=signals.snapshot.identity,
        decisions=ledger.decisions,
        orders=ledger.orders,
        fills=ledger.fills,
        account_daily=ledger.account_daily,
        trades=ledger.trades,
        observations=tuple(observed.observations),
    )
