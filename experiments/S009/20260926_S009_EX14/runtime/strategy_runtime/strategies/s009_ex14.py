"""S009 EX14: opportunity prototypes allowing same-day multi-observation FRED releases."""

from __future__ import annotations

from datetime import date
from typing import Mapping

import numpy as np
import pandas as pd
from dataflows import Dataset
from strategy_runtime import (
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    HistoryPolicy,
    ImplementationRef,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    StrategyCandidate,
    StrategyImplementation,
    TradableWindow,
    next_session_calculation_scope,
    next_session_calendar_window,
)
from strategy_runtime.errors import RuntimeContractError


PROTOTYPES = {
    "P01": "LIQUIDITY_ONLY",
    "P02": "POLICY_ONLY",
    "P03": "OR",
    "P04": "AND",
}
SHARE_SYMBOLS = ("510050.SH", "510300.SH", "159915.SZ")


def _daily(frame: pd.DataFrame, column: str) -> pd.Series:
    if not {"Date", column}.issubset(frame.columns):
        raise RuntimeContractError(f"S009 input lacks Date or {column}")
    dates = pd.to_datetime(frame["Date"], errors="raise").dt.normalize()
    if dates.duplicated().any():
        raise RuntimeContractError("S009 input has duplicate dates")
    values = pd.to_numeric(frame[column], errors="raise").astype(float)
    if not np.isfinite(values).all() or values.le(0).any():
        raise RuntimeContractError(f"S009 input has invalid {column}")
    return pd.Series(values.to_numpy(), index=pd.DatetimeIndex(dates), name=column).sort_index()


def opportunity_history(inputs: Mapping[str, pd.DataFrame], sessions: pd.DatetimeIndex,
                        prototype_id: str) -> pd.DataFrame:
    if prototype_id not in PROTOTYPES:
        raise RuntimeContractError("unsupported S009 prototype")
    calendar = pd.DatetimeIndex(pd.to_datetime(inputs["adjusted_daily"]["Date"]).dt.normalize())
    if calendar.has_duplicates or not calendar.is_monotonic_increasing:
        raise RuntimeContractError("S009 market sessions must be unique and ordered")
    share_flows: dict[int, list[pd.Series]] = {20: [], 60: []}
    for symbol in SHARE_SYMBOLS:
        known = _daily(inputs[f"shares_{symbol}"], "TotalShare").reindex(calendar).ffill()
        if known.isna().any():
            raise RuntimeContractError(f"S009 share history starts too late: {symbol}")
        # T's share count is published T+1 morning, so T's decision uses T-1.
        for window in share_flows:
            share_flows[window].append(np.log(known).diff(window).shift(1))
    values = {}
    for window, series in share_flows.items():
        values[f"BroadLiquidity{window}"] = pd.concat(series, axis=1).median(axis=1)

    policy = inputs["policy_uncertainty"].copy()
    if not {"Date", "AvailableDate", "PolicyUncertaintyIndex"}.issubset(policy.columns):
        raise RuntimeContractError("S009 policy source is incomplete")
    policy["Date"] = pd.to_datetime(policy["Date"], errors="raise").dt.normalize()
    policy["AvailableDate"] = pd.to_datetime(
        policy["AvailableDate"], errors="raise"
    ).dt.normalize()
    policy["PolicyUncertaintyIndex"] = pd.to_numeric(
        policy["PolicyUncertaintyIndex"], errors="raise"
    )
    if (policy["AvailableDate"] < policy["Date"]).any() or (
        policy["PolicyUncertaintyIndex"] <= 0
    ).any():
        raise RuntimeContractError("S009 policy vintage is causally invalid")
    policy = policy.sort_values(["AvailableDate", "Date"])
    policy = policy.drop_duplicates(subset=["AvailableDate"], keep="last")
    aligned = pd.merge_asof(
        pd.DataFrame({"DecisionDate": calendar}),
        policy[["AvailableDate", "PolicyUncertaintyIndex"]],
        left_on="DecisionDate",
        right_on="AvailableDate",
        direction="backward",
        allow_exact_matches=False,
    )
    observed = pd.to_datetime(aligned["AvailableDate"])
    if observed.notna().any() and not observed.dropna().lt(aligned.loc[observed.notna(), "DecisionDate"]).all():
        raise RuntimeContractError("S009 policy observation is not strictly prior")
    policy_values = aligned["PolicyUncertaintyIndex"].astype(float)
    values["PolicyUncertainty20"] = pd.Series(
        np.log(policy_values.rolling(20).mean() / policy_values.rolling(120).mean()).to_numpy(),
        index=calendar,
    )
    history = pd.DataFrame(values, index=calendar)
    liquidity = history["BroadLiquidity20"].gt(0) | history["BroadLiquidity60"].gt(0)
    global_policy = history["PolicyUncertainty20"].gt(0)
    rule = PROTOTYPES[prototype_id]
    target = {
        "LIQUIDITY_ONLY": liquidity,
        "POLICY_ONLY": global_policy,
        "OR": liquidity | global_policy,
        "AND": liquidity & global_policy,
    }[rule]
    history["target_position"] = target.astype(float)
    requested = pd.DatetimeIndex(sessions).normalize()
    if not requested.isin(history.index).all():
        raise RuntimeContractError("S009 history misses requested decision sessions")
    result = history.reindex(requested)
    if result[["BroadLiquidity20", "BroadLiquidity60", "PolicyUncertainty20"]].isna().any().any():
        raise RuntimeContractError("S009 opportunity components are incomplete")
    return result


