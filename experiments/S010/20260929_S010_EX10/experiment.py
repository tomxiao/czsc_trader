"""S010 EX10: VIX and ETF exit-risk feature survey."""

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


EXPERIMENT_ID = "20260929_S010_EX10"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
    "20260929_S010_EX07": "f39fc5db88c7ed9c7996a96fd4d7fee4ec1c73e275c6e553aee343f0e30cb8ba",
    "20260929_S010_EX08": "d48bba43ce2e25e1fd6c3f4a7613f57776331ff79190546986e9ffe4658bf6c9",
    "20260929_S010_EX09": "6c9dc8791d54a205f0356ce587ccb349ceb983757409edd0218b0561fac682d9",
}
START, CUTOFF, WARMUP = "2024-09-09", "2026-09-28", "2024-08-01"
BASE = ("etf_return_1", "etf_return_5", "etf_volatility_20",
        "tsfresh_range__median", "intra_afternoon_return")
BASE_VIX = (*BASE, "etf_volatility_5", "csi300_volatility_20",
            "csi500_volatility_20", "spx_prior_volatility_20")
VIX_FACTORS = ("vix_prior_close", "vix_prior_return_1", "vix_prior_change_5",
               "vix_prior_z20")
DAILY_FACTORS = ("etf_gap", "etf_body", "etf_close_location", "etf_range_5",
                 "etf_range_10", "etf_drawdown_10", "etf_breakout_10",
                 "etf_amihud", "etf_volume_z_5", "etf_amount_z_20")
INTRADAY_FACTORS = ("intra_high_bar", "intra_low_bar", "intra_realized_vol",
                    "intra_close_location", "intra_afternoon_volume_share",
                    "intra_last_hour_range_share")
FACTOR_NAMES = (*VIX_FACTORS, *DAILY_FACTORS, *INTRADAY_FACTORS)
OUTCOMES = (("adverse_1", 1), ("adverse_5", 5), ("open_return_5", 5))
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")


def _zscore(series: pd.Series, window: int) -> pd.Series:
    mean = series.rolling(window).mean()
    std = series.rolling(window).std(ddof=0).replace(0, np.nan)
    return (series - mean) / std


def _prior_us(series: pd.Series, sessions: pd.DatetimeIndex) -> pd.Series:
    series = series.sort_index()
    if series.index.duplicated().any():
        raise ValueError("duplicate VIX source date")
    source_dates = pd.DatetimeIndex(series.index)
    positions = source_dates.searchsorted(sessions, side="left") - 1
    output = np.full(len(sessions), np.nan)
    valid = positions >= 0
    if valid.any():
        lag = (sessions[valid] - source_dates[positions[valid]]).days
        target = np.flatnonzero(valid)[lag <= 7]
        output[target] = series.to_numpy(dtype=float)[positions[target]]
    return pd.Series(output, index=sessions)


def _features(sessions: pd.DatetimeIndex, inherited: pd.DataFrame,
              intraday: pd.DataFrame, vix: pd.DataFrame) -> pd.DataFrame:
    close = vix["Close"].astype(float)
    results = pd.DataFrame(index=sessions)
    sources = {
        "vix_prior_close": close,
        "vix_prior_return_1": close.pct_change(fill_method=None),
        "vix_prior_change_5": close.diff(5),
        "vix_prior_z20": _zscore(close, 20),
    }
    for name, series in sources.items():
        results[name] = _prior_us(series, sessions)
    for name in DAILY_FACTORS:
        results[name] = inherited[name]
    for name in INTRADAY_FACTORS:
        results[name] = intraday[name]
    if tuple(results.columns) != FACTOR_NAMES:
        raise ValueError("factor inventory differs from frozen contract")
    return results.replace([np.inf, -np.inf], np.nan)


