"""Review prototype: one causal action change, then original C0056 policy resumes."""

from datetime import date, datetime, time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset
from strategy_runtime import (
    StrategyImplementation,
    ParameterSet,
    StrategyDefinition,
    ObservationDefinition,
    ObservationSeries,
    InputContract,
    InputRequirement,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    MonitoringPolicy,
    RequiredCapabilities,
    CalculationScope,
)
from trading_execution_engine import OrderSpec, DailyQuote, SessionPriceLimits, resolve_fill

VARIANTS = ("support_entry_H10", "support_exit_H10", "support_exit_reserve_H10")
MODES = ("NOOP", "SKIP_BUY_ONCE", "FORCE_SELL_ONCE")
DIAGNOSTIC = ("intervention_today", "intervention_done")
EVALUATION_START = pd.Timestamp("2020-01-02")
OBSERVED = (
    "ready",
    "support_ok",
    "warmup_sessions",
    "held_at_close",
    "buy_filled_today",
    "sell_filled_today",
    "failed_buy_reset",
    "entry_signal",
    "exit_pending",
    "support_break",
    "deadline_index",
    "entry_index",
)


def tick(value, mode=ROUND_FLOOR):
    return float(
        (Decimal(str(value)) / Decimal(".01")).to_integral_value(rounding=mode) * Decimal(".01")
    )


def buy_limit(previous_raw_close, previous_scale):
    return (
        min(
            tick(previous_raw_close * 1.01),
            tick(tick(previous_raw_close * 1.1) - 0.01, ROUND_HALF_UP),
        )
        * previous_scale
    )


def validate_intervention(mode, decision_date):
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Unknown intervention mode")
    if not isinstance(decision_date, str):
        raise ValueError("Decision date must be a canonical string")
    if mode == "NOOP":
        if decision_date != "":
            raise ValueError("NOOP requires empty decision date")
        return None
    try:
        parsed = date.fromisoformat(decision_date)
    except ValueError as exc:
        raise ValueError("Canonical YYYY-MM-DD required") from exc
    if parsed.isoformat() != decision_date:
        raise ValueError("Canonical YYYY-MM-DD required")
    if parsed < EVALUATION_START.date():
        raise ValueError("Intervention must lie inside original evaluation window")
    return pd.Timestamp(parsed)


