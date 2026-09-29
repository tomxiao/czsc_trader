"""S010 EX08: global-volatility and turnover risk-context audit."""

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


EXPERIMENT_ID = "20260929_S010_EX08"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
    "20260929_S010_EX07": "f39fc5db88c7ed9c7996a96fd4d7fee4ec1c73e275c6e553aee343f0e30cb8ba",
}
START, CUTOFF = "2024-09-09", "2026-09-28"
SPX_VOL = "spx_prior_volatility_20"
TURNOVER = "chinext_turnover_z5"
B0 = ("etf_return_1", "etf_return_5", "etf_volatility_20",
      "tsfresh_range__median", "etf_drawdown_10", "intra_afternoon_return")
B1 = (*B0, "etf_volatility_5", "etf_range_10",
      "csi300_volatility_20", "csi500_volatility_20")
B2 = (*B1, "spx_prior_return_1", "spx_prior_return_5")
B3 = (*B2, TURNOVER)
COMPARISONS = tuple((SPX_VOL, outcome, name, baseline)
                    for outcome in ("open_return_5", "adverse_5")
                    for name, baseline in (("B0", B0), ("B1", B1), ("B2", B2), ("B3", B3))) + (
    (TURNOVER, "adverse_5", "B1", B1),
    (TURNOVER, "adverse_5", "B1_SPX_VOL", (*B1, SPX_VOL)),
)
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
SEED = 2026092908


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


def _folds(index: pd.DatetimeIndex):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 6 < test[0])
        yield start, train, test


