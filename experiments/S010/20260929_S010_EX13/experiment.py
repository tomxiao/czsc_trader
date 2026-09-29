"""S010 EX13: isolate maximum daily return from serial-shape competitors."""

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


EXPERIMENT_ID = "20260929_S010_EX13"
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
    "20260929_S010_EX10": "f31c3df4cec34265cbe59902cbbb5987c1e2ec99e460f6f7aa7d5261886a86ca",
    "20260929_S010_EX11": "577edf88220d5cba3f16c857267ed608fe27d312e3da5f95bc57727a0131cf51",
    "20260929_S010_EX12": "6b0ab17d03232dc2d79afea75a306b11b2efef0d5aaf3775b00f4dd7c83a87c9",
}
MAX_RETURN = "tsfresh_return__maximum"
RANGE_SERIAL = "tsfresh_range__autocorrelation__lag_1"
VOLUME_SERIAL = "tsfresh_volume_change__autocorrelation__lag_1"
B_TREND = ("etf_return_1", "etf_return_5", "etf_volatility_20",
           "tsfresh_range__median", "intra_afternoon_return",
           "etf_return_10", "etf_ma_distance_10", "etf_drawdown_10")
COMPARISONS = (
    (MAX_RETURN, "B_TREND", B_TREND),
    (MAX_RETURN, "B_RANGE_SERIAL", (*B_TREND, RANGE_SERIAL)),
    (MAX_RETURN, "B_VOLUME_SERIAL", (*B_TREND, VOLUME_SERIAL)),
    (MAX_RETURN, "B_BOTH_SERIAL", (*B_TREND, RANGE_SERIAL, VOLUME_SERIAL)),
    (VOLUME_SERIAL, "B_MAX_RETURN", (*B_TREND, MAX_RETURN)),
)
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
SEED = 2026092913


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray):
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights, weights


def _folds(index: pd.DatetimeIndex):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 11 < test[0])
        yield start, train, test


