"""Frozen S007-v1 multi-source causal feature-gate runtime."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping

import numpy as np
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
from ..execution_rules import effective_target_order_type
from ..implementation_identity import implementation_sha256
from ..models import (
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
    StrategyRelease,
)


_SEED = "feature_seed"
_MARKET = "adjusted_daily"
_SHIBOR = "incremental_shibor_daily"
_CHINEXT = "incremental_chinext_daily_basic"
_SHARES = "incremental_etf_share_size"
_SPX = "incremental_spx_daily"
_EXECUTION = "execution_daily"
_CALENDAR = "trading_calendar"
_FROZEN_HISTORY_START = pd.Timestamp("2021-01-04")
_FROZEN_HISTORY_END = pd.Timestamp("2026-09-02")
_GLOBAL_HISTORY_START = pd.Timestamp("2020-12-01")


def _object(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RuntimeContractError(f"{field_name} must be an object")
    return value


def causal_percentile(values: pd.Series, window: int, minimum: int) -> pd.Series:
    def rank_last(items: np.ndarray) -> float:
        current = items[-1]
        valid = items[np.isfinite(items)]
        if not np.isfinite(current) or len(valid) < minimum:
            return np.nan
        return float(
            (np.count_nonzero(valid < current) + 0.5 * np.count_nonzero(valid == current))
            / len(valid)
            - 0.5
        )

    return values.astype(float).rolling(window, min_periods=minimum).apply(rank_last, raw=True)


def materialize_s007_features(inputs: Mapping[str, pd.DataFrame]) -> pd.DataFrame:
    market = inputs[_MARKET].copy()
    market["Date"] = pd.to_datetime(market["Date"]).dt.normalize()
    market = market.drop_duplicates("Date", keep="last").set_index("Date").sort_index()
    sessions = market.index
    close = pd.to_numeric(market["Close"], errors="raise")
    volume = pd.to_numeric(market["Volume"], errors="raise")
    amount = pd.to_numeric(market["Amount"], errors="raise")
    output = pd.DataFrame(index=sessions)
    output["price_close_vwap_deviation"] = close / (amount / volume) - 1.0
    output["price_intraday_range"] = (
        pd.to_numeric(market["High"], errors="raise") - pd.to_numeric(market["Low"], errors="raise")
    ) / close
    output["tsfresh__log_volume_change__mean__lb20"] = (
        np.log(volume).diff().rolling(20, min_periods=20).mean()
    )

    shibor = inputs[_SHIBOR].drop_duplicates("Date", keep="last").copy()
    shibor["Date"] = pd.to_datetime(shibor["Date"]).dt.normalize()
    overnight = (
        shibor.set_index("Date")["OvernightRate"]
        .astype(float)
        .sort_index()
        .reindex(sessions)
        .ffill(limit=4)
    )
    output["risk_shibor_on_change_5d"] = overnight.diff(5)

    chinext = inputs[_CHINEXT].drop_duplicates("Date", keep="last").copy()
    chinext["Date"] = pd.to_datetime(chinext["Date"]).dt.normalize()
    turnover = (
        chinext.set_index("Date")["TurnoverRateFreeFloat"]
        .astype(float)
        .sort_index()
        .reindex(sessions)
    )
    output["risk_chinext_turnover_z20"] = (
        turnover - turnover.rolling(20).mean()
    ) / turnover.rolling(20).std(ddof=0)

    shares = inputs[_SHARES].drop_duplicates("Date", keep="last").copy()
    shares["Date"] = pd.to_datetime(shares["Date"]).dt.normalize()
    total_share = (
        shares.set_index("Date")["TotalShare"].astype(float).sort_index().reindex(sessions)
    )
    output["micro_share_change_5d_lag1"] = total_share.pct_change(5, fill_method=None).shift(1)

    spx = inputs[_SPX].drop_duplicates("Date", keep="last").copy()
    spx["Date"] = pd.to_datetime(spx["Date"]).dt.normalize()
    mapped = pd.merge_asof(
        pd.DataFrame({"date": sessions}),
        spx[["Date", "PercentChange"]].sort_values("Date"),
        left_on="date",
        right_on="Date",
        direction="backward",
        allow_exact_matches=False,
    ).set_index("date")
    output["risk_global_spx_return"] = mapped["PercentChange"].astype(float)
    # S007-v1 was researched and frozen with a feature panel beginning on this
    # session.  Earlier market rows may be published as calculation context,
    # but admitting them into rolling normalization changes the frozen target
    # sequence during 2021.  Keep the historical initialization boundary part
    # of the executable version identity.
    return output.loc[output.index >= _FROZEN_HISTORY_START]


def _seed_panel(seed: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    required = {"Date", *features}
    if not required <= set(seed.columns):
        raise RuntimeContractError("S007-v1 feature seed is structurally incomplete")
    panel = seed.loc[:, ["Date", *features]].copy()
    panel["Date"] = pd.to_datetime(panel["Date"], errors="raise").dt.normalize()
    if panel["Date"].duplicated().any():
        raise RuntimeContractError("S007-v1 feature seed contains duplicate sessions")
    for feature in features:
        panel[feature] = pd.to_numeric(panel[feature], errors="coerce")
    panel = panel.set_index("Date").sort_index()
    if (
        panel.index.min() != _FROZEN_HISTORY_START
        or panel.index.max() > _FROZEN_HISTORY_END
    ):
        raise RuntimeContractError("S007-v1 feature seed has an invalid frozen range")
    return panel


def calculate_s007_history(
    panel: pd.DataFrame, normalization: Mapping[str, Any], score: Mapping[str, Any]
) -> pd.DataFrame:
    orientations = {
        name: int(value) for name, value in _object(score["orientations"], "orientations").items()
    }
    normalized = pd.DataFrame(index=panel.index)
    for feature, orientation in orientations.items():
        normalized[feature] = (
            causal_percentile(
                panel[feature],
                int(normalization["lookback_sessions"]),
                int(normalization["minimum_observations"]),
            )
            * orientation
        )
    base_weights = dict(_object(score["base_weights"], "base weights"))
    confirmation_weights = dict(_object(score["confirmation_weights"], "confirmation weights"))
    base = normalized.mul(pd.Series(base_weights), axis=1).sum(axis=1, min_count=len(base_weights))
    confirmation = normalized.mul(pd.Series(confirmation_weights), axis=1).sum(
        axis=1, min_count=len(confirmation_weights)
    )
    current = 0
    targets: list[int] = []
    actions: list[str] = []
    for base_value, confirmation_value in zip(base, confirmation, strict=True):
        action = "HOLD_POSITION" if current else "HOLD_CASH"
        if np.isfinite(base_value):
            if (
                current == 0
                and base_value >= float(score["entry_threshold"])
                and confirmation_value >= float(score["confirmation_threshold"])
            ):
                current = 1
                action = "ENTER"
            elif current == 1 and base_value <= float(score["exit_threshold"]):
                current = 0
                action = "EXIT"
        targets.append(current)
        actions.append(action)
    return pd.DataFrame(
        {
            "base_score": base,
            "confirmation_score": confirmation,
            "target_position": targets,
            "action": actions,
        },
        index=panel.index,
    )


def resolve_s007_feature_panel(
    inputs: Mapping[str, pd.DataFrame],
    score: Mapping[str, Any],
) -> pd.DataFrame:
    """Combine the immutable frozen seed with point-in-time incremental features."""

    features = sorted(score["orientations"])
    if _SEED not in inputs:
        raise RuntimeContractError("S007-v1 prepared inputs have no feature seed")
    panel = _seed_panel(inputs[_SEED], features)
    incremental_names = {_SHIBOR, _CHINEXT, _SHARES, _SPX}
    present = incremental_names.intersection(inputs)
    if present and present != incremental_names:
        raise RuntimeContractError("S007-v1 incremental inputs are incomplete")
    if present:
        materialized = materialize_s007_features(inputs)
        additions = materialized.loc[
            materialized.index > _FROZEN_HISTORY_END, features
        ]
        panel = pd.concat([panel, additions])
    return panel[~panel.index.duplicated(keep="last")].sort_index()


class S007V1(StrategyImplementation):
    """Executable S007-v1; every feature is materialized from DFLS inputs."""

    def __init__(self, release: StrategyRelease) -> None:
        payload = _object(release.payload, "strategy payload")
        if payload.get("strategy_kind") != "causal_feature_gate":
            raise RuntimeContractError("S007-v1 strategy_kind differs")
        rule = _object(payload.get("rule"), "S007-v1 rule")
        self._normalization = _object(rule.get("normalization"), "S007-v1 normalization")
        self._score = _object(rule.get("score"), "S007-v1 score")
        execution = _object(rule.get("execution"), "S007-v1 execution")
        self._symbol = str(rule.get("symbol", "")).upper()
        if self._symbol != "588080.SH":
            raise RuntimeContractError("S007-v1 frozen symbol must be 588080.SH")
        self._release = release
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
                _MARKET,
                Dataset.ETF_OHLCV.value,
                self._symbol,
                "daily",
                1,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                _SHIBOR, Dataset.SHIBOR_DAILY.value, None, "daily", 6, CutoffRule.SIGNAL_SESSION
            ),
            InputRequirement(
                _CHINEXT,
                Dataset.INDEX_DAILY_BASIC.value,
                "399006.SZ",
                "daily",
                20,
                CutoffRule.SIGNAL_SESSION,
            ),
            InputRequirement(
                _SHARES,
                Dataset.ETF_SHARE_SIZE.value,
                self._symbol,
                "daily",
                6,
                CutoffRule.PREVIOUS_SESSION,
            ),
            InputRequirement(
                _SPX,
                Dataset.GLOBAL_INDEX_DAILY.value,
                "SPX",
                "daily",
                1,
                CutoffRule.LATEST_AVAILABLE,
                7,
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
                        "strategies/s007_v1.py",
                        "calculation.py",
                        "execution_rules.py",
                        "resources/s007_v1_seed.csv.gz",
                    )
                ),
            ),
            ParameterSet(release.payload),
            InputContract(requirements),
            DecisionContract("TARGET_POSITION", 0.0, 1.0, "NEXT_SESSION_OPEN"),
            ExecutionPolicy("FROZEN_RULE", execution),
            MonitoringPolicy("FORWARD_OBSERVATION", {"frozen": True}),
            RequiredCapabilities(
                tuple(sorted({item.dataset for item in requirements})),
                tuple(
                    sorted(
                        {
                            effective_target_order_type(execution, "BUY"),
                            effective_target_order_type(execution, "SELL"),
                        }
                    )
                ),
            ),
            tradable_symbol=self._symbol,
            history=HistoryPolicy("CANONICAL_REPLAY", "2021-01-04", "2020-12-01"),
        )

    @classmethod
    def from_release(cls, release: StrategyRelease) -> "S007V1":
        if release.release_id != "S007-v1":
            raise RuntimeContractError("S007V1 can only load S007-v1")
        return cls(release)

    @property
    def definition(self) -> RuntimeDefinition:
        return self._definition

    def calendar_window(self, tradable_window: TradableWindow) -> CalendarWindow:
        return next_session_calendar_window(self._definition, tradable_window)

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
        calculation_start = date.fromisoformat(
            self._definition.history.canonical_start
        )
        calculation_dates = tuple(
            item for item in calendar_dates if calculation_start <= item <= last_signal
        )
        ranges = dict(base.inputs)
        seed_end = min(_FROZEN_HISTORY_END.date(), last_signal)
        ranges[_SEED] = InputRange(calculation_start, seed_end, None)
        ranges[_EXECUTION] = InputRange(first_signal, last_signal, last_signal)

        incremental_dates = tuple(
            item for item in calculation_dates if item > _FROZEN_HISTORY_END.date()
        )
        if incremental_dates:
            first_incremental = incremental_dates[0]
            available = tuple(item for item in calendar_dates if item <= first_incremental)
            if len(available) < 21:
                raise RuntimeContractError(
                    "S007-v1 trading calendar cannot satisfy incremental feature history"
                )
            feature_start = available[-21]
            ranges[_MARKET] = InputRange(
                min(first_signal, feature_start), last_signal, last_signal
            )
            ranges[_SHIBOR] = InputRange(feature_start, last_signal, last_signal)
            ranges[_CHINEXT] = InputRange(feature_start, last_signal, last_signal)
            previous = tuple(item for item in calendar_dates if item < last_signal)
            if not previous:
                raise RuntimeContractError(
                    "S007-v1 trading calendar has no prior share publication session"
                )
            ranges[_SHARES] = InputRange(feature_start, previous[-1], previous[-1])
            ranges[_SPX] = InputRange(
                feature_start - timedelta(days=7), last_signal, None
            )
        else:
            ranges[_MARKET] = InputRange(first_signal, last_signal, last_signal)
            ranges[_SHIBOR] = None
            ranges[_CHINEXT] = None
            ranges[_SHARES] = None
            ranges[_SPX] = None
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
        panel = resolve_s007_feature_panel(inputs, self._score)
        history = calculate_s007_history(panel, self._normalization, self._score)
        requested = pd.DatetimeIndex(sessions).normalize()
        requested.name = "date"
        missing = requested.difference(history.index)
        if not missing.empty:
            raise RuntimeContractError(
                "S007-v1 prepared history misses calculation sessions: "
                + ",".join(item.date().isoformat() for item in missing)
            )
        return history.reindex(requested)
