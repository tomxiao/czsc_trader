"""Cross-session price processes, computed only from completed public inputs."""

from datetime import date
import numpy as np
import pandas as pd
from dataflows import DataRequest, Dataset, DataCoverageRequirement
from strategy_runtime import (
    StrategyImplementationV2,
    StrategyDefinition,
    InputContract,
    InputRequirement,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    MonitoringPolicy,
    RequiredCapabilities,
    ObservationDefinition,
    ObservationSeries,
    HistoryPolicy,
    CalculationScope,
)

FIRST = date(2025, 1, 2)
LAST = date(2026, 10, 21)
TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
MODES = (
    "U",
    "momentum",
    "center",
    "distributed",
    "concentrated",
    "impulse",
    "center_first",
    "center_cont",
    "center_above",
    "center_below",
    "center_step",
    "center_pull",
    "below",
    "falling_below",
    "center_first_below",
    "center_below_step",
    "inside_advance",
)


def validate_parameters(parameters):
    p = dict(parameters)
    if set(p) != {
        "mode",
        "exit_mode",
        "lookback",
        "concentration",
        "hold",
        "allocation",
        "start",
        "center_kind",
        "confirmation",
        "failure_buffer",
        "max_hold",
        "rearm_mode",
    }:
        raise ValueError("exact process parameters required")
    if p["mode"] not in MODES or p["exit_mode"] not in (
        "fixed",
        "process",
        "stall",
        "reversal",
        "repair",
        "repair_or_reversal",
        "fixed_guard",
        "confirmed_guard",
        "anchored_guard",
        "repair_cap",
        "extend_repair",
        "anchor_repair",
        "anchor_repair_reversal",
        "anchor_repair_floor",
        "repair_floor",
        "anchor_origin",
        "origin_trail",
        "origin_only",
    ):
        raise ValueError("unknown process or exit")
    if type(p["lookback"]) is not int or not 2 <= p["lookback"] <= 10:
        raise ValueError("lookback must be 2..10 sessions")
    if type(p["hold"]) is not int or not 1 <= p["hold"] <= 30:
        raise ValueError("positive bounded intent age required")
    for key in ("concentration", "allocation"):
        if isinstance(p[key], bool) or not isinstance(p[key], (int, float)) or not 0 < p[key] <= 1:
            raise ValueError("fraction outside (0,1]")
    if (
        date.fromisoformat(p["start"]).isoformat() != p["start"]
        or not FIRST <= date.fromisoformat(p["start"]) <= LAST
    ):
        raise ValueError("start outside authorized period")
    if p["center_kind"] not in ("median", "mean", "daily_mid"):
        raise ValueError("unknown center definition")
    if type(p["confirmation"]) is not int or not 1 <= p["confirmation"] <= 5:
        raise ValueError("confirmation must be 1..5")
    if isinstance(p["failure_buffer"], bool) or not isinstance(p["failure_buffer"], (int,float)) or not 0 <= p["failure_buffer"] <= 3:
        raise ValueError("failure_buffer must be 0..3 prior ATR units")
    if type(p["max_hold"]) is not int or not p["hold"] <= p["max_hold"] <= 30:
        raise ValueError("max_hold must be hold..30")
    if p["rearm_mode"] not in ("immediate", "positive_step"):
        raise ValueError("unknown rearm mode")
    return p


