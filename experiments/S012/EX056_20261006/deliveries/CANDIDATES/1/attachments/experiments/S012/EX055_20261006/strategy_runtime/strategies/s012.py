"""S012 causal planned-cycle strategy using public SRT contracts only.

All decisions consume signal-session facts known by 17:00. The public SRT
window replay generates its plans at 20:31 and executes on the next session.
Cycle age and stop references describe planned signals, never actual fills.
"""

from __future__ import annotations

from datetime import date
from math import isfinite
from typing import Mapping

import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    CalendarWindow,
    CalculationScope,
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    HistoryPolicy,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ObservationDefinition,
    ObservationSeries,
    ParameterSet,
    RequiredCapabilities,
    StrategyDefinition,
    StrategyImplementation,
    TradableWindow,
    next_session_calculation_scope,
    next_session_calendar_window,
)


BOOLEAN_COLUMNS = (
    "o01", "n09", "o01_valid", "n09_valid", "own_positive",
    "vol_high", "vol_valid", "kurt_high", "kurt_valid",
    "mom_high", "mom_valid", "m05", "m05_valid", "mom3_positive", "mom3_valid",
)


# Only these research modes have a declared branch-loss exit interpretation.
EXIT_BRANCHES = {
    "momentum": ("momentum",),
    "momentum_union": ("momentum", "o01", "m05"),
    "m05": ("m05",),
    "o01_m05": ("o01", "m05"),
    "n09": ("n09",),
    "all_union": ("o01", "n09", "m05"),
}


def _integer(values: Mapping, name: str, low: int, high: int) -> int:
    value = values[name]
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{name} must be an integer in [{low}, {high}]")
    return value


def _number(values: Mapping, name: str, low: float, high: float) -> float:
    value = values[name]
    if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} must be finite in [{low}, {high}]")
    return float(value)


def _boolean(values: Mapping, name: str) -> bool:
    value = values[name]
    if type(value) is not bool:
        raise ValueError(f"{name} must be bool")
    return value