def history(
    market, raw, limits, status, variant, intervention_mode="NOOP", intervention_decision_date=""
):
    intervention_day = validate_intervention(intervention_mode, intervention_decision_date)
    intervention_done = False
    if variant != "support_exit_reserve_H10":
        raise ValueError("Review is restricted to original C0056 H10 reservation")
    if variant not in VARIANTS:
        raise ValueError("Unknown fixed support variant")
    reserve = variant == "support_exit_reserve_H10"
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
    # The execution prewindow is not support history or one of the 60 warmup closes.
    support = market.Close.where(in_window).shift(1).rolling(5, min_periods=5).min()
    held = False
    entry = None
    deadline = None
    intent = None
    exit_pending = False
    rows = []
    for i, day in enumerate(market.index):
        bought = False
        sold = False
        failed_buy = intent is not None and intent["side"] == "BUY"
        if intent is not None:
            if day not in states.index:
                raise ValueError("Missing stock trading status")
            state = states.loc[day, "Status"]
            if state not in ("TRADING", "SUSPENDED"):
                raise ValueError("Unknown trading status")
            if state == "TRADING":
                if day not in bounds.index:
                    raise ValueError("Missing price limits")
                b = bounds.loc[day]
                bar = market.iloc[i]
                rule = SessionPriceLimits(
                    day.date(),
                    float(b.DownLimit * scale.iloc[i]),
                    float(b.UpLimit * scale.iloc[i]),
                    float(0.01 * scale.iloc[i]),
                )
                order = (
                    OrderSpec("BUY", "LIMIT", 100, intent["limit"])
                    if intent["side"] == "BUY"
                    else OrderSpec("SELL", "MARKET", 100)
                )
                fill = resolve_fill(
                    order,
                    session_open=float(bar.Open),
                    session_time=datetime.combine(day.date(), time(9, 30)),
                    intraday_touches=(),
                    daily_quote=DailyQuote(float(bar.Low), float(bar.High)),
                    session_limits=rule,
                )
                if fill.filled:
                    if intent["side"] == "BUY":
                        held = True
                        entry = i
                        deadline = i + 9
                        bought = True
                        failed_buy = False
                        exit_pending = False
                        if reserve:
                            reservation = i + 10
                    else:
                        held = False
                        entry = None
                        deadline = None
                        sold = True
                        exit_pending = False
        ready = bool(counts[i] >= 60 and np.isfinite(support.iloc[i]))
        support_ok = bool(np.isfinite(support.iloc[i]) and market.Close.iloc[i] >= support.iloc[i])
        support_break = bool(
            np.isfinite(support.iloc[i]) and market.Close.iloc[i] < support.iloc[i]
        )
        intent = None
        target = 0.0
        accepted = False
        if held:
            if i >= deadline or (
                variant in ("support_exit_H10", "support_exit_reserve_H10") and support_break
            ):
                exit_pending = True
            if exit_pending:
                intent = {"side": "SELL"}
            else:
                target = 1.0
        elif (
            not failed_buy
            and ready
            and (not reserve or i >= reservation)
            and (variant == "repeated_H10" or support_ok)
        ):
            intent = {
                "side": "BUY",
                "limit": buy_limit(float(raw.Close.iloc[i]), float(scale.iloc[i])),
            }
            target = 1.0
            accepted = True
        intervention_today = False
        if day == intervention_day:
            if intervention_done:
                raise ValueError("Intervention decision date is not unique")
            if intervention_mode == "SKIP_BUY_ONCE":
                if (
                    held
                    or failed_buy
                    or not accepted
                    or target != 1.0
                    or intent is None
                    or intent["side"] != "BUY"
                ):
                    raise ValueError("SKIP requires original flat accepted BUY intent")
                intent = None
                target = 0.0
                accepted = False
            elif intervention_mode == "FORCE_SELL_ONCE":
                if not held or exit_pending or target != 1.0 or intent is not None:
                    raise ValueError("FORCE requires original held HOLD without pending exit")
                exit_pending = True
                intent = {"side": "SELL"}
                target = 0.0
            else:
                raise ValueError("Unexpected dated NOOP")
            intervention_today = True
            intervention_done = True
        rows.append(
            dict(
                target_position=target,
                ready=ready,
                support_ok=support_ok,
                support_floor=support.iloc[i],
                warmup_sessions=int(counts[i]),
                held_at_close=held,
                buy_filled_today=bought,
                sell_filled_today=sold,
                failed_buy_reset=failed_buy,
                entry_signal=accepted,
                holding_horizon=10 if held or accepted else 0,
                exit_pending=exit_pending,
                support_break=support_break,
                deadline_index=deadline if deadline is not None else -1,
                entry_index=entry if entry is not None else -1,
            )
        )
        if reserve:
            rows[-1]["reservation_index"] = reservation
        rows[-1].update(intervention_today=intervention_today, intervention_done=intervention_done)
    if intervention_mode != "NOOP" and not intervention_done:
        raise ValueError("Requested intervention date absent from supplied sessions")
    return pd.DataFrame(rows, index=market.index)


