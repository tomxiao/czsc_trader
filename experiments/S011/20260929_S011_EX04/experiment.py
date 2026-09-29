"""S011 EX04: fixed census of five explanations through three ETF observations."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S011_EX04"
START, END = "2024-12-26", "2026-09-28"
SEED = 2026092904
HORIZONS = (1, 5, 10)
TEST_WINDOWS = (
    ("2025-07-01", "2026-01-01"),
    ("2026-01-01", "2026-07-01"),
    ("2026-07-01", "2026-10-01"),
)
TIMES = ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
FACTORS = ("overnight_minus_session_5", "flat_turnover", "extreme_order")
BASELINE = (
    "etf_return_1", "etf_return_5", "theme_return_1", "range_median_20",
    "amount_ratio_20", "open_gap_1", "body_return_1", "tail_return_60",
    "range_today", "close_location", "intraday_churn",
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
    if bars[["Open", "High", "Low", "Close"]].le(0).any().any():
        raise ValueError("30-minute source has nonpositive prices")
    result = pd.DataFrame(index=sessions)
    churn_values: list[float] = []
    order_values: list[float] = []
    tail_values: list[float] = []
    for session, group in bars.groupby("Session", sort=True):
        ordered = group.set_index("Time").reindex(TIMES)
        if ordered[["Open", "High", "Low", "Close"]].isna().any().any():
            raise ValueError(f"30-minute clock differs on {session.date()}")
        op = ordered["Open"].to_numpy(dtype=float)
        hi = ordered["High"].to_numpy(dtype=float)
        lo = ordered["Low"].to_numpy(dtype=float)
        cl = ordered["Close"].to_numpy(dtype=float)
        if np.any(hi < np.maximum(op, cl)) or np.any(lo > np.minimum(op, cl)):
            raise ValueError(f"30-minute OHLC is inconsistent on {session.date()}")
        steps = np.empty(len(TIMES), dtype=float)
        steps[0] = np.log(cl[0] / op[0])
        steps[1:] = np.log(cl[1:] / cl[:-1])
        travelled = float(np.abs(steps).sum())
        churn_values.append(float(1 - abs(steps.sum()) / travelled) if travelled > 0 else np.nan)
        high_at = np.flatnonzero(hi == hi.max())
        low_at = np.flatnonzero(lo == lo.min())
        if len(high_at) != 1 or len(low_at) != 1 or high_at[0] == low_at[0]:
            order_values.append(np.nan)
        else:
            order_values.append(1.0 if low_at[0] < high_at[0] else -1.0)
        tail_values.append(float(cl[7] / cl[5] - 1))
    result["intraday_churn"] = churn_values
    result["extreme_order"] = order_values
    result["tail_return_60"] = tail_values
    return result


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
    amount = etf["Amount"]
    ranges = (etf["High"] - etf["Low"]) / etf["Close"]
    overnight = np.log(etf["Open"] / etf["Close"].shift(1))
    session = np.log(etf["Close"] / etf["Open"])
    result["overnight_minus_session_5"] = (overnight - session).rolling(5).sum()
    result["amount_ratio_20"] = amount / amount.shift(1).rolling(20).mean()
    result["flat_turnover"] = result["amount_ratio_20"] * result["intraday_churn"]
    result["etf_return_1"] = ret
    result["etf_return_5"] = etf["Close"].pct_change(5, fill_method=None)
    result["theme_return_1"] = theme_index["Close"].pct_change(fill_method=None)
    result["range_median_20"] = ranges.rolling(20).median()
    result["open_gap_1"] = etf["Open"] / etf["Close"].shift(1) - 1
    result["body_return_1"] = etf["Close"] / etf["Open"] - 1
    result["range_today"] = ranges
    result["close_location"] = (etf["Close"] - etf["Low"]) / (etf["High"] - etf["Low"])
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


def _survey(matrix: pd.DataFrame, labels: pd.DataFrame):
    joined = matrix.join(labels)
    sessions = pd.DatetimeIndex(joined.index)
    coverage, scores, folds, redundant = [], [], [], []
    for factor in FACTORS:
        series = matrix[factor].dropna()
        coverage.append({
            "Factor": factor, "FiniteRows": len(series), "UniqueValues": int(series.nunique()),
            "FirstFiniteDate": str(series.index.min().date()) if len(series) else "",
        })
        for baseline in BASELINE:
            pair = matrix[[factor, baseline]].dropna()
            if len(pair) >= 80:
                rho = pair[factor].corr(pair[baseline], method="spearman")
                if np.isfinite(rho) and abs(rho) >= 0.90:
                    redundant.append({"Factor": factor, "Baseline": baseline, "Rows": len(pair),
                                      "AbsSpearman": float(abs(rho))})
    for factor in FACTORS:
        for horizon in HORIZONS:
            outcome = f"future_hfq_{horizon}"
            pair = joined[[factor, outcome]].dropna()
            rho = pair[factor].corr(pair[outcome], method="spearman") if len(pair) >= 20 else np.nan
            q25, q75 = pair[factor].quantile([0.25, 0.75]) if len(pair) else (np.nan, np.nan)
            high = pair.loc[pair[factor].ge(q75), outcome]
            low = pair.loc[pair[factor].le(q25), outcome]
            binary_high = pair.loc[pair[factor].eq(1), outcome]
            binary_low = pair.loc[pair[factor].eq(-1), outcome]
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
                folds.append({
                    "Factor": factor, "Horizon": horizon, "TestStart": test_start,
                    "Status": "EVALUATED", "TrainRows": len(train), "TestRows": len(test),
                    "TrainLabelEnd": str(sessions[final_train_position + horizon].date()),
                    "BaseMse": float(base_sq.mean()), "ExtraMse": float(extra_sq.mean()),
                    "ExtraCoefficient": float(weights[-1]),
                })
            scores.append({
                "Factor": factor, "Horizon": horizon, "PairedRows": len(pair),
                "Spearman": float(rho) if np.isfinite(rho) else np.nan,
                "HighRows": len(high), "LowRows": len(low),
                "HighMinusLow": float(high.mean() - low.mean()) if len(high) and len(low) else np.nan,
                "PlusMinus": float(binary_high.mean() - binary_low.mean())
                if factor == "extreme_order" and len(binary_high) and len(binary_low) else np.nan,
                "EvaluatedFolds": sum(row["Status"] == "EVALUATED" for row in folds
                                      if row["Factor"] == factor and row["Horizon"] == horizon),
                "PositiveFolds": positive_folds,
                "MseReduction": float(1 - np.mean(extra_errors) / np.mean(baseline_errors))
                if baseline_errors else np.nan,
            })
    return (pd.DataFrame(coverage), pd.DataFrame(scores), pd.DataFrame(folds),
            pd.DataFrame(redundant, columns=["Factor", "Baseline", "Rows", "AbsSpearman"]))


def _precheck() -> None:
    day = pd.Timestamp("2025-03-03")
    closes = np.array([1.0, 0.99, 1.01, 1.005, 1.01, 1.00, 1.02, 1.03])
    opens = np.r_[1.0, closes[:-1]]
    highs = np.maximum(opens, closes) + 0.001
    lows = np.minimum(opens, closes) - 0.001
    highs[7] = 1.10
    lows[1] = 0.90
    bars = pd.DataFrame({
        "Date": [day + pd.Timedelta(time + ":00") for time in TIMES],
        "Open": opens, "High": highs, "Low": lows, "Close": closes,
    })
    expected = _intraday_features(bars, pd.DatetimeIndex([day]))
    if expected["extreme_order"].iloc[0] != 1 or not 0 <= expected["intraday_churn"].iloc[0] <= 1:
        raise ValueError("synthetic path order or churn differs")
    scaled = bars.copy()
    scaled[["Open", "High", "Low", "Close"]] *= 7
    observed = _intraday_features(scaled, pd.DatetimeIndex([day]))
    if not np.allclose(expected.to_numpy(), observed.to_numpy(), equal_nan=True):
        raise ValueError("same-day adjustment did not cancel")
    reversed_bars = bars.copy()
    reversed_bars.loc[1, "Low"] = 0.989
    reversed_bars.loc[7, "High"] = 1.031
    reversed_bars.loc[0, "High"] = 1.20
    reversed_bars.loc[7, "Low"] = 0.80
    if _intraday_features(reversed_bars, pd.DatetimeIndex([day]))["extreme_order"].iloc[0] != -1:
        raise ValueError("reverse synthetic path order differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            research_question="Do overnight/session divergence, high-turnover flat trading, or intraday extreme order add next-session ETF information?",
            hypothesis="Two pairs of opposite predictions share their input; low-before-high predicts stronger later returns.",
            falsification_conditions=(
                "A paired observation has no stable direction or no increment beyond common controls",
                "Extreme order has insufficient unambiguous days or unstable direction",
                "Price, availability, source coverage, or causal time contract fails",
            ),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("ETF demand can show persistent repricing or transient turnover in completed trading paths",),
                information_paths=("T completed ETF daily and 30-minute bars plus theme close -> T+1 or later decisions",),
                stage_objectives=("Census five competing explanations via three frozen observations",),
                observation_metrics=("Coverage, ties, redundancy, rank and group association",
                                     "Chronologically purged MSE increment and direction"),
                methodology=("Three fixed factors, three future horizons, and three chronological folds",
                             "Training-only ridge standardization with penalty 10"),
                predecessor_experiment_ids=(),
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
                "metadata": dict(result.identity.metadata), "rows": len(result.dataframe),
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
            artifacts.append(context.workspace.register_artifact(filename, f"S011-EX04-{filename.split('.')[0]}"))
        summary = {
            "decision": "SURVEY_COMPLETE", "sessions": len(matrix),
            "mechanism_count": 5, "factor_count": len(FACTORS), "comparison_count": len(scores),
            "evaluated_folds": int(folds["Status"].eq("EVALUATED").sum()),
            "insufficient_folds": int(folds["Status"].eq("INSUFFICIENT").sum()),
            "ambiguous_extreme_days": int(matrix["extreme_order"].isna().sum()),
            "redundant_pairs": len(redundant), "source_identities": identities,
            "old_s010_overlap_is_development_pool": True,
            "pcf_or_intraday_vintages_used": False, "account_replay_performed": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
            encoding="utf-8",
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "S011-EX04-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "SURVEY_COMPLETE", "mechanism_count": 5,
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "account_replay_performed": False},
            diagnostics={"evaluated_folds": summary["evaluated_folds"],
                         "ambiguous_extreme_days": summary["ambiguous_extreme_days"]},
            artifacts=tuple(artifacts),
        )