def _indexed(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or "Date" not in frame:
        raise ValueError(f"{name} requires a Date column")
    value = frame.copy()
    value.attrs = {}  # Local numeric copy; original evidence metadata remains intact.
    value["Date"] = pd.to_datetime(value["Date"], errors="raise")
    dates = pd.DatetimeIndex(value["Date"])
    if (dates.hasnans or dates.has_duplicates or dates.tz is not None
            or not dates.equals(dates.normalize()) or not dates.is_monotonic_increasing):
        raise ValueError(f"{name} requires unique ascending naive session dates")
    return value.set_index("Date")


def _price_momentum(
    execution: pd.DataFrame, sessions: pd.DatetimeIndex, lookback: int,
) -> tuple[pd.Series, pd.Series]:
    """Known/positive masks from observed raw closes, before window slicing."""
    prices = pd.to_numeric(execution.loc[execution.index <= sessions[-1], "Close"], errors="raise")
    if not prices.map(lambda value: isfinite(value) and value > 0).all():
        raise ValueError("momentum execution history Close must be positive and finite")
    changes = prices.pct_change(periods=lookback, fill_method=None)
    known = changes.map(lambda value: bool(pd.notna(value) and isfinite(value)))
    return known.reindex(sessions, fill_value=False), changes.gt(0).reindex(sessions, fill_value=False)


class S012PlannedCycle(StrategyImplementation):
    """Opportunity/confirmation/risk composition with explicit signal cycles."""

    def __init__(self, parameters: ParameterSet):
        if type(parameters) is not ParameterSet:
            raise TypeError("parameters must be ParameterSet")
        values = parameters.values
        self.opportunity = values["opportunity"]
        if self.opportunity not in {"o01", "n09", "union", "always", "m05", "o01_m05", "n09_m05", "all_union", "momentum", "momentum_union"}:
            raise ValueError("unsupported opportunity")
        self.confirm_o01 = _boolean(values, "confirm_o01")
        # Research search domain, not a performance acceptance gate.
        self.momentum_lookback = _integer({"momentum_lookback": values.get("momentum_lookback", 3)},
                                          "momentum_lookback", 3, 120)
        self.hold_days = _integer(values, "hold_days", 1, 120)
        self.exit_policy = values.get("exit_policy", "fixed")
        if type(self.exit_policy) is not str:
            raise TypeError("exit_policy must be str")
        if self.exit_policy not in {"fixed", "opportunity_loss"}:
            raise ValueError("exit_policy must be fixed or opportunity_loss")
        self.min_hold = _integer({"min_hold": values.get("min_hold", 1)},
                                 "min_hold", 1, self.hold_days)
        if self.exit_policy == "opportunity_loss" and self.opportunity not in EXIT_BRANCHES:
            raise ValueError("opportunity_loss requires a declared supported opportunity")
        self.cooldown = _integer(values, "cooldown", 0, 10)
        self.risk_gate = values["risk_gate"]
        if self.risk_gate not in {"none", "vol", "kurt", "mom"}:
            raise ValueError("unsupported risk_gate")
        self.risk_unknown_policy = values.get("risk_unknown_policy", "block")
        if type(self.risk_unknown_policy) is not str:
            raise TypeError("risk_unknown_policy must be str")
        if self.risk_unknown_policy not in {"block", "known_only"}:
            raise ValueError("risk_unknown_policy must be block or known_only")
        self.risk_exit = _boolean(values, "risk_exit")
        self.trailing_stop = _number(values, "trailing_stop", 0.0, 0.2)
        premium = _number(values, "entry_premium", -0.05, 0.05)
        allocation = _number(values, "allocation", 0.5, 1.0)
        rule = values.get("rule")
        source = rule.get("data_source") if isinstance(rule, Mapping) else None
        if (not isinstance(source, Mapping) or not isinstance(source.get("path"), str)
                or not isinstance(source.get("sha256"), str)):
            raise ValueError("rule.data_source requires path and sha256")
        self._definition = StrategyDefinition(
            parameters=parameters,
            inputs=InputContract((
                InputRequirement("features", Dataset.STRATEGY_FEATURE_EVIDENCE.value,
                                 "S012", "daily", 1, CutoffRule.SIGNAL_SESSION),
                InputRequirement("market", Dataset.ETF_OHLCV.value,
                                 "518850.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
                InputRequirement("execution", Dataset.ETF_UNADJUSTED_DAILY.value,
                                 "518850.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
                InputRequirement("calendar", Dataset.TRADING_CALENDAR.value,
                                 "SSE", "daily", 0, CutoffRule.LATEST_AVAILABLE),
            )),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION"),
            execution=ExecutionPolicy("FROZEN_RULE", {
                "capital": {
                    "fee_rate": 0.001,
                    "mode": "full_available_cash" if allocation == 1.0 else "available_cash_fraction",
                    "allocation_fraction": allocation,
                    "target_scope": "entry_cycle",
                },
                "entry": {"order_type": "LIMIT", "limit_parameter": premium},
                "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
                "instrument": {
                    "lot_size": 100, "price_tick": 0.001,
                    "price_limit_ratio": 0.1, "maximum_order_quantity": 1_000_000,
                },
            }),
            monitoring=MonitoringPolicy("OBSERVE", {}),
            capabilities=RequiredCapabilities((
                Dataset.STRATEGY_FEATURE_EVIDENCE.value,
                Dataset.ETF_OHLCV.value,
                Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.TRADING_CALENDAR.value,
            ), ("LIMIT", "MARKET")),
            tradable_symbol="518850.SH",
            observation=ObservationDefinition((
                ObservationSeries("target", "计划目标仓位", "planned_target"),
                ObservationSeries("age", "计划周期信号龄", "planned_age"),
            ), ()),
            history=HistoryPolicy("CANONICAL_REPLAY", "2020-06-05", "2020-06-05"),
        )

    @classmethod
    def from_parameters(cls, parameters: ParameterSet) -> S012PlannedCycle:
        return cls(parameters)

    @property
    def definition(self) -> StrategyDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow) -> CalendarWindow:
        if tradable_window.start < date(2020, 6, 8):
            raise ValueError("SRT needs an observed pre-trading reference session; start at 2020-06-08")
        return next_session_calendar_window(self.definition, tradable_window)

    def derive_calculation_scope(
        self, tradable_window: TradableWindow, calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        if tradable_window.start < date(2020, 6, 8):
            raise ValueError("SRT tradable start must be at least 2020-06-08")
        return next_session_calculation_scope(self.definition, tradable_window, calendar_dates)

    def calculate_history(
        self, inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        return self._calculate(inputs, sessions)

    def calculate_window_history(
        self, inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        # SRT passes the evaluation window's signal dates here. Start with no
        # planned cycle, while using already causal features as prepared inputs.
        return self._calculate(inputs, sessions)

    def _calculate(
        self, inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        if (not isinstance(sessions, pd.DatetimeIndex) or sessions.empty
                or sessions.hasnans or sessions.has_duplicates or sessions.tz is not None
                or not sessions.equals(sessions.normalize()) or not sessions.is_monotonic_increasing):
            raise ValueError("sessions must be unique ascending naive session dates")
        features = _indexed(inputs["features"], "features").reindex(sessions)
        execution_history = _indexed(inputs["execution"], "execution")
        execution = execution_history.reindex(sessions)
        if not set(BOOLEAN_COLUMNS) <= set(features.columns):
            raise ValueError("features are missing declared component fields")
        for name in BOOLEAN_COLUMNS:
            if features[name].isna().any() or not features[name].isin([True, False, 0, 1]).all():
                raise ValueError(f"{name} requires explicit Boolean facts at every session")
        if "Close" not in execution:
            raise ValueError("execution requires Close")
        closes = pd.to_numeric(execution["Close"], errors="raise")
        if not closes.map(lambda value: isfinite(value) and value > 0).all():
            raise ValueError("execution Close must be positive and finite at every session")

        derived_momentum = None
        if self.momentum_lookback > 3 and self.opportunity in {"momentum", "momentum_union"}:
            derived_momentum = _price_momentum(execution_history, sessions, self.momentum_lookback)

        active = False
        entry_index = -1
        peak = 0.0
        earliest_entry = 0
        cycle_id = 0
        entry_branches: tuple[str, ...] = ()
        rows = []
        for index, session in enumerate(sessions):
            facts = features.loc[session]
            close = float(closes.loc[session])
            o01 = bool(facts["o01_valid"]) and bool(facts["o01"])
            if self.confirm_o01:
                o01 = o01 and bool(facts["own_positive"])
            n09 = bool(facts["n09_valid"]) and bool(facts["n09"])
            m05 = bool(facts["m05_valid"]) and bool(facts["m05"])
            momentum_known = bool(facts["mom3_valid"])
            momentum = momentum_known and bool(facts["mom3_positive"])
            if derived_momentum is not None:
                known, positive = derived_momentum
                momentum_known = bool(known.loc[session])
                momentum = momentum_known and bool(positive.loc[session])
            opportunity = {
                "o01": o01, "n09": n09, "union": o01 or n09, "always": True,
                "m05": m05, "o01_m05": o01 or m05, "n09_m05": n09 or m05,
                "all_union": o01 or n09 or m05, "momentum": momentum,
                "momentum_union": momentum or o01 or m05,
            }[self.opportunity]
            branch_truth = {}
            if self.exit_policy == "opportunity_loss":
                # Unknown validity is distinct from a known-false signal. The
                # o01 truth includes the same confirmation used at entry.
                branch_truth = {
                    "o01": o01 if bool(facts["o01_valid"]) else None,
                    "n09": n09 if bool(facts["n09_valid"]) else None,
                    "m05": m05 if bool(facts["m05_valid"]) else None,
                    "momentum": momentum if momentum_known else None,
                }
            risk_available = (
                True if self.risk_gate == "none" else bool(facts[f"{self.risk_gate}_valid"])
            )
            risk_ok = risk_available and (
                True if self.risk_gate == "none" else
                bool(facts["mom_high"]) if self.risk_gate == "mom" else
                not bool(facts[f"{self.risk_gate}_high"])
            )
            # An explicit research hypothesis: unknown is not a known risk event.
            # The default block policy above retains the original conservative rule.
            if self.risk_unknown_policy == "known_only" and not risk_available:
                risk_ok = True
            reason = "IDLE"
            age = 0
            drawdown = 0.0
            if active:
                age = index - entry_index
                peak = max(peak, close)
                drawdown = 1.0 - close / peak
                reason = "HOLD"
                if age >= self.hold_days:
                    reason = "EXIT_AGE"
                elif self.risk_exit and not risk_ok:
                    reason = "EXIT_RISK"
                elif self.trailing_stop > 0 and drawdown >= self.trailing_stop:
                    reason = "EXIT_TRAILING"
                elif (self.exit_policy == "opportunity_loss" and age >= self.min_hold
                      and entry_branches
                      and all(branch_truth[branch] is False for branch in entry_branches)):
                    reason = "EXIT_OPPORTUNITY_LOSS"
                if reason.startswith("EXIT_"):
                    active = False
                    # Exit signal itself is always flat; cooldown adds further
                    # flat signal sessions before another entry can be planned.
                    earliest_entry = index + self.cooldown + 1
            elif index < earliest_entry:
                reason = "COOLDOWN"
            elif opportunity and risk_ok:
                active = True
                entry_index = index
                peak = close
                cycle_id += 1
                if self.exit_policy == "opportunity_loss":
                    # Capture only the actual entry-day triggers. Later signals
                    # cannot replace this tuple or restart the entry clock.
                    entry_branches = tuple(branch for branch in EXIT_BRANCHES[self.opportunity]
                                           if branch_truth[branch] is True)
                reason = "ENTRY"
            elif opportunity:
                reason = "RISK_BLOCK"
            rows.append({
                "target_position": float(active),
                "planned_target": float(active),
                "planned_age": age,
                "planned_cycle_id": cycle_id,
                "opportunity_active": opportunity,
                "o01_active": o01,
                "n09_active": n09,
                "risk_available": risk_available,
                "risk_ok": risk_ok,
                "planned_peak_close": peak,
                "signal_drawdown": drawdown,
                "decision_reason": reason,
            })
            if self.exit_policy == "opportunity_loss":
                rows[-1]["planned_entry_branches"] = "|".join(entry_branches)
        return pd.DataFrame(rows, index=sessions)


def synthetic_selfcheck() -> dict[str, object]:
    """Independent boundary expectations and prefix checks; no market reads."""
    sessions = pd.bdate_range("2020-06-05", periods=18, name="dt")
    features = pd.DataFrame({"Date": sessions})
    for name in BOOLEAN_COLUMNS:
        features[name] = name.endswith("_valid") or name in {"o01", "own_positive"}
    execution = pd.DataFrame({"Date": sessions, "Close": 10.0})
    inputs = {"features": features, "execution": execution}
    base = {
        "opportunity": "o01", "confirm_o01": True, "hold_days": 5,
        "cooldown": 0, "risk_gate": "none", "risk_exit": False,
        "trailing_stop": 0.0, "entry_premium": 0.0, "allocation": 1.0,
        "rule": {"data_source": {"path": "synthetic.csv", "sha256": "a" * 64}},
    }
    strategy = S012PlannedCycle(ParameterSet(base))
    full = strategy.calculate_history(inputs, sessions)
    assert full["target_position"].iloc[:7].tolist() == [1., 1., 1., 1., 1., 0., 1.]
    assert full["planned_age"].iloc[5] == 5
    assert full["decision_reason"].iloc[5] == "EXIT_AGE"
    assert "target_position" not in {s.value_field for s in strategy.definition.observation.series}
    assert {s.value_field for s in strategy.definition.observation.series} <= set(full.columns)
    prefix_checks = 0
    for end in range(1, len(sessions) + 1):
        prefix = strategy.calculate_history(inputs, sessions[:end])
        pd.testing.assert_frame_equal(prefix, full.iloc[:end])
        prefix_checks += 1
    delayed = S012PlannedCycle(ParameterSet({**base, "hold_days": 1, "cooldown": 2}))
    result = delayed.calculate_history(inputs, sessions)
    assert result["target_position"].iloc[:5].tolist() == [1., 0., 0., 0., 1.]
    assert result["decision_reason"].iloc[2:4].tolist() == ["COOLDOWN", "COOLDOWN"]
    stop_inputs = {**inputs, "execution": execution.copy()}
    stop_inputs["execution"].loc[1:2, "Close"] = [12., 10.]
    stopping = S012PlannedCycle(ParameterSet({**base, "trailing_stop": 0.1}))
    stopped = stopping.calculate_history(stop_inputs, sessions)
    assert stopped["decision_reason"].iloc[2] == "EXIT_TRAILING"
    assert stopped["target_position"].iloc[2] == 0.0
    blocked_inputs = {**inputs, "features": features.copy()}
    blocked_inputs["features"].loc[1, "vol_high"] = True
    risk = S012PlannedCycle(ParameterSet({**base, "risk_gate": "vol", "risk_exit": True}))
    risk_result = risk.calculate_history(blocked_inputs, sessions)
    assert risk_result["decision_reason"].iloc[1] == "EXIT_RISK"
    assert risk_result["target_position"].iloc[1] == 0.0
    reset = strategy.calculate_window_history(inputs, sessions[3:])
    assert reset["planned_age"].iloc[0] == 0 and reset["decision_reason"].iloc[0] == "ENTRY"
    malformed = {**inputs, "features": features.drop(columns="o01_valid")}
    try:
        strategy.calculate_history(malformed, sessions)
    except ValueError:
        pass
    else:
        raise AssertionError("missing validity must fail")
    # New opportunity definitions must remain causal and preserve independent valid bits.
    for mode in ("m05", "o01_m05", "momentum", "momentum_union", "all_union"):
        ff = features.copy()
        ff["m05"] = True
        ff["mom3_positive"] = True
        ff["o01_valid"] = False
        impl = S012PlannedCycle(ParameterSet({**base, "opportunity": mode}))
        ii = {"features": ff, "execution": execution}
        hh = impl.calculate_history(ii, sessions)
        assert hh.target_position.iloc[0] == 1.0
        for end in (1, 5, 11):
            pd.testing.assert_frame_equal(impl.calculate_history(ii, sessions[:end]), hh.iloc[:end])
    return {
        "status": "PASS", "prefix_checks": prefix_checks,
        "boundaries": ["hold_age", "flat_exit", "cooldown", "trailing_close",
                       "risk_exit", "window_reset", "missing_validity"],
        "history_columns": list(full.columns),
    }


def synthetic_policy_selfcheck() -> dict[str, object]:
    """Hand-built policy witnesses only; no files, market or account operations."""
    base = {
        "opportunity": "momentum", "confirm_o01": True, "hold_days": 6,
        "cooldown": 0, "risk_gate": "none", "risk_exit": False,
        "trailing_stop": 0.0, "entry_premium": 0.0, "allocation": 1.0,
        "exit_policy": "opportunity_loss", "min_hold": 1,
        "risk_unknown_policy": "block",
        "rule": {"data_source": {"path": "synthetic.csv", "sha256": "a" * 64}},
    }
    checks = 0
    prefix_checks = 0

    def require(condition: bool, label: str) -> None:
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    def inputs(count: int = 6):
        dates = pd.bdate_range("2020-06-05", periods=count, name="dt")
        facts = pd.DataFrame({"Date": dates})
        for field in BOOLEAN_COLUMNS:
            facts[field] = field.endswith("_valid") or field in {"own_positive", "mom_high"}
        return {"features": facts, "execution": pd.DataFrame({"Date": dates, "Close": 10.0})}, dates

    def calculate(frames, dates, **changes):
        return S012PlannedCycle(ParameterSet({**base, **changes})).calculate_history(frames, dates)

    frames, dates = inputs()
    frames["features"].loc[0, "mom3_positive"] = True
    result = calculate(frames, dates, min_hold=2)
    require(result.decision_reason.iloc[:3].tolist() == ["ENTRY", "HOLD", "EXIT_OPPORTUNITY_LOSS"],
            "loss must wait for min_hold")
    require(result.planned_age.iloc[:3].tolist() == [0, 1, 2], "entry age must advance")
    frames["features"].loc[1, "mom3_valid"] = False
    result = calculate(frames, dates)
    require(result.decision_reason.iloc[:3].tolist() == ["ENTRY", "HOLD", "EXIT_OPPORTUNITY_LOSS"],
            "unknown trigger cannot imply opportunity loss")
    frames["features"].loc[1:, "mom3_valid"] = False
    result = calculate(frames, dates, hold_days=3, min_hold=3)
    require(result.decision_reason.iloc[3] == "EXIT_AGE", "maximum hold overrides unknown")

    frames, dates = inputs()
    frames["features"].loc[:1, "mom3_positive"] = True
    frames["features"].loc[1:, "m05"] = True
    frames["features"].loc[2, "o01"] = True
    result = calculate(frames, dates, opportunity="momentum_union", min_hold=2, cooldown=1)
    require(result.planned_entry_branches.iloc[:3].tolist() == ["momentum"] * 3,
            "new branches must not replace actual entry triggers")
    require(result.planned_age.iloc[:3].tolist() == [0, 1, 2], "new branches must not reset age")
    require(result.decision_reason.iloc[2:5].tolist() == ["EXIT_OPPORTUNITY_LOSS", "COOLDOWN", "ENTRY"],
            "branch loss exit must retain cooldown")
    require(result.planned_entry_branches.iloc[4] == "m05" and result.planned_cycle_id.iloc[4] == 2,
            "next entry must capture a fresh branch set")

    frames, dates = inputs()
    frames["features"].loc[0, ["o01", "m05"]] = True
    frames["features"].loc[1, "m05"] = True
    frames["features"].loc[2, "m05_valid"] = False
    result = calculate(frames, dates, opportunity="o01_m05")
    require(result.decision_reason.iloc[:4].tolist() == ["ENTRY", "HOLD", "HOLD", "EXIT_OPPORTUNITY_LOSS"],
            "all recorded union triggers must be known false")
    frames["features"].loc[0, "own_positive"] = False
    result = calculate(frames, dates, opportunity="o01_m05")
    require(result.planned_entry_branches.iloc[0] == "m05", "o01 entry truth includes confirmation")

    for policy in ("block", "known_only"):
        frames, dates = inputs()
        frames["features"]["mom3_positive"] = True
        frames["features"].loc[0, "vol_valid"] = False
        result = calculate(frames, dates, risk_gate="vol", risk_unknown_policy=policy)
        require(result.decision_reason.iloc[0] == ("RISK_BLOCK" if policy == "block" else "ENTRY"),
                "unknown-entry policy must be explicit")
        frames["features"].loc[0, "vol_valid"] = True
        frames["features"].loc[1, "vol_valid"] = False
        result = calculate(frames, dates, risk_gate="vol", risk_exit=True, risk_unknown_policy=policy)
        require(result.decision_reason.iloc[1] == ("EXIT_RISK" if policy == "block" else "HOLD"),
                "unknown-holding policy must be explicit")
        require(not bool(result.risk_available.iloc[1]), "unknown must remain visible")
        frames["features"].loc[1, "vol_valid"] = True
        frames["features"].loc[1, "vol_high"] = True
        result = calculate(frames, dates, risk_gate="vol", risk_exit=True, risk_unknown_policy=policy)
        require(result.decision_reason.iloc[1] == "EXIT_RISK", "known high risk must still exit")
        result = calculate(frames, dates, risk_gate="none", risk_exit=True, risk_unknown_policy=policy)
        require(result.decision_reason.iloc[1] == "HOLD", "none risk gate must stay unchanged")

    # Prefix comparisons also exercise both exit policies with future rows present.
    frames, dates = inputs(12)
    frames["features"]["mom3_positive"] = [i % 4 < 2 for i in range(12)]
    frames["features"]["mom3_valid"] = [i % 5 != 1 for i in range(12)]
    frames["features"]["vol_valid"] = [i % 4 != 0 for i in range(12)]
    frames["features"]["vol_high"] = [i % 7 == 3 for i in range(12)]
    for exit_policy in ("fixed", "opportunity_loss"):
        for risk_policy in ("block", "known_only"):
            impl = S012PlannedCycle(ParameterSet({**base, "exit_policy": exit_policy,
                "risk_gate": "vol", "risk_exit": True, "risk_unknown_policy": risk_policy}))
            full = impl.calculate_history(frames, dates)
            for end in range(1, len(dates) + 1):
                pd.testing.assert_frame_equal(impl.calculate_history(frames, dates[:end]), full.iloc[:end],
                                              check_exact=True)
                prefix_checks += 1
            pd.testing.assert_frame_equal(impl.calculate_window_history(frames, dates[3:]),
                                          impl.calculate_history(frames, dates[3:]), check_exact=True)
            checks += 1
    return {
        "status": "PASS", "checks": checks, "prefix_checks": prefix_checks,
        "boundaries": ["min_hold", "unknown_trigger", "max_hold", "entry_branch_lock",
                       "entry_age_lock", "union", "o01_confirmation", "cooldown",
                       "fresh_cycle", "risk_unknown_entry", "risk_unknown_holding",
                       "known_risk_exit", "none_risk", "window_reset"],
        "evidence_scope": "SYNTHETIC_ONLY",
    }


def synthetic_trend_selfcheck() -> dict[str, object]:
    """Synthetic trend witnesses; no files, pytest, real prices or account calls."""
    base = {
        "opportunity": "momentum", "confirm_o01": True, "hold_days": 6,
        "cooldown": 0, "risk_gate": "none", "risk_exit": False,
        "trailing_stop": 0.0, "entry_premium": 0.0, "allocation": 1.0,
        "exit_policy": "opportunity_loss", "min_hold": 1, "risk_unknown_policy": "block",
        "rule": {"data_source": {"path": "synthetic.csv", "sha256": "a" * 64}},
    }
    checks = 0
    prefix_checks = 0
    lookbacks = (5, 10, 20, 60, 120)

    def require(condition: bool, label: str) -> None:
        nonlocal checks
        if not condition:
            raise AssertionError(label)
        checks += 1

    def inputs(prices):
        dates = pd.bdate_range("2020-06-05", periods=len(prices), name="dt")
        facts = pd.DataFrame({"Date": dates})
        for field in BOOLEAN_COLUMNS:
            facts[field] = field.endswith("_valid") or field in {"own_positive", "mom_high"}
        facts["mom3_positive"] = True
        return {"features": facts, "execution": pd.DataFrame({"Date": dates, "Close": prices})}, dates

    for lookback in lookbacks:
        frames, dates = inputs([10.0] * lookback + [11.0, 10.0, 9.0, 10.0, 11.0, 10.0])
        impl = S012PlannedCycle(ParameterSet({**base, "momentum_lookback": lookback}))
        known, positive = _price_momentum(_indexed(frames["execution"], "execution"), dates, lookback)
        require(not known.iloc[:lookback].any(), "first n observed rows must remain unknown")
        require(known.iloc[lookback:].all(), "complete observed references must be known")
        require(positive.iloc[lookback:lookback + 3].tolist() == [True, False, False],
                "only strictly positive known change activates momentum")
        full = impl.calculate_history(frames, dates)
        require(not full.opportunity_active.iloc[:lookback].any(), "unknown warmup cannot enter")
        window = impl.calculate_window_history(frames, dates[lookback:])
        require(window.decision_reason.iloc[:2].tolist() == ["ENTRY", "EXIT_OPPORTUNITY_LOSS"],
                "pre-window history must remain available for the first window signal")
        for end in (1, lookback - 1, lookback, lookback + 1, lookback + 3, len(dates)):
            pd.testing.assert_frame_equal(impl.calculate_history(frames, dates[:end]), full.iloc[:end],
                                          check_exact=True)
            prefix_checks += 1
        altered = {key: value.copy(deep=True) for key, value in frames.items()}
        altered["execution"]["Close"] = altered["execution"]["Close"].astype(object)
        altered["execution"].loc[lookback + 3:, "Close"] = "future-unavailable"
        pd.testing.assert_frame_equal(impl.calculate_history(altered, dates[:lookback + 3]),
                                      full.iloc[:lookback + 3], check_exact=True)
        checks += 1

        union = S012PlannedCycle(ParameterSet({**base, "momentum_lookback": lookback,
                                               "opportunity": "momentum_union"}))
        frames["features"].loc[0, "m05"] = True
        early = union.calculate_history(frames, dates[:3])
        require(early.decision_reason.iloc[:2].tolist() == ["ENTRY", "EXIT_OPPORTUNITY_LOSS"],
                "known union branch remains independent of unknown momentum")
        require(early.planned_entry_branches.iloc[:2].tolist() == ["m05", "m05"],
                "unknown momentum must not become an entry branch")
        frames["features"].loc[0, "m05"] = False
        frames["features"].loc[lookback, "m05"] = True
        frames["features"].loc[lookback + 1, "m05_valid"] = False
        frames["features"].loc[lookback + 1:, "o01"] = True
        window = union.calculate_window_history(frames, dates[lookback:])
        require(window.decision_reason.iloc[:3].tolist() == ["ENTRY", "HOLD", "EXIT_OPPORTUNITY_LOSS"],
                "unknown recorded branch must prevent early opportunity-loss exit")
        require(window.planned_entry_branches.iloc[:3].tolist() == ["momentum|m05"] * 3,
                "later branches cannot replace recorded entry branches")
        require(window.planned_age.iloc[:3].tolist() == [0, 1, 2], "new branches cannot reset age")

    frames, dates = inputs([12.0, 11.0, 10.0, 9.0])
    frames["features"]["mom3_positive"] = [True, False, True, False]
    frames["features"]["mom3_valid"] = [False, True, True, True]
    default = S012PlannedCycle(ParameterSet(base))
    explicit = S012PlannedCycle(ParameterSet({**base, "momentum_lookback": 3}))
    first = default.calculate_history(frames, dates)
    pd.testing.assert_frame_equal(first, explicit.calculate_history(frames, dates), check_exact=True)
    require(first.opportunity_active.tolist() == [False, False, True, False],
            "default three must use declared feature bits, not raw price direction")
    for invalid in (2, 121, True, 3.0):
        try:
            S012PlannedCycle(ParameterSet({**base, "momentum_lookback": invalid}))
        except ValueError as error:
            require("momentum_lookback" in str(error), "invalid lookback must be rejected explicitly")
        else:
            raise AssertionError("invalid lookback was accepted")
    return {
        "status": "PASS", "checks": checks, "prefix_checks": prefix_checks,
        "lookbacks": list(lookbacks),
        "boundaries": ["warmup_unknown", "full_available_history", "strict_positive_direction",
                       "prefix", "future_price_isolation", "union_independent_known",
                       "entry_branch_lock", "unknown_retention", "entry_age_lock",
                       "legacy_three", "integer_search_domain"],
        "evidence_scope": "SYNTHETIC_ONLY",
    }
