"""S010 EX02: purge look-ahead labels from chronological factor comparisons."""

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


EXPERIMENT_ID = "20260929_S010_EX02"
PREDECESSOR = "20260929_S010_EX01"
PREDECESSOR_RECEIPT = "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77"
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
HORIZONS = (1, 5, 10)
BASELINE = ("etf_return_5", "etf_volatility_20")


def _ridge_prediction(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    train = (train_x - center) / scale
    test = (test_x - center) / scale
    intercept = train_y.mean()
    coef = np.linalg.solve(train.T @ train + 10.0 * np.eye(train.shape[1]),
                           train.T @ (train_y - intercept))
    return intercept + test @ coef


def _folds(index: pd.DatetimeIndex, horizon: int):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        # Outcome for decision position i ends at i + 1 + horizon.
        train = np.flatnonzero(np.arange(len(index)) + 1 + horizon < test[0])
        yield start, train, test


def _evaluate(features: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    joined = features.join(labels).replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    summaries = []
    detail = []
    for factor in features.columns:
        for horizon in HORIZONS:
            label = f"open_return_{horizon}"
            if factor in BASELINE:
                summaries.append({"factor": factor, "horizon": horizon, "status": "BASELINE_MEMBER",
                                  "oos_rows": 0, "incremental_mse_reduction": np.nan,
                                  "positive_folds": 0, "evaluated_folds": 0})
                continue
            base_error = []
            extra_error = []
            positive_folds = 0
            evaluated = 0
            for start, train_positions, test_positions in _folds(dates, horizon):
                train = joined.iloc[train_positions][[*BASELINE, factor, label]].dropna()
                test = joined.iloc[test_positions][[*BASELINE, factor, label]].dropna()
                if len(train) < 80 or len(test) < 15:
                    detail.append({"factor": factor, "horizon": horizon, "test_start": start,
                                   "status": "INSUFFICIENT", "train_rows": len(train),
                                   "test_rows": len(test), "train_label_end": "",
                                   "base_mse": np.nan, "extra_mse": np.nan})
                    continue
                last_train_position = dates.get_loc(train.index[-1])
                label_end = dates[last_train_position + 1 + horizon]
                if label_end >= test.index[0]:
                    raise ValueError("training label crosses the test boundary")
                y_train = train[label].to_numpy(dtype=float)
                y_test = test[label].to_numpy(dtype=float)
                base = _ridge_prediction(train[list(BASELINE)].to_numpy(dtype=float),
                                         y_train, test[list(BASELINE)].to_numpy(dtype=float))
                columns = [*BASELINE, factor]
                extra = _ridge_prediction(train[columns].to_numpy(dtype=float),
                                          y_train, test[columns].to_numpy(dtype=float))
                base_squared = (y_test - base) ** 2
                extra_squared = (y_test - extra) ** 2
                base_mse = float(base_squared.mean())
                extra_mse = float(extra_squared.mean())
                base_error.extend(base_squared)
                extra_error.extend(extra_squared)
                positive_folds += extra_mse < base_mse
                evaluated += 1
                detail.append({"factor": factor, "horizon": horizon, "test_start": start,
                               "status": "EVALUATED", "train_rows": len(train),
                               "test_rows": len(test), "train_label_end": label_end.date().isoformat(),
                               "base_mse": base_mse, "extra_mse": extra_mse})
            reduction = float(1 - np.mean(extra_error) / np.mean(base_error)) if base_error else np.nan
            summaries.append({"factor": factor, "horizon": horizon,
                              "status": "EVALUATED" if evaluated else "INSUFFICIENT",
                              "oos_rows": len(base_error), "incremental_mse_reduction": reduction,
                              "positive_folds": positive_folds, "evaluated_folds": evaluated})
    return pd.DataFrame(summaries), pd.DataFrame(detail)


def _redundancy(features: pd.DataFrame) -> pd.DataFrame:
    values = features.replace([np.inf, -np.inf], np.nan)
    pair_counts = values.notna().astype(int).T @ values.notna().astype(int)
    correlations = values.corr(min_periods=150)
    names = list(values.columns)
    rows = []
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            corr = correlations.loc[first, second]
            if np.isfinite(corr) and abs(corr) >= 0.995:
                rows.append({"factor_a": first, "factor_b": second,
                             "paired_rows": int(pair_counts.loc[first, second]),
                             "pearson": float(corr)})
    return pd.DataFrame(rows, columns=["factor_a", "factor_b", "paired_rows", "pearson"])


def _precheck() -> None:
    dates = pd.bdate_range("2024-01-01", periods=650)
    first = next(_folds(dates, 10))
    _, train, test = first
    if len(train) < 80 or dates[train[-1] + 11] >= dates[test[0]]:
        raise ValueError("synthetic purge boundary failed")
    baseline = np.arange(100, dtype=float).reshape(50, 2)
    prediction = _ridge_prediction(baseline, np.linspace(-1, 1, 50), baseline[:5])
    if not np.isfinite(prediction).all():
        raise ValueError("synthetic ridge predictor failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does single-factor incremental information survive strict training-label purging at chronological test boundaries?",
            hypothesis="Some factor families may retain a positive chronological incremental direction once label overlap is removed.",
            falsification_conditions=("Purged comparisons lose apparent increment", "No stable cross-segment direction", "Predecessor identity or matrix differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092902,
            allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Training labels must be fully observable before the first test decision",),
                information_paths=("EX01 causal feature matrix -> purged forward-open label comparison",),
                stage_objectives=("Correct chronological increment", "Inventory highly redundant factors"),
                observation_metrics=("fold MSE", "combined MSE reduction", "paired correlation"),
                methodology=("Purge T labels ending at or after first test decision", "Fixed ridge penalty 10 and three chronological segments", "Absolute Pearson >=0.995 redundancy audit"),
                predecessor_experiment_ids=(PREDECESSOR,),
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
        if context.predecessors[PREDECESSOR].receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("predecessor receipt differs")
        root = Path(__file__).resolve().parent
        prior = root.parent / PREDECESSOR
        validate_experiment_archive(prior)
        factor_matrix = pd.read_csv(prior / "artifacts" / "factor_matrix.csv.gz", parse_dates=["Date"])
        labels = pd.read_csv(prior / "artifacts" / "future_open_labels.csv.gz", parse_dates=["Date"])
        if factor_matrix["Date"].duplicated().any() or labels["Date"].duplicated().any():
            raise ValueError("duplicate predecessor dates")
        factors = factor_matrix.set_index("Date").sort_index()
        outcomes = labels.set_index("Date").sort_index()
        if not factors.index.equals(outcomes.index) or len(factors) != 497:
            raise ValueError("predecessor dates or coverage differ")
        scores, folds = _evaluate(factors, outcomes)
        redundancy = _redundancy(factors)
        artifacts = []
        for name, frame in (("purged_scores.csv", scores), ("purged_fold_scores.csv", folds),
                            ("near_duplicates.csv", redundancy)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX02-{name.split('.')[0]}"))
        summary = {"decision": "PURGED_SURVEY_COMPLETE", "predecessor_receipt": PREDECESSOR_RECEIPT,
                   "factor_count": factors.shape[1], "comparisons": len(scores),
                   "evaluated_comparisons": int(scores["status"].eq("EVALUATED").sum()),
                   "near_duplicate_pairs": len(redundancy), "sealed_date_rows_read": 0,
                   "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX02-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "PURGED_SURVEY_COMPLETE", "evaluated_comparisons": summary["evaluated_comparisons"],
                   "near_duplicate_pairs": len(redundancy), "sealed_date_rows_read": 0},
            diagnostics={"factor_count": factors.shape[1]}, artifacts=tuple(artifacts),
        )
