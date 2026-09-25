"""Frozen S003-v1 constituent-moneyflow intraday overlay runtime."""

from __future__ import annotations

from datetime import date, timedelta
import json
from typing import Any, Mapping

import pandas as pd
from dataflows import Dataset

from ..algorithm import StrategyImplementation
from ..calculation import (
    CalculationScope,
    CalendarWindow,
    InputRange,
    next_session_calculation_scope,
    next_session_calendar_window,
)
from ..contracts import TradableWindow
from ..errors import RuntimeContractError
from ..implementation_identity import implementation_sha256
from ..models import (
    CutoffRule,
    DecisionContract,
    ExecutionPolicy,
    ImplementationRef,
    InputContract,
    InputRequirement,
    MonitoringPolicy,
    ParameterSet,
    RequiredCapabilities,
    RuntimeDefinition,
    StrategyRelease,
)


_SEED = "constituent_moneyflow_seed"
_WEIGHTS = "incremental_constituent_weights"
_MONEYFLOW = "incremental_constituent_moneyflow"
_MARKET = "adjusted_daily"
_EXECUTION = "execution_daily"
_CALENDAR = "trading_calendar"
_INDEX_SYMBOL = "000905.SH"
_SEED_START = date(2021, 1, 4)
_SEED_CUTOFF = date(2026, 9, 8)


def _object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be an object")
    return value


def _seed_history(seed: pd.DataFrame) -> pd.DataFrame:
    required = ("Date", "ObservedWeightRatio", "MoneyflowBreadth")
    if not set(required) <= set(seed.columns):
        raise RuntimeContractError("S003-v1 seed history is structurally incomplete")
    history = seed.loc[:, required].rename(
        columns={
            "Date": "date",
            "ObservedWeightRatio": "observed_weight_ratio",
            "MoneyflowBreadth": "moneyflow_breadth",
        }
    )
    history["date"] = pd.to_datetime(history["date"], errors="raise").dt.normalize()
    history["observed_weight_ratio"] = pd.to_numeric(
        history["observed_weight_ratio"], errors="raise"
    )
    history["moneyflow_breadth"] = pd.to_numeric(
        history["moneyflow_breadth"], errors="raise"
    )
    if history["date"].duplicated().any():
        raise RuntimeContractError("S003-v1 seed history contains duplicate sessions")
    return history.set_index("date").sort_index()


def _seed_snapshot(seed: pd.DataFrame) -> pd.DataFrame:
    required = {"SnapshotDate", "ConstituentsJson"}
    if not required <= set(seed.columns):
        raise RuntimeContractError("S003-v1 seed snapshot is structurally incomplete")
    rows = seed.loc[seed["ConstituentsJson"].notna() & seed["ConstituentsJson"].ne("")]
    if len(rows) != 1:
        raise RuntimeContractError("S003-v1 seed must contain one constituent snapshot")
    row = rows.iloc[0]
    try:
        members = json.loads(str(row["ConstituentsJson"]))
    except json.JSONDecodeError as exc:
        raise RuntimeContractError("S003-v1 seed snapshot is invalid") from exc
    if not isinstance(members, list) or not members:
        raise RuntimeContractError("S003-v1 seed snapshot has no members")
    snapshot = pd.DataFrame(members)
    if set(snapshot.columns) != {"symbol", "weight"}:
        raise RuntimeContractError("S003-v1 seed snapshot members are invalid")
    snapshot["Date"] = pd.Timestamp(row["SnapshotDate"]).normalize()
    snapshot["ConstituentSymbol"] = snapshot["symbol"].astype(str)
    snapshot["Weight"] = pd.to_numeric(snapshot["weight"], errors="raise")
    if snapshot["ConstituentSymbol"].duplicated().any():
        raise RuntimeContractError("S003-v1 seed snapshot contains duplicate members")
    return snapshot[["Date", "ConstituentSymbol", "Weight"]]


