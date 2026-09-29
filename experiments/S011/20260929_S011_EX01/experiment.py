"""S011 EX01: fixed A/B/C factor census with post-adjusted return labels."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import tsfresh
from tsfresh.feature_extraction import feature_calculators as fc

from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S011_EX01"
START, END = "2024-12-26", "2026-09-28"
SEED = 2026092901
HORIZONS = (1, 5, 10)
TEST_WINDOWS = (
    ("2025-07-01", "2026-01-01"),
    ("2026-01-01", "2026-07-01"),
    ("2026-07-01", "2026-10-01"),
)
TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
FACTORS = (
    "tail_return_60", "tail_return_90", "tail_vs_morning",
    "tail_amount_share_60", "tail_pressure_60",
    "range_cooling_3", "amount_cooling_3", "shock_absorption",
    "tsfresh_return_autocorr_20", "tsfresh_return_changes_20",
    "tsfresh_return_cid_20", "tsfresh_range_autocorr_20",
    "tsfresh_range_changes_20", "tsfresh_range_cid_20",
)
BASELINE = (
    "etf_return_1", "etf_return_5", "theme_return_1",
    "range_median_20", "amount_ratio_20",
)


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="raise")
    if result["Date"].duplicated().any() or not result["Date"].is_monotonic_increasing:
        raise ValueError("daily source dates are duplicated or unordered")
    return result.set_index("Date")


def _intraday_features(frame: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    bars = frame.copy()
    bars["Date"] = pd.to_datetime(bars["Date"], errors="raise")
    bars["Session"] = bars["Date"].dt.normalize()
    bars["Time"] = bars["Date"].dt.strftime("%H:%M")
    counts = bars.groupby("Session").size()
    if not counts.index.equals(sessions) or not counts.eq(len(TIMES)).all():
        raise ValueError("30-minute source does not cover eight bars per daily session")
    if bars.duplicated(["Session", "Time"]).any():
        raise ValueError("30-minute source has duplicate session bars")
    close = bars.pivot(index="Session", columns="Time", values="Close")
    amount = bars.pivot(index="Session", columns="Time", values="Amount")
    if set(close.columns) != set(TIMES) or set(amount.columns) != set(TIMES):
        raise ValueError("30-minute source has an unexpected clock")
    if close.le(0).any().any() or amount.lt(0).any().any() or amount.sum(axis=1).le(0).any():
        raise ValueError("30-minute price or amount is invalid")
    result = pd.DataFrame(index=sessions)
    result["tail_return_60"] = close["15:00"] / close["14:00"] - 1
    result["tail_return_90"] = close["15:00"] / close["13:30"] - 1
    result["tail_vs_morning"] = result["tail_return_60"] - (
        close["11:30"] / close["10:00"] - 1
    )
    result["tail_amount_share_60"] = (
        amount["14:30"] + amount["15:00"]
    ) / amount.sum(axis=1)
    result["tail_pressure_60"] = result["tail_return_60"] * result["tail_amount_share_60"]
    return result


def _tsfresh_roll(series: pd.Series, method: str) -> pd.Series:
    calculators = {
        "autocorr": lambda x: fc.autocorrelation(x, lag=1),
        "changes": fc.absolute_sum_of_changes,
        "cid": lambda x: fc.cid_ce(x, normalize=True),
    }
    return series.rolling(20, min_periods=20).apply(calculators[method], raw=True)


def _matrix(
    daily: pd.DataFrame, intraday: pd.DataFrame, theme: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    etf = _indexed(daily)
    theme_index = _indexed(theme)
    if not etf.index.equals(theme_index.index):
        raise ValueError("ETF and theme-index sessions differ")
    if etf[["Open", "High", "Low", "Close", "Amount"]].le(0).any().any():
        raise ValueError("ETF daily prices or amount are invalid")
    if theme_index["Close"].le(0).any():
        raise ValueError("theme index close is invalid")
    result = _intraday_features(intraday, etf.index)
    ret = etf["Close"].pct_change(fill_method=None)
    ranges = (etf["High"] - etf["Low"]) / etf["Close"]
    amount = etf["Amount"]
    old_range = ranges.shift(3).rolling(20).median()
    old_amount = amount.shift(3).rolling(20).mean()
    prior_shock = ranges.shift(1).rolling(3).max()
    result["range_cooling_3"] = -(ranges.rolling(3).mean() / old_range)
    result["amount_cooling_3"] = -(amount.rolling(3).mean() / old_amount)
    result["shock_absorption"] = (
        prior_shock / ranges.shift(4).rolling(20).median()
    ) * (1 - ranges / prior_shock)
    for name, series in (("return", ret), ("range", ranges)):
        for method in ("autocorr", "changes", "cid"):
            result[f"tsfresh_{name}_{method}_20"] = _tsfresh_roll(series, method)
    result["etf_return_1"] = ret
    result["etf_return_5"] = etf["Close"].pct_change(5, fill_method=None)
    result["theme_return_1"] = theme_index["Close"].pct_change(fill_method=None)
    result["range_median_20"] = ranges.rolling(20).median()
    result["amount_ratio_20"] = amount / amount.shift(1).rolling(20).mean()
    labels = pd.DataFrame(index=etf.index)
    entry = etf["Open"].shift(-1)
    for horizon in HORIZONS:
        labels[f"future_hfq_{horizon}"] = etf["Close"].shift(-horizon) / entry - 1
    return result.replace([np.inf, -np.inf], np.nan), labels


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights, weights


def _survey(matrix: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    joined = matrix.join(labels)
    sessions = pd.DatetimeIndex(joined.index)
    coverage, scores, folds, redundant = [], [], [], []
    for factor in FACTORS:
        series = matrix[factor].dropna()
        coverage.append({"Factor": factor, "FiniteRows": len(series),
                         "UniqueValues": int(series.nunique()),
                         "FirstFiniteDate": str(series.index.min().date()) if len(series) else ""})
    for left_index, left in enumerate(FACTORS):
        for right in FACTORS[left_index + 1:]:
            pair = matrix[[left, right]].dropna()
            if len(pair) >= 80:
                rho = pair[left].corr(pair[right], method="spearman")
                if np.isfinite(rho) and abs(rho) >= 0.95:
                    redundant.append({"Left": left, "Right": right, "Rows": len(pair),
                                      "AbsSpearman": float(abs(rho))})
    for factor in FACTORS:
        for horizon in HORIZONS:
            outcome = f"future_hfq_{horizon}"
            pair = joined[[factor, outcome]].dropna()
            rho = pair[factor].corr(pair[outcome], method="spearman") if len(pair) >= 20 else np.nan
            q25, q75 = pair[factor].quantile([0.25, 0.75]) if len(pair) else (np.nan, np.nan)
            high = pair.loc[pair[factor].ge(q75), outcome]
            low = pair.loc[pair[factor].le(q25), outcome]
            baseline_errors: list[float] = []
            extra_errors: list[float] = []
            positive_folds = 0
            for test_start, test_end in TEST_WINDOWS:
                test_positions = np.flatnonzero(
                    (sessions >= pd.Timestamp(test_start)) & (sessions < pd.Timestamp(test_end))
                )
                if not len(test_positions):
                    continue
                train_positions = np.flatnonzero(np.arange(len(sessions)) + horizon < test_positions[0])
                columns = [*BASELINE, factor, outcome]
                train = joined.iloc[train_positions][columns].dropna()
                test = joined.iloc[test_positions][columns].dropna()
                if len(train) < 80 or len(test) < 15:
                    folds.append({"Factor": factor, "Horizon": horizon, "TestStart": test_start,
                                  "Status": "INSUFFICIENT", "TrainRows": len(train),
                                  "TestRows": len(test)})
                    continue
                final_train_position = sessions.get_loc(train.index[-1])
                if final_train_position + horizon >= test_positions[0]:
                    raise ValueError("training label reaches chronological test segment")
                y_train = train[outcome].to_numpy(dtype=float)
                y_test = test[outcome].to_numpy(dtype=float)
                base, _ = _ridge(train[list(BASELINE)].to_numpy(dtype=float), y_train,
                                 test[list(BASELINE)].to_numpy(dtype=float))
                extra, weights = _ridge(train[[*BASELINE, factor]].to_numpy(dtype=float), y_train,
                                        test[[*BASELINE, factor]].to_numpy(dtype=float))
                base_sq = np.square(y_test - base)
                extra_sq = np.square(y_test - extra)
                baseline_errors.extend(base_sq.tolist())
                extra_errors.extend(extra_sq.tolist())
                positive_folds += int(extra_sq.mean() < base_sq.mean())
                folds.append({"Factor": factor, "Horizon": horizon, "TestStart": test_start,
                              "Status": "EVALUATED", "TrainRows": len(train),
                              "TestRows": len(test),
                              "TrainLabelEnd": str(sessions[final_train_position + horizon].date()),
                              "BaseMse": float(base_sq.mean()), "ExtraMse": float(extra_sq.mean()),
                              "ExtraCoefficient": float(weights[-1])})
            scores.append({
                "Factor": factor, "Horizon": horizon, "PairedRows": len(pair),
                "Spearman": float(rho) if np.isfinite(rho) else np.nan,
                "HighRows": len(high), "LowRows": len(low),
                "HighMinusLow": float(high.mean() - low.mean()) if len(high) and len(low) else np.nan,
                "EvaluatedFolds": sum(row["Status"] == "EVALUATED" for row in folds
                                      if row["Factor"] == factor and row["Horizon"] == horizon),
                "PositiveFolds": positive_folds,
                "MseReduction": float(1 - np.mean(extra_errors) / np.mean(baseline_errors))
                if baseline_errors else np.nan,
            })
    return (pd.DataFrame(coverage), pd.DataFrame(scores), pd.DataFrame(folds),
            pd.DataFrame(redundant, columns=["Left", "Right", "Rows", "AbsSpearman"]))


def _precheck() -> None:
    day = pd.Timestamp("2025-03-03")
    bars = pd.DataFrame({
        "Date": [day + pd.Timedelta(time + ":00") for time in TIMES],
        "Close": [1.00, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07],
        "Amount": [100.0] * len(TIMES),
    })
    original = _intraday_features(bars, pd.DatetimeIndex([day]))
    bars["Close"] *= 7
    scaled = _intraday_features(bars, pd.DatetimeIndex([day]))
    if not np.allclose(original.to_numpy(), scaled.to_numpy()):
        raise ValueError("same-day adjustment did not cancel from intraday factors")
    if not np.isclose(original["tail_amount_share_60"].iloc[0], 0.25):
        raise ValueError("synthetic tail amount share differs")
    if not np.isfinite(fc.autocorrelation(np.arange(20, dtype=float), lag=1)):
        raise ValueError("tsfresh calculator is unavailable")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            research_question="Which of A/B tail pressure or C volatility absorption adds information beyond daily controls?",
            hypothesis="Tail strength has competing continuation/reversion predictions; post-shock cooling may describe a separate horizon.",
            falsification_conditions=(
                "Tail direction is unstable or adds no information beyond daily controls",
                "Cooling only repeats daily return/range or changes sign across periods",
                "Coverage, post-adjustment or time contract fails",
            ),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Completed tail trading and post-shock absorption offer competing future-price explanations",),
                information_paths=("T completed ETF bars and theme close -> T+1 decision -> later continuous prices",),
                stage_objectives=("Census fixed A/B/C factors", "Compare each with identical daily controls and chronology"),
                observation_metrics=("Coverage and redundancy", "Rank association and high-low difference",
                                     "Purged chronological MSE increment and coefficient direction"),
                methodology=("14 fixed factors and three future horizons", "Three chronological test segments",
                             "Training-only ridge standardization; alpha 10"),
                predecessor_experiment_ids=(),
            ),
            subjects=("159326.SZ",),
            dependencies=(ExperimentDependency("numpy", np.__version__),
                          ExperimentDependency("pandas", pd.__version__),
                          ExperimentDependency("tsfresh", tsfresh.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
        )

    def synthetic_precheck(self) -> None:
        _precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        repository = Path(__file__).resolve().parents[3]
        env_file = str(repository / ".env")
        requests = (
            ("daily", Dataset.ETF_OHLCV, "159326.SZ", "daily"),
            ("intraday", Dataset.ETF_OHLCV, "159326.SZ", "30m"),
            ("theme", Dataset.DOMESTIC_INDEX_CLOSE_DAILY, "931994.CSI", "daily"),
        )
        frames: dict[str, pd.DataFrame] = {}
        identities: dict[str, dict] = {}
        for name, dataset, symbol, frequency in requests:
            result = context.data.fetch(DataRequest(
                dataset, symbol, START, END, None, frequency, {"env_file": env_file},
            ))
            if not result.ready or result.identity is None:
                error = result.error
                raise ValueError(f"{name} DFLS unavailable: {result.status.value}"
                                 + ("" if error is None else f" {error.code}: {error.message}"))
            if name != "theme" and (
                result.identity.metadata.get("adjustment") != "hfq"
                or result.identity.metadata.get("availability_time_field") != "AvailableDate"
            ):
                raise ValueError(f"{name} DFLS price or availability contract differs")
            frames[name] = result.dataframe.copy()
            identities[name] = {
                "dataset": dataset.value, "symbol": symbol, "frequency": frequency,
                "content_sha256": result.identity.content_sha256,
                "metadata": dict(result.identity.metadata),
                "rows": len(result.dataframe),
            }
        if (len(frames["daily"]), len(frames["intraday"]), len(frames["theme"])) != (426, 3408, 426):
            raise ValueError("source coverage differs from the registered 426-session contract")
        for name in ("daily", "intraday"):
            available = pd.to_datetime(frames[name]["AvailableDate"], errors="raise")
            if not available.dt.strftime("%H:%M:%S").eq("17:00:00").all():
                raise ValueError(f"{name} post-adjustment availability differs")
        matrix, labels = _matrix(frames["daily"], frames["intraday"], frames["theme"])
        if len(matrix) != 426 or tuple(matrix.loc[:, FACTORS].columns) != FACTORS:
            raise ValueError("factor matrix does not match frozen census")
        coverage, scores, folds, redundant = _survey(matrix, labels)
        if len(scores) != len(FACTORS) * len(HORIZONS):
            raise ValueError("factor survey comparison count differs")
        artifacts = []
        for filename, frame in (
            ("factor_matrix.csv.gz", matrix.reset_index(names="Date")),
            ("future_labels.csv.gz", labels.reset_index(names="Date")),
            ("factor_coverage.csv", coverage), ("factor_scores.csv", scores),
            ("fold_scores.csv", folds), ("redundancy.csv", redundant),
        ):
            frame.to_csv(context.workspace.path(filename), index=False,
                         compression="gzip" if filename.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(filename, f"S011-EX01-{filename.split('.')[0]}"))
        summary = {
            "decision": "SURVEY_COMPLETE", "sessions": len(matrix),
            "factor_count": len(FACTORS), "comparison_count": len(scores),
            "evaluated_folds": int(folds["Status"].eq("EVALUATED").sum()),
            "insufficient_folds": int(folds["Status"].eq("INSUFFICIENT").sum()),
            "redundant_pairs": len(redundant), "source_identities": identities,
            "old_s010_overlap_is_development_pool": True,
            "pcf_or_intraday_vintages_used": False, "account_replay_performed": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
            encoding="utf-8",
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "S011-EX01-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "SURVEY_COMPLETE", "factor_count": len(FACTORS),
                   "comparison_count": len(scores), "account_replay_performed": False},
            diagnostics={"evaluated_folds": summary["evaluated_folds"],
                         "redundant_pairs": summary["redundant_pairs"]},
            artifacts=tuple(artifacts),
        )
