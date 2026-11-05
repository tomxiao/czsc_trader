"""Pure frozen signal mathematics, copied without changes for native V4."""
from __future__ import annotations
from datetime import date
import json
from typing import Any, Mapping
import pandas as pd
from strategy_runtime import RuntimeContractError

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
    history["moneyflow_breadth"] = pd.to_numeric(history["moneyflow_breadth"], errors="raise")
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
        members = snapshots.loc[snapshots["snapshot_date"].eq(snapshot_date), ["symbol", "weight"]]
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
