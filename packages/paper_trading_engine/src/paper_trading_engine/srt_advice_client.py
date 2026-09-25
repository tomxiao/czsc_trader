"""PTE adapter from SRT execution plans to durable account decisions."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import re
from threading import Lock
import time as clock
from typing import Callable
from uuid import uuid4

from strategy_runtime import (
    DataPreparationResult,
    ExecutionPlan,
    ExecutionState,
    PortfolioSnapshot,
    StrategyInit,
    StrategyInstance,
    StrategyRelease,
    StrategyRuntime,
    TradableWindow,
    TradingPoint,
    canonical_sha256,
    load_strategy_deployment,
    materialize_observation,
    unavailable_observation,
    validate_observation_descriptor,
)
from dataflows import Dataflows, DataRequest, Dataset

from .audit import AuditRecorder
from .contracts import AdviceContractError, AdviceDecision
from .errors import AdviceClientError


_BEIJING = timezone(timedelta(hours=8), "Asia/Shanghai")
_ACCOUNT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PREPARED_STORAGE_REVISION = 1


@dataclass(frozen=True, slots=True)
class PreparedAccountStrategy:
    """One prepared SRT instance and the opaque evidence returned with it."""

    instance: StrategyInstance
    result: DataPreparationResult
    observation_descriptor: Mapping[str, object]

    @property
    def strategy(self):
        return self.result.strategy

    @property
    def tradable_window(self):
        return self.result.tradable_window

    @property
    def available_through(self):
        return self.result.available_through

    @property
    def data_identity(self):
        return self.result.data_identity


def _load_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdviceClientError(f"cannot read prepared-data index {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise AdviceClientError(f"prepared-data index {path.name} must be an object")
    return value


def _strategy_identity(repo_root: Path, release: StrategyRelease) -> dict[str, str]:
    root = repo_root / "strategies" / release.strategy_family_id
    family = _load_manifest(root / "family.json")
    qualification = None
    for line in (root / "lifecycle.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if event.get("version") == release.version and event.get("release_hash") == release.release_hash:
            qualification = event.get("to_state")
    if qualification not in {"PAPER_READY", "LIVE_READY"}:
        raise AdviceClientError(f"{release.release_id} is not approved for paper trading")
    return {
        "strategy_id": release.strategy_family_id,
        "name": str(family["name"]),
        "version": release.version,
        "release_id": release.release_id,
        "release_hash": release.release_hash,
        "qualification": str(qualification),
    }


def _order_payload(order) -> dict[str, object]:
    if order.limit_price is None:
        raise AdviceClientError("PTE requires an executable reference price for every order")
    return {
        "side": order.side.value,
        "quantity": order.quantity,
        "order_type": order.order_type.value,
        "limit_price": float(order.limit_price),
        "time_in_force": "DAY",
    }


def _decision_from_plan(
    plan: ExecutionPlan,
    identity: dict[str, str],
    observation_descriptor: Mapping[str, object],
) -> AdviceDecision:
    orders = [_order_payload(order) for order in plan.orders]
    legs = [
        {
            "sequence": leg.sequence,
            "role": leg.role,
            "checkpoint": leg.checkpoint,
            "submit_after": leg.submit_after.isoformat(),
            "submit_before": leg.submit_before.isoformat(),
            "dependency_sequence": leg.dependency_sequence,
            "dependency_required_status": leg.dependency_required_status,
            "order": _order_payload(leg.order),
        }
        for leg in plan.legs
    ]
    source_decision_id = f"SRT-{plan.signal_date:%Y%m%d}-{plan.signal_identity[:12].upper()}"
    try:
        observation = materialize_observation(
            observation_descriptor,
            plan.evidence,
            action=plan.action,
            target_position=plan.target_position,
        )
    except ValueError as exc:
        observation = unavailable_observation(exc)
    payload = {
        "contract_version": "advice.v5" if plan.plan_mode != "NONE" or legs else "advice.v4",
        "decision_id": source_decision_id,
        "source_decision_id": source_decision_id,
        "signal_identity": plan.signal_identity,
        "plan_identity": plan.plan_identity,
        "portfolio_revision": plan.expected_portfolio_revision,
        "state_revision": plan.expected_state_revision,
        "symbol": plan.symbol,
        "signal_date": plan.signal_date.isoformat(),
        "valid_session": plan.trading_date.isoformat(),
        "actual_quantity": plan.actual_quantity,
        "target_quantity": plan.target_quantity,
        "cycle_target_quantity": plan.cycle_target_quantity,
        "delta_quantity": plan.target_quantity - plan.actual_quantity,
        "action": plan.action,
        "strategy": identity,
        "signal_reference_price": float(plan.references.signal_price),
        "execution_reference_price": float(plan.references.execution_price),
        "data_cutoff": plan.signal_date.isoformat(),
        "order": orders[0] if len(orders) == 1 else None,
        "orders": orders,
        "available_cash": float(plan.available_cash),
        "fee_rate": float(plan.fee_rate),
        "estimated_order_cost": float(plan.estimated_order_cost),
        "unallocated_cash": float(plan.unallocated_cash),
        "capital_rule": {
            "mode": plan.capital_mode,
            "allocation_fraction": float(plan.allocation_fraction),
            "target_scope": "entry_cycle",
        },
        "plan_mode": plan.plan_mode,
        "plan_legs": legs,
        "runtime_sha256": plan.strategy.runtime_sha256,
        "strategy_output": dict(plan.evidence),
        "observation": observation,
        "input_identity_hashes": dict(plan.input_identities),
    }
    try:
        return AdviceDecision.from_cli_payload({"status": "PASS", "result": payload})
    except AdviceContractError as exc:
        raise AdviceClientError(f"SRT execution plan violates PTE contract: {exc}") from exc


class SrtAdviceClient:
    """Generate PTE decisions from the caller-neutral SRT API."""

    def __init__(
        self,
        *,
        repo_root: Path,
        data_dir: Path,
        symbol: str | None = None,
        asset: str = "etf",
        audit: AuditRecorder | None = None,
        now: Callable[[], datetime] | None = None,
        session_resolver: Callable[[date], date | None] | None = None,
    ) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.symbol = symbol.upper() if symbol else None
        self.asset = asset
        self.audit = audit
        self.now = now or (lambda: datetime.now(_BEIJING))
        self.session_resolver = session_resolver or self._next_tradable_session
        self._session_cache: dict[date, date | None] = {}
        self._session_cache_lock = Lock()

    def _load_release(self, strategy_id: str, strategy_version: str) -> StrategyRelease:
        path = self.repo_root / "strategies" / strategy_id / "versions" / f"{strategy_version}.json"
        return StrategyRelease.from_mapping(_load_manifest(path))

    def _account_root(self, account_id: str) -> Path:
        if _ACCOUNT_ID.fullmatch(account_id) is None:
            raise AdviceClientError("invalid PTE account id")
        root = (self.data_dir / "accounts" / account_id).resolve()
        if root.parent != (self.data_dir / "accounts").resolve():
            raise AdviceClientError("account data directory is unsafe")
        return root

    def _entry(self, account_id: str, release_id: str) -> dict[str, object]:
        index = self._account_index(account_id)
        releases = index.get("releases")
        if not isinstance(releases, dict) or not isinstance(releases.get(release_id), dict):
            raise AdviceClientError(f"prepared data is unavailable for {release_id}")
        entry = dict(releases[release_id])
        entry["symbol"] = index.get("symbol")
        entry["signal_date"] = index.get("signal_date")
        entry["trading_date"] = index.get("trading_date")
        return entry

    def _account_index(self, account_id: str) -> dict[str, object]:
        index = _load_manifest(self._account_root(account_id) / "current.json")
        index_hash = index.pop("index_sha256", None)
        if index_hash != canonical_sha256(index):
            raise AdviceClientError("prepared-data index was modified")
        if index.get("schema_version") != 2:
            raise AdviceClientError("prepared-data index version is unsupported")
        if index.get("account_id") != account_id:
            raise AdviceClientError("prepared data belongs to another account")
        releases = index.get("releases")
        if not isinstance(releases, dict):
            raise AdviceClientError("prepared-data releases are invalid")
        return index

    def prepared_through(
        self, account_id: str, strategy_id: str, strategy_version: str
    ) -> date:
        entry = self._entry(account_id, f"{strategy_id}-{strategy_version}")
        try:
            return date.fromisoformat(str(entry["signal_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AdviceClientError("prepared-data signal date is invalid") from exc

    def tradable_date(
        self, account_id: str, strategy_id: str, strategy_version: str
    ) -> date:
        entry = self._entry(account_id, f"{strategy_id}-{strategy_version}")
        try:
            return date.fromisoformat(str(entry["trading_date"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AdviceClientError("prepared-data trading date is invalid") from exc

    def data_identity(
        self, account_id: str, strategy_id: str, strategy_version: str
    ) -> str:
        entry = self._entry(account_id, f"{strategy_id}-{strategy_version}")
        identity = entry.get("data_identity")
        if not isinstance(identity, str) or not identity:
            raise AdviceClientError("prepared-data identity is invalid")
        return identity

    def _instance(
        self, account_id: str, release: StrategyRelease, trading_date: date
    ) -> PreparedAccountStrategy:
        entry = self._entry(account_id, release.release_id)
        if date.fromisoformat(str(entry["trading_date"])) != trading_date:
            raise AdviceClientError("requested trading date differs from prepared data")
        if entry.get("release_hash") != release.release_hash:
            raise AdviceClientError("prepared data belongs to another strategy release")
        relative = Path(str(entry.get("data_dir", "")))
        account_root = self._account_root(account_id)
        directory = (account_root / relative).resolve()
        if relative.is_absolute() or not directory.is_relative_to(account_root):
            raise AdviceClientError("prepared-data directory is unsafe")
        strategy = StrategyRuntime(self.repo_root / "strategies").create(
            StrategyInit(
                release,
                TradableWindow(trading_date, trading_date),
                directory,
                symbol=str(entry["symbol"]).upper(),
            )
        )
        prepared = strategy.prepare_data()
        descriptor = validate_observation_descriptor(entry.get("observation"))
        return PreparedAccountStrategy(strategy, prepared, descriptor)

    def _trading_calendar(self, start: date, end: date) -> dict[date, int]:
        result = Dataflows().fetch(
            DataRequest(
                Dataset.TRADING_CALENDAR,
                "SSE",
                start.isoformat(),
                end.isoformat(),
                end.isoformat(),
            )
        )
        if not result.ready:
            message = result.error.message if result.error is not None else result.status
            raise AdviceClientError(f"SSE trading calendar is unavailable: {message}")
        return {
            value.date(): int(flag)
            for value, flag in zip(
                result.dataframe["Date"], result.dataframe["IsOpen"], strict=True
            )
        }

    def _next_tradable_session(self, signal_date: date) -> date | None:
        sessions = self._trading_calendar(
            signal_date, signal_date + timedelta(days=40)
        )
        if sessions.get(signal_date) != 1:
            return None
        future = sorted(day for day, is_open in sessions.items() if day > signal_date and is_open)
        if not future:
            raise AdviceClientError(f"SSE calendar has no session after {signal_date}")
        return future[0]

    def latest_completed_signal_date(
        self,
        at: datetime | None = None,
        *,
        completion_time: time = time(20, 30),
    ) -> date:
        moment = at or self.now()
        moment = (
            moment.replace(tzinfo=_BEIJING)
            if moment.tzinfo is None
            else moment.astimezone(_BEIJING)
        )
        end = moment.date()
        sessions = self._trading_calendar(end - timedelta(days=40), end)
        candidates = [
            day
            for day, is_open in sessions.items()
            if is_open
            and (day < end or (day == end and moment.time() >= completion_time))
        ]
        if not candidates:
            raise AdviceClientError("SSE calendar has no completed trading session")
        return max(candidates)

    def _active_space(
        self,
        root: Path,
        *,
        account_id: str,
        release: StrategyRelease,
        symbol: str,
    ) -> Path | None:
        if not (root / "current.json").is_file():
            return None
        index = self._account_index(account_id)
        if index.get("prepared_storage_revision") != _PREPARED_STORAGE_REVISION:
            return None
        releases = index["releases"]
        entry = releases.get(release.release_id)
        if (
            index.get("symbol") != symbol.upper()
            or not isinstance(entry, dict)
            or entry.get("release_hash") != release.release_hash
        ):
            return None
        runtime_sha256 = StrategyRuntime(self.repo_root / "strategies").describe(
            release, symbol=symbol.upper()
        ).runtime_sha256
        if entry.get("runtime_sha256") != runtime_sha256:
            return None
        relative = Path(str(entry.get("data_dir", "")))
        directory = (root / relative).resolve()
        spaces_root = (root / "spaces").resolve()
        if relative.is_absolute() or not directory.is_relative_to(root):
            raise AdviceClientError("prepared-data directory is unsafe")
        if directory.parent != spaces_root:
            return None
        if not directory.name.startswith(f"{account_id}_"):
            raise AdviceClientError("account strategy-space name is invalid")
        if not directory.is_dir():
            raise AdviceClientError("active account strategy-space is unavailable")
        return directory

    def _new_space(self, root: Path, account_id: str) -> Path:
        moment = self.now()
        moment = (
            moment.replace(tzinfo=_BEIJING)
            if moment.tzinfo is None
            else moment.astimezone(_BEIJING)
        )
        timestamp = moment.strftime("%Y%m%dT%H%M%S%f")
        directory = root / "spaces" / f"{account_id}_{timestamp}"
        if directory.exists():
            raise AdviceClientError("account strategy-space name already exists")
        return directory

    @staticmethod
    def _write_index(root: Path, index: dict[str, object]) -> None:
        index["index_sha256"] = canonical_sha256(index)
        temporary_root = root / ".tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = temporary_root / f"current-{uuid4().hex}.json"
        try:
            temporary.write_text(
                json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, root / "current.json")
        finally:
            temporary.unlink(missing_ok=True)
            try:
                temporary_root.rmdir()
            except OSError:
                pass

    def prepare_account_data(
        self,
        *,
        account_id: str,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        asset: str,
        signal_date: date,
    ) -> PreparedAccountStrategy | None:
        if asset != "etf":
            raise AdviceClientError("PTE currently requires one ETF strategy")
        release = self._load_release(strategy_id, strategy_version)
        with self._session_cache_lock:
            cached = self._session_cache.get(signal_date, ...)
        if cached is ...:
            resolved = self.session_resolver(signal_date)
            with self._session_cache_lock:
                trading_date = self._session_cache.setdefault(signal_date, resolved)
        else:
            trading_date = cached
        if trading_date is None:
            return None
        root = self._account_root(account_id)
        root.mkdir(parents=True, exist_ok=True)
        directory = self._active_space(
            root,
            account_id=account_id,
            release=release,
            symbol=symbol,
        ) or self._new_space(root, account_id)
        strategy = StrategyRuntime(self.repo_root / "strategies").create(
            StrategyInit(
                release,
                TradableWindow(trading_date, trading_date),
                directory,
                symbol=symbol.upper(),
            )
        )
        prepared = strategy.prepare_data()
        if prepared.available_through != signal_date:
            raise AdviceClientError(
                f"SRT prepared through {prepared.available_through}, expected {signal_date}"
            )
        if strategy.identity.symbol != symbol.upper():
            raise AdviceClientError("SRT execution-pricing symbol differs from account")
        deployment = load_strategy_deployment(
            self.repo_root / "strategies", release.release_id
        )
        observation = validate_observation_descriptor(
            deployment.binding.get("observation")
        )
        self._write_index(
            root,
            {
                "schema_version": 2,
                "prepared_storage_revision": _PREPARED_STORAGE_REVISION,
                "account_id": account_id,
                "symbol": symbol.upper(),
                "signal_date": signal_date.isoformat(),
                "trading_date": trading_date.isoformat(),
                "releases": {
                    release.release_id: {
                        "release_hash": release.release_hash,
                        "runtime_sha256": strategy.identity.runtime_sha256,
                        "data_dir": directory.relative_to(root).as_posix(),
                        "data_identity": prepared.data_identity,
                        "observation": observation,
                    }
                },
            },
        )
        return PreparedAccountStrategy(strategy, prepared, observation)

    def verify_account_data(
        self,
        *,
        account_id: str,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        asset: str,
    ) -> DataPreparationResult:
        if asset != "etf":
            raise AdviceClientError("PTE currently requires one ETF strategy")
        release = self._load_release(strategy_id, strategy_version)
        trading_date = self.tradable_date(account_id, strategy_id, strategy_version)
        prepared = self._instance(account_id, release, trading_date)
        if prepared.instance.identity.symbol != symbol.upper():
            raise AdviceClientError("SRT execution-pricing symbol differs from account")
        return prepared.result

    def validate_account_binding(
        self,
        *,
        strategy_id: str,
        strategy_version: str,
        symbol: str,
        asset: str,
    ) -> dict[str, str]:
        """Validate one account's frozen strategy binding without preparing data."""
        if asset != "etf":
            raise AdviceClientError("PTE currently requires one ETF strategy")
        release = self._load_release(strategy_id, strategy_version)
        StrategyRuntime(self.repo_root / "strategies").describe(
            release, symbol=symbol.upper(),
        )
        return _strategy_identity(self.repo_root, release)

    def _audit_call(self, started: float, *, error=None, **scope) -> None:
        if self.audit is None or error is None:
            return
        self.audit.record(
            "DECISION_GENERATION_FAILED",
            source="srt_advice_client",
            outcome="FAILURE",
            actor_type="ENGINE",
            actor_id="strategy_runtime",
            correlation_id=f"srt:{scope.get('symbol')}",
            details={
                "service": "strategy_runtime",
                "operation": "plan_at",
                "duration_ms": round((clock.perf_counter() - started) * 1000, 3),
                "error_type": type(error).__name__,
                "error": str(error),
            },
            **scope,
        )

    def get_decision(
        self,
        actual_quantity: int,
        available_cash: float,
        total_assets: float,
        *,
        trading_date: date,
        portfolio_revision: int,
        state_revision: int,
        cycle_target_quantity: int | None = None,
        strategy_id: str | None = None,
        strategy_version: str | None = None,
        baseline: str | None = None,
        account_id: str | None = None,
        symbol: str | None = None,
        asset: str | None = None,
        prepared: PreparedAccountStrategy | None = None,
    ) -> AdviceDecision:
        del baseline
        started = clock.perf_counter()
        selected_symbol = (symbol or self.symbol or "").upper()
        selected_asset = asset or self.asset
        scope = {
            "account_id": account_id,
            "strategy_id": strategy_id,
            "strategy_version": strategy_version,
            "symbol": selected_symbol,
        }
        try:
            if not strategy_id or not strategy_version or not account_id:
                raise AdviceClientError("SRT advice requires strategy, version, and account")
            if selected_asset != "etf" or not selected_symbol:
                raise AdviceClientError("SRT advice requires one ETF symbol")
            release = self._load_release(strategy_id, strategy_version)
            if not isinstance(prepared, PreparedAccountStrategy):
                raise AdviceClientError("SRT advice requires one prepared strategy instance")
            strategy = prepared.instance
            if prepared.tradable_window != TradableWindow(trading_date, trading_date):
                raise AdviceClientError("prepared strategy window differs from decision date")
            if (
                prepared.strategy.reference_id != release.release_id
                or prepared.strategy.release_hash != release.release_hash
            ):
                raise AdviceClientError("prepared strategy belongs to another release")
            if strategy.definition.state_mode != "STATELESS":
                raise AdviceClientError("PTE does not support persisted SRT strategy state yet")
            if strategy.identity.symbol != selected_symbol:
                raise AdviceClientError("SRT strategy symbol differs from account")
            identity = _strategy_identity(self.repo_root, release)
            generated_at = self.now()
            generated_at = (
                generated_at.replace(tzinfo=_BEIJING)
                if generated_at.tzinfo is None
                else generated_at.astimezone(_BEIJING)
            )
            plan = strategy.plan_at(
                point=TradingPoint(trading_date, generated_at),
                portfolio=PortfolioSnapshot(
                    account_id,
                    selected_symbol,
                    Decimal(str(available_cash)),
                    Decimal(str(total_assets)),
                    int(actual_quantity),
                    portfolio_revision,
                    generated_at,
                ),
                state=ExecutionState(state_revision, generated_at, cycle_target_quantity),
            )
            decision = _decision_from_plan(
                plan, identity, prepared.observation_descriptor
            )
        except Exception as exc:
            self._audit_call(started, error=exc, **scope)
            if isinstance(exc, AdviceClientError):
                raise
            raise AdviceClientError(f"SRT decision generation failed: {exc}") from exc
        return decision
