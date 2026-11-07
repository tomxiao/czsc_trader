"""Caller-neutral strategy instance and its planning operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import Dataflows, Dataset, DataRequest, DataResult, PreparePolicy

from .contracts import (
    DataPreparationResult,
    SignalHistoryMode,
    StrategyIdentity,
    TradingPoint,
    TradableWindow,
    signal_identity_for,
)
from .data import PreparedStrategyData
from .errors import RuntimeContractError
from .models import ExecutionPolicy, ExecutionPricingData, RuntimeDefinition
from .pricing import ExecutionPricing
from .preparation import PreparedInputs, prepare_inputs, acquire_binding, calendar_request, plan_inputs
from .input_binding import StrategyInputPlan, StrategyInputBinding
from .prepared_store import save_prepared_inputs
from .signals import StrategySignal
from .entry_cycle import CycleTarget
from .calculation import HistoryCalculationContext
from .session_proposal import SessionProposal


_SHANGHAI = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True, slots=True)
class _PreparedBatchAlgorithm:
    """Facts consumed by account replay; no mutable implementation is shared."""
    definition: RuntimeDefinition


class StrategyInstance:
    """One immutable strategy identity, parameter set and tradable window."""

    def __init__(
        self,
        *,
        algorithm,
        identity: StrategyIdentity,
        tradable_window: TradableWindow,
        data_dir: Path,
        execution_policy,
        dataflows: Dataflows | None = None,
        pricing: ExecutionPricing = ExecutionPricing(),
    ) -> None:
        self._algorithm = algorithm
        self._identity = identity
        self._tradable_window = tradable_window
        self._data_dir = Path(data_dir).resolve()
        self._execution_policy = execution_policy
        cycle_mode = execution_policy.settings.get("capital", {}).get("mode") == "signal_cash_fraction"
        if cycle_mode != (algorithm.definition.decision.output_kind == "CYCLE_TARGET"):
            raise RuntimeContractError("CYCLE_TARGET and signal_cash_fraction must be declared together")
        self._dataflows = dataflows
        self._pricing_contract = pricing
        if pricing.anchor_date is not None and pricing.anchor_date >= tradable_window.start:
            raise RuntimeContractError("HFQ anchor must precede the tradable window")
        self._prepared_data: PreparedStrategyData | None = None
        self._input_binding: StrategyInputBinding | None = None
        self._history_cache: dict[
            tuple[str, SignalHistoryMode], tuple[pd.DataFrame, pd.DatetimeIndex]
        ] = {}

    @property
    def identity(self) -> StrategyIdentity:
        return self._identity

    @property
    def tradable_window(self) -> TradableWindow:
        return self._tradable_window

    @property
    def definition(self):
        return self._algorithm.definition

    @property
    def execution_policy(self):
        return self._execution_policy

    def _pricing(self, inputs: PreparedInputs) -> ExecutionPricingData:
        adjusted = [
            result.dataframe
            for name, result in inputs.results.items()
            if str(inputs.requests[name].dataset) in {Dataset.ETF_OHLCV.value, Dataset.STOCK_OHLCV.value}
            and inputs.requests[name].frequency == "daily"
            and inputs.requests[name].symbol == self._identity.symbol
        ]
        execution = [
            result.dataframe
            for name, result in inputs.results.items()
            if str(inputs.requests[name].dataset) in {Dataset.ETF_UNADJUSTED_DAILY.value, Dataset.STOCK_UNADJUSTED_DAILY.value}
            and inputs.requests[name].frequency == "daily"
            and inputs.requests[name].symbol == self._identity.symbol
        ]
        price_families = {
            str(request.dataset).split(".", 1)[0]
            for request in inputs.requests.values()
            if request.dataset in {Dataset.ETF_OHLCV, Dataset.STOCK_OHLCV,
                                   Dataset.ETF_UNADJUSTED_DAILY, Dataset.STOCK_UNADJUSTED_DAILY}
            and request.frequency == "daily" and request.symbol == self._identity.symbol
        }
        if len(adjusted) != 1 or len(execution) != 1 or len(price_families) != 1:
            raise RuntimeContractError(
                "strategy input contract must declare one adjusted and one execution price"
            )
        return ExecutionPricingData(
            self._identity.symbol,
            adjusted[0],
            execution[0],
            self._pricing_contract,
        )

    def _summary(self, data: PreparedStrategyData) -> DataPreparationResult:
        return DataPreparationResult(
            self._identity,
            self._tradable_window,
            data.available_through,
            data.dataset_identity,
        )

    def calendar_request(self) -> DataRequest:
        """Return the strategy-declared prerequisite request without supplier access."""
        return calendar_request(algorithm=self._algorithm, tradable_window=self._tradable_window)

    def plan_inputs(self, calendar: DataResult, *, trading_status: DataResult | None = None,
                    status_request: DataRequest | None = None) -> StrategyInputPlan:
        """Authenticate the strategy-declared requests against a prepared calendar."""
        return plan_inputs(strategy=self._identity, algorithm=self._algorithm,
                           tradable_window=self._tradable_window, calendar=calendar,
                           trading_status=trading_status, status_request=status_request)

    @property
    def input_binding(self) -> StrategyInputBinding:
        if self._input_binding is None:
            raise RuntimeContractError("strategy data is not prepared; call prepare_data() first")
        return self._input_binding

    def prepare_data(self, *, binding: StrategyInputBinding | None = None,
                     policy: PreparePolicy | None = None, persist: bool = True) -> DataPreparationResult:
        """Prepare explicitly selected inputs, or read an existing binding offline."""
        if (binding is None) == (policy is None):
            raise RuntimeContractError("provide exactly one input binding or preparation policy")
        if type(persist) is not bool:
            raise TypeError("persist must be bool")
        if self._dataflows is None:
            raise RuntimeContractError("data preparation requires host-supplied Dataflows")
        if binding is not None and not isinstance(binding, StrategyInputBinding):
            raise RuntimeContractError("binding must be StrategyInputBinding")
        if policy is not None and not isinstance(policy, PreparePolicy):
            raise RuntimeContractError("policy must be PreparePolicy")
        if self._prepared_data is not None and policy is not None:
            raise RuntimeContractError("strategy instance is already prepared; reuse its explicit binding")
        if binding is None:
            binding = acquire_binding(strategy=self._identity, algorithm=self._algorithm,
                                      tradable_window=self._tradable_window,
                                      dataflows=self._dataflows, policy=policy)
        if self._prepared_data is not None:
            if binding != self._input_binding:
                raise RuntimeContractError("strategy instance is already bound to different inputs")
            return self._summary(self._prepared_data)
        inputs = prepare_inputs(strategy=self._identity, algorithm=self._algorithm,
                                tradable_window=self._tradable_window,
                                dataflows=self._dataflows, binding=binding)
        prepared = PreparedStrategyData.from_inputs(inputs=inputs, pricing=self._pricing(inputs))
        if persist:
            save_prepared_inputs(inputs, self._data_dir, binding=binding)
        self._input_binding = binding
        self._prepared_data = prepared
        return self._summary(prepared)

    def fork_for_replay(self, *, execution_policy: ExecutionPolicy) -> StrategyInstance:
        """Create an independent account view from authenticated batch facts.

        The WINDOW history must already exist. This view has no strategy module
        or implementation to execute: source globals and implementation state
        therefore cannot leak between accounts. Only private read-only input and
        history facts are shared; public inspections still return defensive copies.
        """
        data = self._prepared()
        if type(execution_policy) is not ExecutionPolicy:
            raise TypeError("replay requires ExecutionPolicy")
        if execution_policy.policy_type != self._execution_policy.policy_type:
            raise RuntimeContractError("replay policy must preserve the strategy policy type")
        key = (data.dataset_identity, SignalHistoryMode.WINDOW)
        if key not in self._history_cache:
            raise RuntimeContractError("calculate WINDOW history before forking account replay")
        replay = StrategyInstance(algorithm=_PreparedBatchAlgorithm(self.definition),
            identity=self._identity, tradable_window=self._tradable_window, data_dir=self._data_dir,
            execution_policy=execution_policy, dataflows=self._dataflows, pricing=self._pricing_contract)
        replay._prepared_data = data
        replay._input_binding = self._input_binding
        replay._history_cache = {key: self._history_cache[key]}
        return replay

    def _prepared(self) -> PreparedStrategyData:
        if self._prepared_data is None:
            raise RuntimeContractError("strategy data is not prepared; call prepare_data() first")
        return self._prepared_data

    def _history(
        self,
        data: PreparedStrategyData,
        mode: SignalHistoryMode,
    ) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
        if not isinstance(mode, SignalHistoryMode):
            raise RuntimeContractError("history_mode must be SignalHistoryMode")
        cache_key = (data.dataset_identity, mode)
        cached = self._history_cache.get(cache_key)
        if cached is not None:
            return cached
        if type(self._algorithm) is _PreparedBatchAlgorithm:
            raise RuntimeContractError("account replay cannot calculate new history; prepare it explicitly")
        frames = {name: result.dataframe.copy(deep=True) for name, result in data._inputs.results.items()}
        if mode is SignalHistoryMode.CONTINUOUS:
            dates = data.calculation_dates()
        elif mode is SignalHistoryMode.WINDOW:
            dates = tuple(dict.fromkeys(data._inputs.signal_dates.values()))
        else:
            raise RuntimeContractError(f"unsupported calculation mode: {mode}")
        sessions = pd.DatetimeIndex(
            pd.to_datetime(dates, errors="raise"), name="dt"
        ).normalize()
        if self.definition.implementation.contract_version == 2:
            context = HistoryCalculationContext(
                mode, self._tradable_window,
                tuple(dict.fromkeys(data._inputs.signal_dates.values())),
                tuple(data.calculation_dates()),
            )
            history = self._algorithm.calculate_context_history(frames, context)
        else:
            history = (
                self._algorithm.calculate_window_history(frames, sessions)
                if mode is SignalHistoryMode.WINDOW
                else self._algorithm.calculate_history(frames, sessions)
            )
        if not isinstance(history, pd.DataFrame) or not isinstance(
            history.index, pd.DatetimeIndex
        ):
            raise RuntimeContractError(
                "strategy history must use a DatetimeIndex"
            )
        actual_sessions = pd.DatetimeIndex(history.index).tz_localize(None).normalize()
        if actual_sessions.has_duplicates or not actual_sessions.is_monotonic_increasing:
            raise RuntimeContractError(
                "strategy history sessions must be unique and ordered"
            )
        if (mode is SignalHistoryMode.WINDOW or self.definition.implementation.contract_version == 2) and not actual_sessions.equals(sessions):
            raise RuntimeContractError(
                "strategy window history differs from requested evaluation sessions"
            )
        if mode is SignalHistoryMode.CONTINUOUS and not sessions.difference(actual_sessions).empty:
            raise RuntimeContractError(
                "strategy point history omits required calculation sessions"
            )
        history = history.copy()
        history.index = actual_sessions
        if "target_position" not in history:
            raise RuntimeContractError("strategy history requires target_position")
        targets = pd.to_numeric(history["target_position"], errors="coerce")
        if targets.isna().any() or not targets.between(
            self.definition.decision.minimum_target,
            self.definition.decision.maximum_target,
        ).all():
            raise RuntimeContractError("strategy history contains invalid target positions")
        if self._execution_policy.settings.get("capital", {}).get("mode") == "signal_cash_fraction":
            if self.definition.decision.output_kind != "CYCLE_TARGET":
                raise RuntimeContractError("signal allocation requires CYCLE_TARGET decision contract")
            if "entry_allocation_fraction" not in history or not targets.isin([0., 1.]).all():
                raise RuntimeContractError("cycle history requires binary target and entry_allocation_fraction")
            for active, fraction in zip(targets, history["entry_allocation_fraction"], strict=True):
                CycleTarget(bool(active), None if not active and pd.isna(fraction) else fraction)
        panel = self.definition.observation.signal_panel
        if panel is not None:
            if self.definition.implementation.contract_version != 2:
                raise RuntimeContractError("signal panels require implementation contract 2")
            try:
                observation = self._algorithm.observation_history(
                    {name: frame.copy(deep=True) for name, frame in frames.items()},
                    context, history.copy(deep=True),
                )
                if (not isinstance(observation, pd.DataFrame)
                        or not observation.index.equals(history.index)
                        or observation.columns.has_duplicates):
                    raise RuntimeContractError("observation history must preserve trading sessions")
                allowed = set(panel.evidence_fields)
                if any(not isinstance(name, str) or not name.startswith("obs_")
                       or name not in allowed or name in history for name in observation.columns):
                    raise RuntimeContractError("observation history may only add declared obs_ columns")
                for column in observation.columns:
                    for value in observation[column]:
                        if not pd.api.types.is_scalar(value):
                            raise RuntimeContractError("observation history requires scalar values")
                        if pd.isna(value) or isinstance(value, pd.Timestamp):
                            continue
                        if hasattr(value, "item"):
                            value = value.item()
                        if type(value) not in (str, bool, int, float):
                            raise RuntimeContractError("observation history requires JSON scalar values")
                        if type(value) is float and not math.isfinite(value):
                            raise RuntimeContractError("observation history requires finite values")
                history = history.join(observation)
            except Exception as exc:
                # Observation-only failures never supply partial display facts or
                # alter already validated trading history. Materialization emits
                # an explicit UNAVAILABLE observation for this recorded reason.
                history["_observation_error"] = f"{type(exc).__name__}: {exc}"
        cached = (history, sessions)
        self._history_cache[cache_key] = cached
        return cached

    def _calculate_signal(
        self,
        data: PreparedStrategyData,
        point: TradingPoint,
        history_mode: SignalHistoryMode,
    ) -> StrategySignal:
        history, _ = self._history(data, history_mode)
        signal_date = data.signal_date_for(point.trading_date)
        signal_session = pd.Timestamp(signal_date).normalize()
        try:
            signal_position = history.index.get_loc(signal_session)
        except KeyError:
            raise RuntimeContractError(
                "strategy history does not reach the signal date: "
                f"signal={signal_date.isoformat()}, "
                f"range={history.index.min()}..{history.index.max()}"
            ) from None
        row = history.iloc[signal_position]
        target_position = float(row["target_position"])
        cycle_target = None
        if self._execution_policy.settings.get("capital", {}).get("mode") == "signal_cash_fraction":
            fraction = row["entry_allocation_fraction"]
            cycle_target = CycleTarget(bool(target_position),
                                       None if not target_position and pd.isna(fraction) else fraction)
        if not (
            self.definition.decision.minimum_target
            <= target_position
            <= self.definition.decision.maximum_target
        ):
            raise RuntimeContractError("strategy target position violates its contract")
        evidence: dict[str, object] = {"signal_date": signal_date.isoformat()}
        for name, value in row.items():
            if name == "target_position" or pd.isna(value):
                continue
            if isinstance(value, pd.Timestamp):
                evidence[str(name)] = value.date().isoformat()
            elif hasattr(value, "item"):
                evidence[str(name)] = value.item()
            else:
                evidence[str(name)] = value
        if "action" not in evidence:
            if bool(evidence.get("signal_active", False)):
                evidence["action"] = "INTRADAY_LONG_OVERLAY"
            elif self.definition.decision.output_kind == "INTRADAY_OVERLAY":
                evidence["action"] = "NO_EVENT"
            else:
                # History is ordered and unique. Read its predecessor directly;
                # shifting the full column for every session is quadratic work.
                previous = (
                    history["target_position"].iat[signal_position - 1]
                    if signal_position > 0 else 0.0
                )
                evidence["action"] = (
                    "BUY"
                    if target_position > float(previous)
                    else "SELL"
                    if target_position < float(previous)
                    else "HOLD"
                )
        return StrategySignal(
            trading_date=point.trading_date,
            target_position=target_position,
            cycle_target=cycle_target,
            evidence=evidence,
            next_state={
                "signal_date": signal_date.isoformat(),
                "target_position": target_position,
            },
        )

    def inspect_signals(
        self, *, history_mode: SignalHistoryMode = SignalHistoryMode.WINDOW,
    ) -> pd.DataFrame:
        """Return defensive history; default WINDOW uses window initialization."""

        data = self._prepared()
        history, _ = self._history(data, history_mode)
        return history.copy()

    def inspect_price_history(self) -> pd.DataFrame:
        """Return adjusted daily prices without exposing strategy input datasets."""

        return self._prepared().adjusted_daily

    def decision_points(self) -> tuple[TradingPoint, ...]:
        """Return the prepared window's calendar-resolved decision times."""
        data = self._prepared()
        return tuple(TradingPoint(day, datetime.combine(data.signal_date_for(day),
            time(20, 31), tzinfo=_SHANGHAI)) for day in data.trading_dates())

    def propose_at(
        self,
        *,
        point: TradingPoint,
        history_mode: SignalHistoryMode = SignalHistoryMode.CONTINUOUS,
    ) -> SessionProposal:
        """Calculate one signal and its observed references; never size orders."""
        if type(point) is not TradingPoint:
            raise TypeError("strategy proposal requires TradingPoint")
        data = self._prepared()
        if not self._tradable_window.contains(point.trading_date):
            raise RuntimeContractError("trading point is outside the strategy window")
        signal_date = data.signal_date_for(point.trading_date)
        signal_available_at = datetime.combine(signal_date, time(15), tzinfo=_SHANGHAI)
        if point.calculation_time.astimezone(_SHANGHAI) < signal_available_at:
            raise RuntimeContractError("calculation time precedes the signal-session close")
        signal = self._calculate_signal(data, point, history_mode)
        if signal.evidence.get("signal_date") != signal_date.isoformat():
            raise RuntimeContractError("strategy signal evidence refers to another date")
        references = data.price_reference(signal_date, point.trading_date)
        identity = signal_identity_for(strategy=self._identity, signal_date=signal_date,
            target_position=signal.target_position, input_identities=data.input_identities,
            price_identities=data.price_identities, cycle_target=signal.cycle_target)
        return SessionProposal(self._identity, point, signal_date, signal, references,
            data.input_identities, data.price_identities, self._execution_policy, identity)