def _evaluate(inherited: pd.DataFrame, intraday: pd.DataFrame,
              cross_source: pd.DataFrame, labels: pd.DataFrame):
    if not inherited.index.equals(intraday.index) or not inherited.index.equals(cross_source.index):
        raise ValueError("feature calendars differ")
    if not inherited.index.equals(labels.index) or inherited.index.duplicated().any():
        raise ValueError("label calendar differs")
    domestic_columns = [name for name in B1 if name != "intra_afternoon_return"]
    joined = inherited[domestic_columns].join(intraday[["intra_afternoon_return"]])
    joined = joined.join(cross_source[[SPX_VOL, TURNOVER, "spx_prior_return_1", "spx_prior_return_5"]])
    joined = joined.join(labels).replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for factor, outcome, base_name, baseline in COMPARISONS:
        base_errors, extra_errors, positive = [], [], 0
        for start, train_positions, test_positions in _folds(dates):
            columns = [*baseline, factor, outcome]
            train = joined.iloc[train_positions][columns].dropna()
            test = joined.iloc[test_positions][columns].dropna()
            if len(train) < 80 or len(test) < 15:
                details.append({"factor": factor, "outcome": outcome, "baseline": base_name,
                                "test_start": start, "status": "INSUFFICIENT",
                                "train_rows": len(train), "test_rows": len(test)})
                continue
            last = dates.get_loc(train.index[-1]) + 6
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
            details.append({"factor": factor, "outcome": outcome, "baseline": base_name,
                            "test_start": start, "status": "EVALUATED",
                            "train_rows": len(train), "test_rows": len(test),
                            "train_label_end": dates[last].date().isoformat(),
                            "base_mse": float(b.mean()), "extra_mse": float(e.mean()),
                            "extra_standardized_coefficient": float(weights[-1])})
        totals.append({"factor": factor, "outcome": outcome, "baseline": base_name,
                       "oos_rows": len(base_errors), "positive_folds": positive,
                       "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                       if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _states(cross_source: pd.DataFrame, labels: pd.DataFrame):
    dates = pd.DatetimeIndex(cross_source.index)
    rows = []
    for factor in (SPX_VOL, TURNOVER):
        measure = cross_source[factor]
        for start, train_positions, test_positions in _folds(dates):
            history = measure.iloc[train_positions].dropna()
            if len(history) < 80:
                continue
            q25, q75 = history.quantile([0.25, 0.75])
            for position in test_positions:
                value = measure.iloc[position]
                future = labels.iloc[position]
                if not np.isfinite(value) or future.isna().any():
                    continue
                state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
                rows.append({"factor": factor, "Date": dates[position], "test_start": start,
                             "state": state, "value": value, "training_q25": q25,
                             "training_q75": q75,
                             "open_return_5": future["open_return_5"],
                             "adverse_5": future["adverse_5"]})
    result = pd.DataFrame(rows).sort_values(["factor", "Date"]).reset_index(drop=True)
    if result.empty:
        raise ValueError("no risk-state observations")
    rng = np.random.default_rng(SEED)
    summary = []
    for factor in (SPX_VOL, TURNOVER):
        frame = result.loc[result["factor"].eq(factor)].reset_index(drop=True)
        length, width = len(frame), 10
        starts = np.arange(length - width + 1)
        for outcome in ("open_return_5", "adverse_5"):
            high = frame.loc[frame["state"].eq("HIGH"), outcome]
            low = frame.loc[frame["state"].eq("LOW"), outcome]
            contrasts = []
            for _ in range(2000):
                draw = rng.choice(starts, size=int(np.ceil(length / width)), replace=True)
                positions = (draw[:, None] + np.arange(width)).reshape(-1)[:length]
                sample = frame.iloc[positions]
                sampled_high = sample.loc[sample["state"].eq("HIGH"), outcome]
                sampled_low = sample.loc[sample["state"].eq("LOW"), outcome]
                if not sampled_high.empty and not sampled_low.empty:
                    contrasts.append(float(sampled_high.mean() - sampled_low.mean()))
            interval = list(np.quantile(contrasts, [0.025, 0.975])) if contrasts else [np.nan, np.nan]
            summary.append({"factor": factor, "outcome": outcome, "high_days": len(high),
                            "low_days": len(low), "high_mean": float(high.mean()) if len(high) else np.nan,
                            "low_mean": float(low.mean()) if len(low) else np.nan,
                            "high_minus_low_ci95_low": float(interval[0]),
                            "high_minus_low_ci95_high": float(interval[1])})
    return result, pd.DataFrame(summary)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    first = next(_folds(days))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
        raise ValueError("synthetic purge boundary failed")
    daily = pd.DataFrame({"Open": np.full(800, 1.0),
                          "Low": np.full(800, 0.9)}, index=days)
    adverse = _adverse_labels(daily, days)
    if not np.isclose(adverse.iloc[0], -0.1) or not np.isnan(adverse.iloc[-1]):
        raise ValueError("synthetic adverse label boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does prior US volatility identify ETF downside risk beyond domestic and ETF volatility?",
            hypothesis="Elevated overnight global uncertainty may weaken later ETF participation and deepen adverse excursions.",
            falsification_conditions=("Increment vanishes under domestic volatility controls",
                                    "Risk-state adverse difference has no stable direction",
                                    "Source or predecessor identity differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Global volatility can change risk appetite before China opens",),
                information_paths=("Prior US closes and T domestic state -> later ETF open prices and adverse path",),
                stage_objectives=("Compete global against domestic volatility", "Audit risk-state prices"),
                observation_metrics=("purged MSE", "training coefficient direction",
                                     "high-low return and adverse-path block intervals"),
                methodology=("Ten fixed candidate-control comparisons", "Training-only quartile states",
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
        seventh = root.parent / "20260929_S010_EX07" / "artifacts"
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        cross_source = pd.read_csv(seventh / "cross_source_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        result = context.data.fetch(DataRequest(
            Dataset.ETF_OHLCV, "159326.SZ", START, CUTOFF, CUTOFF, "daily",
            {"env_file": str(root.parents[2] / ".env")},
        ))
        if not result.ready or result.identity is None:
            error = result.error
            raise ValueError("ETF daily DFLS unavailable: " + result.status.value
                             + ("" if error is None else f" {error.code}: {error.message}"))
        daily = result.dataframe.copy()
        daily["Date"] = pd.to_datetime(daily["Date"], errors="raise")
        daily = daily.set_index("Date").sort_index()
        if not inherited.index.equals(labels.index) or not inherited.index.equals(cross_source.index):
            raise ValueError("predecessor calendars differ")
        adverse = _adverse_labels(daily, pd.DatetimeIndex(inherited.index))
        outcomes = labels[["open_return_5"]].join(adverse)
        scores, folds = _evaluate(inherited, intraday, cross_source, outcomes)
        states, state_summary = _states(cross_source, outcomes)
        artifacts = []
        for name, frame in (("risk_scores.csv", scores), ("risk_fold_scores.csv", folds),
                            ("risk_states.csv", states), ("risk_state_summary.csv", state_summary)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX08-{name.split('.')[0]}"))
        summary = {"decision": "GLOBAL_RISK_REVIEW_COMPLETE", "comparison_count": len(scores),
                   "etf_identity": {"dataset": result.identity.dataset,
                                    "source": result.identity.source,
                                    "sha256": result.identity.content_sha256,
                                    "rows": len(daily),
                                    "available_at": result.identity.temporal_contract.available_at},
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX08-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"state_rows": len(states)}, artifacts=tuple(artifacts),
        )
