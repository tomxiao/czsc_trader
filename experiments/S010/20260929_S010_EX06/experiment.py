"""S010 EX06: responsibility and redundancy audit of selected daily clues."""

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


EXPERIMENT_ID = "20260929_S010_EX06"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
}
PRICE = ("etf_return_5", "etf_volatility_20")
DAY = ("etf_return_1", *PRICE)
RANGE_10 = "etf_range_10"
RANGE_MEDIAN = "tsfresh_range__median"
AFTERNOON = "intra_afternoon_return"
CSI_300 = "csi300_return_1"
COMPARISONS = (
    ("etf_return_1", 1, "PRICE", PRICE),
    ("etf_return_1", 1, "PRICE_AFTERNOON", (*PRICE, AFTERNOON)),
    (RANGE_10, 5, "DAY", DAY),
    (RANGE_10, 5, "DAY_MEDIAN", (*DAY, RANGE_MEDIAN)),
    (RANGE_MEDIAN, 5, "DAY", DAY),
    (RANGE_MEDIAN, 5, "DAY_RANGE10", (*DAY, RANGE_10)),
    (CSI_300, 5, "DAY_MEDIAN", (*DAY, RANGE_MEDIAN)),
    (CSI_300, 5, "DAY_RANGE10", (*DAY, RANGE_10)),
)
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
SEED = 2026092906


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


def _evaluate(factors: pd.DataFrame, intraday: pd.DataFrame, labels: pd.DataFrame):
    if not factors.index.equals(labels.index) or not factors.index.equals(intraday.index):
        raise ValueError("predecessor calendars differ")
    if factors.index.duplicated().any():
        raise ValueError("duplicate predecessor date")
    joined = factors[[*DAY, RANGE_10, RANGE_MEDIAN, CSI_300]].join(intraday[[AFTERNOON]]).join(labels)
    joined = joined.replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor, horizon, base_name, baseline in COMPARISONS:
        label = f"open_return_{horizon}"
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
            extra, coefficients = _ridge(train[[*baseline, factor]].to_numpy(dtype=float),
                                         y_train, test[[*baseline, factor]].to_numpy(dtype=float))
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


def _range_states(factors: pd.DataFrame, labels: pd.DataFrame):
    measure = factors[RANGE_10]
    outcome = labels["open_return_5"]
    dates = pd.DatetimeIndex(factors.index)
    rows = []
    for start, train_positions, test_positions in _folds(dates, 5):
        history = measure.iloc[train_positions].dropna()
        if len(history) < 80:
            continue
        q25, q75 = history.quantile([0.25, 0.75])
        for position in test_positions:
            value, future = measure.iloc[position], outcome.iloc[position]
            if not np.isfinite(value) or not np.isfinite(future):
                continue
            state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
            rows.append({"Date": dates[position], "test_start": start, "state": state,
                         "range_10": value, "training_q25": q25, "training_q75": q75,
                         "future_5d_open_return": future,
                         "roundtrip_20bp_proxy": future - 0.002})
    result = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    if result.empty:
        raise ValueError("no range-state observations")
    rng = np.random.default_rng(SEED)
    length, width = len(result), 10
    starts = np.arange(length - width + 1)
    contrasts = []
    for _ in range(2000):
        draw = rng.choice(starts, size=int(np.ceil(length / width)), replace=True)
        positions = (draw[:, None] + np.arange(width)).reshape(-1)[:length]
        sample = result.iloc[positions]
        high = sample.loc[sample["state"].eq("HIGH"), "future_5d_open_return"]
        low = sample.loc[sample["state"].eq("LOW"), "future_5d_open_return"]
        if not high.empty and not low.empty:
            contrasts.append(float(high.mean() - low.mean()))
    interval = list(np.quantile(contrasts, [0.025, 0.975])) if contrasts else [None, None]
    return result, [None if value is None else float(value) for value in interval]


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    first = next(_folds(days, 5))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
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
            research_question="Do selected daily clues have distinct short-horizon and risk-environment responsibilities?",
            hypothesis="Short-term ETF reversal, range state and broad-market impulse may carry distinct information.",
            falsification_conditions=("Increment disappears against the competing feature",
                                    "Training direction changes across segments",
                                    "Range state does not isolate adverse or favorable later prices"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("ETF price and broad-market shocks can mean-revert or persist",),
                information_paths=("T daily return and range -> subsequent executable-session prices",),
                stage_objectives=("Audit independent information and directions",
                                  "Audit 10-day range conditional prices"),
                observation_metrics=("per-fold and pooled MSE", "training coefficient direction",
                                     "range-state mean and block interval"),
                methodology=("Eight fixed candidate-control comparisons", "Three purged segments",
                             "Training-only range quartiles", "Ten-session moving-block interval"),
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
        factors = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        totals, details = _evaluate(factors, intraday, labels)
        states, interval = _range_states(factors, labels)
        high = states.loc[states["state"].eq("HIGH"), "future_5d_open_return"]
        low = states.loc[states["state"].eq("LOW"), "future_5d_open_return"]
        artifacts = []
        for name, frame in (("responsibility_scores.csv", totals),
                            ("responsibility_fold_scores.csv", details),
                            ("range10_states.csv", states)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX06-{name.split('.')[0]}"))
        summary = {"decision": "DAILY_ROLE_REVIEW_COMPLETE",
                   "comparison_count": len(totals), "range_state_days": len(states),
                   "range_high_days": len(high), "range_low_days": len(low),
                   "range_high_mean": float(high.mean()) if len(high) else None,
                   "range_low_mean": float(low.mean()) if len(low) else None,
                   "range_high_20bp_proxy_mean": float(high.mean() - 0.002) if len(high) else None,
                   "range_high_minus_low_ci95": interval,
                   "range10_median_correlation": float(factors[RANGE_10].corr(factors[RANGE_MEDIAN])),
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX06-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(totals),
                   "sealed_date_rows_read": 0},
            diagnostics={"range_high_days": len(high), "range_low_days": len(low)},
            artifacts=tuple(artifacts),
        )