def _adverse_labels(daily: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.DataFrame:
    if not daily.index.equals(sessions):
        raise ValueError("ETF daily dates differ from predecessor calendar")
    opens = daily["Open"].to_numpy(dtype=float)
    lows = daily["Low"].to_numpy(dtype=float)
    if not np.isfinite(opens).all() or not np.isfinite(lows).all():
        raise ValueError("ETF execution prices contain nonfinite value")
    if (opens <= 0).any() or (lows <= 0).any() or (lows > opens).any():
        raise ValueError("ETF execution low or open is invalid")
    one = np.full(len(sessions), np.nan)
    five = np.full(len(sessions), np.nan)
    for position in range(len(sessions) - 1):
        one[position] = lows[position + 1] / opens[position + 1] - 1
    for position in range(len(sessions) - 5):
        five[position] = lows[position + 1:position + 6].min() / opens[position + 1] - 1
    return pd.DataFrame({"adverse_1": one, "adverse_5": five}, index=sessions)


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
              cross_source: pd.DataFrame, features: pd.DataFrame, labels: pd.DataFrame):
    if not inherited.index.equals(intraday.index) or not inherited.index.equals(cross_source.index):
        raise ValueError("predecessor feature calendars differ")
    if not inherited.index.equals(features.index) or not inherited.index.equals(labels.index):
        raise ValueError("new feature or label calendar differs")
    domestic = [name for name in BASE_VIX if name in inherited.columns]
    joined = inherited[domestic].join(intraday[["intra_afternoon_return"]])
    joined = joined.join(cross_source[["spx_prior_volatility_20"]]).join(features).join(labels)
    joined = joined.replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor in FACTOR_NAMES:
        baselines = (("BASE", BASE), ("BASE_GLOBAL", BASE_VIX)) if factor in VIX_FACTORS else (("BASE", BASE),)
        for outcome, horizon in OUTCOMES:
            for base_name, baseline in baselines:
                base_errors, extra_errors, positive = [], [], 0
                for start, train_positions, test_positions in _folds(dates, horizon):
                    columns = [*baseline, factor, outcome]
                    train = joined.iloc[train_positions][columns].dropna()
                    test = joined.iloc[test_positions][columns].dropna()
                    if len(train) < 80 or len(test) < 15:
                        details.append({"factor": factor, "outcome": outcome,
                                        "baseline": base_name, "test_start": start,
                                        "status": "INSUFFICIENT", "train_rows": len(train),
                                        "test_rows": len(test)})
                        continue
                    last = dates.get_loc(train.index[-1]) + 1 + horizon
                    if last >= len(dates) or dates[last] >= test.index[0]:
                        raise ValueError("training label crosses chronological test boundary")
                    y_train = train[outcome].to_numpy(dtype=float)
                    y_test = test[outcome].to_numpy(dtype=float)
                    base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                                     test[list(baseline)].to_numpy(dtype=float))
                    extra, weights = _ridge(train[[*baseline, factor]].to_numpy(dtype=float),
                                            y_train, test[[*baseline, factor]].to_numpy(dtype=float))
                    b, e = np.square(y_test - base), np.square(y_test - extra)
                    base_errors.extend(b)
                    extra_errors.extend(e)
                    positive += int(e.mean() < b.mean())
                    details.append({"factor": factor, "outcome": outcome,
                                    "baseline": base_name, "test_start": start,
                                    "status": "EVALUATED", "train_rows": len(train),
                                    "test_rows": len(test),
                                    "train_label_end": dates[last].date().isoformat(),
                                    "base_mse": float(b.mean()), "extra_mse": float(e.mean()),
                                    "extra_standardized_coefficient": float(weights[-1])})
                totals.append({"factor": factor, "outcome": outcome,
                               "baseline": base_name, "oos_rows": len(base_errors),
                               "positive_folds": positive,
                               "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                               if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    us = pd.Series(np.arange(800, dtype=float), index=days)
    shifted = _prior_us(us, days)
    if not np.isnan(shifted.iloc[0]) or shifted.iloc[1] != 0:
        raise ValueError("synthetic US ordering failed")
    daily = pd.DataFrame({"Open": np.full(800, 1.0),
                          "Low": np.full(800, 0.9)}, index=days)
    adverse = _adverse_labels(daily, days)
    if not np.isclose(adverse["adverse_1"].iloc[0], -0.1) or not np.isnan(adverse["adverse_5"].iloc[-1]):
        raise ValueError("synthetic adverse label failed")
    first = next(_folds(days, 5))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
        raise ValueError("synthetic purge failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Do VIX expectations or ETF price paths add usable downside and exit information?",
            hypothesis="Risk expectations or market microstructure may identify near-term adverse prices beyond current ETF return and range.",
            falsification_conditions=("VIX causal alignment fails", "No stable adverse-price increment",
                                    "Apparent effect duplicates global realized or ETF volatility"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092910,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.VIX_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Volatility expectations and intraday trading can precede downside risk",),
                information_paths=("Prior US VIX or T ETF price/volume path -> subsequent ETF adverse prices",),
                stage_objectives=("Audit VIX source timing", "Survey next-day and five-day adverse price", 
                                  "Compare VIX with realized global and domestic volatility"),
                observation_metrics=("coverage", "per-fold and pooled MSE", "training coefficient direction"),
                methodology=("Twenty fixed factors", "Three outcomes", "Purged chronological ridge comparisons"),
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
        seventh = root.parent / "20260929_S010_EX07" / "artifacts"
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        cross_source = pd.read_csv(seventh / "cross_source_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        if not inherited.index.equals(labels.index) or not inherited.index.equals(cross_source.index):
            raise ValueError("predecessor calendars differ")
        inputs, lineage = {}, {}
        for name, dataset, symbol, start in (
            ("etf", Dataset.ETF_OHLCV, "159326.SZ", START),
            ("vix", Dataset.VIX_DAILY, "VIX", WARMUP),
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
            if frame.index.duplicated().any():
                raise ValueError(f"{name} duplicate source date")
            inputs[name] = frame
            lineage[name] = {"dataset": result.identity.dataset, "source": result.identity.source,
                             "rows": len(frame), "start": result.identity.data_start,
                             "cutoff": result.identity.data_cutoff,
                             "sha256": result.identity.content_sha256,
                             "available_at": result.identity.temporal_contract.available_at}
        sessions = pd.DatetimeIndex(inherited.index)
        features = _features(sessions, inherited, intraday, inputs["vix"])
        adverse = _adverse_labels(inputs["etf"], sessions)
        outcomes = labels[["open_return_5"]].join(adverse)
        scores, folds = _evaluate(inherited, intraday, cross_source, features, outcomes)
        quality = pd.DataFrame({"factor": features.columns,
                                "finite_rows": features.notna().sum().to_numpy(),
                                "missing_rows": features.isna().sum().to_numpy(),
                                "unique_values": features.nunique().to_numpy()})
        corr = features.corr(min_periods=150)
        near = [{"factor_a": a, "factor_b": b, "pearson": float(corr.loc[a, b])}
                for i, a in enumerate(features.columns) for b in features.columns[i + 1:]
                if np.isfinite(corr.loc[a, b]) and abs(corr.loc[a, b]) >= 0.995]
        relation = pd.DataFrame([{"measure": "vix_close_vs_etf_vol20", 
                                  "pearson": float(features["vix_prior_close"].corr(inherited["etf_volatility_20"]))},
                                 {"measure": "vix_close_vs_spx_realized_vol20",
                                  "pearson": float(features["vix_prior_close"].corr(cross_source["spx_prior_volatility_20"]))}])
        artifacts = []
        for name, frame in (("vix_exit_features.csv.gz", features.reset_index()),
                            ("factor_quality.csv", quality), ("factor_scores.csv", scores),
                            ("fold_scores.csv", folds), ("factor_relation.csv", relation),
                            ("near_duplicates.csv", pd.DataFrame(near, columns=["factor_a", "factor_b", "pearson"]))):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX10-{name.split('.')[0]}"))
        summary = {"decision": "EXIT_RISK_SURVEY_COMPLETE", "input_identity": lineage,
                   "factor_count": len(FACTOR_NAMES), "comparison_count": len(scores),
                   "near_duplicate_pairs": len(near), "sealed_date_rows_read": 0,
                   "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX10-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "factor_count": len(FACTOR_NAMES),
                   "sealed_date_rows_read": 0},
            diagnostics={"comparison_count": len(scores)}, artifacts=tuple(artifacts),
        )
