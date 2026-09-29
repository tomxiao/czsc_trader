"""S011 EX08: external risk preference and rates against ETF outcomes."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd

from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition,
    ExperimentDependency, ExperimentMode, ExperimentOutcome, ExperimentProtocol,
    ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260929_S011_EX08"
START, INDEX_START, END = "2024-09-09", "2022-10-11", "2026-09-28"
FACTORS = ("us_tech_5", "shibor_change_5")
BASE = ("etf_return_1", "etf_return_5", "etf_return_20", "etf_vol_20",
        "etf_range_20", "amount_activity_20", "index_return_5", "index_return_20")
HORIZONS = (5, 10)
WINDOWS = (("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-07-01"),
           ("2026-07-01", "2026-10-01"))


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="raise").dt.normalize()
    if result["Date"].duplicated().any() or not result["Date"].is_monotonic_increasing:
        raise ValueError("source dates are duplicated or unordered")
    return result.set_index("Date")


def _strict_prior(source: pd.Series, sessions: pd.DatetimeIndex) -> tuple[pd.Series, pd.Series]:
    left = pd.DataFrame({"DecisionDate": sessions})
    right = pd.DataFrame({"SourceDate": source.index, "Value": source.to_numpy()})
    aligned = pd.merge_asof(left, right, left_on="DecisionDate", right_on="SourceDate",
                            direction="backward", allow_exact_matches=False)
    lag = (aligned["DecisionDate"] - aligned["SourceDate"]).dt.days
    aligned.loc[lag.gt(10), "Value"] = np.nan
    aligned.loc[lag.gt(10), "SourceDate"] = pd.NaT
    return (pd.Series(aligned["Value"].to_numpy(), index=sessions),
            pd.Series(aligned["SourceDate"].to_numpy(), index=sessions))


def _matrix(etf: pd.DataFrame, index: pd.DataFrame, ixic: pd.DataFrame,
            shibor: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    close, amount = etf["Close"].astype(float), etf["Amount"].astype(float)
    if (close.le(0).any() or amount.le(0).any()
            or not np.isfinite(etf[["Open", "High", "Low", "Close", "Amount"]]
                               .to_numpy(dtype=float)).all()):
        raise ValueError("ETF values invalid")
    us_return = ixic["PercentChange"].astype(float)
    rate = shibor["OvernightRate"].astype(float)
    if not np.isfinite(us_return.to_numpy()).all() or not np.isfinite(rate.to_numpy()).all():
        raise ValueError("external inputs invalid")
    us_5 = (1 + us_return).rolling(5).apply(np.prod, raw=True) - 1
    rate_5 = rate - rate.shift(5)
    us_aligned, us_date = _strict_prior(us_5, etf.index)
    rate_aligned, rate_date = _strict_prior(rate_5, etf.index)
    matrix = pd.DataFrame(index=etf.index)
    matrix["us_tech_5"] = us_aligned
    matrix["shibor_change_5"] = rate_aligned
    for days in (1, 5, 20):
        matrix[f"etf_return_{days}"] = close.pct_change(days, fill_method=None)
    matrix["etf_vol_20"] = np.log(close / close.shift(1)).rolling(20).std()
    matrix["etf_range_20"] = ((etf["High"] - etf["Low"]) / close).rolling(20).mean()
    matrix["amount_activity_20"] = np.log(amount / amount.rolling(20).median())
    for days in (5, 20):
        matrix[f"index_return_{days}"] = index["Close"].astype(float).pct_change(
            days, fill_method=None,
        ).reindex(etf.index)
    quality = pd.DataFrame({"Date": etf.index, "UsSourceDate": us_date.to_numpy(),
                            "RateSourceDate": rate_date.to_numpy()})
    return matrix.replace([np.inf, -np.inf], np.nan), quality


def _labels(etf: pd.DataFrame) -> pd.DataFrame:
    labels = pd.DataFrame(index=etf.index)
    entry = etf["Open"].astype(float).shift(-1)
    for horizon in HORIZONS:
        endpoint = etf["Close"].astype(float).shift(-horizon)
        future_low = pd.concat([
            etf["Low"].astype(float).shift(-step)
            for step in range(1, horizon + 1)
        ], axis=1).min(axis=1).where(endpoint.notna())
        labels[f"future_return_{horizon}"] = endpoint / entry - 1
        labels[f"future_adverse_{horizon}"] = future_low / entry - 1
    return labels


def _ridge(train_x: np.ndarray, train_y: np.ndarray,
           test_x: np.ndarray) -> tuple[np.ndarray, float]:
    center, scale = train_x.mean(axis=0), train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x, future = (train_x - center) / scale, (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]),
                              x.T @ (train_y - intercept))
    return intercept + future @ weights, float(weights[-1])


def _survey(features: pd.DataFrame, labels: pd.DataFrame):
    joined = features.join(labels)
    sessions = pd.DatetimeIndex(joined.index)
    positions = np.arange(len(sessions))
    coverage, scores, folds, redundant = [], [], [], []
    for factor in FACTORS:
        finite = features[factor].dropna()
        coverage.append({"Factor": factor, "FiniteRows": len(finite),
                         "UniqueValues": int(finite.nunique()),
                         "FirstFiniteDate": str(finite.index.min().date()) if len(finite) else ""})
        for baseline in BASE:
            pair = features[[factor, baseline]].dropna()
            if len(pair) >= 80:
                rho = pair[factor].corr(pair[baseline], method="spearman")
                if np.isfinite(rho) and abs(rho) >= 0.90:
                    redundant.append({"Factor": factor, "Baseline": baseline,
                                      "Rows": len(pair), "AbsSpearman": float(abs(rho))})
        for target in ("return", "adverse"):
            for horizon in HORIZONS:
                outcome = f"future_{target}_{horizon}"
                columns = [*BASE, factor, outcome]
                pair = joined[[factor, outcome]].dropna()
                q25, q75 = pair[factor].quantile([0.25, 0.75])
                high = pair.loc[pair[factor].ge(q75), outcome]
                low = pair.loc[pair[factor].le(q25), outcome]
                base_errors, extra_errors, improved, evaluated = [], [], 0, 0
                for test_start, test_end in WINDOWS:
                    test_pos = positions[(sessions >= pd.Timestamp(test_start))
                                         & (sessions < pd.Timestamp(test_end))]
                    train_pos = positions[positions + horizon < test_pos[0]]
                    train = joined.iloc[train_pos][columns].dropna()
                    test = joined.iloc[test_pos][columns].dropna()
                    record = {"Factor": factor, "Target": target, "Horizon": horizon,
                              "TestStart": test_start, "TrainRows": len(train),
                              "TestRows": len(test)}
                    if len(train) < 80 or len(test) < 15:
                        folds.append({**record, "Status": "INSUFFICIENT"})
                        continue
                    last_train_pos = sessions.get_loc(train.index[-1])
                    if last_train_pos + horizon >= test_pos[0]:
                        raise ValueError("training label endpoint reaches test period")
                    y_train, y_test = (train[outcome].to_numpy(dtype=float),
                                       test[outcome].to_numpy(dtype=float))
                    base, _ = _ridge(train[list(BASE)].to_numpy(dtype=float), y_train,
                                     test[list(BASE)].to_numpy(dtype=float))
                    extra, coefficient = _ridge(train[[*BASE, factor]].to_numpy(dtype=float),
                                                y_train, test[[*BASE, factor]].to_numpy(dtype=float))
                    base_sq, extra_sq = np.square(y_test - base), np.square(y_test - extra)
                    base_errors.extend(base_sq.tolist())
                    extra_errors.extend(extra_sq.tolist())
                    improved += int(extra_sq.mean() < base_sq.mean())
                    evaluated += 1
                    folds.append({**record, "Status": "EVALUATED", "BaseMse": float(base_sq.mean()),
                                  "ExtraMse": float(extra_sq.mean()),
                                  "ExtraCoefficient": coefficient,
                                  "TrainLabelEnd": str(sessions[last_train_pos + horizon].date())})
                scores.append({"Factor": factor, "Target": target, "Horizon": horizon,
                               "PairedRows": len(pair),
                               "Spearman": float(pair[factor].corr(pair[outcome], method="spearman")),
                               "HighRows": len(high), "LowRows": len(low),
                               "HighMinusLow": float(high.mean() - low.mean()),
                               "EvaluatedFolds": evaluated, "PositiveFolds": improved,
                               "MseReduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                               if base_errors else np.nan})
    return (pd.DataFrame(coverage), pd.DataFrame(scores), pd.DataFrame(folds),
            pd.DataFrame(redundant, columns=["Factor", "Baseline", "Rows", "AbsSpearman"]))


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=90)
    close = pd.Series(1 + np.arange(90) * .002 + np.sin(np.arange(90) / 5) * .02,
                      index=days)
    etf = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * .99,
                        "Close": close, "Amount": 1e7 * (1 + np.arange(90) % 11)}, index=days)
    index = pd.DataFrame({"Close": close * 1000}, index=days)
    ixic = pd.DataFrame({"PercentChange": np.linspace(-.01, .01, 90)}, index=days)
    shibor = pd.DataFrame({"OvernightRate": np.linspace(1., 2., 90)}, index=days)
    matrix, quality = _matrix(etf, index, ixic, shibor)
    if not (quality["UsSourceDate"].iloc[30] < days[30]
            and quality["RateSourceDate"].iloc[30] < days[30]):
        raise ValueError("strict prior source alignment differs")
    changed = ixic.copy()
    changed.iloc[-5:, 0] *= 10
    after, _ = _matrix(etf, index, changed, shibor)
    if not np.allclose(matrix.iloc[:-5]["us_tech_5"], after.iloc[:-5]["us_tech_5"],
                       equal_nan=True):
        raise ValueError("US factor reads future data")
    if not _labels(etf).iloc[-10:]["future_return_10"].isna().all():
        raise ValueError("future label endpoint differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            research_question="Do prior US technology-market and domestic short-rate states add ETF path information?",
            hypothesis="US risk appetite and short rates each have opposing transmission explanations for later ETF returns and adverse paths.",
            falsification_conditions=("No stable direction or baseline increment for ETF outcomes",
                                      "Cross-market source time or data contract differs"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092907,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value,
                              Dataset.GLOBAL_INDEX_DAILY.value, Dataset.SHIBOR_DAILY.value,
                              Dataset.TRADING_CALENDAR.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Risk appetite and funding cost may transmit to ETF prices with delay",),
                information_paths=("Strictly prior US close and SHIBOR plus T ETF/theme bars -> later ETF order",),
                stage_objectives=("Survey two opposing-prediction external state factors for ETF outcomes",),
                observation_metrics=("Coverage, source lag, redundancy and high-low association",
                                     "Purged ETF MSE increment and coefficient direction"),
                methodology=("Two factors, two targets, two horizons, three chronological folds",
                             "Training-only standardized ridge with penalty 10"),
                predecessor_experiment_ids=(),
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
        repository = Path(__file__).resolve().parents[3]
        options = {"env_file": str(repository / ".env")}
        requests = (("etf", Dataset.ETF_OHLCV, "159326.SZ", START),
                    ("index", Dataset.DOMESTIC_INDEX_CLOSE_DAILY, "931994.CSI", INDEX_START),
                    ("ixic", Dataset.GLOBAL_INDEX_DAILY, "IXIC", "2024-08-01"),
                    ("shibor", Dataset.SHIBOR_DAILY, None, "2024-08-01"),
                    ("calendar", Dataset.TRADING_CALENDAR, "SSE", INDEX_START))
        frames, identities = {}, {}
        for name, dataset, symbol, start in requests:
            result = context.data.fetch(DataRequest(dataset, symbol, start, END, None,
                                                    "daily", options))
            if not result.ready or result.identity is None:
                error = result.error
                raise ValueError(f"{name} DFLS unavailable: {result.status.value}"
                                 + ("" if error is None else f" {error.code}: {error.message}"))
            frames[name] = result.dataframe.copy()
            identities[name] = {"dataset": dataset.value, "symbol": symbol,
                                "content_sha256": result.identity.content_sha256,
                                "metadata": dict(result.identity.metadata),
                                "rows": len(result.dataframe)}
        if (len(frames["etf"]), len(frames["index"])) != (497, 965):
            raise ValueError("ETF or theme coverage differs")
        if (identities["etf"]["metadata"].get("adjustment") != "hfq"
                or identities["etf"]["metadata"].get("availability_time_field") != "AvailableDate"):
            raise ValueError("ETF adjustment or availability contract differs")
        if not pd.to_datetime(frames["etf"]["AvailableDate"]).dt.strftime(
            "%H:%M:%S").eq("17:00:00").all():
            raise ValueError("ETF adjustment availability differs")
        if identities["index"]["metadata"].get("price_scope") != "CLOSE_ONLY":
            raise ValueError("theme index control contract differs")
        if identities["ixic"]["metadata"].get("unit") != "decimal_return":
            raise ValueError("IXIC return unit differs")
        etf, index, ixic, shibor, calendar = (_indexed(frames[name]) for name in
                                             ("etf", "index", "ixic", "shibor", "calendar"))
        open_days = calendar.index[calendar["IsOpen"].eq(1)]
        if not index.index.equals(open_days) or not etf.index.equals(
            open_days[open_days >= pd.Timestamp(START)]
        ):
            raise ValueError("ETF or theme dates differ from calendar")
        matrix, source_dates = _matrix(etf, index, ixic, shibor)
        if (source_dates["UsSourceDate"].isna().any()
                or source_dates["RateSourceDate"].isna().any()):
            raise ValueError("external source has excessive lag or missing history")
        labels = _labels(etf)
        coverage, scores, folds, redundant = _survey(matrix, labels)
        if len(scores) != 8 or len(folds) != 24:
            raise ValueError("fixed survey budget differs")
        artifacts = []
        for filename, frame in (("factor_matrix.csv.gz", matrix.reset_index(names="Date")),
                                ("future_labels.csv.gz", labels.reset_index(names="Date")),
                                ("source_dates.csv", source_dates),
                                ("factor_coverage.csv", coverage), ("factor_scores.csv", scores),
                                ("fold_scores.csv", folds), ("redundancy.csv", redundant)):
            frame.to_csv(context.workspace.path(filename), index=False,
                         compression="gzip" if filename.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(
                filename, f"S011-EX08-{filename.split('.')[0]}",
            ))
        summary = {"decision": "SURVEY_COMPLETE", "etf_sessions": len(etf),
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "evaluated_folds": int(folds["Status"].eq("EVALUATED").sum()),
                   "insufficient_folds": int(folds["Status"].eq("INSUFFICIENT").sum()),
                   "redundant_pairs": len(redundant), "source_identities": identities,
                   "s011_prior_experiments_share_development_pool": True,
                   "other_batch_material_previously_seen_not_used_for_selection": True,
                   "historical_source_publication_verified": False,
                   "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
            encoding="utf-8",
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "S011-EX08-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "SURVEY_COMPLETE", "factor_count": len(FACTORS),
                   "comparison_count": len(scores), "account_replay_performed": False},
            diagnostics={"evaluated_folds": summary["evaluated_folds"],
                         "redundant_pairs": summary["redundant_pairs"]},
            artifacts=tuple(artifacts),
        )
