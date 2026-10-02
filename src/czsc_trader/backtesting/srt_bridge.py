"""TDR bridge from candidate/frozen SRT strategies to TXE historical execution."""

from __future__ import annotations

from dataflows import Dataflows

from hashlib import sha256
from pathlib import Path
from collections.abc import Mapping
from datetime import date
import re

import numpy as np
import pandas as pd
from strategy_runtime import (
    TradableWindow,
    ExecutionPolicy,
    StrategyInit,
    StrategyRelease,
    StrategyRuntime,
    StrategyCandidate,
    RuntimeContractError,
    canonical_sha256,
)

from trading_execution_engine import HistoricalExecutor
from .execution_data import BacktestExecutionData
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
    return ("5m",) if "11:30_CLOSE" in checkpoints else ()


def srt_data_directory(
    root: Path,
    snapshot: StrategySnapshot,
    symbol: str,
    *,
    created_on: date | None = None,
) -> Path:
    """Find or create the reusable SRT space for one strategy and symbol."""

    parent = Path(root).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    reference = re.sub(r"[^A-Za-z0-9]+", "", snapshot.identity.reference)
    instrument = re.sub(r"[^A-Za-z0-9]+", "", symbol.split(".", 1)[0].upper())
    if not reference or not instrument:
        raise RuntimeContractError("SRT data-space identity is not path-safe")
    prefix = f"{reference}_{instrument}_"
    pattern = re.compile(rf"^{re.escape(prefix)}\d{{6}}$")
    existing = sorted(
        item for item in parent.iterdir() if item.is_dir() and pattern.fullmatch(item.name)
    )
    if len(existing) > 1:
        raise RuntimeContractError(
            f"multiple reusable SRT data spaces exist for {snapshot.identity.reference} {symbol}"
        )
    if existing:
        return existing[0]
    target = parent / f"{prefix}{(created_on or date.today()):%y%m%d}"
    target.mkdir(exist_ok=False)
    return target


def build_srt_signal_replay(
    *,
    snapshot: StrategySnapshot,
    execution_data: BacktestExecutionData,
    start: pd.Timestamp,
    end: pd.Timestamp,
    repository_root: Path,
    space_created_on: date | None = None,
    dataflows: Dataflows | None = None,
) -> tuple[object, SignalReplay]:
    """Create one SRT instance and calculate its complete historical window."""

    source, definition = describe_snapshot_strategy(
        repository_root,
        snapshot,
        deployment_symbol=execution_data.symbol,
    )
    runtime = StrategyRuntime(Path(repository_root) / "strategies", dataflows=dataflows)
    if end.normalize() > pd.Timestamp(execution_data.cutoff):
        raise RuntimeContractError("backtest window exceeds the published cutoff")
    sessions = pd.DatetimeIndex(
        pd.to_datetime(execution_data.adjusted_daily["dt"]).dt.normalize(), name="dt"
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
            symbol=(
                execution_data.symbol
                if snapshot.identity.kind == "REGISTERED"
                else None
            ),
        )
    )
    prepared = strategy.prepare_data()
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
        )
    )
    strategy.prepare_data()
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
    )
    ledger = strategy.run_window(executor=channel)
    return BacktestResult(
        identity=signals.snapshot.identity,
        decisions=ledger.decisions,
        orders=ledger.orders,
        fills=ledger.fills,
        account_daily=ledger.account_daily,
        trades=ledger.trades,
    )
