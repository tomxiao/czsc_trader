"""Deterministic historical executor for channel-neutral SRT plans."""

from __future__ import annotations

from strategy_runtime import ExecutionOutcomeStatus

from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from math import isfinite
import pandas as pd
from strategy_runtime import (
    ExecutionCapabilities,
    ExecutionOutcome,
    ExecutionPlan,
    ExecutionState,
    ExecutionPolicy,
    OrderType,
    PortfolioSnapshot,
    RuntimeContractError,
    TradingPoint,
)
from .fills import OrderSpec, resolve_fill
from .result import ExecutionResult


def _id(prefix: str, *parts: object) -> str:
    raw = "|".join(map(str, parts)).encode()
    return f"{prefix}-" + sha256(raw).hexdigest()[:20].upper()


def _frame(rows: list[dict[str, object]], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=columns)


def _prices(frame: pd.DataFrame, name: str, columns: tuple[str, ...]) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or not {"dt", *columns}.issubset(frame.columns):
        raise RuntimeContractError(f"{name} price columns are incomplete")
    value = frame.copy()
    # Preserve source evidence without copying it through every price lookup.
    value.attrs = {}
    try:
        value["dt"] = pd.to_datetime(value["dt"], errors="raise")
        indexed = value.set_index("dt").sort_index()
        indexed.index = pd.DatetimeIndex(indexed.index, name="dt")
        valid = all(
            indexed[column].map(lambda price: isfinite(float(price)) and float(price) > 0).all()
            for column in columns
        )
    except (ValueError, TypeError) as exc:
        raise RuntimeContractError(f"{name} has invalid prices or timestamps") from exc
    if indexed.index.hasnans or indexed.index.has_duplicates or indexed.index.tz is not None:
        raise RuntimeContractError(f"{name} requires unique local exchange timestamps")
    if not valid:
        raise RuntimeContractError(f"{name} prices must be positive and finite")
    return indexed


def _overlay_checkpoints(
    frame: pd.DataFrame,
) -> dict[pd.Timestamp, tuple[tuple[float, ...], tuple[float, ...]]]:
    """Index prices once, retaining duplicate checkpoints for execution-time validation."""
    clocks = frame["dt"].dt.strftime("%H:%M")
    selected = frame.loc[clocks.isin(("09:35", "11:30"))].copy()
    selected["session"] = selected["dt"].dt.normalize()
    selected["clock"] = clocks.loc[selected.index]
    return {
        session: (
            tuple(float(value) for value in day.loc[day["clock"].eq("09:35"), "open"]),
            tuple(float(value) for value in day.loc[day["clock"].eq("11:30"), "close"]),
        )
        for session, day in selected.groupby("session")
    }


