"""S010 EX07: cross-source confirmation and adverse-path factor survey."""

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


EXPERIMENT_ID = "20260929_S010_EX07"
START, CUTOFF, WARMUP = "2024-09-09", "2026-09-28", "2024-08-01"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
}
BASELINE = ("etf_return_1", "etf_return_5", "etf_volatility_20",
            "tsfresh_range__median", "etf_drawdown_10", "intra_afternoon_return")
FACTOR_NAMES = (
    "shibor_change_1", "shibor_change_5", "shibor_z20",
    "chinext_turnover_z5", "chinext_turnover_z20", "chinext_turnover_change_5",
    "spx_prior_return_1", "spx_prior_return_5", "spx_prior_volatility_20",
    "known_share_change_1", "known_share_change_5",
    "etf_volume_z_5", "etf_amount_z_20", "etf_amihud",
)
OUTCOMES = (("open_return_1", 1), ("open_return_5", 5), ("adverse_5", 5))
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")


def _zscore(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window).mean()
    std = values.rolling(window).std(ddof=0)
    return (values - mean) / std.replace(0, np.nan)


def _strict_prior(us_values: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    us_values = us_values.sort_index()
    if us_values.index.duplicated().any():
        raise ValueError("duplicate US source date")
    source_dates = pd.DatetimeIndex(us_values.index)
    positions = source_dates.searchsorted(sessions, side="left") - 1
    output = np.full(len(sessions), np.nan)
    valid = positions >= 0
    if valid.any():
        lag = (sessions[valid] - source_dates[positions[valid]]).days
        usable = lag <= 7
        target = np.flatnonzero(valid)[usable]
        output[target] = us_values.to_numpy(dtype=float)[positions[target]]
    return pd.Series(output, index=sessions)


def _features(sessions: pd.DatetimeIndex, inherited: pd.DataFrame,
              shibor: pd.DataFrame, chinext: pd.DataFrame, spx: pd.DataFrame) -> pd.DataFrame:
    for name, frame in (("shibor", shibor), ("chinext", chinext), ("spx", spx)):
        if frame.index.duplicated().any() or not frame.index.is_monotonic_increasing:
            raise ValueError(f"{name} source dates invalid")
    rate = shibor["OvernightRate"].astype(float)
    turnover = chinext["TurnoverRateFreeFloat"].astype(float)
    us_return = spx["PercentChange"].astype(float)
    result = pd.DataFrame(index=sessions)
    domestic = {
        "shibor_change_1": rate.diff(),
        "shibor_change_5": rate.diff(5),
        "shibor_z20": _zscore(rate, 20),
        "chinext_turnover_z5": _zscore(turnover, 5),
        "chinext_turnover_z20": _zscore(turnover, 20),
        "chinext_turnover_change_5": turnover.diff(5),
    }
    for name, series in domestic.items():
        result[name] = series.reindex(sessions)
    us_sources = {
        "spx_prior_return_1": us_return,
        "spx_prior_return_5": (1 + us_return).rolling(5).apply(np.prod, raw=True) - 1,
        "spx_prior_volatility_20": us_return.rolling(20).std(ddof=0),
    }
    for name, series in us_sources.items():
        result[name] = _strict_prior(series, sessions)
    for name in FACTOR_NAMES[9:]:
        result[name] = inherited[name]
    if tuple(result.columns) != FACTOR_NAMES:
        raise ValueError("factor inventory differs from frozen contract")
    return result.replace([np.inf, -np.inf], np.nan)


def _adverse_labels(daily: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    if not daily.index.equals(sessions):
        raise ValueError("ETF daily dates differ from predecessor calendar")
    opens = daily["Open"].to_numpy(dtype=float)
    lows = daily["Low"].to_numpy(dtype=float)
    if not np.isfinite(opens).all() or not np.isfinite(lows).all():
        raise ValueError("ETF execution prices contain nonfinite value")
    if (opens <= 0).any() or (lows <= 0).any() or (lows > opens).any():
        raise ValueError("ETF execution low or open is invalid")
    outcome = np.full(len(sessions), np.nan)
    for index in range(len(sessions) - 5):
        outcome[index] = lows[index + 1:index + 6].min() / opens[index + 1] - 1
    return pd.Series(outcome, index=sessions, name="adverse_5")


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray):
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights, weights


def _folds(index: pd.DatetimeIndex, horizon: int):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 1 + horizon < test[0])
        yield start, train, test