def causal_features(market, execution, intraday, lookback=3, center_kind="median"):
    frames = []
    for name, frame in (("market", market), ("execution", execution), ("intraday", intraday)):
        f = frame[["Date", "Open", "High", "Low", "Close"]].copy()
        f.attrs = {}
        f["Date"] = pd.to_datetime(f.Date)
        if f.Date.duplicated().any() or not f.Date.is_monotonic_increasing:
            raise ValueError(name + ": ordered unique dates required")
        z = f[["Open", "High", "Low", "Close"]].to_numpy(float)
        if not np.isfinite(z).all() or (z <= 0).any():
            raise ValueError("positive finite prices required")
        frames.append(f)
    adj, raw, bars = frames
    if (
        not adj.Date.equals(raw.Date)
        or len(adj) < 75
        or adj.Date.iloc[0] != pd.Timestamp("2024-09-09")
        or adj.Date.iloc[74] != pd.Timestamp("2024-12-31")
    ):
        raise ValueError("canonical daily preheat mismatch")
    dev = adj.iloc[75:]
    groups = list(bars.groupby(bars.Date.dt.normalize(), sort=False))
    if [d for d, _ in groups] != list(dev.Date) or len(bars) != 8 * len(dev):
        raise ValueError("exact eight bars for each development session required")
    centers = []
    for pos, (day, b) in enumerate(groups):
        if tuple(b.Date.dt.strftime("%H:%M")) != TIMES:
            raise ValueError("invalid bar clock")
        if center_kind == "median":
            center = float(np.median(np.log(b.Close.to_numpy(float))))
        elif center_kind == "mean":
            center = float(np.mean(np.log(b.Close.to_numpy(float))))
        elif center_kind == "daily_mid":
            center = 0.5 * float(np.log(raw.High.iloc[pos + 75]) + np.log(raw.Low.iloc[pos + 75]))
        else:
            raise ValueError("unknown center definition")
        centers.append(center + float(np.log(adj.Close.iloc[pos + 75] / raw.Close.iloc[pos + 75])))
    logc = np.log(adj.Close.to_numpy(float))
    logh = np.log(adj.High.to_numpy(float))
    logl = np.log(adj.Low.to_numpy(float))
    prev = np.r_[logc[0], logc[:-1]]
    tr = np.maximum.reduce([logh - logl, np.abs(logh - prev), np.abs(logl - prev)])
    atr = pd.Series(tr).shift().rolling(20).mean().to_numpy()[75:]
    idx = pd.DatetimeIndex(dev.Date)
    m = pd.Series(centers, index=idx, dtype=float)
    delta = m.diff()
    pos = delta.clip(lower=0)
    den = pos.rolling(lookback).sum()
    q = pos.rolling(lookback).max().div(den.where(den > 0)).where(den > 0, 0.0)
    out = pd.DataFrame(
        {
            "m": m,
            "low": logl[75:],
            "high": logh[75:],
            "p": logc[75:],
            "dcenter": delta,
            "center_gain": m - m.shift(lookback),
            "concentration": q,
            "up_count": delta.gt(0).astype(int).rolling(lookback).sum(),
            "atr": atr,
            "r1": pd.Series(logc).diff().to_numpy()[75:],
            "r3": pd.Series(logc).diff(lookback).to_numpy()[75:],
            "r5": pd.Series(logc).diff(5).to_numpy()[75:],
            "vol20": pd.Series(logc).diff().rolling(20).std().to_numpy()[75:],
        },
        index=idx,
    )
    out["feature_ready"] = out.notna().all(axis=1)
    out["prior_positive"] = out.center_gain.shift().gt(0).astype(float)
    out = out.fillna(0.0)
    seed = pd.DataFrame(
        [{**{k: 0.0 for k in out.columns}, "feature_ready": False}],
        index=pd.DatetimeIndex(["2024-12-31"]),
    )
    out = pd.concat([seed, out])
    out.index.name = "date"
    return out


def permission(row, p):
    if not row.feature_ready or row.name.date().isoformat() < p["start"]:
        return False
    positive = row.center_gain > 0
    distributed = (
        positive
        and row.up_count >= int(np.ceil(2 * p["lookback"] / 3))
        and row.concentration <= p["concentration"]
        and row.p >= row.m
    )
    return {
        "U": True,
        "momentum": row.r3 > 0,
        "center": positive,
        "below": row.p < row.m,
        "falling_below": not positive and row.p < row.m,
        "center_first_below": positive and not row.prior_positive and row.p < row.m,
        "center_below_step": positive and row.dcenter > 0 and row.p < row.m,
        "center_first": positive and not row.prior_positive,
        "center_cont": positive and bool(row.prior_positive),
        "center_above": positive and row.p >= row.m,
        "center_below": positive and row.p < row.m,
        "inside_advance": positive and row.m - row.center_gain < row.p < row.m,
        "center_step": positive and row.dcenter > 0,
        "center_pull": positive and row.dcenter <= 0,
        "distributed": distributed,
        "concentrated": positive and row.concentration > p["concentration"] and row.p >= row.m,
        "impulse": row.dcenter > row.atr and row.p >= row.m,
    }[p["mode"]]


