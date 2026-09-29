"""S010 EX20: focused review of ETF-versus-theme residual reversion."""

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


EXPERIMENT_ID = "20260929_S010_EX20"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX15": "fcde0f6a106126949f175edc31a4f36492242e68a680cfd6af398230f494b2e8",
    "20260929_S010_EX19": "63f80bada987fb52e660d235e5693be39ef2d2a7f1d067db48e79b195997faff",
}
SEED = 2026092920
FACTOR = "tracking_residual_1_z20"
OUTCOMES = ("open_return_5", "open_return_10")
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
B1 = ("etf_return_1", "etf_return_5", "theme_return_1", "theme_return_5",
      "tsfresh_range__median", "intra_afternoon_return", "tsfresh_return__maximum",
      "etf_volatility_20", "etf_drawdown_20",
      "tsfresh_volume_change__autocorrelation__lag_1", "basket_breadth_equal_5")
B2 = (*B1, "csi300_return_1", "csi500_return_5", "etf_volatility_5",
      "etf_gap", "intra_afternoon_volume_share", "intra_close_location")
COMPARISONS = tuple((outcome, name, baseline) for outcome in OUTCOMES
                    for name, baseline in (("B1", B1), ("B2", B2)))


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
        length, width = len(frame), 10
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
    first = next(_folds(dates, 10))
    if first[1][-1] + 11 >= first[2][0]:
        raise ValueError("synthetic label purge failed")
    frame = pd.DataFrame({FACTOR: [0.1, 0.2, 0.3, 0.4]}, index=range(4))
    q25, q75 = frame[FACTOR].quantile([0.25, 0.75])
    if not (frame[FACTOR].iloc[0] <= q25 < q75 <= frame[FACTOR].iloc[-1]):
        raise ValueError("synthetic state threshold failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does ETF/theme residual reversion survive broad-market and intraday controls?",
            hypothesis="Positive ETF-specific residual indicates temporary dislocation and lower later prices.",
            falsification_conditions=("No increment after broad-market and intraday controls",
                                    "Training direction reverses across folds",
                                    "Direct state comparison does not support reversion"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Temporary ETF trading pressure can mean-revert",),
                information_paths=("Sealed T ETF/theme residual -> later ETF opens",),
                stage_objectives=("Retest residual against stronger controls",
                                  "Audit training-only high-low state interpretation"),
                observation_metrics=("Purged MSE", "training coefficient direction",
                                     "state counts and moving-block intervals"),
                methodology=("Four fixed comparisons", "Three purged chronological folds",
                             "Ten-session moving-block intervals"),
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
        fifteenth = root.parent / "20260929_S010_EX15" / "artifacts"
        nineteenth = root.parent / "20260929_S010_EX19" / "artifacts"
        gate = json.loads((nineteenth / "summary.json").read_text(encoding="utf-8"))
        if gate["decision"] != "THREE_MECHANISM_SURVEY_COMPLETE":
            raise ValueError("predecessor mechanism survey is incomplete")
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        theme = pd.read_csv(fourth / "theme_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        basket = pd.read_csv(fifteenth / "basket_factors.csv.gz", parse_dates=["Date"]).set_index("Date")
        residual = pd.read_csv(nineteenth / "mechanism_factors.csv.gz", parse_dates=["Date"]).set_index("Date")
        sessions = pd.DatetimeIndex(inherited.index)
        for frame in (labels, intraday, theme, basket, residual):
            if not sessions.equals(pd.DatetimeIndex(frame.index)):
                raise ValueError("predecessor calendars differ")
        joined = inherited[list(name for name in B2 if name in inherited.columns)]
        joined = joined.join(intraday[["intra_afternoon_return",
                                       "intra_afternoon_volume_share", "intra_close_location"]])
        joined = joined.join(theme[["theme_return_1", "theme_return_5"]])
        joined = joined.join(basket[["basket_breadth_equal_5"]])
        joined = joined.join(residual[[FACTOR]]).join(labels[list(OUTCOMES)])
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
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX20-{name.split('.')[0]}"))
        summary = {"decision": "TRACKING_REVERSION_REVIEW_COMPLETE",
                   "comparison_count": len(scores),
                   "factor_source_receipt_sha256": RECEIPTS["20260929_S010_EX19"],
                   "index_is_realtime_nav": False,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX20-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"residual_finite_rows": int(residual[FACTOR].notna().sum())},
            artifacts=tuple(artifacts),
        )
