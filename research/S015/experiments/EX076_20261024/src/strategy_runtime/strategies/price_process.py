"""Conditional repair after center migration; opportunity anchors, no holding timer."""

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
def validate_parameters(parameters):
    p = dict(parameters)
    if set(p) != {"center_kind", "lookback", "allocation", "minimum_repair_space"}:
        raise ValueError("exact active parameters required")
    if p["center_kind"] not in ("mean", "median"):
        raise ValueError("unknown center definition")
    if type(p["lookback"]) is not int or not 1 <= p["lookback"] <= 30:
        raise ValueError("lookback must be 1..30 completed sessions")
    if isinstance(p["allocation"], bool) or not isinstance(p["allocation"], (int, float)) or not 0 < p["allocation"] <= 1:
        raise ValueError("allocation outside (0,1]")
    if isinstance(p["minimum_repair_space"], bool) or not isinstance(p["minimum_repair_space"], (int,float)) or not 0 <= p["minimum_repair_space"] <= 0.05:
        raise ValueError("minimum repair price-ratio space outside [0,.05]")
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
        else:
            raise ValueError("unknown center definition")
        centers.append(center + float(np.log(adj.Close.iloc[pos + 75] / raw.Close.iloc[pos + 75])))
    logc = np.log(adj.Close.to_numpy(float))
    idx = pd.DatetimeIndex(dev.Date)
    m = pd.Series(centers, index=idx, dtype=float)
    out = pd.DataFrame({"m": m, "p": logc[75:], "center_gain": m - m.shift(lookback)}, index=idx)
    out["repair_space"] = np.expm1(out.m - out.p)
    out["feature_ready"] = out.notna().all(axis=1)
    out = out.fillna(0.0)
    seed = pd.DataFrame([{**{k: 0.0 for k in out.columns}, "feature_ready": False}], index=pd.DatetimeIndex(["2024-12-31"]))
    out = pd.concat([seed, out])
    out.index.name = "date"
    return out


def intentions(features, parameters):
    p = validate_parameters(parameters)
    active = False
    repair_target = invalidation_origin = 0.0
    rows = []
    for day, row in features.iterrows():
        enter = exit_ = False
        permit = bool(row.feature_ready and day.date() >= FIRST and row.center_gain > 0 and row.p < row.m and row.repair_space >= p["minimum_repair_space"])
        if active:
            if row.p >= repair_target or row.m <= invalidation_origin:
                active = False
                exit_ = True
        elif permit:
            active = True
            enter = True
            repair_target = row.m
            invalidation_origin = row.m - row.center_gain
        rows.append({"target_position": float(active), "entry_allocation_fraction": p["allocation"] if active else None,
                     "permission": float(permit), "entry_signal": float(enter), "exit_signal": float(exit_),
                     "repair_target": repair_target, "invalidation_origin": invalidation_origin})
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
                    ObservationSeries("repair_space", "当前中心相对收盘修复空间", "repair_space"),
                    ObservationSeries("center_gain", "跨日价格中心变化", "center_gain"),
                    ObservationSeries("repair_target", "机会激活时固定的修复目标", "repair_target"),
                    ObservationSeries("invalidation_origin", "机会激活时固定的中心失效起点", "invalidation_origin"),
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