def intentions(features, parameters):
    p = validate_parameters(parameters)
    age = 0
    peak = 0.0
    anchor = 0.0
    stale = 0
    armed = True
    bad_streak = 0
    entry_center = 0.0
    entry_atr = 0.0
    entry_floor = 0.0
    origin_floor = 0.0
    trail_floor = 0.0
    rows = []
    for day, row in features.iterrows():
        permit = permission(row, p)
        reason = 0
        if age:
            stale = 0 if row.m > peak else stale + 1
            if row.m > peak and row.center_gain > 0:
                trail_floor = max(trail_floor, row.m - row.center_gain)
            peak = max(peak, row.m)
            failed = row.dcenter < 0 and row.p < row.m
            bad_streak = bad_streak + 1 if failed else 0
            expired = (
                (p["exit_mode"] == "fixed" and age >= p["hold"])
                or (p["exit_mode"] == "anchor_repair" and row.p >= entry_center)
                or (p["exit_mode"] == "anchor_repair_reversal" and (row.p >= entry_center or row.center_gain <= 0))
                or (p["exit_mode"] == "anchor_repair_floor" and (row.p >= entry_center or row.p < entry_floor))
                or (p["exit_mode"] == "repair_floor" and (row.p >= row.m or row.p < entry_floor))
                or (p["exit_mode"] == "anchor_origin" and (row.p >= entry_center or row.p <= origin_floor))
                or (p["exit_mode"] == "origin_trail" and row.p <= trail_floor)
                or (p["exit_mode"] == "origin_only" and row.p <= origin_floor)
                or (p["exit_mode"] == "process" and failed)
                or (p["exit_mode"] == "repair" and row.p >= row.m)
                or (
                    p["exit_mode"] == "repair_or_reversal"
                    and (row.p >= row.m or row.center_gain <= 0)
                )
                or (p["exit_mode"] == "fixed_guard" and (failed or age >= p["hold"]))
                or (p["exit_mode"] == "reversal" and row.center_gain <= 0)
                or (p["exit_mode"] == "confirmed_guard" and (age >= p["hold"] or bad_streak >= p["confirmation"]))
                or (p["exit_mode"] == "anchored_guard" and (age >= p["hold"] or row.m <= entry_center - p["failure_buffer"] * entry_atr))
                or (p["exit_mode"] == "repair_cap" and (age >= p["hold"] or row.p >= row.m))
                or (p["exit_mode"] == "extend_repair" and (bad_streak >= p["confirmation"] or age >= p["max_hold"] or (age >= p["hold"] and not (row.center_gain > 0 and row.p < row.m))))
                or (p["exit_mode"] == "stall" and (row.p < anchor or stale >= 2))
            )
            if expired:
                age = 0
                armed = False
                reason = 1
            else:
                age += 1
        else:
            if row.dcenter > 0:
                armed = True
            if permit and (armed or p["rearm_mode"] == "immediate"):
                age = 1
                bad_streak = 0
                entry_center = row.m
                entry_atr = row.atr
                entry_floor = row.low
                origin_floor = row.m - row.center_gain
                trail_floor = origin_floor
                peak = row.m
                anchor = row.m - 0.5 * row.dcenter
                stale = 0
                reason = 2
        rows.append(
            {
                "target_position": float(age > 0),
                "entry_allocation_fraction": p["allocation"] if age else None,
                "intent_age": age,
                "permission": float(permit),
                "exit_signal": float(reason == 1),
                "entry_signal": float(reason == 2),
            }
        )
    decisions = pd.DataFrame(rows, index=features.index)
    decisions["entry_allocation_fraction"] = decisions.entry_allocation_fraction.astype(float)
    return features.join(decisions)