def _evaluate(inherited: pd.DataFrame, intraday: pd.DataFrame,
              features: pd.DataFrame, labels: pd.DataFrame):
    if not inherited.index.equals(intraday.index) or not inherited.index.equals(features.index):
        raise ValueError("feature calendars differ")
    if not inherited.index.equals(labels.index) or inherited.index.duplicated().any():
        raise ValueError("label calendar differs")
    joined = inherited[list(BASELINE[:-1])].join(intraday[[BASELINE[-1]]]).join(features).join(labels)
    joined = joined.replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor in FACTOR_NAMES:
        for outcome, horizon in OUTCOMES:
            base_errors, extra_errors, positive = [], [], 0
            for start, train_positions, test_positions in _folds(dates, horizon):
                columns = [*BASELINE, factor, outcome]
                train = joined.iloc[train_positions][columns].dropna()
                test = joined.iloc[test_positions][columns].dropna()
                if len(train) < 80 or len(test) < 15:
                    details.append({"factor": factor, "outcome": outcome, "test_start": start,
                                    "status": "INSUFFICIENT", "train_rows": len(train),
                                    "test_rows": len(test)})
                    continue
                last = dates.get_loc(train.index[-1]) + 1 + horizon
                if last >= len(dates) or dates[last] >= test.index[0]:
                    raise ValueError("training label crosses chronological test boundary")
                y_train = train[outcome].to_numpy(dtype=float)
                y_test = test[outcome].to_numpy(dtype=float)
                base, _ = _ridge(train[list(BASELINE)].to_numpy(dtype=float), y_train,
                                 test[list(BASELINE)].to_numpy(dtype=float))
                extra, weights = _ridge(train[[*BASELINE, factor]].to_numpy(dtype=float), y_train,
                                        test[[*BASELINE, factor]].to_numpy(dtype=float))
                b, e = np.square(y_test - base), np.square(y_test - extra)
                base_errors.extend(b)
                extra_errors.extend(e)
                positive += int(e.mean() < b.mean())
                details.append({"factor": factor, "outcome": outcome, "test_start": start,
                                "status": "EVALUATED", "train_rows": len(train),
                                "test_rows": len(test),
                                "train_label_end": dates[last].date().isoformat(),
                                "base_mse": float(b.mean()), "extra_mse": float(e.mean()),
                                "extra_standardized_coefficient": float(weights[-1])})
            totals.append({"factor": factor, "outcome": outcome, "oos_rows": len(base_errors),
                           "positive_folds": positive,
                           "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                           if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    us = pd.Series(np.arange(800, dtype=float), index=days)
    shifted = _strict_prior(us, days)
    if not np.isnan(shifted.iloc[0]) or shifted.iloc[1] != 0:
        raise ValueError("synthetic US close ordering failed")
    daily = pd.DataFrame({"Open": np.full(800, 1.0),
                          "Low": np.full(800, 0.9)}, index=days)
    adverse = _adverse_labels(daily, days)
    if not np.isclose(adverse.iloc[0], -0.1) or not np.isnan(adverse.iloc[-1]):
        raise ValueError("synthetic adverse label boundary failed")
    first = next(_folds(days, 5))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
        raise ValueError("synthetic purge boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Do cross-source liquidity and risk-appetite features add confirmation or adverse-path information?",
            hypothesis="Funding conditions, turnover and overnight global sentiment may change ETF opportunity or downside risk beyond ETF price and range.",
            falsification_conditions=("Causal source dates or coverage fail", "No stable incremental information",
                                    "Apparent risk relation duplicates existing ETF information"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092907,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.SHIBOR_DAILY.value,
                              Dataset.INDEX_DAILY_BASIC.value, Dataset.GLOBAL_INDEX_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Funding, turnover and overnight sentiment can alter liquidity and risk appetite",),
                information_paths=("Causally available cross-source observations -> later ETF open prices and adverse path",),
                stage_objectives=("Audit source timing and coverage", "Survey fixed confirmation and risk families"),
                observation_metrics=("coverage", "per-fold and pooled MSE", "training coefficient direction"),
                methodology=("Fourteen fixed factors", "Three outcomes", "Purged three-segment ridge comparisons"),
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
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        if not inherited.index.equals(labels.index):
            raise ValueError("predecessor factor and label calendars differ")
        inputs, lineage = {}, {}
        for name, dataset, symbol, start in (
            ("etf", Dataset.ETF_OHLCV, "159326.SZ", START),
            ("shibor", Dataset.SHIBOR_DAILY, None, WARMUP),
            ("chinext", Dataset.INDEX_DAILY_BASIC, "399006.SZ", WARMUP),
            ("spx", Dataset.GLOBAL_INDEX_DAILY, "SPX", WARMUP),
        ):
            result = context.data.fetch(DataRequest(
                dataset, symbol, start, CUTOFF, CUTOFF, "daily",
                {"env_file": str(root.parents[2] / ".env")},
            ))
            if not result.ready or result.identity is None:
                error = result.error
                raise ValueError(f"{name} DFLS unavailable: {result.status.value}"
                                 + ("" if error is None else f" {error.code}: {error.message}"))
            frame = result.dataframe.copy()
            frame["Date"] = pd.to_datetime(frame["Date"], errors="raise")
            frame = frame.set_index("Date").sort_index()
            inputs[name] = frame
            lineage[name] = {"dataset": result.identity.dataset, "source": result.identity.source,
                             "rows": len(frame), "start": result.identity.data_start,
                             "cutoff": result.identity.data_cutoff,
                             "sha256": result.identity.content_sha256,
                             "available_at": result.identity.temporal_contract.available_at}
        sessions = pd.DatetimeIndex(inherited.index)
        features = _features(sessions, inherited, inputs["shibor"], inputs["chinext"], inputs["spx"])
        adverse = _adverse_labels(inputs["etf"], sessions)
        labels = labels[["open_return_1", "open_return_5"]].join(adverse)
        scores, folds = _evaluate(inherited, intraday, features, labels)
        quality = pd.DataFrame({"factor": features.columns,
                                "finite_rows": features.notna().sum().to_numpy(),
                                "missing_rows": features.isna().sum().to_numpy(),
                                "unique_values": features.nunique().to_numpy()})
        corr = features.corr(min_periods=150)
        near = [{"factor_a": a, "factor_b": b, "pearson": float(corr.loc[a, b])}
                for i, a in enumerate(features.columns) for b in features.columns[i + 1:]
                if np.isfinite(corr.loc[a, b]) and abs(corr.loc[a, b]) >= 0.995]
        artifacts = []
        for name, frame in (("cross_source_features.csv.gz", features.reset_index()),
                            ("factor_quality.csv", quality), ("factor_scores.csv", scores),
                            ("fold_scores.csv", folds),
                            ("near_duplicates.csv", pd.DataFrame(near, columns=["factor_a", "factor_b", "pearson"]))):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX07-{name.split('.')[0]}"))
        summary = {"decision": "CROSS_SOURCE_SURVEY_COMPLETE", "input_identity": lineage,
                   "factor_count": len(FACTOR_NAMES), "comparison_count": len(scores),
                   "near_duplicate_pairs": len(near),
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX07-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "factor_count": len(FACTOR_NAMES),
                   "sealed_date_rows_read": 0},
            diagnostics={"comparison_count": len(scores), "near_duplicate_pairs": len(near)},
            artifacts=tuple(artifacts),
        )