class S009PrototypeEx14(StrategyImplementation):
    def __init__(self, candidate: StrategyCandidate) -> None:
        parameters = candidate.payload["parameters"]
        prototype_id = str(parameters.get("prototype_id", ""))
        if prototype_id not in PROTOTYPES or set(parameters) != {"prototype_id"}:
            raise RuntimeContractError("S009 prototype parameters are invalid")
        self._prototype_id = prototype_id
        runtime = candidate.payload["runtime"]
        requirements = (
            InputRequirement("adjusted_daily", Dataset.ETF_OHLCV.value, "518880.SH", "daily", 120, CutoffRule.SIGNAL_SESSION),
            InputRequirement("execution_daily", Dataset.ETF_UNADJUSTED_DAILY.value, "518880.SH", "daily", 1, CutoffRule.SIGNAL_SESSION),
            *(InputRequirement(f"shares_{symbol}", Dataset.ETF_SHARE_SIZE.value, symbol, "daily", 120, CutoffRule.PREVIOUS_SESSION) for symbol in SHARE_SYMBOLS),
            InputRequirement("policy_uncertainty", Dataset.US_POLICY_UNCERTAINTY_DAILY.value, None, "daily", 120, CutoffRule.LATEST_AVAILABLE, 7),
            InputRequirement("trading_calendar", Dataset.TRADING_CALENDAR.value, "SSE", "daily", 0, CutoffRule.LATEST_AVAILABLE),
        )
        self._definition = RuntimeDefinition(
            schema_version=2,
            strategy_family_id="S009",
            version=None,
            release_id=candidate.reference_id,
            release_hash=candidate.runtime_identity_sha256,
            implementation=ImplementationRef(
                str(runtime["module"]), str(runtime["qualname"]),
                int(runtime["contract_version"]), str(runtime["source_sha256"]),
            ),
            parameters=ParameterSet(parameters),
            inputs=InputContract(requirements),
            decision=DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION_OPEN"),
            execution=ExecutionPolicy("FROZEN_RULE", {
                "capital": {"fee_rate": 0.001, "mode": "full_available_cash", "target_scope": "entry_cycle"},
                "entry": {"order_type": "LIMIT", "limit_family": "previous_close_ratio", "limit_parameter": 0.1},
                "exit": {"order_type": "MARKET", "limit_ratio": 0.1},
                "instrument": {"symbol": "518880.SH", "lot_size": 100, "maximum_order_quantity": 100000000, "price_limit_ratio": 0.1, "price_tick": 0.001},
            }),
            monitoring=MonitoringPolicy("FORWARD_OBSERVATION", {"prototype_id": prototype_id}),
            capabilities=RequiredCapabilities(
                tuple(sorted({item.dataset for item in requirements})), ("LIMIT", "MARKET")
            ),
            tradable_symbol="518880.SH",
            state_mode="STATELESS",
            identity_kind="CANDIDATE",
            candidate_id=candidate.candidate_id,
            history=HistoryPolicy("CANONICAL_REPLAY", "2019-01-02", "2018-01-01"),
        )

    @classmethod
    def from_candidate(cls, candidate: StrategyCandidate) -> "S009PrototypeEx14":
        return cls(candidate)

    @property
    def definition(self) -> RuntimeDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow):
        return next_session_calendar_window(self._definition, tradable_window)

    def derive_calculation_scope(self, tradable_window: TradableWindow,
                                 calendar_dates: tuple[date, ...]):
        return next_session_calculation_scope(self._definition, tradable_window, calendar_dates)

    def calculate_history(self, inputs: Mapping[str, pd.DataFrame],
                          sessions: pd.DatetimeIndex) -> pd.DataFrame:
        return opportunity_history(inputs, sessions, self._prototype_id)

