"""Research prototype: fixed May30 H10 cycle plus fixed June19 actual-entry sale."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from enum import Enum

import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset
from strategy_runtime import (
    CalculationScope, CutoffRule, DecisionContract, ExecutionPolicy, InputContract,
    InputRequirement, MonitoringPolicy, ObservationDefinition, ObservationSeries,
    ParameterSet, RequiredCapabilities, StrategyDefinition, StrategyImplementation,
)
from trading_execution_engine import DailyQuote, OrderSpec, SessionPriceLimits, resolve_fill

EVALUATION_START = pd.Timestamp("2020-01-02")
FIXED_ENTRY_DATE = date(2025, 5, 30)
FIXED_FORCE_DATE = date(2025, 6, 19)
OBSERVED = (
    "ready", "support_ok", "warmup_sessions", "held_at_close", "buy_filled_today",
    "sell_filled_today", "failed_buy_reset", "entry_signal", "exit_pending",
    "support_break", "deadline_index", "entry_index", "reservation_index",
)
DIAGNOSTIC = (
    "cycle_mode_active", "target_entry_seen", "target_cycle_completed",
    "protected_cycle_active", "support_exit_suppressed", "deadline_exit_pending",
    "protected_sell_blocked", "fixed_cycle_entry_index", "fixed_cycle_deadline_index",
    "fixed_cycle_reservation_index",
)

JOINT_DIAGNOSTIC = (
    "joint_mode_active", "joint_node_eligible", "joint_trigger_today", "joint_done",
    "joint_target_cycle_entry_index", "joint_target_deadline_index",
    "joint_target_reservation_index", "joint_sale_blocked", "joint_actual_sale_today",
    "joint_target_cycle_completed",
)
DIAGNOSTIC = DIAGNOSTIC + JOINT_DIAGNOSTIC


class UnsupportedJointNodeError(ValueError):
    """The one fixed joint node is unavailable; no alternate date/position is chosen."""


class CycleMode(str, Enum):
    NOOP = "NOOP"
    HOLD_ORIGINAL_CYCLE_H10 = "HOLD_ORIGINAL_CYCLE_H10"
    JOINT = "JOINT"


@dataclass(frozen=True)
class JointConfig:
    mode: CycleMode
    entry_execution_date: date
    force_decision_date: date

    def __post_init__(self):
        if (type(self.mode) is not CycleMode or type(self.entry_execution_date) is not date
                or type(self.force_decision_date) is not date):
            raise ValueError("Typed cycle mode and execution date required")
        if self.entry_execution_date != FIXED_ENTRY_DATE:
            raise ValueError("Only original2025-05-30 execution cycle is allowed")
        if self.force_decision_date != FIXED_FORCE_DATE:
            raise ValueError("Only fixed2025-06-19 decision is allowed")

    @classmethod
    def parse(cls, values: Mapping):
        if not isinstance(values, Mapping) or set(values) != {"mode", "entry_execution_date", "force_decision_date"}:
            raise ValueError("Exactly mode, entry_execution_date and force_decision_date parameters required")
        mode, execution, force = values["mode"], values["entry_execution_date"], values["force_decision_date"]
        if type(mode) is not str or type(execution) is not str or type(force) is not str:
            raise ValueError("Canonical string parameters required")
        try:
            mode_value = CycleMode(mode)
            date_value = date.fromisoformat(execution)
            force_value = date.fromisoformat(force)
        except ValueError as exc:
            raise ValueError("Invalid cycle mode or canonical execution date") from exc
        if date_value.isoformat() != execution or force_value.isoformat() != force:
            raise ValueError("Canonical YYYY-MM-DD required")
        return cls(mode_value, date_value, force_value)


def tick(value, mode=ROUND_FLOOR):
    return float((Decimal(str(value)) / Decimal(".01")).to_integral_value(rounding=mode) * Decimal(".01"))


def buy_limit(previous_raw_close, previous_scale):
    return min(tick(previous_raw_close * 1.01),
               tick(tick(previous_raw_close * 1.1) - .01, ROUND_HALF_UP)) * previous_scale


def history(market, raw, limits, status, config: JointConfig):
    if type(config) is not JointConfig:
        raise ValueError("JointConfig required")
    protected_mode = config.mode in (CycleMode.HOLD_ORIGINAL_CYCLE_H10, CycleMode.JOINT)
    joint_mode = config.mode is CycleMode.JOINT
    reservation = -1
    market = market.set_index(pd.to_datetime(market.Date)).sort_index()
    raw = raw.set_index(pd.to_datetime(raw.Date)).reindex(market.index)
    bounds = limits.set_index(pd.to_datetime(limits.Date))
    states = status.set_index(pd.to_datetime(status.Date))
    if market.index.has_duplicates or raw.Close.isna().any():
        raise ValueError("Unique aligned prices required")
    scale = market.Close / raw.Close
    in_window = market.index >= EVALUATION_START
    counts = np.cumsum(in_window)
    # Preserve original prewindow, support and warmup definitions verbatim.
    support = market.Close.where(in_window).shift(1).rolling(5, min_periods=5).min()
    held = False
    entry = deadline = intent = None
    exit_pending = False
    target_seen = target_completed = False
    fixed_entry = fixed_deadline = fixed_reservation = -1
    joint_seen = joint_done = joint_completed = False
    joint_entry = joint_deadline = joint_reservation = -1
    rows = []
    for i, session in enumerate(market.index):
        bought = sold = blocked_sale = False
        joint_trigger = joint_blocked = joint_sold = False
        failed_buy = intent is not None and intent["side"] == "BUY"
        was_protected = protected_mode and held and entry == fixed_entry and not target_completed
        if intent is not None:
            if session not in states.index:
                raise ValueError("Missing stock trading status")
            state = states.loc[session, "Status"]
            if state not in ("TRADING", "SUSPENDED"):
                raise ValueError("Unknown trading status")
            blocked_sale = bool(was_protected and intent["side"] == "SELL")
            joint_blocked = bool(joint_mode and joint_done and not joint_completed
                                 and held and entry == joint_entry and intent["side"] == "SELL")
            if state == "TRADING":
                if session not in bounds.index:
                    raise ValueError("Missing price limits")
                bound, bar = bounds.loc[session], market.iloc[i]
                rule = SessionPriceLimits(session.date(), float(bound.DownLimit * scale.iloc[i]),
                                          float(bound.UpLimit * scale.iloc[i]), float(.01 * scale.iloc[i]))
                order = (OrderSpec("BUY", "LIMIT", 100, intent["limit"])
                         if intent["side"] == "BUY" else OrderSpec("SELL", "MARKET", 100))
                fill = resolve_fill(order, session_open=float(bar.Open),
                                    session_time=datetime.combine(session.date(), time(9, 30)),
                                    intraday_touches=(), daily_quote=DailyQuote(float(bar.Low), float(bar.High)),
                                    session_limits=rule)
                if fill.filled:
                    if intent["side"] == "BUY":
                        held = True
                        entry, deadline = i, i + 9
                        bought, failed_buy, exit_pending = True, False, False
                        reservation = i + 10
                        if session.date() == config.entry_execution_date:
                            if target_seen:
                                raise ValueError("Fixed execution cycle encountered twice")
                            target_seen = True
                            fixed_entry, fixed_deadline, fixed_reservation = entry, deadline, reservation
                    else:
                        if joint_mode and joint_done and entry == joint_entry:
                            joint_completed, joint_sold, joint_blocked = True, True, False
                        if target_seen and entry == fixed_entry:
                            target_completed = True
                        held, entry, deadline, sold, exit_pending = False, None, None, True, False
                        blocked_sale = False
        ready = bool(counts[i] >= 60 and np.isfinite(support.iloc[i]))
        support_ok = bool(np.isfinite(support.iloc[i]) and market.Close.iloc[i] >= support.iloc[i])
        support_break = bool(np.isfinite(support.iloc[i]) and market.Close.iloc[i] < support.iloc[i])
        protected = bool(protected_mode and held and entry == fixed_entry and target_seen and not target_completed)
        suppressed = bool(protected and support_break and i < deadline and not exit_pending)
        intent, target, accepted = None, 0., False
        if held:
            # Never clear existing pending; deadline always overrides support suppression.
            if i >= deadline or (support_break and not protected):
                exit_pending = True
            if exit_pending:
                intent = {"side": "SELL"}
            else:
                target = 1.
        elif not failed_buy and ready and i >= reservation and support_ok:
            intent = {"side": "BUY", "limit": buy_limit(float(raw.Close.iloc[i]), float(scale.iloc[i]))}
            target, accepted = 1., True
        joint_eligible = bool(session.date() == config.force_decision_date and target_completed
                              and bought and held and entry == i and entry != fixed_entry
                              and target == 1. and not exit_pending and not accepted
                              and deadline == i + 9 and reservation == i + 10)
        if joint_mode and session.date() == config.force_decision_date:
            if joint_seen or not joint_eligible:
                raise UnsupportedJointNodeError("UNSUPPORTED_FIXED_JUNE19_NODE: actual same-day BUY and original HOLD required")
            joint_seen = joint_done = joint_trigger = True
            joint_entry, joint_deadline, joint_reservation = entry, deadline, reservation
            # One intent change at the fixed D, actual full inventory sold under original rules.
            exit_pending, intent, target = True, {"side": "SELL"}, 0.
        rows.append(dict(target_position=target, ready=ready, support_ok=support_ok,
                         support_floor=support.iloc[i], warmup_sessions=int(counts[i]),
                         held_at_close=held, buy_filled_today=bought, sell_filled_today=sold,
                         failed_buy_reset=failed_buy, entry_signal=accepted,
                         holding_horizon=10 if held or accepted else 0, exit_pending=exit_pending,
                         support_break=support_break, deadline_index=deadline if deadline is not None else -1,
                         entry_index=entry if entry is not None else -1, reservation_index=reservation,
                         cycle_mode_active=float(protected_mode), target_entry_seen=float(target_seen),
                         target_cycle_completed=float(target_completed), protected_cycle_active=float(protected),
                         support_exit_suppressed=float(suppressed),
                         deadline_exit_pending=float(protected and i >= deadline and exit_pending),
                         protected_sell_blocked=float(blocked_sale), fixed_cycle_entry_index=float(fixed_entry),
                         fixed_cycle_deadline_index=float(fixed_deadline),
                         fixed_cycle_reservation_index=float(fixed_reservation),
                         joint_mode_active=float(joint_mode), joint_node_eligible=float(joint_eligible),
                         joint_trigger_today=float(joint_trigger), joint_done=float(joint_done),
                         joint_target_cycle_entry_index=float(joint_entry),
                         joint_target_deadline_index=float(joint_deadline),
                         joint_target_reservation_index=float(joint_reservation),
                         joint_sale_blocked=float(joint_blocked), joint_actual_sale_today=float(joint_sold),
                         joint_target_cycle_completed=float(joint_completed)))
    if protected_mode and len(market) and market.index[-1].date() >= config.entry_execution_date and not target_seen:
        raise ValueError("Expected original entry execution did not occur; no alternative cycle selected")
    if joint_mode and len(market) and market.index[-1].date() >= config.force_decision_date and not joint_seen:
        raise UnsupportedJointNodeError("UNSUPPORTED_FIXED_JUNE19_NODE: fixed decision session absent")
    out = pd.DataFrame(rows, index=market.index)
    out[list(DIAGNOSTIC)] = out[list(DIAGNOSTIC)].astype(float)
    return out


class JointActionStrategy(StrategyImplementation):
    def __init__(self, parameters: ParameterSet):
        if not isinstance(parameters, ParameterSet):
            raise ValueError("ParameterSet required")
        self._config = JointConfig.parse(parameters.values)
        self._parameters = parameters
        self._observed = OBSERVED + DIAGNOSTIC
        self._definition = StrategyDefinition(
            parameters=parameters, tradable_symbol="600722.SH",
            inputs=InputContract((InputRequirement("calendar", Dataset.TRADING_CALENDAR.value, "SSE", "daily", 0,
                                                   CutoffRule.SIGNAL_SESSION),) + tuple(
                InputRequirement(n, d.value, "600722.SH", "daily", 1 if n in ("market", "raw") else 0,
                                 CutoffRule.SIGNAL_SESSION) for n, d in [
                    ("market", Dataset.STOCK_OHLCV), ("raw", Dataset.STOCK_UNADJUSTED_DAILY),
                    ("limits", Dataset.SECURITY_PRICE_LIMITS), ("status", Dataset.SECURITY_TRADING_STATUS)])),
            decision=DecisionContract("TARGET_POSITION", 0., 1., "NEXT_SESSION"),
            execution=ExecutionPolicy("FROZEN_RULE", {
                "capital": {"fee_rate": .001, "mode": "full_available_cash", "target_scope": "entry_cycle"},
                "entry": {"order_type": "LIMIT", "limit_parameter": .01},
                "exit": {"order_type": "MARKET", "limit_ratio": .1},
                "instrument": {"lot_size": 100, "maximum_order_quantity": 1000000,
                               "price_limit_ratio": .1, "price_tick": .01}}),
            monitoring=MonitoringPolicy("OBSERVE", {}),
            capabilities=RequiredCapabilities((Dataset.TRADING_CALENDAR.value, Dataset.STOCK_OHLCV.value,
                Dataset.STOCK_UNADJUSTED_DAILY.value, Dataset.SECURITY_PRICE_LIMITS.value,
                Dataset.SECURITY_TRADING_STATUS.value), ("LIMIT", "MARKET")),
            observation=ObservationDefinition(tuple(ObservationSeries(name, name, name) for name in self._observed), ()))

    @classmethod
    def from_parameters(cls, parameters: ParameterSet):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    def calendar_request(self,tradable_window):
        return DataRequest(Dataset.TRADING_CALENDAR,'SSE','2019-12-01',tradable_window.end.isoformat(),tradable_window.end.isoformat())

    def derive_calculation_scope(self,tradable_window,calendar_dates):
        if tradable_window.start!=date(2020,1,2):
            raise ValueError('This comparison requires the original full-window account start')
        trading=tuple(x for x in calendar_dates if tradable_window.contains(x))
        signals={x:max(p for p in calendar_dates if p<x) for x in trading}
        first,last=min(signals.values()),max(signals.values())
        requests={}
        for requirement in self.definition.inputs.requirements:
            if requirement.name=='calendar':
                continue
            start=max(first,date(2020,1,1)) if requirement.name=='limits' else first
            requests[requirement.name]=DataRequest(requirement.dataset,requirement.subject,start.isoformat(),last.isoformat(),last.isoformat())
        calculation=tuple(x for x in calendar_dates if first<=x<=last)
        return CalculationScope(tradable_window,trading,signals,calculation,requests)

    def calculate_history(self, inputs, sessions):
        out = history(inputs["market"], inputs["raw"], inputs["limits"], inputs["status"], self._config)
        # SRT ObservationSeries requires numbers, explicitly rejecting bools.
        out[list(self._observed)] = out[list(self._observed)].astype(float)
        return out.loc[sessions]
