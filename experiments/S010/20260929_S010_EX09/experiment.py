"""S010 EX09: rolling-normalized global volatility audit."""

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


EXPERIMENT_ID = "20260929_S010_EX09"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX05": "a5f4f9d56696fe894da94ef4a37591887f141664f8819cc064d7f6290747626d",
    "20260929_S010_EX06": "a5ae3eb4633f97d0b4c1aa815fc5fc6992eff7d4adc0e0a2afb009c331b02276",
    "20260929_S010_EX07": "f39fc5db88c7ed9c7996a96fd4d7fee4ec1c73e275c6e553aee343f0e30cb8ba",
    "20260929_S010_EX08": "d48bba43ce2e25e1fd6c3f4a7613f57776331ff79190546986e9ffe4658bf6c9",
}
RAW = "spx_prior_volatility_20"
NORMAL = "spx_prior_volatility_z60"
BASELINE = ("etf_return_1", "etf_return_5", "etf_volatility_20",
            "tsfresh_range__median", "etf_drawdown_10", "intra_afternoon_return",
            "etf_volatility_5", "etf_range_10",
            "csi300_volatility_20", "csi500_volatility_20")
COMPARISONS = (
    (NORMAL, "DOMESTIC", BASELINE),
    (NORMAL, "DOMESTIC_RAW", (*BASELINE, RAW)),
    (RAW, "DOMESTIC", BASELINE),
    (RAW, "DOMESTIC_NORMAL", (*BASELINE, NORMAL)),
)
OUTCOMES = ("open_return_5", "adverse_5")
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
SEED = 2026092909


def _z60(raw: pd.Series) -> pd.Series:
    mean = raw.rolling(60).mean()
    std = raw.rolling(60).std(ddof=0).replace(0, np.nan)
    return (raw - mean) / std


