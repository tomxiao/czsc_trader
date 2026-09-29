"""S010 EX18: role and redundancy review of late directional volume."""

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


EXPERIMENT_ID = "20260929_S010_EX18"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX12": "6b0ab17d03232dc2d79afea75a306b11b2efef0d5aaf3775b00f4dd7c83a87c9",
    "20260929_S010_EX13": "ae3ff0deff311b496e5b22bd84b1b54a2aea83567e3f086f3a265709c8500619",
    "20260929_S010_EX17": "66aa85ccdb4c5036d689a991c6e195293db60330ed87e6d63c182fab5c8a26cb",
}
SEED = 2026092918
FACTOR = "flow_late_signed_volume"
OUTCOMES = ("open_return_1", "open_return_5")
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
B_SHAPE = ("etf_return_1", "etf_return_5", "etf_volatility_20",
           "tsfresh_range__median", "intra_afternoon_return",
           "intra_afternoon_volume_share", "intra_realized_vol",
           "intra_close_location", "theme_return_1")
B_FULL = (*B_SHAPE, "theme_return_5", "etf_drawdown_20",
          "tsfresh_return__maximum", "tsfresh_volume_change__autocorrelation__lag_1")
COMPARISONS = tuple((outcome, name, baseline) for outcome in OUTCOMES
                    for name, baseline in (("B_SHAPE", B_SHAPE), ("B_FULL", B_FULL)))


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
    for outcome, baseline_name, baseline in COMPARISONS:
        horizon = int(outcome.rsplit("_", 1)[-1])
        base_errors, extra_errors, positive = [], [], 0
        for start, train_positions, test_positions in _folds(dates, horizon):
            columns = [*baseline, FACTOR, outcome]
            train = joined.iloc[train_positions][columns].dropna()
            test = joined.iloc[test_positions][columns].dropna()
            if len(train) < 80 or len(test) < 15:
                details.append({"Outcome": outcome, "Baseline": baseline_name,
                                "TestStart": start, "Status": "INSUFFICIENT",
                                "TrainRows": len(train), "TestRows": len(test)})
                continue
            label_end = dates.get_loc(train.index[-1]) + 1 + horizon
            if label_end >= len(dates) or dates[label_end] >= test.index[0]:
                raise ValueError("training label crosses chronological test boundary")
            y_train = train[outcome].to_numpy(dtype=float)
            y_test = test[outcome].to_numpy(dtype=float)
            base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                             test[list(baseline)].to_numpy(dtype=float))
            extra, weights = _ridge(train[[*baseline, FACTOR]].to_numpy(dtype=float), y_train,
                                    test[[*baseline, FACTOR]].to_numpy(dtype=float))
            b, e = np.square(y_test - base), np.square(y_test - extra)
            base_errors.extend(b)
            extra_errors.extend(e)
            positive += int(e.mean() < b.mean())
            details.append({"Outcome": outcome, "Baseline": baseline_name,
                            "TestStart": start, "Status": "EVALUATED",
                            "TrainRows": len(train), "TestRows": len(test),
                            "TrainLabelEnd": dates[label_end].date().isoformat(),
                            "BaseMse": float(b.mean()), "ExtraMse": float(e.mean()),
                            "ExtraCoefficient": float(weights[-1])})
        totals.append({"Outcome": outcome, "Baseline": baseline_name,
                       "OosRows": len(base_errors), "PositiveFolds": positive,
                       "MseReduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                       if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _states(joined: pd.DataFrame):
    dates = pd.DatetimeIndex(joined.index)
    records, summaries = [], []
    for index, outcome in enumerate(OUTCOMES):
        horizon = int(outcome.rsplit("_", 1)[-1])
        rows = []
        for start, train_positions, test_positions in _folds(dates, horizon):
            history = joined.iloc[train_positions][FACTOR].dropna()
            if len(history) < 80:
                continue
            q25, q75 = history.quantile([0.25, 0.75])
            for position in test_positions:
                value = joined.iloc[position][FACTOR]
                future = joined.iloc[position][outcome]
                if not np.isfinite(value) or not np.isfinite(future):
                    continue
                state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
                rows.append({"Date": dates[position], "Outcome": outcome,
                             "TestStart": start, "State": state, "Value": value,
                             "TrainingQ25": q25, "TrainingQ75": q75, "Future": future})
        frame = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"no state observations: {outcome}")
        rng = np.random.default_rng(SEED + index)
        length, width = len(frame), 5
        starts = np.arange(length - width + 1)
        differences = []
        for _ in range(2000):
            draw = rng.choice(starts, size=int(np.ceil(length / width)), replace=True)
            positions = (draw[:, None] + np.arange(width)).reshape(-1)[:length]
            sample = frame.iloc[positions]
            high = sample.loc[sample["State"].eq("HIGH"), "Future"]
            low = sample.loc[sample["State"].eq("LOW"), "Future"]
            if not high.empty and not low.empty:
                differences.append(float(high.mean() - low.mean()))
        high = frame.loc[frame["State"].eq("HIGH"), "Future"]
        low = frame.loc[frame["State"].eq("LOW"), "Future"]
        interval = list(np.quantile(differences, [0.025, 0.975])) if differences else [np.nan, np.nan]
        summaries.append({"Outcome": outcome, "HighDays": len(high), "LowDays": len(low),
                          "HighMean": float(high.mean()) if len(high) else np.nan,
                          "LowMean": float(low.mean()) if len(low) else np.nan,
                          "HighMinusLowCi95Low": float(interval[0]),
                          "HighMinusLowCi95High": float(interval[1])})
        records.append(frame)
    return pd.concat(records, ignore_index=True), pd.DataFrame(summaries)


def _precheck() -> None:
    dates = pd.bdate_range("2024-01-01", periods=800)
    first = next(_folds(dates, 5))
    if first[1][-1] + 6 >= first[2][0]:
        raise ValueError("synthetic label purge failed")
    sample = pd.DataFrame({FACTOR: [0.1, 0.2, 0.3, 0.4],
                           "open_return_1": [0.0] * 4})
    q25, q75 = sample[FACTOR].quantile([0.25, 0.75])
    if not (sample[FACTOR].iloc[0] <= q25 < q75 <= sample[FACTOR].iloc[-1]):
        raise ValueError("synthetic state threshold failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does late directional volume retain a distinct confirmation role?",
            hypothesis="Late price-volume participation can confirm near-term ETF opportunity beyond price shape.",
            falsification_conditions=("No increment after existing components and trend controls",
                                    "High-low state relation is absent or unstable",
                                    "Direction reverses across chronological folds"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Directional participation may signal near-term price confirmation",),
                information_paths=("Sealed T intraday directional-volume proxy -> later ETF opens",),
                stage_objectives=("Retest selected proxy against existing component controls",
                                  "Audit training-only high-low state interpretation"),
                observation_metrics=("Purged MSE", "training coefficient direction",
                                     "state counts and moving-block intervals"),
                methodology=("Four fixed comparisons", "Training-only quartiles",
                             "Five-session moving-block intervals"),
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
        seventeenth = root.parent / "20260929_S010_EX17" / "artifacts"
        gate = json.loads((seventeenth / "summary.json").read_text(encoding="utf-8"))
        if gate["decision"] != "INTRADAY_FLOW_SURVEY_COMPLETE":
            raise ValueError("predecessor flow survey is incomplete")
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        theme = pd.read_csv(fourth / "theme_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        flow = pd.read_csv(seventeenth / "flow_factors.csv.gz", parse_dates=["Date"]).set_index("Date")
        sessions = pd.DatetimeIndex(inherited.index)
        for frame in (labels, intraday, theme, flow):
            if not sessions.equals(pd.DatetimeIndex(frame.index)):
                raise ValueError("predecessor calendars differ")
        joined = inherited[list(name for name in B_FULL if name in inherited.columns)]
        joined = joined.join(intraday[["intra_afternoon_return", "intra_afternoon_volume_share",
                                       "intra_realized_vol", "intra_close_location"]])
        joined = joined.join(theme[["theme_return_1", "theme_return_5"]])
        joined = joined.join(flow[[FACTOR]]).join(labels[list(OUTCOMES)])
        joined = joined.replace([np.inf, -np.inf], np.nan)
        scores, folds = _evaluate(joined)
        states, state_summary = _states(joined)
        counts = states.groupby(["Outcome", "TestStart", "State"]).size().unstack(
            fill_value=0).reset_index()
        artifacts = []
        for name, frame in (("factor_scores.csv", scores), ("fold_scores.csv", folds),
                            ("state_days.csv", states), ("state_counts.csv", counts),
                            ("state_summary.csv", state_summary)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX18-{name.split('.')[0]}"))
        summary = {"decision": "LATE_FLOW_ROLE_REVIEW_COMPLETE",
                   "comparison_count": len(scores),
                   "flow_source_receipt_sha256": RECEIPTS["20260929_S010_EX17"],
                   "sealed_date_rows_read": 0, "account_replay_performed": False,
                   "order_flow_observed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX18-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"flow_finite_rows": int(flow[FACTOR].notna().sum())},
            artifacts=tuple(artifacts),
        )