def _incremental_history(
    seed: pd.DataFrame,
    weights: pd.DataFrame,
    moneyflow: pd.DataFrame,
    minimum_coverage: float,
) -> pd.DataFrame:
    snapshot_frames = [weights]
    if not seed.empty:
        snapshot_frames.insert(0, _seed_snapshot(seed))
    snapshots = pd.concat(snapshot_frames, ignore_index=True).rename(
        columns={
            "Date": "snapshot_date",
            "ConstituentSymbol": "symbol",
            "Weight": "weight",
        }
    )
    snapshots["snapshot_date"] = pd.to_datetime(
        snapshots["snapshot_date"], errors="raise"
    ).dt.normalize()
    snapshots["weight"] = pd.to_numeric(snapshots["weight"], errors="raise")
    snapshots = snapshots.drop_duplicates(["snapshot_date", "symbol"], keep="last")
    flows = moneyflow.rename(
        columns={
            "Date": "date",
            "Symbol": "symbol",
            "NetMoneyflowAmount": "net_moneyflow",
        }
    ).copy()
    flows["date"] = pd.to_datetime(flows["date"], errors="raise").dt.normalize()
    flows["net_moneyflow"] = pd.to_numeric(flows["net_moneyflow"], errors="coerce")
    if flows.duplicated(["date", "symbol"]).any():
        raise RuntimeContractError("S003-v1 moneyflow contains duplicate member sessions")

    rows: list[dict[str, object]] = []
    for session in pd.DatetimeIndex(flows["date"].drop_duplicates().sort_values()):
        eligible = snapshots.loc[snapshots["snapshot_date"].lt(session), "snapshot_date"]
        if eligible.empty:
            raise RuntimeContractError(
                f"S003-v1 has no constituent snapshot before {session.date().isoformat()}"
            )
        snapshot_date = eligible.max()
        members = snapshots.loc[
            snapshots["snapshot_date"].eq(snapshot_date), ["symbol", "weight"]
        ]
        selected = members.merge(
            flows.loc[flows["date"].eq(session), ["symbol", "net_moneyflow"]],
            on="symbol",
            how="left",
            validate="one_to_one",
        )
        total = float(selected["weight"].sum())
        observed = float(selected.loc[selected["net_moneyflow"].notna(), "weight"].sum())
        coverage = observed / total if total else float("nan")
        if pd.isna(coverage) or coverage < minimum_coverage:
            raise RuntimeContractError(
                "S003-v1 incremental constituent moneyflow coverage is below the frozen gate: "
                f"session={session.date().isoformat()}, coverage={coverage:.2%}"
            )
        positive = float(selected.loc[selected["net_moneyflow"].gt(0), "weight"].sum())
        rows.append(
            {
                "date": session,
                "observed_weight_ratio": coverage,
                "moneyflow_breadth": positive / observed,
            }
        )
    if not rows:
        return pd.DataFrame(columns=["observed_weight_ratio", "moneyflow_breadth"])
    return pd.DataFrame(rows).set_index("date").sort_index()


def _decision_history(history: pd.DataFrame, feature: Mapping[str, Any]) -> pd.DataFrame:
    result = history.sort_index().copy()
    values = result["moneyflow_breadth"]
    if feature["threshold_excludes_current_session"]:
        values = values.shift(1)
    lookback = int(feature["threshold_lookback_sessions"])
    result["threshold"] = values.rolling(lookback, min_periods=lookback).quantile(
        float(feature["threshold_quantile"])
    )
    result["signal_active"] = result["moneyflow_breadth"].ge(result["threshold"])
    result["target_position"] = result["signal_active"].astype(float)
    return result


