"""S010 EX17: intraday price-volume directional proxy survey."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S010_EX17"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX16": "377498ab48b3d06d1d21328344703312777b0caaefb685e7d6afdf38769a5a11",
}
START, CUTOFF = "2024-09-09", "2026-09-28"
MINUTE_SHA256 = "a585da0e526018c90320b71626c8768bb5020692c8fcf85597d5a55e8e2e71c6"
DAILY_SHA256 = "727085dab698e770ef1afd82eefbc460d4b68a2bb72820ba3d3ef86b4dab7212"
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
SEED = 2026092917
FACTORS = ("flow_signed_volume", "flow_late_signed_volume", "flow_late_minus_early",
           "flow_final_bar_share", "flow_weighted_return_efficiency")
OUTCOMES = ("open_return_1", "open_return_5", "adverse_5")
B_PRICE = ("etf_return_1", "etf_return_5", "etf_volatility_20",
           "tsfresh_range__median", "intra_afternoon_return")
B_SHAPE = (*B_PRICE, "intra_afternoon_volume_share", "intra_realized_vol",
           "intra_close_location", "theme_return_1")
COMPARISONS = tuple((factor, outcome, name, baseline)
                    for factor in FACTORS for outcome in OUTCOMES
                    for name, baseline in (("B_PRICE", B_PRICE), ("B_SHAPE", B_SHAPE)))


def _features(minute: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    bars = minute.copy()
    day = daily.copy()
    bars["Date"] = pd.to_datetime(bars["Date"], errors="raise")
    day["Date"] = pd.to_datetime(day["Date"], errors="raise").dt.normalize()
    if bars["Date"].duplicated().any() or day["Date"].duplicated().any():
        raise ValueError("duplicate intraday bar or daily session")
    day = day.sort_values("Date").set_index("Date")
    rows = []
    for session, group in bars.groupby(bars["Date"].dt.normalize(), sort=True):
        group = group.sort_values("Date")
        if len(group) != 8 or session not in day.index:
            raise ValueError("intraday session has missing bars or daily reference")
        item = day.loc[session]
        close = group["Close"].to_numpy(dtype=float)
        high = group["High"].to_numpy(dtype=float)
        low = group["Low"].to_numpy(dtype=float)
        volume = group["Volume"].to_numpy(dtype=float)
        amount = group["Amount"].to_numpy(dtype=float)
        if (not np.isfinite(np.r_[close, high, low, volume, amount]).all()
                or (close <= 0).any() or (volume < 0).any() or (amount < 0).any()):
            raise ValueError("invalid intraday bar")
        for field, observed in (("High", high.max()), ("Low", low.min()),
                                ("Close", close[-1]), ("Volume", volume.sum()),
                                ("Amount", amount.sum())):
            if not np.isclose(observed, float(item[field]), atol=1e-5, rtol=1e-6):
                raise ValueError(f"intraday {field} differs from daily reference")
        returns = np.diff(np.log(close))
        signs = np.sign(returns)
        weights = volume[1:]
        total = weights.sum()
        early = weights[:3].sum()
        late = weights[3:].sum()
        realized = np.sqrt(np.square(returns).sum())
        signed_all = float(np.dot(signs, weights) / total) if total else np.nan
        signed_early = float(np.dot(signs[:3], weights[:3]) / early) if early else np.nan
        signed_late = float(np.dot(signs[3:], weights[3:]) / late) if late else np.nan
        rows.append({
            "Date": session,
            "flow_signed_volume": signed_all,
            "flow_late_signed_volume": signed_late,
            "flow_late_minus_early": signed_late - signed_early,
            "flow_final_bar_share": float(signs[-1] * volume[-1] / volume.sum())
            if volume.sum() else np.nan,
            "flow_weighted_return_efficiency": float(np.dot(returns, weights) / total / realized)
            if total and realized else np.nan,
        })
    frame = pd.DataFrame(rows).set_index("Date").sort_index()
    if not frame.index.equals(day.index):
        raise ValueError("intraday and daily session calendars differ")
    return frame


def _adverse(daily: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    daily = daily.copy()
    daily["Date"] = pd.to_datetime(daily["Date"], errors="raise")
    daily = daily.set_index("Date").sort_index()
    if not daily.index.equals(sessions):
        raise ValueError("daily and predecessor calendars differ")
    opens = daily["Open"].to_numpy(dtype=float)
    lows = daily["Low"].to_numpy(dtype=float)
    if not np.isfinite(opens).all() or not np.isfinite(lows).all():
        raise ValueError("ETF execution prices contain nonfinite value")
    if (opens <= 0).any() or (lows <= 0).any() or (lows > opens).any():
        raise ValueError("ETF execution low or open is invalid")
    out = np.full(len(sessions), np.nan)
    for position in range(len(sessions) - 5):
        out[position] = lows[position + 1:position + 6].min() / opens[position + 1] - 1
    return pd.Series(out, index=sessions, name="adverse_5")


def _folds(index: pd.DatetimeIndex, horizon: int):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 1 + horizon < test[0])
        yield start, train, test


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray):
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights, weights


def _evaluate(joined: pd.DataFrame):
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor, outcome, baseline_name, baseline in COMPARISONS:
        horizon = 5 if outcome == "adverse_5" else int(outcome.rsplit("_", 1)[-1])
        base_errors, extra_errors, positive = [], [], 0
        for start, train_positions, test_positions in _folds(dates, horizon):
            columns = [*baseline, factor, outcome]
            train = joined.iloc[train_positions][columns].dropna()
            test = joined.iloc[test_positions][columns].dropna()
            if len(train) < 80 or len(test) < 15:
                details.append({"Factor": factor, "Outcome": outcome,
                                "Baseline": baseline_name, "TestStart": start,
                                "Status": "INSUFFICIENT", "TrainRows": len(train),
                                "TestRows": len(test)})
                continue
            label_end = dates.get_loc(train.index[-1]) + 1 + horizon
            if label_end >= len(dates) or dates[label_end] >= test.index[0]:
                raise ValueError("training label crosses chronological test boundary")
            y_train = train[outcome].to_numpy(dtype=float)
            y_test = test[outcome].to_numpy(dtype=float)
            base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                             test[list(baseline)].to_numpy(dtype=float))
            extra, weights = _ridge(train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                                    test[[*baseline, factor]].to_numpy(dtype=float))
            b, e = np.square(y_test - base), np.square(y_test - extra)
            base_errors.extend(b)
            extra_errors.extend(e)
            positive += int(e.mean() < b.mean())
            details.append({"Factor": factor, "Outcome": outcome,
                            "Baseline": baseline_name, "TestStart": start,
                            "Status": "EVALUATED", "TrainRows": len(train),
                            "TestRows": len(test),
                            "TrainLabelEnd": dates[label_end].date().isoformat(),
                            "BaseMse": float(b.mean()), "ExtraMse": float(e.mean()),
                            "ExtraCoefficient": float(weights[-1])})
        totals.append({"Factor": factor, "Outcome": outcome, "Baseline": baseline_name,
                       "OosRows": len(base_errors), "PositiveFolds": positive,
                       "MseReduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                       if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    minute = pd.DataFrame({"Date": [day + pd.Timedelta(hours=10) + pd.Timedelta(minutes=30 * i)
                                    for day in days for i in range(8)],
                           "Close": [1.0 + 0.01 * i for _ in days for i in range(8)],
                           "High": 1.08, "Low": 0.99, "Volume": 100.0, "Amount": 100.0})
    daily = pd.DataFrame({"Date": days, "Open": 1.0, "High": 1.08, "Low": 0.99,
                          "Close": 1.07, "Volume": 800.0, "Amount": 800.0})
    features = _features(minute, daily)
    if len(features) != 800 or not np.isclose(features.iloc[0]["flow_signed_volume"], 1.0):
        raise ValueError("synthetic directional flow failed")
    first = next(_folds(pd.DatetimeIndex(days), 5))
    if first[1][-1] + 6 >= first[2][0]:
        raise ValueError("synthetic label purge failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does intraday directional volume add information beyond known ETF price and shape?",
            hypothesis="Volume accompanying directional 30-minute moves can distinguish price discovery from noise.",
            falsification_conditions=("No stable increment after afternoon price and shape controls",
                                    "New factors are redundant with prior intraday features",
                                    "Sign or source identity differs across time"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Directional participation may carry information beyond price change",),
                information_paths=("T ETF 30-minute price-volume bars -> later executable-session prices",),
                stage_objectives=("Audit five intraday directional-volume definitions",
                                  "Compare with existing price and intraday-shape information"),
                observation_metrics=("coverage", "purged MSE", "training coefficient direction",
                                     "near-duplicate relationships"),
                methodology=("Thirty fixed comparisons", "Three purged chronological folds",
                             "Standardized ridge with penalty ten"),
                predecessor_experiment_ids=tuple(RECEIPTS),
            ),
            subjects=("159326.SZ",),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
        )

    def synthetic_precheck(self) -> None:
        _precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parent
        for name, receipt in RECEIPTS.items():
            if context.predecessors[name].receipt_sha256 != receipt:
                raise ValueError(f"predecessor receipt differs: {name}")
            validate_experiment_archive(root.parent / name)
        first = root.parent / "20260929_S010_EX01" / "artifacts"
        third = root.parent / "20260929_S010_EX03" / "artifacts"
        fourth = root.parent / "20260929_S010_EX04" / "artifacts"
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        prior = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        theme = pd.read_csv(fourth / "theme_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        sessions = pd.DatetimeIndex(inherited.index)
        for frame in (labels, prior, theme):
            if not sessions.equals(pd.DatetimeIndex(frame.index)):
                raise ValueError("predecessor calendars differ")
        data = {}
        lineage = {}
        for name, frequency, expected in (("minute", "30m", MINUTE_SHA256),
                                          ("daily", "daily", DAILY_SHA256)):
            result = context.data.fetch(DataRequest(
                Dataset.ETF_OHLCV, "159326.SZ", START, CUTOFF, CUTOFF, frequency,
                {"env_file": str(root.parents[2] / ".env")},
            ))
            if not result.ready or result.identity is None:
                error = result.error
                raise ValueError(f"{frequency} DFLS unavailable: {result.status.value}"
                                 + ("" if error is None else f" {error.code}: {error.message}"))
            if result.identity.content_sha256 != expected:
                raise ValueError(f"{frequency} DFLS identity differs from EX03")
            data[name] = result.dataframe
            lineage[name] = {"sha256": expected, "rows": len(result.dataframe),
                             "available_at": result.identity.temporal_contract.available_at}
        features = _features(data["minute"], data["daily"])
        if not features.index.equals(sessions):
            raise ValueError("intraday and predecessor calendar differ")
        adverse = _adverse(data["daily"], sessions)
        joined = inherited[list(name for name in B_SHAPE if name in inherited.columns)]
        joined = joined.join(prior[["intra_afternoon_return", "intra_afternoon_volume_share",
                                    "intra_realized_vol", "intra_close_location"]])
        joined = joined.join(theme[["theme_return_1"]]).join(features)
        joined = joined.join(labels[["open_return_1", "open_return_5"]]).join(adverse)
        joined = joined.replace([np.inf, -np.inf], np.nan)
        scores, folds = _evaluate(joined)
        quality = pd.DataFrame({"Factor": FACTORS,
                                "FiniteRows": features.notna().sum().to_numpy(),
                                "UniqueValues": features.nunique().to_numpy()})
        relations = joined[[*FACTORS, "intra_afternoon_return",
                            "intra_afternoon_volume_share", "etf_return_1"]].corr().loc[list(FACTORS)]
        relations.index.name = "Factor"
        artifacts = []
        for name, frame in (("flow_factors.csv.gz", features.reset_index()),
                            ("factor_quality.csv", quality), ("factor_scores.csv", scores),
                            ("fold_scores.csv", folds),
                            ("factor_relations.csv", relations.reset_index())):
            frame.to_csv(context.workspace.path(name), index=False,
                         compression="gzip" if name.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX17-{name.split('.')[0]}"))
        summary = {"decision": "INTRADAY_FLOW_SURVEY_COMPLETE",
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "input_identity": lineage, "sealed_date_rows_read": 0,
                   "account_replay_performed": False,
                   "order_flow_observed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX17-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"finite_all_factor_rows": int(features.notna().all(axis=1).sum())},
            artifacts=tuple(artifacts),
        )
