"""S010 EX19: three competing tracking-residual and basket-diffusion mechanisms."""

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


EXPERIMENT_ID = "20260929_S010_EX19"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX03": "11650e695bffb0776dd700eb763fb644836878998ae46006acabdac86c1fb815",
    "20260929_S010_EX04": "aa501bc4e97f57378f79cbe57e689ff11f3641c57a665b254c1e6e8f75e8d0ee",
    "20260929_S010_EX13": "ae3ff0deff311b496e5b22bd84b1b54a2aea83567e3f086f3a265709c8500619",
    "20260929_S010_EX14": "1bb95559a3c1653326320af64c81f7a0d8b8d8b453a9d687ab5e66fca00907e2",
    "20260929_S010_EX15": "fcde0f6a106126949f175edc31a4f36492242e68a680cfd6af398230f494b2e8",
    "20260929_S010_EX18": "6e2d612a341311971f6cc71c4fb4323850c10460c75a95c3d834400b2356f475",
}
SEED = 2026092919
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
FACTORS = ("tracking_residual_1_z20", "tracking_residual_5_z60",
           "tracking_persistence_10", "small_member_participation_1",
           "small_member_participation_5", "breadth_acceleration")
OUTCOMES = ("open_return_1", "open_return_5", "open_return_10")
B0 = ("etf_return_1", "etf_return_5", "theme_return_1", "theme_return_5",
      "tsfresh_range__median", "intra_afternoon_return", "tsfresh_return__maximum")
B1 = (*B0, "etf_volatility_20", "etf_drawdown_20",
      "tsfresh_volume_change__autocorrelation__lag_1", "basket_breadth_equal_5")
COMPARISONS = tuple((factor, outcome, name, baseline) for factor in FACTORS
                    for outcome in OUTCOMES for name, baseline in (("B0", B0), ("B1", B1)))
STATES = (("tracking_residual_1_z20", "open_return_1"),
          ("small_member_participation_5", "open_return_5"))


