"""Pure frozen signal mathematics, copied without changes for native V4."""
from __future__ import annotations
from typing import Any, Mapping
import numpy as np
import pandas as pd
from strategy_runtime import RuntimeContractError

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
    if panel.index.min() != _FROZEN_HISTORY_START or panel.index.max() > _FROZEN_HISTORY_END:
        raise RuntimeContractError("S007-v1 feature seed has an invalid frozen range")
    return panel

def calculate_scores(
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
    return base, confirmation

def calculate_s007_history(panel, normalization, score):
    base, confirmation = calculate_scores(panel, normalization, score)
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
        additions = materialized.loc[materialized.index > _FROZEN_HISTORY_END, features]
        panel = pd.concat([panel, additions])
    return panel[~panel.index.duplicated(keep="last")].sort_index()
