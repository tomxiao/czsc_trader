"""Fixed SHOCK_OFF/cost; only own completed-net-loss pause LOSS/BASE interaction."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
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


class EntryGuard(str, Enum):
    BASE = "BASE"
    BLOCK_SHOCK = "BLOCK_SHOCK"


class ExitDomain(str, Enum):
    POSITIVE_P = "POSITIVE_P"
    ANY_P = "ANY_P"


class CostStop(str, Enum):
    BASE = "BASE"
    NET_LOSS_1ATR = "NET_LOSS_1ATR"


class PauseProfile(str, Enum):
    BASE = "BASE"
    AFTER_NET_LOSS_SKIP1 = "AFTER_NET_LOSS_SKIP1"
    AFTER_NET_PROFIT_SKIP1 = "AFTER_NET_PROFIT_SKIP1"


class ShockProfile(str, Enum):
    SHOCK_ON = "SHOCK_ON"
    SHOCK_OFF = "SHOCK_OFF"


@dataclass(frozen=True)
class InteractionConfig:
    pause_profile: PauseProfile

    def __post_init__(self):
        if type(self.pause_profile) is not PauseProfile or self.pause_profile not in (
            PauseProfile.AFTER_NET_LOSS_SKIP1, PauseProfile.BASE
        ):
            raise ValueError("Typed fixed LOSS/BASE PauseProfile required")

    @classmethod
    def parse(cls, values):
        if not isinstance(values, Mapping) or set(values) != {"pause_profile"}:
            raise ValueError("Exactly pause_profile required; SHOCK_OFF and all cost roles fixed")
        if type(values["pause_profile"]) is not str:
            raise ValueError("Canonical PauseProfile string required")
        try:
            return cls(PauseProfile(values["pause_profile"]))
        except ValueError as exc:
            raise ValueError("Unknown fixed interaction pause profile") from exc

    @property
    def shock_profile(self):
        return ShockProfile.SHOCK_OFF

    @property
    def entry_guard(self):
        return EntryGuard.BASE

    @property
    def exit_domain(self):
        return ExitDomain.POSITIVE_P

    @property
    def cost_stop(self):
        return CostStop.NET_LOSS_1ATR


def completed_sign(net_unit):
    if not np.isfinite(net_unit):
        raise ValueError("Actual finite completed net outcome required")
    return -1 if net_unit < 0 else 1 if net_unit > 0 else 0


DIAGNOSTIC = (
    "ma_known",
    "atr_known",
    "atr_positive",
    "sigma20_known",
    "sigma20_positive",
    "shock_known",
    "pending_inherited",
    "deadline_exit",
    "profit_exit_eligible",
    "shock_condition",
    "giveback_condition",
    "selected_profit_exit",
    "profit_exit_added_vs_base_support",
    "profit_exit_added_vs_selected_hold",
    "profit_support_overlap",
    "entry_grace_eligible",
    "entry_grace_applied",
    "trend_cycle_eligible",
    "trend_cycle_activated",
    "trend_cycle_active",
    "support_protection_applied",
    "support_exit_suppressed",
    "original_support_exit",
    "ordinary_support_exit",
    "holding_age",
    "peak_known",
)

ROLE_DIAGNOSTIC = (
    "entry_guard_active",
    "exit_domain_any",
    "cost_stop_active",
    "original_entry_candidate",
    "candidate_shock",
    "entry_guard_blocked",
    "acceleration_condition",
    "selected_shock_exit",
    "selected_cost_exit",
    "selected_risk_exit",
    "cost_stop_condition",
    "shock_exit_added_vs_positive",
    "cost_exit_added_vs_baseline",
    "risk_exit_added_vs_baseline",
    "cost_support_overlap",
    "cost_grace_override",
)
DIAGNOSTIC = DIAGNOSTIC + ROLE_DIAGNOSTIC
PAUSE_DIAGNOSTIC = (
    "pause_loss_profile", "pause_profit_profile",
    "completed_cycle_today", "completed_loss_today", "completed_profit_today",
    "completed_zero_today", "completed_net_known", "last_completed_sign",
    "pause_armed_before_candidate", "pause_armed", "pause_slot_consumed",
    "planned_slot_active", "planned_slot_until", "reservation_before_pause",
)
DIAGNOSTIC = DIAGNOSTIC + PAUSE_DIAGNOSTIC
SHOCK_DIAGNOSTIC = ("shock_action_enabled", "shock_action_suppressed")
DIAGNOSTIC = DIAGNOSTIC + SHOCK_DIAGNOSTIC
# Legacy shock_condition/selected_profit_exit and their attribution columns retain
# the original truthful positive-P condition. selected_shock_exit/selected_risk_exit
# express the adopted actual action; OFF does not erase the observed condition.

# Original columns remain: shock_condition/selected_profit_exit retain the original
# positive-P shock meaning. selected_shock_exit is the active domain's actual rule.


def causal_features(market):
    frame = market.set_index(pd.to_datetime(market.Date)).sort_index()
    if frame.index.has_duplicates:
        raise ValueError("Unique price sessions required")
    columns = ["Open", "High", "Low", "Close"]
    prices = frame[columns].to_numpy(dtype=float)
    if not np.isfinite(prices).all() or not (prices > 0).all():
        raise ValueError("Missing or invalid original market OHLC; no input fallback")
    close = frame.Close.astype(float)
    previous = close.shift(1)
    tr = pd.concat(
        [frame.High - frame.Low, (frame.High - previous).abs(), (frame.Low - previous).abs()],
        axis=1,
    ).max(axis=1)
    tr = tr.where(previous.notna())
    out = pd.DataFrame(index=frame.index)
    in_window = frame.index >= EVALUATION_START
    out["ma20_prior"] = close.where(in_window).shift(1).rolling(20, min_periods=20).mean()
    out["ma20_prior_lag5"] = out.ma20_prior.shift(5)
    out["atr20_prior"] = tr.where(in_window).shift(1).rolling(20, min_periods=20).mean()
    returns = np.log(close / previous).where(in_window)
    out["ret5_log"] = returns.rolling(5, min_periods=5).sum()
    out["sigma20_pre5"] = returns.shift(5).rolling(20, min_periods=20).std(ddof=1)
    out["ma_known"] = np.isfinite(out.ma20_prior) & np.isfinite(out.ma20_prior_lag5)
    out["atr_known"] = np.isfinite(out.atr20_prior)
    out["atr_positive"] = out.atr_known & out.atr20_prior.gt(0)
    out["sigma20_known"] = np.isfinite(out.sigma20_pre5)
    out["sigma20_positive"] = out.sigma20_known & out.sigma20_pre5.gt(0)
    out["z5"] = out.ret5_log / (np.sqrt(5) * out.sigma20_pre5.where(out.sigma20_positive))
    out["shock_known"] = np.isfinite(out.z5)
    return out


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


def history(market, raw, limits, status, config):
    if type(config) is not InteractionConfig:
        raise ValueError("InteractionConfig required")
    variant = "support_exit_reserve_H10"
    features = causal_features(market)
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
    support = market.Close.where(in_window).shift(1).rolling(5, min_periods=5).min()
    held = False
    entry = None
    deadline = None
    intent = None
    exit_pending = False
    rows = []
    entry_fill_price = np.nan
    peak_close = np.nan
    protected_cycle = False
    armed = False
    planned_until = -1
    last_completed_net = np.nan
    last_sign = 0
    for i, day in enumerate(market.index):
        pending_at_start = bool(
            held and exit_pending and (intent is not None) and (intent["side"] == "SELL")
        )
        bought = False
        sold = False
        completed_net = np.nan
        completion_sign = 0
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
                        planned_until = -1
                        entry_fill_price = float(fill.price)
                        peak_close = np.nan
                        protected_cycle = False
                    else:
                        if not held or not np.isfinite(entry_fill_price):
                            raise ValueError("Cannot complete an unfunded shadow cycle")
                        completed_net = float(fill.price) * .999 - entry_fill_price * 1.001
                        completion_sign = completed_sign(completed_net)
                        last_completed_net = completed_net
                        last_sign = completion_sign
                        armed = bool(
                            (config.pause_profile is PauseProfile.AFTER_NET_LOSS_SKIP1 and completion_sign < 0)
                            or (config.pause_profile is PauseProfile.AFTER_NET_PROFIT_SKIP1 and completion_sign > 0)
                        )
                        held = False
                        entry = None
                        deadline = None
                        sold = True
                        exit_pending = False
                        entry_fill_price = np.nan
                        peak_close = np.nan
                        protected_cycle = False
        ready = bool(counts[i] >= 60 and np.isfinite(support.iloc[i]))
        support_ok = bool(np.isfinite(support.iloc[i]) and market.Close.iloc[i] >= support.iloc[i])
        support_break = bool(
            np.isfinite(support.iloc[i]) and market.Close.iloc[i] < support.iloc[i]
        )
        reservation_before = reservation
        armed_before = armed
        consumed = False
        intent = None
        target = 0.0
        accepted = False
        feature = features.loc[day]
        diagnostics = {key: False for key in DIAGNOSTIC}
        diagnostics["holding_age"] = -1.0
        diagnostics["entry_guard_active"] = config.entry_guard is EntryGuard.BLOCK_SHOCK
        diagnostics["exit_domain_any"] = config.exit_domain is ExitDomain.ANY_P
        diagnostics["cost_stop_active"] = config.cost_stop is CostStop.NET_LOSS_1ATR
        diagnostics["shock_action_enabled"] = config.shock_profile is ShockProfile.SHOCK_ON
        for key in (
            "ma_known",
            "atr_known",
            "atr_positive",
            "sigma20_known",
            "sigma20_positive",
            "shock_known",
        ):
            diagnostics[key] = bool(feature[key])
        inherited = bool(pending_at_start and held and (not sold))
        expired = bool(held and i >= deadline)
        eligible = bool(held and (not inherited) and (not expired))
        net_profit = np.nan
        peak_net_gain_price = np.nan
        giveback_price = np.nan
        breach_atr = np.nan
        cost_loss_price = np.nan
        cost_loss_atr = np.nan
        if held:
            close = float(market.Close.iloc[i])
            peak_close = close if bought else max(float(peak_close), close)
            net_profit = close * (1 - 0.001) / (entry_fill_price * (1 + 0.001)) - 1
            peak_net_gain_price = peak_close * (1 - 0.001) - entry_fill_price * (1 + 0.001)
            giveback_price = peak_close - close
            if feature.atr_positive:
                breach_atr = (float(support.iloc[i]) - close) / float(feature.atr20_prior)
            shock = bool(eligible and feature.shock_known and (net_profit > 0) and (feature.z5 > 2))
            giveback = bool(
                eligible
                and feature.atr_positive
                and (peak_net_gain_price >= 2 * feature.atr20_prior)
                and (giveback_price >= feature.atr20_prior)
            )
            profit_exit = bool(shock)
            acceleration = bool(eligible and feature.shock_known and feature.z5 > 2)
            selected_shock = bool(
                config.shock_profile is ShockProfile.SHOCK_ON
                and acceleration and (config.exit_domain is ExitDomain.ANY_P or net_profit > 0)
            )
            cost_loss_price = entry_fill_price * (1 + 0.001) - close * (1 - 0.001)
            if feature.atr_positive:
                cost_loss_atr = cost_loss_price / float(feature.atr20_prior)
            cost_condition = bool(
                eligible and feature.atr_positive and cost_loss_price >= feature.atr20_prior
            )
            selected_cost = bool(config.cost_stop is CostStop.NET_LOSS_1ATR and cost_condition)
            risk_exit = bool(selected_shock or selected_cost)
            grace_eligible = bool(eligible and bought and support_break)
            trend_eligible = bool(
                grace_eligible
                and feature.ma_known
                and feature.atr_positive
                and (close >= feature.ma20_prior)
                and (feature.ma20_prior > feature.ma20_prior_lag5)
                and (breach_atr <= 1)
            )
            # Preserve inherited observability, while this family fixes ENTRY_GRACE.
            activated = False
            grace = bool(grace_eligible)
            protected = grace
            suppressed = bool(eligible and support_break and protected and (not risk_exit))
            original_support = bool(eligible and support_break)
            ordinary_support = bool(original_support and (not protected))
            diagnostics.update(
                pending_inherited=inherited,
                deadline_exit=expired,
                profit_exit_eligible=eligible,
                shock_condition=shock,
                giveback_condition=giveback,
                selected_profit_exit=profit_exit,
                profit_exit_added_vs_base_support=profit_exit and (not support_break),
                profit_exit_added_vs_selected_hold=profit_exit and (not ordinary_support),
                profit_support_overlap=profit_exit and support_break,
                entry_grace_eligible=grace_eligible,
                entry_grace_applied=grace and (not risk_exit),
                trend_cycle_eligible=trend_eligible,
                trend_cycle_activated=activated,
                trend_cycle_active=protected_cycle,
                support_protection_applied=suppressed,
                support_exit_suppressed=suppressed,
                original_support_exit=original_support,
                ordinary_support_exit=ordinary_support,
                holding_age=i - entry,
                peak_known=True,
            )
            diagnostics.update(
                acceleration_condition=acceleration,
                shock_action_suppressed=shock and config.shock_profile is ShockProfile.SHOCK_OFF,
                selected_shock_exit=selected_shock,
                selected_cost_exit=selected_cost,
                selected_risk_exit=risk_exit,
                cost_stop_condition=cost_condition,
                shock_exit_added_vs_positive=selected_shock and not profit_exit,
                cost_exit_added_vs_baseline=selected_cost and not (profit_exit or ordinary_support),
                risk_exit_added_vs_baseline=risk_exit and not (profit_exit or ordinary_support),
                cost_support_overlap=selected_cost and original_support,
                cost_grace_override=selected_cost and grace,
            )
            if inherited or expired or risk_exit or ordinary_support:
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
            diagnostics["original_entry_candidate"] = True
            diagnostics["candidate_shock"] = bool(feature.shock_known and feature.z5 > 2)
            blocked = bool(
                config.entry_guard is EntryGuard.BLOCK_SHOCK and diagnostics["candidate_shock"]
            )
            diagnostics["entry_guard_blocked"] = blocked
            if armed:
                # Consume one planned next-E plus H10 opportunity, not an actual fill.
                reservation = i + 11
                planned_until = reservation
                armed = False
                consumed = True
            elif not blocked:
                intent = {
                    "side": "BUY",
                    "limit": buy_limit(float(raw.Close.iloc[i]), float(scale.iloc[i])),
                }
                target = 1.0
                accepted = True
        diagnostics.update(
            pause_loss_profile=config.pause_profile is PauseProfile.AFTER_NET_LOSS_SKIP1,
            pause_profit_profile=config.pause_profile is PauseProfile.AFTER_NET_PROFIT_SKIP1,
            completed_cycle_today=sold,
            completed_loss_today=sold and completion_sign < 0,
            completed_profit_today=sold and completion_sign > 0,
            completed_zero_today=sold and completion_sign == 0,
            completed_net_known=np.isfinite(last_completed_net),
            last_completed_sign=last_sign,
            pause_armed_before_candidate=armed_before,
            pause_armed=armed,
            pause_slot_consumed=consumed,
            planned_slot_active=not held and planned_until >= 0 and i < planned_until,
            planned_slot_until=planned_until,
            reservation_before_pause=reservation_before,
        )
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
        rows[-1].update({key: float(value) for key, value in diagnostics.items()})
        rows[-1].update(
            {
                key: float(feature[key])
                for key in (
                    "ma20_prior",
                    "ma20_prior_lag5",
                    "atr20_prior",
                    "ret5_log",
                    "sigma20_pre5",
                    "z5",
                )
            }
        )
        rows[-1].update(
            entry_fill_price=entry_fill_price,
            net_profit=net_profit,
            peak_close=peak_close,
            peak_net_gain_price=peak_net_gain_price,
            giveback_price=giveback_price,
            breach_atr=breach_atr,
            completed_net_unit=completed_net,
            last_completed_net_unit=last_completed_net,
            cost_loss_price=cost_loss_price,
            cost_loss_atr=cost_loss_atr,
        )
    return pd.DataFrame(rows, index=market.index)


class LossInteractionStrategy(StrategyImplementation):
    def __init__(self, parameters):
        if not isinstance(parameters, ParameterSet):
            raise ValueError("ParameterSet required")
        self._config = InteractionConfig.parse(parameters.values)
        self._parameters = parameters
        self._observed = OBSERVED + ("reservation_index",) + DIAGNOSTIC
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
                    (
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
                tuple((ObservationSeries(name, name, name) for name in self._observed)), ()
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
        trading = tuple((x for x in calendar_dates if tradable_window.contains(x)))
        signals = {x: max((p for p in calendar_dates if p < x)) for x in trading}
        first, last = (min(signals.values()), max(signals.values()))
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
        calculation = tuple((x for x in calendar_dates if first <= x <= last))
        return CalculationScope(tradable_window, trading, signals, calculation, requests)

    def calculate_history(self, inputs, sessions):
        out = history(
            inputs["market"], inputs["raw"], inputs["limits"], inputs["status"], self._config
        )
        out[list(self._observed)] = out[list(self._observed)].astype(float)
        return out.loc[sessions]