class PriceProcess(StrategyImplementationV2):
    def __init__(self, parameters):
        validate_parameters(parameters.values)
        inputs = InputContract(
            (
                InputRequirement(
                    "market",
                    Dataset.ETF_OHLCV.value,
                    "159326.SZ",
                    "daily",
                    21,
                    CutoffRule.SIGNAL_SESSION,
                ),
                InputRequirement(
                    "execution",
                    Dataset.ETF_UNADJUSTED_DAILY.value,
                    "159326.SZ",
                    "daily",
                    21,
                    CutoffRule.SIGNAL_SESSION,
                ),
                InputRequirement(
                    "intraday",
                    Dataset.ETF_UNADJUSTED_INTRADAY.value,
                    "159326.SZ",
                    "30m",
                    0,
                    CutoffRule.SIGNAL_SESSION,
                ),
                InputRequirement(
                    "calendar",
                    Dataset.TRADING_CALENDAR.value,
                    "SZSE",
                    "daily",
                    0,
                    CutoffRule.LATEST_AVAILABLE,
                ),
            )
        )
        self._definition = StrategyDefinition(
            parameters=parameters,
            inputs=inputs,
            decision=DecisionContract("CYCLE_TARGET", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy(
                "FROZEN_RULE",
                {
                    "capital": {
                        "fee_rate": 0.001,
                        "mode": "signal_cash_fraction",
                        "target_scope": "entry_cycle",
                    },
                    "entry": {"limit_parameter": 0.01, "order_type": "LIMIT"},
                    "exit": {"limit_ratio": 0.1, "order_type": "MARKET"},
                    "instrument": {
                        "lot_size": 100,
                        "maximum_order_quantity": 1000000,
                        "price_limit_ratio": 0.1,
                        "price_tick": 0.001,
                    },
                },
            ),
            monitoring=MonitoringPolicy("OBSERVE", {}),
            capabilities=RequiredCapabilities(
                tuple(r.dataset for r in inputs.requirements), ("LIMIT", "MARKET")
            ),
            tradable_symbol="159326.SZ",
            observation=ObservationDefinition(
                (
                    ObservationSeries("center_gain", "跨日价格中心变化", "center_gain"),
                    ObservationSeries("concentration", "正推进集中程度", "concentration"),
                    ObservationSeries("intent_age", "价格过程意图年龄", "intent_age"),
                ),
                (),
            ),
            history=HistoryPolicy("CANONICAL_REPLAY", "2024-12-31", "2024-09-09"),
        )

    @classmethod
    def from_parameters(cls, parameters):
        return cls(parameters)

    @property
    def definition(self):
        return self._definition

    def calendar_request(self, tradable_window):
        if tradable_window.start < FIRST or tradable_window.end > LAST:
            raise ValueError("outside approved development windows")
        return DataRequest(
            Dataset.TRADING_CALENDAR,
            "SZSE",
            "2024-09-09",
            tradable_window.end.isoformat(),
            tradable_window.end.isoformat(),
        )

    def derive_calculation_scope(self, tradable_window, calendar_dates):
        days = tuple(d for d in calendar_dates if tradable_window.contains(d))
        signals = {d: max(x for x in calendar_dates if x < d) for d in days}
        end = max(signals.values())
        first = min(signals.values())
        calc = tuple(d for d in calendar_dates if date(2024, 12, 31) <= d <= end)
        requests = {}
        for r in self.definition.inputs.requirements:
            if r.name == "calendar":
                continue
            minute = r.name == "intraday"
            start = "2025-01-02" if minute else "2024-09-09"
            through = max(FIRST, first) if minute else first
            requests[r.name] = DataRequest(
                r.dataset,
                r.subject,
                start,
                end.isoformat(),
                end.isoformat(),
                r.frequency,
                coverage=DataCoverageRequirement(
                    maximum_start_lag_days=0,
                    minimum_sessions=r.lookback_sessions,
                    minimum_observations=8 if minute else 1,
                    observations_through=through.isoformat(),
                ),
            )
        return CalculationScope(tradable_window, days, signals, calc, requests)

    def calculate_context_history(self, inputs, context):
        f = causal_features(
            inputs["market"],
            inputs["execution"],
            inputs["intraday"],
            self.definition.parameters.values["lookback"],
            self.definition.parameters.values["center_kind"],
        )
        out = intentions(f, self.definition.parameters.values).reindex(context.sessions)
        if out.drop(columns=["entry_allocation_fraction"]).isna().any().any():
            raise ValueError("missing canonical dates")
        return out