class RepairStrategy(StrategyImplementation):
    def __init__(self, parameters):
        if (
            set(parameters.values) != {"variant", "intervention_mode", "intervention_decision_date"}
            or parameters.values["variant"] != "support_exit_reserve_H10"
        ):
            raise ValueError("Exactly C0056 variant, intervention mode and decision date required")
        validate_intervention(
            parameters.values["intervention_mode"], parameters.values["intervention_decision_date"]
        )
        self._parameters = parameters
        self._observed = OBSERVED + (
            ("reservation_index",)
            if parameters.values["variant"] == "support_exit_reserve_H10"
            else ()
        )
        self._definition = StrategyDefinition(
            parameters=parameters,
            tradable_symbol="600722.SH",
            inputs=InputContract(
                (
                    InputRequirement(
                        "calendar",
                        Dataset.TRADING_CALENDAR.value,
                        "SSE",
                        "daily",
                        0,
                        CutoffRule.SIGNAL_SESSION,
                    ),
                )
                + tuple(
                    InputRequirement(
                        n,
                        d.value,
                        "600722.SH",
                        "daily",
                        1 if n in ("market", "raw") else 0,
                        CutoffRule.SIGNAL_SESSION,
                    )
                    for n, d in [
                        ("market", Dataset.STOCK_OHLCV),
                        ("raw", Dataset.STOCK_UNADJUSTED_DAILY),
                        ("limits", Dataset.SECURITY_PRICE_LIMITS),
                        ("status", Dataset.SECURITY_TRADING_STATUS),
                    ]
                )
            ),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy(
                "FROZEN_RULE",
                {
                    "capital": {
                        "fee_rate": 0.001,
                        "mode": "full_available_cash",
                        "target_scope": "entry_cycle",
                    },
                    "entry": {"order_type": "LIMIT", "limit_parameter": 0.01},
                    "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
                    "instrument": {
                        "lot_size": 100,
                        "maximum_order_quantity": 1000000,
                        "price_limit_ratio": 0.1,
                        "price_tick": 0.01,
                    },
                },
            ),
            monitoring=MonitoringPolicy("OBSERVE", {}),
            capabilities=RequiredCapabilities(
                (
                    Dataset.TRADING_CALENDAR.value,
                    Dataset.STOCK_OHLCV.value,
                    Dataset.STOCK_UNADJUSTED_DAILY.value,
                    Dataset.SECURITY_PRICE_LIMITS.value,
                    Dataset.SECURITY_TRADING_STATUS.value,
                ),
                ("LIMIT", "MARKET"),
            ),
            observation=ObservationDefinition(
                tuple(ObservationSeries(name, name, name) for name in self._observed + DIAGNOSTIC),
                (),
            ),
        )

    @classmethod
    def from_parameters(cls, parameters: ParameterSet):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    def calendar_request(self, tradable_window):
        return DataRequest(
            Dataset.TRADING_CALENDAR,
            "SSE",
            "2019-12-01",
            tradable_window.end.isoformat(),
            tradable_window.end.isoformat(),
        )

    def derive_calculation_scope(self, tradable_window, calendar_dates):
        if tradable_window.start != date(2020, 1, 2):
            raise ValueError("This comparison requires the original full-window account start")
        trading = tuple(x for x in calendar_dates if tradable_window.contains(x))
        signals = {x: max(p for p in calendar_dates if p < x) for x in trading}
        first, last = min(signals.values()), max(signals.values())
        requests = {}
        for requirement in self.definition.inputs.requirements:
            if requirement.name == "calendar":
                continue
            start = max(first, date(2020, 1, 1)) if requirement.name == "limits" else first
            requests[requirement.name] = DataRequest(
                requirement.dataset,
                requirement.subject,
                start.isoformat(),
                last.isoformat(),
                last.isoformat(),
            )
        calculation = tuple(x for x in calendar_dates if first <= x <= last)
        return CalculationScope(tradable_window, trading, signals, calculation, requests)

    def calculate_history(self, inputs, sessions):
        out = history(
            inputs["market"],
            inputs["raw"],
            inputs["limits"],
            inputs["status"],
            self._parameters.values["variant"],
            self._parameters.values["intervention_mode"],
            self._parameters.values["intervention_decision_date"],
        )
        out[list(self._observed + DIAGNOSTIC)] = out[list(self._observed + DIAGNOSTIC)].astype(
            float
        )
        return out.loc[sessions]