def _adverse(daily: pd.DataFrame, sessions: pd.DatetimeIndex) -> pd.Series:
    if not daily.index.equals(sessions):
        raise ValueError("ETF daily dates differ from predecessor calendar")
    opens = daily["Open"].to_numpy(dtype=float)
    lows = daily["Low"].to_numpy(dtype=float)
    if not np.isfinite(opens).all() or not np.isfinite(lows).all():
        raise ValueError("ETF execution prices contain nonfinite value")
    if (opens <= 0).any() or (lows <= 0).any() or (lows > opens).any():
        raise ValueError("ETF execution low or open is invalid")
    values = np.full(len(sessions), np.nan)
    for position in range(len(sessions) - 5):
        values[position] = lows[position + 1:position + 6].min() / opens[position + 1] - 1
    return pd.Series(values, index=sessions, name="adverse_5")


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
              risk: pd.DataFrame, labels: pd.DataFrame):
    if not inherited.index.equals(intraday.index) or not inherited.index.equals(risk.index):
        raise ValueError("feature calendars differ")
    if not inherited.index.equals(labels.index) or inherited.index.duplicated().any():
        raise ValueError("label calendar differs")
    domestic = [name for name in BASELINE if name != "intra_afternoon_return"]
    joined = inherited[domestic].join(intraday[["intra_afternoon_return"]])
    joined = joined.join(risk[[RAW, NORMAL]]).join(labels)
    joined = joined.replace([np.inf, -np.inf], np.nan)
    dates = pd.DatetimeIndex(joined.index)
    totals, details = [], []
    for outcome in OUTCOMES:
        for factor, base_name, baseline in COMPARISONS:
            base_errors, extra_errors, positive = [], [], 0
            for start, train_positions, test_positions in _folds(dates):
                columns = list(dict.fromkeys([*baseline, factor, outcome, NORMAL]))
                train = joined.iloc[train_positions][columns].dropna()
                test = joined.iloc[test_positions][columns].dropna()
                if len(train) < 80 or len(test) < 15:
                    details.append({"factor": factor, "outcome": outcome,
                                    "baseline": base_name, "test_start": start,
                                    "status": "INSUFFICIENT", "train_rows": len(train),
                                    "test_rows": len(test)})
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
            totals.append({"factor": factor, "outcome": outcome,
                           "baseline": base_name, "oos_rows": len(base_errors),
                           "positive_folds": positive,
                           "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                           if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _states(risk: pd.DataFrame, labels: pd.DataFrame):
    dates = pd.DatetimeIndex(risk.index)
    measure = risk[NORMAL]
    rows = []
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
            rows.append({"Date": dates[position], "test_start": start,
                         "state": state, "value": value,
                         "training_q25": q25, "training_q75": q75,
                         "open_return_5": future["open_return_5"],
                         "adverse_5": future["adverse_5"]})
    frame = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    if frame.empty:
        raise ValueError("no normalized risk-state observations")
    rng = np.random.default_rng(SEED)
    length, width = len(frame), 10
    starts = np.arange(length - width + 1)
    summary = []
    for outcome in OUTCOMES:
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
        summary.append({"outcome": outcome, "high_days": len(high), "low_days": len(low),
                        "high_mean": float(high.mean()) if len(high) else np.nan,
                        "low_mean": float(low.mean()) if len(low) else np.nan,
                        "high_minus_low_ci95_low": float(interval[0]),
                        "high_minus_low_ci95_high": float(interval[1])})
    return frame, pd.DataFrame(summary)


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    raw = pd.Series(1 + np.arange(800, dtype=float) / 100, index=days)
    z = _z60(raw)
    if z.iloc[:59].notna().any() or not np.isfinite(z.iloc[59:]).all():
        raise ValueError("synthetic rolling normalization failed")
    first = next(_folds(days))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
        raise ValueError("synthetic purge boundary failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Does relative global volatility preserve adverse-price information across market states?",
            hypothesis="Recent US volatility relative to its own prior distribution may mark recurring risk rather than an absolute historical regime.",
            falsification_conditions=("Relative signal loses domestic-controlled increment",
                                    "Risk-state direction is unstable", "Predecessor identity differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Volatility regimes can be expressed in absolute or relative scale",),
                information_paths=("Prior US realized volatility relative to own history -> later ETF risk",),
                stage_objectives=("Compare relative and absolute global volatility",
                                  "Audit high/low state support in each chronological segment"),
                observation_metrics=("purged MSE", "coefficient direction",
                                     "state counts and block intervals"),
                methodology=("Sixty-session causal normalization", "Eight matched-date comparisons",
                             "Training-only quartile states and ten-session block intervals"),
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
        risk = cross_source[[RAW]].copy()
        risk[NORMAL] = _z60(risk[RAW])
        result = context.data.fetch(DataRequest(
            Dataset.ETF_OHLCV, "159326.SZ", "2024-09-09", "2026-09-28", "2026-09-28", "daily",
            {"env_file": str(root.parents[2] / ".env")},
        ))
        if not result.ready or result.identity is None:
            error = result.error
            raise ValueError("ETF daily DFLS unavailable: " + result.status.value
                             + ("" if error is None else f" {error.code}: {error.message}"))
        daily = result.dataframe.copy()
        daily["Date"] = pd.to_datetime(daily["Date"], errors="raise")
        daily = daily.set_index("Date").sort_index()
        adverse = _adverse(daily, pd.DatetimeIndex(inherited.index))
        outcomes = labels[["open_return_5"]].join(adverse)
        scores, folds = _evaluate(inherited, intraday, risk, outcomes)
        states, state_summary = _states(risk, outcomes)
        counts = states.groupby(["test_start", "state"]).size().unstack(fill_value=0).reset_index()
        artifacts = []
        for name, frame in (("normalized_features.csv.gz", risk.reset_index()),
                            ("normalization_scores.csv", scores),
                            ("normalization_fold_scores.csv", folds),
                            ("normalized_states.csv", states),
                            ("normalized_state_counts.csv", counts),
                            ("normalized_state_summary.csv", state_summary)):
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX09-{name.split('.')[0]}"))
        summary = {"decision": "RELATIVE_GLOBAL_VOL_REVIEW_COMPLETE",
                   "comparison_count": len(scores), "risk_rows": int(risk[NORMAL].notna().sum()),
                   "etf_sha256": result.identity.content_sha256,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX09-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"risk_rows": summary["risk_rows"]}, artifacts=tuple(artifacts),
        )