def _evaluate(factors: pd.DataFrame, intraday: pd.DataFrame, labels: pd.DataFrame):
    if not factors.index.equals(labels.index) or not factors.index.equals(intraday.index):
        raise ValueError("predecessor calendars differ")
    if factors.index.duplicated().any():
        raise ValueError("duplicate predecessor date")
    names = list(dict.fromkeys(name for _, _, base in COMPARISONS for name in base
                               if name in factors.columns))
    names.extend(name for name in (MAX_RETURN, RANGE_SERIAL, VOLUME_SERIAL) if name not in names)
    joined = factors[names].join(intraday[["intra_afternoon_return"]])
    joined = joined.join(labels[["open_return_10"]]).replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor, base_name, baseline in COMPARISONS:
        base_errors, extra_errors, positive = [], [], 0
        for start, train_positions, test_positions in _folds(dates):
            columns = [*baseline, factor, "open_return_10"]
            train = joined.iloc[train_positions][columns].dropna()
            test = joined.iloc[test_positions][columns].dropna()
            if len(train) < 80 or len(test) < 15:
                details.append({"factor": factor, "baseline": base_name,
                                "test_start": start, "status": "INSUFFICIENT",
                                "train_rows": len(train), "test_rows": len(test)})
                continue
            last = dates.get_loc(train.index[-1]) + 11
            if last >= len(dates) or dates[last] >= test.index[0]:
                raise ValueError("training label crosses chronological test boundary")
            y_train = train["open_return_10"].to_numpy(dtype=float)
            y_test = test["open_return_10"].to_numpy(dtype=float)
            base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                             test[list(baseline)].to_numpy(dtype=float))
            extra, weights = _ridge(train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                                    test[[*baseline, factor]].to_numpy(dtype=float))
            b, e = np.square(y_test - base), np.square(y_test - extra)
            base_errors.extend(b)
            extra_errors.extend(e)
            positive += int(e.mean() < b.mean())
            details.append({"factor": factor, "baseline": base_name,
                            "test_start": start, "status": "EVALUATED",
                            "train_rows": len(train), "test_rows": len(test),
                            "train_label_end": dates[last].date().isoformat(),
                            "base_mse": float(b.mean()), "extra_mse": float(e.mean()),
                            "extra_standardized_coefficient": float(weights[-1])})
        totals.append({"factor": factor, "baseline": base_name,
                       "oos_rows": len(base_errors), "positive_folds": positive,
                       "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                       if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _states(factors: pd.DataFrame, labels: pd.DataFrame):
    dates = pd.DatetimeIndex(factors.index)
    measure = factors[MAX_RETURN]
    outcome = labels["open_return_10"]
    rows = []
    for start, train_positions, test_positions in _folds(dates):
        history = measure.iloc[train_positions].dropna()
        if len(history) < 80:
            continue
        q25, q75 = history.quantile([0.25, 0.75])
        for position in test_positions:
            value, future = measure.iloc[position], outcome.iloc[position]
            if not np.isfinite(value) or not np.isfinite(future):
                continue
            state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
            rows.append({"Date": dates[position], "test_start": start,
                         "state": state, "maximum_return_20": value,
                         "training_q25": q25, "training_q75": q75,
                         "open_return_10": future, "roundtrip_20bp_proxy": future - 0.002})
    frame = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    if frame.empty:
        raise ValueError("no maximum-return-state observations")
    rng = np.random.default_rng(SEED)
    length, width = len(frame), 15
    starts = np.arange(length - width + 1)
    contrasts = []
    for _ in range(2000):
        draw = rng.choice(starts, size=int(np.ceil(length / width)), replace=True)
        positions = (draw[:, None] + np.arange(width)).reshape(-1)[:length]
        sample = frame.iloc[positions]
        high = sample.loc[sample["state"].eq("HIGH"), "open_return_10"]
        low = sample.loc[sample["state"].eq("LOW"), "open_return_10"]
        if not high.empty and not low.empty:
            contrasts.append(float(high.mean() - low.mean()))
    high = frame.loc[frame["state"].eq("HIGH"), "open_return_10"]
    low = frame.loc[frame["state"].eq("LOW"), "open_return_10"]
    interval = list(np.quantile(contrasts, [0.025, 0.975])) if contrasts else [np.nan, np.nan]
    summary = pd.DataFrame([{
        "high_days": len(high), "low_days": len(low),
        "high_mean": float(high.mean()) if len(high) else np.nan,
        "low_mean": float(low.mean()) if len(low) else np.nan,
        "high_minus_low_ci95_low": float(interval[0]),
        "high_minus_low_ci95_high": float(interval[1]),
    }])
    return frame, summary


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    first = next(_folds(days))
    if days[first[1][-1] + 11] >= days[first[2][0]]:
        raise ValueError("synthetic purge boundary failed")
    predictions, weights = _ridge(np.arange(100, dtype=float).reshape(50, 2),
                                  np.arange(50, dtype=float),
                                  np.arange(20, dtype=float).reshape(10, 2))
    if len(predictions) != 10 or len(weights) != 2 or not np.isfinite(predictions).all():
        raise ValueError("synthetic ridge output invalid")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does the prior maximum daily return retain ten-day information apart from serial range and volume shapes?",
            hypothesis="A discrete upward shock may indicate thematic buying beyond gradual trend and volatility level.",
            falsification_conditions=("Increment is absorbed by either serial-shape peer",
                                    "High-low state price contrast lacks direction",
                                    "Predecessor identity or dates differ"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("A discrete upward shock can signal a short-lived influx of theme demand",),
                information_paths=("Past 20 day largest daily ETF return -> ten-day subsequent ETF open-price path",),
                stage_objectives=("Isolate maximum-return clue from each serial-shape peer",
                                  "Audit training-defined shock states"),
                observation_metrics=("Purged MSE", "training coefficient direction",
                                     "state counts and moving-block interval"),
                methodology=("Five fixed comparisons", "Training-only quartiles",
                             "Fifteen-session moving-block intervals"),
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
        scores, folds = _evaluate(factors, intraday, labels)
        states, state_summary = _states(factors, labels)
        state_counts = states.groupby(["test_start", "state"]).size().unstack(fill_value=0).reset_index()
        artifacts = []
        for name, frame in (("shock_scores.csv", scores), ("shock_fold_scores.csv", folds),
                            ("shock_states.csv", states), ("shock_state_counts.csv", state_counts),
                            ("shock_state_summary.csv", state_summary)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX13-{name.split('.')[0]}"))
        summary = {"decision": "MAXIMUM_RETURN_PEER_REVIEW_COMPLETE", "comparison_count": len(scores),
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX13-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"state_rows": len(states)}, artifacts=tuple(artifacts),
        )
