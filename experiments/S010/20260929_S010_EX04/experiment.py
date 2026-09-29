"""S010 EX04: causal theme-index close survey."""

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


EXPERIMENT_ID = "20260929_S010_EX04"
START, CUTOFF = "2024-09-09", "2026-09-28"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
}
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
HORIZONS = (1, 5, 10)
BASE_0 = ("etf_return_5", "etf_volatility_20")
BASE_1 = (*BASE_0, "tsfresh_range__median")


def _features(index_close: pd.Series, etf_close: pd.Series) -> pd.DataFrame:
    if not index_close.index.equals(etf_close.index) or index_close.index.duplicated().any():
        raise ValueError("theme index and ETF calendars differ")
    if not np.isfinite(index_close).all() or not np.isfinite(etf_close).all():
        raise ValueError("theme index or ETF has nonfinite price")
    if (index_close <= 0).any() or (etf_close <= 0).any():
        raise ValueError("theme index or ETF has nonpositive price")
    result = pd.DataFrame(index=index_close.index)
    for window in (1, 3, 5, 10, 20):
        result[f"theme_return_{window}"] = index_close.pct_change(window, fill_method=None)
    for window in (1, 5, 20):
        result[f"etf_minus_theme_{window}"] = (
            etf_close.pct_change(window, fill_method=None)
            - result[f"theme_return_{window}"]
        )
    return result


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights


def _folds(index: pd.DatetimeIndex, horizon: int):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 1 + horizon < test[0])
        yield start, train, test


def _scores(features: pd.DataFrame, inherited: pd.DataFrame, labels: pd.DataFrame):
    joined = inherited[[*BASE_1]].join(features).join(labels).replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor in features.columns:
        for horizon in HORIZONS:
            label = f"open_return_{horizon}"
            for baseline_name, baseline in (("PRICE", BASE_0), ("PRICE_RANGE", BASE_1)):
                base_errors, extra_errors = [], []
                positive = 0
                for start, train_positions, test_positions in _folds(dates, horizon):
                    columns = [*baseline, factor, label]
                    train = joined.iloc[train_positions][columns].dropna()
                    test = joined.iloc[test_positions][columns].dropna()
                    if len(train) < 80 or len(test) < 15:
                        details.append({"factor": factor, "horizon": horizon, "baseline": baseline_name,
                                        "test_start": start, "status": "INSUFFICIENT",
                                        "train_rows": len(train), "test_rows": len(test)})
                        continue
                    last = dates.get_loc(train.index[-1]) + 1 + horizon
                    if last >= len(dates) or dates[last] >= test.index[0]:
                        raise ValueError("training label crosses chronological test boundary")
                    y_train = train[label].to_numpy(dtype=float)
                    y_test = test[label].to_numpy(dtype=float)
                    base = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                                  test[list(baseline)].to_numpy(dtype=float))
                    extra = _ridge(train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                                   test[[*baseline, factor]].to_numpy(dtype=float))
                    b, e = np.square(y_test - base), np.square(y_test - extra)
                    base_errors.extend(b)
                    extra_errors.extend(e)
                    positive += int(e.mean() < b.mean())
                    details.append({"factor": factor, "horizon": horizon, "baseline": baseline_name,
                                    "test_start": start, "status": "EVALUATED",
                                    "train_rows": len(train), "test_rows": len(test),
                                    "train_label_end": dates[last].date().isoformat(),
                                    "base_mse": float(b.mean()), "extra_mse": float(e.mean())})
                totals.append({"factor": factor, "horizon": horizon, "baseline": baseline_name,
                               "oos_rows": len(base_errors), "positive_folds": positive,
                               "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                               if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    index_close = pd.Series(100.0 + np.arange(len(days)), index=days)
    etf_close = index_close * 0.001
    features = _features(index_close, etf_close)
    if len(features.columns) != 8 or features.iloc[20:].isna().any().any():
        raise ValueError("synthetic feature boundary failed")
    first = next(_folds(days, 5))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
        raise ValueError("synthetic purge boundary failed")
    pred = _ridge(np.arange(100, dtype=float).reshape(50, 2),
                  np.linspace(-1, 1, 50), np.ones((5, 2)))
    if not np.isfinite(pred).all():
        raise ValueError("synthetic model boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does causal theme-index close information add to ETF price and range for subsequent open returns?",
            hypothesis="Tracking-index returns or relative moves may identify theme-specific information beyond ETF price.",
            falsification_conditions=("Index close fails causal data contract", "Index and ETF calendars differ",
                                    "No stable incremental information beyond ETF price and range"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092904,
            allowed_datasets=(Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value, Dataset.ETF_OHLCV.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("An ETF and its tracking index share exposure but can differ in price discovery",),
                information_paths=("T theme-index close and ETF close -> later executable-session prices",),
                stage_objectives=("Audit index close identity and calendar", "Quantify theme factor coverage and redundancy",
                                  "Measure purged chronological increment"),
                observation_metrics=("coverage", "ETF-index return correlation", "per-fold and combined MSE"),
                methodology=("Eight fixed close-derived factors", "Three purged test segments", "Two fixed ridge baselines"),
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
        prior = root.parent / "20260929_S010_EX01" / "artifacts"
        inherited = pd.read_csv(prior / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(prior / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        if not inherited.index.equals(labels.index) or inherited.index.duplicated().any():
            raise ValueError("predecessor dates differ")
        inputs, lineage = {}, {}
        for name, dataset, symbol in (
            ("theme", Dataset.DOMESTIC_INDEX_CLOSE_DAILY, "931994.CSI"),
            ("etf", Dataset.ETF_OHLCV, "159326.SZ"),
        ):
            result = context.data.fetch(DataRequest(
                dataset, symbol, START, CUTOFF, CUTOFF, "daily",
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
                raise ValueError(f"{name} duplicate date")
            inputs[name] = frame
            lineage[name] = {"dataset": result.identity.dataset, "source": result.identity.source,
                             "rows": len(frame), "start": result.identity.data_start,
                             "cutoff": result.identity.data_cutoff,
                             "sha256": result.identity.content_sha256,
                             "available_at": result.identity.temporal_contract.available_at}
        features = _features(inputs["theme"]["Close"], inputs["etf"]["Close"])
        if not features.index.equals(inherited.index):
            raise ValueError("theme, ETF, and predecessor calendars differ")
        scores, folds = _scores(features, inherited, labels)
        quality = pd.DataFrame({"factor": features.columns,
                                "finite_rows": features.notna().sum().to_numpy(),
                                "missing_rows": features.isna().sum().to_numpy(),
                                "unique_values": features.nunique().to_numpy()})
        corr = float(features["theme_return_1"].corr(
            inputs["etf"]["Close"].pct_change(fill_method=None)))
        relation = pd.DataFrame([{"measure": "etf_theme_daily_return_pearson", "value": corr}])
        outputs = (("theme_features.csv.gz", features.reset_index()),
                   ("theme_quality.csv", quality), ("theme_scores.csv", scores),
                   ("theme_fold_scores.csv", folds), ("theme_relation.csv", relation))
        artifacts = []
        for name, frame in outputs:
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX04-{name.split('.')[0]}"))
        summary = {"decision": "THEME_INDEX_REVIEW_COMPLETE", "input_identity": lineage,
                   "factor_count": features.shape[1], "comparison_count": len(scores),
                   "etf_theme_daily_return_pearson": corr,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX04-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "factor_count": features.shape[1],
                   "sealed_date_rows_read": 0},
            diagnostics={"etf_theme_daily_return_pearson": corr},
            artifacts=tuple(artifacts),
        )
