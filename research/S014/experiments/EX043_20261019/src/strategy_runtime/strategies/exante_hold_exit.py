"""Fixed date-free 3x3 hold/exit state mechanisms over original C0056 execution."""

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


class HoldRule(str, Enum):
    BASE = "BASE"
    ENTRY_GRACE = "ENTRY_GRACE"
    TREND_CYCLE = "TREND_CYCLE"


class ExitRule(str, Enum):
    BASE = "BASE"
    SHOCK_PROFIT = "SHOCK_PROFIT"
    PROFIT_GIVEBACK = "PROFIT_GIVEBACK"


@dataclass(frozen=True)
class HoldExitConfig:
    hold_rule: HoldRule
    exit_rule: ExitRule

    def __post_init__(self):
        if type(self.hold_rule) is not HoldRule or type(self.exit_rule) is not ExitRule:
            raise ValueError("Typed HoldRule and ExitRule required")

    @classmethod
    def parse(cls, values):
        if not isinstance(values, Mapping) or set(values) != {"hold_rule", "exit_rule"}:
            raise ValueError("Exactly hold_rule and exit_rule required")
        if any(type(values[k]) is not str for k in values):
            raise ValueError("Canonical enum strings required")
        try:
            return cls(HoldRule(values["hold_rule"]), ExitRule(values["exit_rule"]))
        except ValueError as exc:
            raise ValueError("Unknown fixed hold or exit rule") from exc


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
    if type(config) is not HoldExitConfig:
        raise ValueError("HoldExitConfig required")
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
    # The execution prewindow is not support history or one of the 60 warmup closes.
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
    for i, day in enumerate(market.index):
        pending_at_start = bool(
            held and exit_pending and intent is not None and intent["side"] == "SELL"
        )
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
                        entry_fill_price = float(fill.price)
                        peak_close = np.nan
                        protected_cycle = False
                    else:
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
        intent = None
        target = 0.0
        accepted = False
        feature = features.loc[day]
        diagnostics = {key: False for key in DIAGNOSTIC}
        diagnostics["holding_age"] = -1.0
        for key in (
            "ma_known",
            "atr_known",
            "atr_positive",
            "sigma20_known",
            "sigma20_positive",
            "shock_known",
        ):
            diagnostics[key] = bool(feature[key])
        inherited = bool(pending_at_start and held and not sold)
        expired = bool(held and i >= deadline)
        eligible = bool(held and not inherited and not expired)
        net_profit = np.nan
        peak_net_gain_price = np.nan
        giveback_price = np.nan
        breach_atr = np.nan
        if held:
            close = float(market.Close.iloc[i])
            peak_close = close if bought else max(float(peak_close), close)
            net_profit = close * (1 - 0.001) / (entry_fill_price * (1 + 0.001)) - 1
            peak_net_gain_price = peak_close * (1 - 0.001) - entry_fill_price * (1 + 0.001)
            giveback_price = peak_close - close
            if feature.atr_positive:
                breach_atr = (float(support.iloc[i]) - close) / float(feature.atr20_prior)
            shock = bool(eligible and feature.shock_known and net_profit > 0 and feature.z5 > 2)
            giveback = bool(
                eligible
                and feature.atr_positive
                and peak_net_gain_price >= 2 * feature.atr20_prior
                and giveback_price >= feature.atr20_prior
            )
            profit_exit = bool(
                (config.exit_rule is ExitRule.SHOCK_PROFIT and shock)
                or (config.exit_rule is ExitRule.PROFIT_GIVEBACK and giveback)
            )
            grace_eligible = bool(eligible and bought and support_break)
            trend_eligible = bool(
                grace_eligible
                and feature.ma_known
                and feature.atr_positive
                and close >= feature.ma20_prior
                and feature.ma20_prior > feature.ma20_prior_lag5
                and breach_atr <= 1
            )
            activated = bool(config.hold_rule is HoldRule.TREND_CYCLE and trend_eligible)
            if activated:
                protected_cycle = True
            grace = bool(config.hold_rule is HoldRule.ENTRY_GRACE and grace_eligible)
            protected = bool(
                grace or (config.hold_rule is HoldRule.TREND_CYCLE and protected_cycle)
            )
            suppressed = bool(eligible and support_break and protected and not profit_exit)
            original_support = bool(eligible and support_break)
            ordinary_support = bool(original_support and not protected)
            diagnostics.update(
                pending_inherited=inherited,
                deadline_exit=expired,
                profit_exit_eligible=eligible,
                shock_condition=shock,
                giveback_condition=giveback,
                selected_profit_exit=profit_exit,
                profit_exit_added_vs_base_support=profit_exit and not support_break,
                profit_exit_added_vs_selected_hold=profit_exit and not ordinary_support,
                profit_support_overlap=profit_exit and support_break,
                entry_grace_eligible=grace_eligible,
                entry_grace_applied=grace and not profit_exit,
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
            # Never let a newly computed support exit masquerade as inherited pending.
            # Existing pending/deadline > selected profit-risk exit > support protection.
            if inherited or expired or profit_exit or ordinary_support:
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
        )
    return pd.DataFrame(rows, index=market.index)


class HoldExitStrategy(StrategyImplementation):
    def __init__(self, parameters):
        if not isinstance(parameters, ParameterSet):
            raise ValueError("ParameterSet required")
        self._config = HoldExitConfig.parse(parameters.values)
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
                tuple(ObservationSeries(name, name, name) for name in self._observed), ()
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
            inputs["market"], inputs["raw"], inputs["limits"], inputs["status"], self._config
        )
        out[list(self._observed)] = out[list(self._observed)].astype(float)
        return out.loc[sessions]