class S003V1(StrategyImplementation):
    """Executable S003-v1 with an immutable seed and point-in-time increments."""

    def __init__(self, release: StrategyRelease) -> None:
        payload = _object(release.payload, "strategy payload")
        if payload.get("strategy_kind") != "constituent_moneyflow_intraday_overlay":
            raise RuntimeContractError("S003-v1 strategy_kind differs")
        rule = _object(payload.get("rule"), "S003-v1 rule")
        self._feature = _object(rule.get("feature"), "S003-v1 feature")
        execution = _object(rule.get("execution"), "S003-v1 execution")
        self._symbol = str(rule.get("symbol", "")).upper()
        if self._symbol != "510500.SH":
            raise RuntimeContractError("S003-v1 frozen symbol must be 510500.SH")
        requirements = (
            InputRequirement(
                _SEED,
                Dataset.STRATEGY_FEATURE_EVIDENCE.value,
                release.release_id,
                "daily",
                0,
                CutoffRule.LATEST_AVAILABLE,
            ),
            InputRequirement(
                _WEIGHTS,
                Dataset.INDEX_CONSTITUENT_WEIGHT.value,
                _INDEX_SYMBOL,
                "snapshot",
                1,
                CutoffRule.LATEST_AVAILABLE,
                370,
            ),
            InputRequirement(
                _MONEYFLOW,
                Dataset.STOCK_MONEYFLOW.value,
                None,
                "daily",
                0,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                _MARKET,
                Dataset.ETF_OHLCV.value,
                self._symbol,
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                _EXECUTION,
                Dataset.ETF_UNADJUSTED_DAILY.value,
                self._symbol,
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                _CALENDAR,
                Dataset.TRADING_CALENDAR.value,
                "SSE",
                "daily",
                0,
                CutoffRule.LATEST_AVAILABLE,
            ),
        )
        self._definition = RuntimeDefinition(
            1,
            release.strategy_family_id,
            release.version,
            release.release_id,
            release.release_hash,
            ImplementationRef(
                __name__,
                self.__class__.__name__,
                1,
                implementation_sha256(
                    (
                        "strategies/s003_v1.py",
                        "calculation.py",
                        "execution_rules.py",
                        "resources/s003_v1_seed.csv.gz",
                    )
                ),
            ),
            ParameterSet(release.payload),
            InputContract(requirements),
            DecisionContract("INTRADAY_OVERLAY", 0.0, 1.0, "NEXT_SESSION_OPEN_TO_11_30"),
            ExecutionPolicy("INTRADAY_OVERLAY", execution),
            MonitoringPolicy("FORWARD_OBSERVATION", {"frozen": True}),
            RequiredCapabilities(
                tuple(item.dataset for item in requirements),
                ("LIMIT", "MARKET"),
                ("OPEN", "11:30_CLOSE"),
            ),
            tradable_symbol=self._symbol,
        )

    @classmethod
    def from_release(cls, release: StrategyRelease) -> "S003V1":
        if release.release_id != "S003-v1":
            raise RuntimeContractError("S003V1 can only load S003-v1")
        return cls(release)

    @property
    def definition(self) -> RuntimeDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow) -> CalendarWindow:
        window = next_session_calendar_window(self._definition, tradable_window)
        lookback_start = tradable_window.start - timedelta(
            days=int(self._feature["threshold_lookback_sessions"]) * 2 + 31
        )
        return CalendarWindow(min(window.start, lookback_start), window.end)

    def derive_calculation_scope(
        self,
        tradable_window: TradableWindow,
        calendar_dates: tuple[date, ...],
    ) -> CalculationScope:
        base = next_session_calculation_scope(
            self._definition,
            tradable_window,
            calendar_dates,
        )
        first_signal = base.signal_dates[base.trading_dates[0]]
        last_signal = base.signal_dates[base.trading_dates[-1]]
        history_length = int(self._feature["threshold_lookback_sessions"]) + 1
        available = tuple(item for item in calendar_dates if item <= first_signal)
        if len(available) < history_length:
            raise RuntimeContractError("S003-v1 trading calendar cannot satisfy threshold history")
        calculation_start = available[-history_length]
        calculation_dates = tuple(
            item for item in calendar_dates if calculation_start <= item <= last_signal
        )
        ranges = dict(base.inputs)
        seed_start = max(_SEED_START, calculation_start)
        seed_end = min(_SEED_CUTOFF, last_signal)
        ranges[_SEED] = (
            InputRange(seed_start, seed_end, None) if seed_start <= seed_end else None
        )
        incremental_dates = tuple(item for item in calculation_dates if item > _SEED_CUTOFF)
        if incremental_dates:
            incremental_start = incremental_dates[0]
            incremental_end = incremental_dates[-1]
            ranges[_WEIGHTS] = InputRange(
                incremental_start - timedelta(days=370), incremental_end, None
            )
            ranges[_MONEYFLOW] = InputRange(
                incremental_start, incremental_end, incremental_end
            )
        else:
            ranges[_WEIGHTS] = None
            ranges[_MONEYFLOW] = None
        return CalculationScope(
            tradable_window,
            base.trading_dates,
            base.signal_dates,
            calculation_dates,
            ranges,
        )

    def calculate_history(
        self,
        inputs: Mapping[str, pd.DataFrame],
        sessions: pd.DatetimeIndex,
    ) -> pd.DataFrame:
        if _SEED in inputs:
            seed = inputs[_SEED]
            history = _seed_history(seed)
        else:
            seed = pd.DataFrame()
            history = pd.DataFrame(
                columns=["observed_weight_ratio", "moneyflow_breadth"]
            )
        has_weights = _WEIGHTS in inputs
        has_moneyflow = _MONEYFLOW in inputs
        if has_weights != has_moneyflow:
            raise RuntimeContractError("S003-v1 incremental inputs are incomplete")
        if has_weights:
            incremental = _incremental_history(
                seed,
                inputs[_WEIGHTS],
                inputs[_MONEYFLOW],
                float(self._feature["minimum_observed_weight_ratio"]),
            )
            history = pd.concat([history, incremental]).sort_index()
            history = history.loc[~history.index.duplicated(keep="last")]
        decisions = _decision_history(history, self._feature)
        requested = pd.DatetimeIndex(sessions).normalize()
        requested.name = "date"
        missing = requested.difference(decisions.index)
        if not missing.empty:
            raise RuntimeContractError(
                "S003-v1 prepared history misses calculation sessions: "
                + ",".join(item.date().isoformat() for item in missing)
            )
        return decisions.reindex(requested)
