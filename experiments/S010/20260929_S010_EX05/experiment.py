"""S010 EX05: conditional audit of selected intraday information."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
from czsc_trader.experiment_archive import validate_experiment_archive
from dataflows import Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S010_EX05"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
}
FACTORS = ("intra_afternoon_return", "intra_high_bar", "intra_close_location")
HORIZONS = (1, 5, 10)
BASE_0 = ("etf_return_1", "etf_return_5", "etf_volatility_20")
BASE_1 = (*BASE_0, "tsfresh_range__median")
BASE_2 = (*BASE_1, "etf_body", "etf_close_location")
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")


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


def _evaluate(inherited: pd.DataFrame, intraday: pd.DataFrame, labels: pd.DataFrame):
    if not inherited.index.equals(labels.index) or not inherited.index.equals(intraday.index):
        raise ValueError("predecessor calendars differ")
    if inherited.index.duplicated().any():
        raise ValueError("duplicate predecessor date")
    joined = inherited[[*BASE_2]].join(intraday[list(FACTORS)]).join(labels)
    joined = joined.replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor in FACTORS:
        for horizon in HORIZONS:
            label = f"open_return_{horizon}"
            for base_name, baseline in (("DAY", BASE_0), ("DAY_RANGE", BASE_1),
                                        ("DAY_CANDLE", BASE_2)):
                base_errors, extra_errors, positive = [], [], 0
                for start, train_positions, test_positions in _folds(dates, horizon):
                    columns = [*baseline, factor, label]
                    train = joined.iloc[train_positions][columns].dropna()
                    test = joined.iloc[test_positions][columns].dropna()
                    if len(train) < 80 or len(test) < 15:
                        details.append({"factor": factor, "horizon": horizon,
                                        "baseline": base_name, "test_start": start,
                                        "status": "INSUFFICIENT", "train_rows": len(train),
                                        "test_rows": len(test)})
                        continue
                    last = dates.get_loc(train.index[-1]) + 1 + horizon
                    if last >= len(dates) or dates[last] >= test.index[0]:
                        raise ValueError("training label crosses chronological test boundary")
                    y_train = train[label].to_numpy(dtype=float)
                    y_test = test[label].to_numpy(dtype=float)
                    base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                                     test[list(baseline)].to_numpy(dtype=float))
                    extra, coefficients = _ridge(
                        train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                        test[[*baseline, factor]].to_numpy(dtype=float))
                    b, e = np.square(y_test - base), np.square(y_test - extra)
                    base_errors.extend(b)
                    extra_errors.extend(e)
                    positive += int(e.mean() < b.mean())
                    details.append({"factor": factor, "horizon": horizon,
                                    "baseline": base_name, "test_start": start,
                                    "status": "EVALUATED", "train_rows": len(train),
                                    "test_rows": len(test),
                                    "train_label_end": dates[last].date().isoformat(),
                                    "base_mse": float(b.mean()), "extra_mse": float(e.mean()),
                                    "extra_standardized_coefficient": float(coefficients[-1])})
                totals.append({"factor": factor, "horizon": horizon, "baseline": base_name,
                               "oos_rows": len(base_errors), "positive_folds": positive,
                               "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                               if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    first = next(_folds(days, 10))
    if days[first[1][-1] + 11] >= days[first[2][0]]:
        raise ValueError("synthetic purge boundary failed")
    predictions, weights = _ridge(np.arange(100, dtype=float).reshape(50, 2),
                                  np.linspace(-1, 1, 50), np.ones((5, 2)))
    if not np.isfinite(predictions).all() or not np.isfinite(weights).all():
        raise ValueError("synthetic model boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Do selected intraday signals add information after controlling same-day ETF return and candle?",
            hypothesis="Afternoon pressure or within-day high timing may contain price-discovery information beyond daily return and candle.",
            falsification_conditions=("Increment disappears under daily controls",
                                    "Direction changes across chronological training segments",
                                    "Predecessor calendar or receipt differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092905, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Intraday pressure can carry information but may duplicate the daily candle",),
                information_paths=("T intraday distribution -> T+1 or later executable-session prices",),
                stage_objectives=("Separate intraday content from same-day daily return and candle",),
                observation_metrics=("per-fold and pooled MSE", "training coefficient direction"),
                methodology=("Three selected prior factors", "Three purged segments",
                             "Daily-return, range and candle controls"),
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
        totals, details = _evaluate(inherited, intraday, labels)
        artifacts = []
        for name, frame in (("conditional_scores.csv", totals),
                            ("conditional_fold_scores.csv", details)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX05-{name.split('.')[0]}"))
        summary = {"decision": "CONDITIONAL_INTRADAY_REVIEW_COMPLETE",
                   "factor_count": len(FACTORS), "comparison_count": len(totals),
                   "predecessor_receipts": RECEIPTS,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX05-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(totals),
                   "sealed_date_rows_read": 0},
            diagnostics={"factor_count": len(FACTORS)}, artifacts=tuple(artifacts),
        )
