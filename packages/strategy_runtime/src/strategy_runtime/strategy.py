"""Caller-neutral strategy instance and its planning operations."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pandas as pd
from dataflows import Dataflows, Dataset, DataRequest, DataResult, PreparePolicy

from .contracts import (
    DataPreparationResult,
    ExecutionCapabilities,
    ExecutionOutcome,
    ExecutionOutcomeStatus,
    ExecutionPlan,
    ExecutionState,
    SignalHistoryMode,
    OrderSide,
    OrderType,
    PlanLeg,
    PlannedOrder,
    PortfolioSnapshot,
    StrategyIdentity,
    TradingPoint,
    TradableWindow,
    WindowExecutor,
    plan_identity_for,
    signal_identity_for,
)
from .data import PreparedStrategyData
from .errors import RuntimeCompatibilityError, RuntimeContractError, RuntimeExecutionError
from .execution_planner import build_execution_plan
from .models import ExecutionPolicy, ExecutionPricingData
from .preparation import PreparedInputs, prepare_inputs, acquire_binding, calendar_request, plan_inputs
from .input_binding import StrategyInputPlan, StrategyInputBinding
from .prepared_store import save_prepared_inputs
from .signals import StrategySignal


_SHANGHAI = ZoneInfo("Asia/Shanghai")


def _planned_order(value: dict[str, object]) -> PlannedOrder:
    order_type = OrderType(str(value["order_type"]).upper())
    raw_price = value.get("limit_price")
    return PlannedOrder(
        side=OrderSide(str(value["side"]).upper()),
        quantity=int(value["quantity"]),
        order_type=order_type,
        limit_price=None if raw_price is None else Decimal(str(raw_price)),
    )


def _parse_time(value: object, name: str) -> time:
    try:
        return time.fromisoformat(str(value))
    except ValueError as exc:
        raise RuntimeContractError(f"{name} must use ISO local time") from exc


def _capital_terms(
    *, raw: dict[str, object], execution_policy: ExecutionPolicy
) -> tuple[str, Decimal]:
    """Map one policy-specific planner result to the public plan capital terms."""

    policy_type = str(execution_policy.policy_type)
    if policy_type == "FROZEN_RULE":
        capital_rule = dict(raw["capital_rule"])
        return (
            str(capital_rule["mode"]),
            Decimal(str(capital_rule["allocation_fraction"])),
        )
    if policy_type == "INTRADAY_OVERLAY":
        plan_mode = str(raw.get("plan_mode", "NONE"))
        if plan_mode == "CORE_SETUP":
            return (
                "available_cash_fraction",
                Decimal(str(execution_policy.settings["core_fraction"])),
            )
        if plan_mode in {"NONE", "CORE_EVENT_INTRADAY_ROTATION"}:
            return "full_available_cash", Decimal("1")
        raise RuntimeContractError(f"unsupported intraday overlay plan mode: {plan_mode}")
    raise RuntimeContractError(f"unsupported execution policy: {policy_type}")


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
    ) -> None:
        self._algorithm = algorithm
        self._identity = identity
        self._tradable_window = tradable_window
        self._data_dir = Path(data_dir).resolve()
        self._execution_policy = execution_policy
        self._dataflows = dataflows
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
            if str(inputs.requests[name].dataset) == Dataset.ETF_OHLCV.value
            and inputs.requests[name].frequency == "daily"
            and inputs.requests[name].symbol == self._identity.symbol
        ]
        execution = [
            result.dataframe
            for name, result in inputs.results.items()
            if str(inputs.requests[name].dataset) == Dataset.ETF_UNADJUSTED_DAILY.value
            and inputs.requests[name].frequency == "daily"
            and inputs.requests[name].symbol == self._identity.symbol
        ]
        if len(adjusted) != 1 or len(execution) != 1:
            raise RuntimeContractError(
                "strategy input contract must declare one adjusted and one execution price"
            )
        return ExecutionPricingData(
            self._identity.symbol,
            adjusted[0],
            execution[0],
        )

    def _summary(self, data: PreparedStrategyData) -> DataPreparationResult:
        return DataPreparationResult(
            self._identity,
            self._tradable_window,
            data.available_through,
            data.dataset_identity,
        )

    def calendar_request(self) -> DataRequest:
        """Describe the prerequisite calendar without accessing a supplier."""
        return calendar_request(algorithm=self._algorithm, tradable_window=self._tradable_window)

    def plan_inputs(self, calendar: DataResult) -> StrategyInputPlan:
        """Derive named input requirements from a caller-prepared calendar."""
        return plan_inputs(strategy=self._identity, algorithm=self._algorithm,
                           tradable_window=self._tradable_window, calendar=calendar)

    @property
    def input_binding(self) -> StrategyInputBinding:
        if self._input_binding is None:
            raise RuntimeContractError("strategy data is not prepared; call prepare_data() first")
        return self._input_binding

    def prepare_data(self, *, binding: StrategyInputBinding | None = None,
                     policy: PreparePolicy | None = None) -> DataPreparationResult:
        """Prepare explicitly selected inputs, or read an existing binding offline."""
        if (binding is None) == (policy is None):
            raise RuntimeContractError("provide exactly one input binding or preparation policy")
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
        save_prepared_inputs(inputs, self._data_dir, binding=binding)
        self._input_binding = binding
        self._prepared_data = prepared
        return self._summary(prepared)

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
        frames = {name: result.dataframe for name, result in data._inputs.results.items()}
        if mode is SignalHistoryMode.CONTINUOUS:
            dates = data.calculation_dates()
        elif mode is SignalHistoryMode.WINDOW:
            dates = tuple(dict.fromkeys(data._inputs.signal_dates.values()))
        else:
            raise RuntimeContractError(f"unsupported calculation mode: {mode}")
        sessions = pd.DatetimeIndex(
            pd.to_datetime(dates, errors="raise"), name="dt"
        ).normalize()
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
        if mode is SignalHistoryMode.WINDOW and not actual_sessions.equals(sessions):
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
        if signal_session not in history.index:
            raise RuntimeContractError(
                "strategy history does not reach the signal date: "
                f"signal={signal_date.isoformat()}, "
                f"range={history.index.min()}..{history.index.max()}"
            )
        row = history.loc[signal_session]
        target_position = float(row["target_position"])
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
                previous = history["target_position"].shift(1, fill_value=0.0).loc[signal_session]
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
            evidence=evidence,
            next_state={
                "signal_date": signal_date.isoformat(),
                "target_position": target_position,
            },
        )

    def inspect_signals(
        self, *, history_mode: SignalHistoryMode = SignalHistoryMode.WINDOW,
    ) -> pd.DataFrame:
        """Return defensive history; default WINDOW matches run_window initialization."""

        data = self._prepared()
        history, _ = self._history(data, history_mode)
        return history.copy()

    def inspect_price_history(self) -> pd.DataFrame:
        """Return adjusted daily prices without exposing strategy input datasets."""

        return self._prepared().adjusted_daily

    def plan_at(
        self,
        *,
        point: TradingPoint,
        portfolio: PortfolioSnapshot,
        state: ExecutionState,
        history_mode: SignalHistoryMode = SignalHistoryMode.CONTINUOUS,
    ) -> ExecutionPlan:
        """Plan with continuous warmup state, or explicitly match WINDOW replay history."""

        return self._plan_at(
            point=point,
            portfolio=portfolio,
            state=state,
            history_mode=history_mode,
        )

    def _plan_at(
        self,
        *,
        point: TradingPoint,
        portfolio: PortfolioSnapshot,
        state: ExecutionState,
        history_mode: SignalHistoryMode,
    ) -> ExecutionPlan:
        data = self._prepared()
        if not self._tradable_window.contains(point.trading_date):
            raise RuntimeContractError("trading point is outside the strategy window")
        if portfolio.symbol != self._identity.symbol:
            raise RuntimeContractError("portfolio symbol differs from strategy")
        if portfolio.as_of > point.calculation_time or state.as_of > point.calculation_time:
            raise RuntimeContractError("planning state is newer than calculation time")

        signal_date = data.signal_date_for(point.trading_date)
        signal_available_at = datetime.combine(
            signal_date, time(15, 0), tzinfo=_SHANGHAI,
        )
        if point.calculation_time.astimezone(_SHANGHAI) < signal_available_at:
            raise RuntimeContractError(
                "calculation time precedes the signal-session close"
            )
        signal = self._calculate_signal(data, point, history_mode)
        if signal.evidence.get("signal_date") != signal_date.isoformat():
            raise RuntimeContractError("strategy signal evidence refers to another date")
        references = data.price_reference(signal_date, point.trading_date)
        raw = dict(
            build_execution_plan(
                deployment_settings={"cycle_target_quantity": state.cycle_target_quantity},
                available_cash=float(portfolio.available_cash),
                position_quantity=portfolio.position_quantity,
                target_position=signal.target_position,
                policy=self._execution_policy,
                signal_reference_price=float(references.signal_price),
                execution_reference_price=float(references.execution_price),
            )
        )
        orders = tuple(_planned_order(value) for value in raw.get("orders", ()))
        legs = tuple(
            PlanLeg(
                sequence=int(value["sequence"]),
                role=str(value["role"]),
                checkpoint=str(value["checkpoint"]),
                submit_after=_parse_time(value["submit_after"], "submit_after"),
                submit_before=_parse_time(value["submit_before"], "submit_before"),
                dependency_sequence=(
                    None
                    if value.get("dependency_sequence") is None
                    else int(value["dependency_sequence"])
                ),
                dependency_required_status=(
                    None
                    if value.get("dependency_required_status") is None
                    else str(value["dependency_required_status"])
                ),
                order=_planned_order(dict(value["order"])),
            )
            for value in raw.get("plan_legs", ())
        )
        required_orders = tuple(
            sorted(
                {order.order_type for order in orders} | {leg.order.order_type for leg in legs},
                key=lambda value: value.value,
            )
        )
        required_checkpoints = tuple(sorted({leg.checkpoint for leg in legs}))
        signal_identity = signal_identity_for(
            strategy=self._identity,
            signal_date=signal_date,
            target_position=signal.target_position,
            input_identities=data.input_identities,
            price_identities=data.price_identities,
        )
        cycle_target = int(raw["cycle_target_quantity"])
        target_quantity = int(raw["target_quantity"])
        plan_mode = str(raw.get("plan_mode", "NONE"))
        capital_mode, allocation_fraction = _capital_terms(
            raw=raw,
            execution_policy=self._execution_policy,
        )
        plan_identity = plan_identity_for(
            signal_identity=signal_identity,
            actual_quantity=portfolio.position_quantity,
            target_quantity=target_quantity,
            cycle_target_quantity=cycle_target,
            plan_mode=plan_mode,
            capital_mode=capital_mode,
            allocation_fraction=allocation_fraction,
            orders=orders,
            legs=legs,
        )
        return ExecutionPlan(
            strategy=self._identity,
            signal_identity=signal_identity,
            plan_identity=plan_identity,
            symbol=self._identity.symbol,
            signal_date=signal_date,
            trading_date=point.trading_date,
            generated_at=point.calculation_time,
            expected_portfolio_revision=portfolio.revision,
            expected_state_revision=state.revision,
            actual_quantity=portfolio.position_quantity,
            target_quantity=target_quantity,
            cycle_target_quantity=cycle_target,
            target_position=signal.target_position,
            action=str(raw["action"]),
            plan_mode=plan_mode,
            capital_mode=capital_mode,
            allocation_fraction=allocation_fraction,
            orders=orders,
            legs=legs,
            available_cash=portfolio.available_cash,
            fee_rate=Decimal(str(raw["fee_rate"])),
            estimated_order_cost=Decimal(str(raw["estimated_order_cost"])),
            unallocated_cash=Decimal(str(raw["unallocated_cash"])),
            references=references,
            required_capabilities=ExecutionCapabilities(
                required_orders,
                required_checkpoints,
            ),
            input_identities=data.input_identities,
            price_identities=data.price_identities,
            evidence=MappingProxyType(dict(signal.evidence)),
        )

    def run_window(self, *, executor: WindowExecutor):
        """Replay WINDOW history and finish only after every plan is SETTLED."""
        data = self._prepared()
        capabilities = executor.capabilities
        if not isinstance(capabilities, ExecutionCapabilities):
            raise RuntimeContractError("executor capabilities must be ExecutionCapabilities")
        missing_orders = set(self.definition.capabilities.order_types) - {
            item.value for item in capabilities.order_types
        }
        missing_checkpoints = set(self.definition.capabilities.checkpoints) - set(capabilities.checkpoints)
        if missing_orders or missing_checkpoints:
            raise RuntimeCompatibilityError(
                "window executor lacks required capabilities before execution: "
                f"order_types={sorted(missing_orders)}, checkpoints={sorted(missing_checkpoints)}"
            )
        for trading_date in data.trading_dates():
            signal_date = data.signal_date_for(trading_date)
            point = TradingPoint(
                trading_date,
                datetime.combine(signal_date, time(20, 31), tzinfo=_SHANGHAI),
            )
            portfolio, state = executor.snapshot(point)
            plan = self._plan_at(
                point=point,
                portfolio=portfolio,
                state=state,
                history_mode=SignalHistoryMode.WINDOW,
            )
            missing_orders = set(plan.required_capabilities.order_types) - set(
                executor.capabilities.order_types
            )
            missing_checkpoints = set(plan.required_capabilities.checkpoints) - set(
                executor.capabilities.checkpoints
            )
            if missing_orders or missing_checkpoints:
                raise RuntimeCompatibilityError(
                    "window executor lacks required capabilities: "
                    f"order_types={sorted(value.value for value in missing_orders)}, "
                    f"checkpoints={sorted(missing_checkpoints)}"
                )
            outcome = executor.execute(plan)
            if not isinstance(outcome, ExecutionOutcome):
                raise RuntimeContractError("executor must return ExecutionOutcome")
            if outcome.plan_identity != plan.plan_identity:
                raise RuntimeContractError("executor outcome refers to another plan")
            if outcome.status is not ExecutionOutcomeStatus.SETTLED:
                raise RuntimeExecutionError(f"window executor did not settle the plan: {plan.plan_identity}")
        return executor.finish()