class HistoricalExecutor:
    """Execute SRT plans for search, replay and review without host dependencies.

    Create one executor per trial/account. Input frames are copied on admission;
    immutable source data can therefore be shared by independent trials.
    """

    def __init__(
        self,
        *,
        strategy_reference: str,
        symbol: str,
        execution_daily: pd.DataFrame,
        execution_intraday: pd.DataFrame,
        evaluation_start: pd.Timestamp,
        evaluation_end: pd.Timestamp,
        initial_cash: float,
        execution_policy: ExecutionPolicy,
        order_types: tuple[str, ...],
        checkpoints: tuple[str, ...] = (),
        account_id: str = "backtest-account",
        execution_five_minute: pd.DataFrame | None = None,
    ) -> None:
        if not account_id.strip():
            raise RuntimeContractError("backtest account_id must be non-empty")
        if not isfinite(initial_cash) or initial_cash <= 0:
            raise RuntimeContractError("backtest initial_cash must be positive and finite")
        if execution_policy.policy_type not in {"FROZEN_RULE", "INTRADAY_OVERLAY"}:
            raise RuntimeContractError(
                f"unsupported backtest execution policy: {execution_policy.policy_type}"
            )
        self._account_id = account_id.strip()
        self._capabilities = ExecutionCapabilities(
            tuple(OrderType(value) for value in order_types), checkpoints
        )
        if not strategy_reference.strip():
            raise RuntimeContractError("strategy_reference must be non-empty")
        self._strategy_reference = strategy_reference
        if not symbol.strip():
            raise RuntimeContractError("backtest symbol must be non-empty")
        self._strategy_symbol = symbol.strip().upper()
        self._policy = execution_policy
        try:
            configured_fee = (
                execution_policy.settings["capital"]["fee_rate"]
                if execution_policy.policy_type == "FROZEN_RULE"
                else execution_policy.settings["one_way_cost"]
            )
            self._configured_fee_rate = Decimal(str(configured_fee))
        except (InvalidOperation, KeyError, TypeError, ValueError) as exc:
            raise RuntimeContractError("historical execution policy has no valid fee rate") from exc
        if not self._configured_fee_rate.is_finite() or not 0 <= self._configured_fee_rate < 1:
            raise RuntimeContractError("historical execution policy fee rate must be in [0, 1)")
        self._initial_cash = float(initial_cash)
        self._daily = _prices(execution_daily, "execution daily", ("open", "close"))
        self._intraday = _prices(execution_intraday, "execution intraday", ("high", "low"))
        self._overlay_checkpoints = (
            None
            if execution_five_minute is None
            else _overlay_checkpoints(
                _prices(execution_five_minute, "execution 5m", ("open", "close")).reset_index()
            )
        )
        start = pd.Timestamp(evaluation_start).normalize()
        end = pd.Timestamp(evaluation_end).normalize()
        if start > end or start not in self._daily.index or end not in self._daily.index:
            raise RuntimeContractError(
                "execution prices do not cover the declared evaluation sessions"
            )
        self._evaluation = self._daily.loc[
            pd.Timestamp(evaluation_start).normalize() : pd.Timestamp(evaluation_end).normalize()
        ]
        if self._evaluation.empty:
            raise RuntimeContractError("historical executor evaluation interval is empty")

        self._cash = self._initial_cash
        self._quantity = 0
        self._cycle_target: int | None = None
        self._cycle_id: str | None = None
        self._revision = 0
        self._last_execution: pd.Timestamp | None = None
        self._plans: dict[str, ExecutionPlan] = {}
        self._outcomes: dict[str, ExecutionOutcome] = {}
        self._decision_rows: list[dict[str, object]] = []
        self._order_rows: list[dict[str, object]] = []
        self._fill_rows: list[dict[str, object]] = []
        self._trade_rows: list[dict[str, object]] = []
        self._state_by_date: dict[pd.Timestamp, dict[str, object]] = {}
        self._open_trade: dict[str, object] | None = None
        self._result: ExecutionResult | None = None

        self._opening_cash = self._cash
        self._opening_quantity = self._quantity

    @property
    def capabilities(self) -> ExecutionCapabilities:
        return self._capabilities

    def snapshot(self, point: TradingPoint) -> tuple[PortfolioSnapshot, ExecutionState]:
        """Return the confirmed ledger and strategy state for one signal point."""

        as_of = point.calculation_time
        if as_of.tzinfo is None:
            raise RuntimeContractError("backtest account snapshot time must be timezone-aware")
        session = pd.Timestamp(as_of.date())
        prices = self._daily.loc[self._daily.index <= session, "close"]
        if prices.empty:
            raise RuntimeContractError("backtest account snapshot has no reference close")
        total_assets = self._cash + self._quantity * float(prices.iloc[-1])
        return PortfolioSnapshot(
            self._account_id,
            self._strategy_symbol,
            Decimal(str(self._cash)),
            Decimal(str(total_assets)),
            self._quantity,
            self._revision,
            as_of,
        ), ExecutionState(self._revision, as_of, self._cycle_target)

    def execute(self, plan: ExecutionPlan) -> ExecutionOutcome:
        if self._result is not None:
            raise RuntimeContractError("historical executor is already finalized")
        key = plan.plan_identity
        existing = self._plans.get(key)
        if existing is not None:
            if existing != plan:
                raise RuntimeContractError("plan identity was reused for another plan")
            return self._outcomes[key]
        self._validate_plan(plan)

        signal_date = pd.Timestamp(plan.signal_date).normalize()
        execution_date = pd.Timestamp(plan.trading_date).normalize()
        fee_rate = float(plan.fee_rate)
        if not isfinite(fee_rate) or not 0 <= fee_rate < 1:
            raise RuntimeContractError("execution fee_rate must be finite and in [0, 1)")
        should_record = True
        if self._policy.policy_type == "INTRADAY_OVERLAY" and plan.legs:
            self._execute_overlay(plan, signal_date, execution_date)
        elif self._policy.policy_type == "INTRADAY_OVERLAY":
            self._state_by_date[execution_date] = {
                "signal_date": signal_date,
                "target_position": float(self._policy.settings["core_fraction"]),
                "cash_before": self._cash,
                "quantity_before": self._quantity,
                "cash": self._cash,
                "quantity": self._quantity,
            }
            should_record = False
        else:
            self._execute_target(plan, signal_date, execution_date)
        if should_record:
            self._record_decision(plan, signal_date, execution_date)
        self._revision += 1
        self._last_execution = execution_date

        outcome = ExecutionOutcome(
            plan_identity=key,
            portfolio=self.snapshot(
                TradingPoint(
                    plan.trading_date,
                    datetime.combine(
                        plan.trading_date,
                        time(15, 0),
                        tzinfo=plan.generated_at.tzinfo,
                    ),
                )
            )[0],
            state=ExecutionState(
                self._revision,
                datetime.combine(
                    plan.trading_date,
                    time(15, 0),
                    tzinfo=plan.generated_at.tzinfo,
                ),
                self._cycle_target,
            ),
            status=ExecutionOutcomeStatus.SETTLED,
        )
        self._plans[key] = plan
        self._outcomes[key] = outcome
        return outcome

    def finish(self) -> ExecutionResult:
        """Close the deterministic ledger exactly once."""

        if self._result is not None:
            return self._result
        if self._policy.policy_type == "FROZEN_RULE":
            submitted = pd.DatetimeIndex(sorted(self._state_by_date))
            expected = pd.DatetimeIndex(self._evaluation.index)
            if not submitted.equals(expected):
                missing = expected.difference(submitted)
                unexpected = submitted.difference(expected)
                raise RuntimeContractError(
                    "historical executor has incomplete target-position plans: "
                    f"missing={[item.date().isoformat() for item in missing]}, "
                    f"unexpected={[item.date().isoformat() for item in unexpected]}"
                )

        account_rows = self._account_daily_rows()
        trades = list(self._trade_rows)
        if self._open_trade is not None:
            entry_quantity = int(self._open_trade["quantity"])
            entry_gross = float(self._open_trade["gross"])
            trades.append(
                {
                    "cycle_id": self._open_trade["cycle_id"],
                    "status": "OPEN",
                    "entry_date": self._open_trade["entry_date"],
                    "exit_date": pd.NaT,
                    "quantity": entry_quantity,
                    "entry_price": entry_gross / entry_quantity,
                    "exit_price": float("nan"),
                    "net_return": float("nan"),
                }
            )
        order_columns = [
            "order_id",
            "decision_id",
            "cycle_id",
            "signal_date",
            "execution_date",
            "side",
            "quantity",
            "order_type",
            "limit_price",
            "status",
        ]
        if self._policy.policy_type == "INTRADAY_OVERLAY":
            order_columns.extend(("checkpoint", "role"))
        self._result = ExecutionResult(
            decisions=pd.DataFrame(self._decision_rows),
            orders=_frame(self._order_rows, order_columns),
            fills=_frame(
                self._fill_rows,
                [
                    "fill_id",
                    "order_id",
                    "decision_id",
                    "cycle_id",
                    "signal_date",
                    "fill_time",
                    "side",
                    "quantity",
                    "price",
                    "fees",
                    "trigger",
                ],
            ),
            account_daily=pd.DataFrame(account_rows),
            trades=_frame(
                trades,
                [
                    "cycle_id",
                    "status",
                    "entry_date",
                    "exit_date",
                    "quantity",
                    "entry_price",
                    "exit_price",
                    "net_return",
                ],
            ),
        )
        return self._result

    @staticmethod
    def _decision_id(plan: ExecutionPlan) -> str:
        return "DEC-" + plan.plan_identity[:20].upper()

    def _validate_plan(self, plan: ExecutionPlan) -> None:
        if plan.fee_rate != self._configured_fee_rate:
            raise RuntimeContractError(
                "historical plan fee rate differs from execution policy"
            )
        execution_date = pd.Timestamp(plan.trading_date).normalize()
        signal_date = pd.Timestamp(plan.signal_date).normalize()
        if signal_date >= execution_date:
            raise RuntimeContractError("historical execution must follow the signal session")
        if signal_date not in self._daily.index:
            raise RuntimeContractError("historical execution is missing its signal session")
        if plan.strategy.reference_id != self._strategy_reference:
            raise RuntimeContractError("plan belongs to another strategy")
        if plan.symbol != self._strategy_symbol:
            raise RuntimeContractError("plan belongs to another instrument")
        if execution_date not in self._evaluation.index:
            raise RuntimeContractError("historical plan is outside the evaluation interval")
        if self._last_execution is not None and execution_date <= self._last_execution:
            raise RuntimeContractError("historical plans must use increasing sessions")
        if plan.expected_state_revision != self._revision:
            raise RuntimeContractError("historical plan execution state is stale")
        if plan.expected_portfolio_revision != self._revision:
            raise RuntimeContractError("historical plan portfolio revision is stale")
        if plan.actual_quantity != self._quantity:
            raise RuntimeContractError("historical plan position differs from ledger")
        if abs(float(plan.available_cash) - self._cash) > 1e-6:
            raise RuntimeContractError("historical plan cash differs from ledger")

    def _execute_target(
        self,
        plan: ExecutionPlan,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> None:
        price_row = self._evaluation.loc[execution_date]
        cash_before = self._cash
        quantity_before = self._quantity
        target = int(plan.target_position)
        decision_id = self._decision_id(plan)
        if target == 1 and self._quantity == 0 and self._cycle_id is None:
            self._cycle_id = _id("CYC", self._strategy_reference, signal_date)
        exit_time: pd.Timestamp | None = None
        exit_quantity = 0
        fee_rate = float(plan.fee_rate)
        day_bars = self._intraday.loc[
            self._intraday.index.normalize() == execution_date.normalize()
        ]
        for slice_number, order in enumerate(plan.orders, start=1):
            order_id = _id("ORD", decision_id, execution_date, slice_number)
            side = order.side.value
            quantity = order.quantity
            order_type = order.order_type.value
            limit_price = (
                None if order.limit_price is None else float(order.limit_price)
            )
            touch_column = "low" if side == "BUY" else "high"
            fill = resolve_fill(
                OrderSpec(
                    side, order_type, quantity, limit_price
                ),
                session_open=float(price_row["open"]),
                session_time=execution_date.to_pydatetime(),
                intraday_touches=[
                    (pd.Timestamp(timestamp).to_pydatetime(), float(value))
                    for timestamp, value in day_bars[touch_column].items()
                ],
            )
            trigger = fill.trigger
            fill_price = fill.price
            fill_time = None if fill.filled_at is None else pd.Timestamp(fill.filled_at)
            if side == "BUY":
                required = (
                    quantity * fill_price * (1.0 + fee_rate) if fill_price is not None else None
                )
                if required is not None and required > self._cash + 1e-8:
                    trigger = fill_price = fill_time = None
            self._order_rows.append(
                {
                    "order_id": order_id,
                    "decision_id": decision_id,
                    "cycle_id": self._cycle_id,
                    "signal_date": signal_date,
                    "execution_date": execution_date,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "limit_price": limit_price,
                    "status": "FILLED" if fill_price is not None else "UNFILLED",
                }
            )
            if fill_price is None or fill_time is None:
                continue
            gross = quantity * fill_price
            fees = gross * fee_rate
            if side == "BUY":
                self._cash -= gross + fees
                self._quantity += quantity
            else:
                self._cash += gross - fees
                self._quantity -= quantity
            self._fill_rows.append(
                {
                    "fill_id": _id("FIL", order_id, fill_time),
                    "order_id": order_id,
                    "decision_id": decision_id,
                    "cycle_id": self._cycle_id,
                    "signal_date": signal_date,
                    "fill_time": fill_time,
                    "side": side,
                    "quantity": quantity,
                    "price": fill_price,
                    "fees": fees,
                    "trigger": trigger,
                }
            )
            if side == "BUY":
                if self._open_trade is None:
                    self._open_trade = {
                        "cycle_id": self._cycle_id,
                        "entry_date": fill_time,
                        "quantity": 0,
                        "gross": 0.0,
                        "fees": 0.0,
                        "exit_proceeds": 0.0,
                        "exit_fees": 0.0,
                        "exit_quantity": 0,
                    }
                self._open_trade["quantity"] = int(self._open_trade["quantity"]) + quantity
                self._open_trade["gross"] = float(self._open_trade["gross"]) + gross
                self._open_trade["fees"] = float(self._open_trade["fees"]) + fees
            else:
                if self._open_trade is not None:
                    self._open_trade["exit_proceeds"] = float(self._open_trade["exit_proceeds"]) + (gross - fees)
                    self._open_trade["exit_fees"] = float(self._open_trade["exit_fees"]) + fees
                    self._open_trade["exit_quantity"] = int(self._open_trade["exit_quantity"]) + quantity
                exit_time = fill_time
                exit_quantity += quantity
        if (
            exit_quantity
            and self._quantity == 0
            and self._open_trade is not None
            and exit_time is not None
        ):
            entry_quantity = int(self._open_trade["quantity"])
            entry_gross = float(self._open_trade["gross"])
            entry_cost = entry_gross + float(self._open_trade["fees"])
            exit_proceeds = float(self._open_trade["exit_proceeds"])
            exit_fees = float(self._open_trade["exit_fees"])
            cycle_exit_quantity = int(self._open_trade["exit_quantity"])
            self._trade_rows.append(
                {
                    "cycle_id": self._cycle_id,
                    "status": "CLOSED",
                    "entry_date": self._open_trade["entry_date"],
                    "exit_date": exit_time,
                    "quantity": entry_quantity,
                    "entry_price": entry_gross / entry_quantity,
                    "exit_price": (exit_proceeds + exit_fees) / cycle_exit_quantity,
                    "net_return": exit_proceeds / entry_cost - 1.0,
                }
            )
            self._open_trade = None
        self._cycle_target = plan.cycle_target_quantity
        if target == 0 and self._quantity == 0:
            self._cycle_target = None
            self._cycle_id = None
        self._state_by_date[execution_date] = {
            "signal_date": signal_date,
            "target_position": target,
            "cash_before": cash_before,
            "quantity_before": quantity_before,
            "cash": self._cash,
            "quantity": self._quantity,
        }

    def _execute_overlay(
        self,
        plan: ExecutionPlan,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> None:
        if plan.plan_mode not in {"CORE_SETUP", "CORE_EVENT_INTRADAY_ROTATION"}:
            raise RuntimeContractError(f"unsupported historical overlay plan: {plan.plan_mode}")
        core_setup = plan.plan_mode == "CORE_SETUP"
        if core_setup and (self._quantity != 0 or self._cycle_target is not None):
            raise RuntimeContractError("historical overlay core setup requires an empty account")
        if not core_setup and self._cycle_target is None:
            raise RuntimeContractError("historical overlay rotation requires a sellable core")
        checkpoints = self._overlay_checkpoints
        if checkpoints is None:
            raise RuntimeContractError("intraday overlay requires 5m execution data")
        opening, closing = checkpoints.get(execution_date, ((), ()))
        if len(opening) != 1 or len(closing) != 1:
            raise RuntimeContractError("intraday overlay has incomplete execution checkpoints")
        cash_before = self._cash
        quantity_before = self._quantity
        decision_id = self._decision_id(plan)
        cycle_id = _id("CYC", decision_id, execution_date)
        fee_rate = float(plan.fee_rate)
        leg_status: dict[int, str] = {}
        entry_price = 0.0
        exit_price = 0.0
        trade_quantity = 0
        for leg in plan.legs:
            sequence = leg.sequence
            dependency = leg.dependency_sequence
            if dependency is not None and leg_status.get(int(dependency)) != "FILLED_ALL":
                leg_status[sequence] = "BLOCKED"
                continue
            order = leg.order
            side = order.side.value
            quantity = order.quantity
            order_type = order.order_type.value
            checkpoint = leg.checkpoint
            reference = opening[0] if checkpoint == "OPEN" else closing[0]
            limit_price = (
                None if order.limit_price is None else float(order.limit_price)
            )
            can_fill = (
                order_type == "MARKET"
                or (
                    limit_price is not None
                    and side == "BUY"
                    and reference <= limit_price
                )
                or (
                    limit_price is not None
                    and side == "SELL"
                    and reference >= limit_price
                )
            )
            if side == "BUY" and can_fill:
                can_fill = quantity * reference * (1.0 + fee_rate) <= self._cash + 1e-8
            status = "FILLED" if can_fill else "UNFILLED"
            leg_status[sequence] = "FILLED_ALL" if can_fill else status
            order_id = _id("ORD", cycle_id, side)
            self._order_rows.append(
                {
                    "order_id": order_id,
                    "decision_id": decision_id,
                    "cycle_id": cycle_id,
                    "signal_date": signal_date,
                    "execution_date": execution_date,
                    "side": side,
                    "quantity": quantity,
                    "order_type": order_type,
                    "limit_price": limit_price,
                    "status": status,
                    "checkpoint": checkpoint,
                    "role": leg.role,
                }
            )
            if not can_fill:
                continue
            fees = quantity * reference * fee_rate
            if side == "BUY":
                self._cash -= quantity * reference + fees
                self._quantity += quantity
                entry_price = reference
                trade_quantity = quantity
            else:
                self._cash += quantity * reference - fees
                self._quantity -= quantity
                exit_price = reference
            fill_time = (
                execution_date + pd.Timedelta(hours=9, minutes=30)
                if checkpoint == "OPEN"
                else execution_date + pd.Timedelta(hours=11, minutes=30)
            )
            self._fill_rows.append(
                {
                    "fill_id": _id("FIL", order_id, checkpoint),
                    "order_id": order_id,
                    "decision_id": decision_id,
                    "cycle_id": cycle_id,
                    "signal_date": signal_date,
                    "fill_time": fill_time,
                    "side": side,
                    "quantity": quantity,
                    "price": reference,
                    "fees": fees,
                    "trigger": checkpoint,
                }
            )
        if not core_setup and entry_price and exit_price and trade_quantity:
            self._trade_rows.append(
                {
                    "cycle_id": cycle_id,
                    "status": "CLOSED",
                    "entry_date": execution_date + pd.Timedelta(hours=9, minutes=30),
                    "exit_date": execution_date + pd.Timedelta(hours=11, minutes=30),
                    "quantity": trade_quantity,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "net_return": exit_price * (1.0 - fee_rate) / (entry_price * (1.0 + fee_rate))
                    - 1.0,
                }
            )
        if core_setup:
            self._cycle_target = plan.cycle_target_quantity if self._quantity else None
            if self._quantity and self._quantity != self._cycle_target:
                raise RuntimeContractError("intraday overlay core setup quantity is inconsistent")
        elif self._quantity != self._cycle_target:
            raise RuntimeContractError("intraday overlay did not restore its sellable core")
        self._state_by_date[execution_date] = {
            "signal_date": signal_date,
            "target_position": float(self._policy.settings["core_fraction"]),
            "cash_before": cash_before,
            "quantity_before": quantity_before,
            "cash": self._cash,
            "quantity": self._quantity,
        }

    def _record_decision(
        self,
        plan: ExecutionPlan,
        signal_date: pd.Timestamp,
        execution_date: pd.Timestamp,
    ) -> None:
        row: dict[str, object] = {
            "decision_id": self._decision_id(plan),
            "signal_date": signal_date,
            "valid_session": execution_date,
            "target_position": plan.target_position,
            "plan_mode": plan.plan_mode,
        }
        for key, value in plan.evidence.items():
            if key not in row:
                row[key] = value
        self._decision_rows.append(row)

    def _account_daily_rows(self) -> list[dict[str, object]]:
        cash = self._opening_cash
        quantity = self._opening_quantity
        rows: list[dict[str, object]] = []
        for day, price_row in self._evaluation.iterrows():
            state = self._state_by_date.get(pd.Timestamp(day))
            if state is None:
                cash_before = cash
                quantity_before = quantity
                signal_date = pd.NaT
                target = (
                    float(self._policy.settings["core_fraction"])
                    if self._policy.policy_type == "INTRADAY_OVERLAY"
                    else float(quantity > 0)
                )
            else:
                cash_before = float(state["cash_before"])
                quantity_before = int(state["quantity_before"])
                cash = float(state["cash"])
                quantity = int(state["quantity"])
                signal_date = state["signal_date"]
                target = state["target_position"]
            rows.append(
                {
                    "date": pd.Timestamp(day),
                    "signal_date": signal_date,
                    "target_position": target,
                    "cash_before": cash_before,
                    "quantity_before": quantity_before,
                    "cash": cash,
                    "quantity": quantity,
                    "close": float(price_row["close"]),
                    "equity": cash + quantity * float(price_row["close"]),
                }
            )
        return rows