def _features(theme: pd.DataFrame, basket: pd.DataFrame) -> pd.DataFrame:
    if not theme.index.equals(basket.index):
        raise ValueError("theme and basket calendars differ")
    residual_1 = theme["etf_minus_theme_1"]
    residual_5 = theme["etf_minus_theme_5"]
    std_1 = residual_1.shift(1).rolling(20, min_periods=20).std(ddof=0)
    std_5 = residual_5.shift(1).rolling(60, min_periods=60).std(ddof=0)
    return pd.DataFrame({
        "tracking_residual_1_z20": residual_1 / std_1.where(std_1 > 0),
        "tracking_residual_5_z60": residual_5 / std_5.where(std_5 > 0),
        "tracking_persistence_10": np.sign(residual_1).rolling(10, min_periods=10).mean(),
        "small_member_participation_1": (basket["basket_breadth_equal_1"]
                                         - basket["basket_breadth_weighted_1"]),
        "small_member_participation_5": (basket["basket_breadth_equal_5"]
                                         - basket["basket_breadth_weighted_5"]),
        "breadth_acceleration": (basket["basket_breadth_equal_1"]
                                 - basket["basket_breadth_equal_5"]),
    }, index=theme.index)


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
    for factor, outcome, baseline_name, baseline in COMPARISONS:
        horizon = int(outcome.rsplit("_", 1)[-1])
        base_errors, extra_errors, positive = [], [], 0
        for start, train_positions, test_positions in _folds(dates, horizon):
            columns = [*baseline, factor, outcome]
            train = joined.iloc[train_positions][columns].dropna()
            test = joined.iloc[test_positions][columns].dropna()
            if len(train) < 80 or len(test) < 15:
                details.append({"Factor": factor, "Outcome": outcome,
                                "Baseline": baseline_name, "TestStart": start,
                                "Status": "INSUFFICIENT", "TrainRows": len(train),
                                "TestRows": len(test)})
                continue
            label_end = dates.get_loc(train.index[-1]) + 1 + horizon
            if label_end >= len(dates) or dates[label_end] >= test.index[0]:
                raise ValueError("training label crosses chronological test boundary")
            y_train = train[outcome].to_numpy(dtype=float)
            y_test = test[outcome].to_numpy(dtype=float)
            base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                             test[list(baseline)].to_numpy(dtype=float))
            extra, weights = _ridge(train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                                    test[[*baseline, factor]].to_numpy(dtype=float))
            b, e = np.square(y_test - base), np.square(y_test - extra)
            base_errors.extend(b)
            extra_errors.extend(e)
            positive += int(e.mean() < b.mean())
            details.append({"Factor": factor, "Outcome": outcome,
                            "Baseline": baseline_name, "TestStart": start,
                            "Status": "EVALUATED", "TrainRows": len(train),
                            "TestRows": len(test),
                            "TrainLabelEnd": dates[label_end].date().isoformat(),
                            "BaseMse": float(b.mean()), "ExtraMse": float(e.mean()),
                            "ExtraCoefficient": float(weights[-1])})
        totals.append({"Factor": factor, "Outcome": outcome, "Baseline": baseline_name,
                       "OosRows": len(base_errors), "PositiveFolds": positive,
                       "MseReduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                       if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _states(joined: pd.DataFrame):
    dates = pd.DatetimeIndex(joined.index)
    records, summaries = [], []
    for index, (factor, outcome) in enumerate(STATES):
        horizon = int(outcome.rsplit("_", 1)[-1])
        rows = []
        for start, train_positions, test_positions in _folds(dates, horizon):
            history = joined.iloc[train_positions][factor].dropna()
            if len(history) < 80:
                continue
            q25, q75 = history.quantile([0.25, 0.75])
            for position in test_positions:
                value = joined.iloc[position][factor]
                future = joined.iloc[position][outcome]
                if not np.isfinite(value) or not np.isfinite(future):
                    continue
                state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
                rows.append({"Date": dates[position], "Factor": factor, "Outcome": outcome,
                             "TestStart": start, "State": state, "Value": value,
                             "TrainingQ25": q25, "TrainingQ75": q75, "Future": future})
        frame = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
        if frame.empty:
            raise ValueError(f"no state observations: {factor}")
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
        summaries.append({"Factor": factor, "Outcome": outcome,
                          "HighDays": len(high), "LowDays": len(low),
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
    tiny = pd.bdate_range("2024-01-01", periods=80)
    residual = pd.Series(np.arange(80, dtype=float) / 10000, index=tiny)
    theme = pd.DataFrame({"etf_minus_theme_1": residual,
                          "etf_minus_theme_5": residual * 2}, index=tiny)
    basket = pd.DataFrame({"basket_breadth_equal_1": 0.6,
                           "basket_breadth_weighted_1": 0.5,
                           "basket_breadth_equal_5": 0.7,
                           "basket_breadth_weighted_5": 0.4}, index=tiny)
    factors = _features(theme, basket)
    if not factors["tracking_residual_1_z20"].iloc[:20].isna().all():
        raise ValueError("current residual entered historical volatility")
    if not np.isclose(factors["small_member_participation_5"].iloc[-1], 0.3):
        raise ValueError("synthetic breadth difference failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Do ETF-led continuation, dislocation reversion, or constituent diffusion explain later prices?",
            hypothesis="Opposing residual directions and basket participation can distinguish these mechanisms.",
            falsification_conditions=("Residual direction is unstable or absent after controls",
                                    "Breadth gap has no independent price increment",
                                    "Source timing or identity fails"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Relative pricing can lead or revert after theme information",
                                  "Breadth can reveal diffusion beyond dominant weights"),
                information_paths=("T ETF/theme residual or basket participation -> subsequent ETF opens",),
                stage_objectives=("Compare ETF-led continuation with reversion",
                                  "Survey three constituent-diffusion expressions"),
                observation_metrics=("Coverage", "purged MSE", "training coefficient direction",
                                     "training-only state counts and moving-block intervals"),
                methodology=("Thirty-six fixed comparisons", "Three purged chronological folds",
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
        inherited = pd.read_csv(first / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(first / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        intraday = pd.read_csv(third / "intraday_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        theme = pd.read_csv(fourth / "theme_features.csv.gz", parse_dates=["Date"]).set_index("Date")
        basket = pd.read_csv(fifteenth / "basket_factors.csv.gz", parse_dates=["Date"]).set_index("Date")
        sessions = pd.DatetimeIndex(inherited.index)
        for frame in (labels, intraday, theme, basket):
            if not sessions.equals(pd.DatetimeIndex(frame.index)):
                raise ValueError("predecessor calendars differ")
        features = _features(theme, basket)
        joined = inherited[list(name for name in B1 if name in inherited.columns)]
        joined = joined.join(intraday[["intra_afternoon_return"]])
        joined = joined.join(theme[["theme_return_1", "theme_return_5"]])
        joined = joined.join(basket[["basket_breadth_equal_5"]])
        joined = joined.join(features).join(labels[list(OUTCOMES)])
        joined = joined.replace([np.inf, -np.inf], np.nan)
        scores, folds = _evaluate(joined)
        states, state_summary = _states(joined)
        counts = states.groupby(["Factor", "TestStart", "State"]).size().unstack(
            fill_value=0).reset_index()
        quality = pd.DataFrame({"Factor": FACTORS,
                                "FiniteRows": features.notna().sum().to_numpy(),
                                "FirstDate": [features[name].first_valid_index() for name in FACTORS]})
        relations = joined[[*FACTORS, "etf_return_1", "etf_return_5",
                            "theme_return_1", "theme_return_5",
                            "basket_breadth_equal_5"]].corr().loc[list(FACTORS)]
        relations.index.name = "Factor"
        artifacts = []
        for name, frame in (("mechanism_factors.csv.gz", features.reset_index()),
                            ("factor_quality.csv", quality), ("factor_scores.csv", scores),
                            ("fold_scores.csv", folds), ("state_days.csv", states),
                            ("state_counts.csv", counts), ("state_summary.csv", state_summary),
                            ("factor_relations.csv", relations.reset_index())):
            frame.to_csv(context.workspace.path(name), index=False,
                         compression="gzip" if name.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX19-{name.split('.')[0]}"))
        summary = {"decision": "THREE_MECHANISM_SURVEY_COMPLETE",
                   "mechanism_count": 3, "factor_count": len(FACTORS),
                   "comparison_count": len(scores),
                   "basket_source_receipt_sha256": RECEIPTS["20260929_S010_EX15"],
                   "source_publication_timestamp_verified": False,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX19-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "comparison_count": len(scores),
                   "sealed_date_rows_read": 0},
            diagnostics={"factor_finite_all_rows": int(features.notna().all(axis=1).sum())},
            artifacts=tuple(artifacts),
        )
