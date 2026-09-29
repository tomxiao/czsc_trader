"""S011 EX06: pre-listing index mechanisms and post-listing ETF translation."""

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


EXPERIMENT_ID = "20260929_S011_EX06"
INDEX_START, ETF_START, END = "2022-10-11", "2024-09-09", "2026-09-28"
SEED = 2026092905
HORIZONS = (5, 10)
FACTORS = ("position_120", "vol_ratio_10_60", "loss_concentration_60")
INDEX_BASE = ("index_return_5", "index_return_20", "index_return_60", "index_vol_20")
ETF_BASE = (
    "etf_return_1", "etf_return_5", "etf_vol_20", "index_return_5",
    "index_return_20", "index_return_60",
)
PHASES = (
    ("PRE_INDEX", "2022-10-11", "2024-09-09",
     (("2023-10-01", "2024-04-01"), ("2024-04-01", "2024-09-09")), INDEX_BASE),
    ("ETF_OVERLAP", "2024-09-09", "2026-10-01",
     (("2025-07-01", "2026-01-01"), ("2026-01-01", "2026-07-01"),
      ("2026-07-01", "2026-10-01")), ETF_BASE),
)


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    value = frame.copy()
    value["Date"] = pd.to_datetime(value["Date"], errors="raise").dt.normalize()
    if value["Date"].duplicated().any() or not value["Date"].is_monotonic_increasing:
        raise ValueError("source dates are duplicated or unordered")
    return value.set_index("Date")


def _loss_concentration(values: np.ndarray) -> float:
    losses = -np.minimum(values, 0.0)
    total = float(losses.sum())
    return float(np.sort(losses)[-5:].sum() / total) if total > 0 else np.nan


def _features(index: pd.DataFrame, etf: pd.DataFrame) -> pd.DataFrame:
    close = index["Close"].astype(float)
    if close.le(0).any() or not np.isfinite(close.to_numpy()).all():
        raise ValueError("index close is nonpositive or nonfinite")
    low = close.rolling(120).min()
    high = close.rolling(120).max()
    daily_log = np.log(close / close.shift(1))
    output = pd.DataFrame(index=index.index)
    output["position_120"] = (close - low) / (high - low)
    output["vol_ratio_10_60"] = daily_log.rolling(10).std() / daily_log.rolling(60).std()
    output["loss_concentration_60"] = daily_log.rolling(60).apply(
        _loss_concentration, raw=True,
    )
    for window in (5, 20, 60):
        output[f"index_return_{window}"] = close.pct_change(window, fill_method=None)
    output["index_vol_20"] = daily_log.rolling(20).std()
    etf_close = etf["Close"].astype(float)
    etf_log = np.log(etf_close / etf_close.shift(1))
    if not etf.index.isin(index.index).all():
        raise ValueError("ETF dates are missing from index dates")
    output["etf_return_1"] = etf_close.pct_change(fill_method=None).reindex(index.index)
    output["etf_return_5"] = etf_close.pct_change(5, fill_method=None).reindex(index.index)
    output["etf_vol_20"] = etf_log.rolling(20).std().reindex(index.index)
    return output.replace([np.inf, -np.inf], np.nan)


def _labels(index: pd.DataFrame, etf: pd.DataFrame) -> pd.DataFrame:
    output = pd.DataFrame(index=index.index)
    index_close = index["Close"].astype(float)
    etf_open = etf["Open"].astype(float)
    etf_close = etf["Close"].astype(float)
    etf_low = etf["Low"].astype(float)
    for horizon in HORIZONS:
        future_index_close = index_close.shift(-horizon)
        future_index_min = pd.concat(
            [index_close.shift(-step) for step in range(1, horizon + 1)], axis=1,
        ).min(axis=1).where(future_index_close.notna())
        output[f"pre_return_{horizon}"] = future_index_close / index_close - 1
        output[f"pre_adverse_{horizon}"] = future_index_min / index_close - 1
        entry = etf_open.shift(-1)
        future_etf_close = etf_close.shift(-horizon)
        future_etf_low = pd.concat(
            [etf_low.shift(-step) for step in range(1, horizon + 1)], axis=1,
        ).min(axis=1).where(future_etf_close.notna())
        output[f"etf_future_return_{horizon}"] = (future_etf_close / entry - 1).reindex(index.index)
        output[f"etf_future_adverse_{horizon}"] = (future_etf_low / entry - 1).reindex(index.index)
        # The pre-listing arm must not borrow a label endpoint after ETF listing.
        pre_last = index.index.searchsorted(pd.Timestamp(ETF_START)) - horizon
        output.iloc[pre_last:, output.columns.get_loc(f"pre_return_{horizon}")] = np.nan
        output.iloc[pre_last:, output.columns.get_loc(f"pre_adverse_{horizon}")] = np.nan
    return output


def _ridge(train_x: np.ndarray, train_y: np.ndarray,
           test_x: np.ndarray) -> tuple[np.ndarray, float]:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]),
                              x.T @ (train_y - intercept))
    return intercept + future @ weights, float(weights[-1])


def _survey(features: pd.DataFrame, labels: pd.DataFrame):
    joined = features.join(labels)
    sessions = pd.DatetimeIndex(joined.index)
    positions = np.arange(len(sessions))
    coverage: list[dict] = []
    redundant: list[dict] = []
    scores: list[dict] = []
    folds: list[dict] = []
    for factor in FACTORS:
        finite = features[factor].dropna()
        coverage.append({
            "Factor": factor, "FiniteRows": len(finite), "UniqueValues": int(finite.nunique()),
            "FirstFiniteDate": str(finite.index.min().date()) if len(finite) else "",
            "PreListingFiniteRows": int((finite.index < pd.Timestamp(ETF_START)).sum()),
            "EtfOverlapFiniteRows": int((finite.index >= pd.Timestamp(ETF_START)).sum()),
        })
        for baseline in (*INDEX_BASE, *ETF_BASE):
            pair = features[[factor, baseline]].dropna()
            if len(pair) >= 80:
                rho = pair[factor].corr(pair[baseline], method="spearman")
                if np.isfinite(rho) and abs(rho) >= 0.90:
                    redundant.append({"Factor": factor, "Baseline": baseline,
                                      "Rows": len(pair), "AbsSpearman": float(abs(rho))})
    for phase, phase_start, phase_end, windows, baseline in PHASES:
        phase_mask = (sessions >= pd.Timestamp(phase_start)) & (sessions < pd.Timestamp(phase_end))
        for factor in FACTORS:
            for target in ("return", "adverse"):
                for horizon in HORIZONS:
                    outcome = f"{'pre' if phase == 'PRE_INDEX' else 'etf_future'}_{target}_{horizon}"
                    columns = [*baseline, factor, outcome]
                    pair = joined.loc[phase_mask, [factor, outcome]].dropna()
                    q25, q75 = pair[factor].quantile([0.25, 0.75]) if len(pair) else (np.nan, np.nan)
                    high = pair.loc[pair[factor].ge(q75), outcome]
                    low = pair.loc[pair[factor].le(q25), outcome]
                    base_errors: list[float] = []
                    extra_errors: list[float] = []
                    improved = 0
                    for test_start, test_end in windows:
                        test_pos = positions[phase_mask & (sessions >= pd.Timestamp(test_start))
                                             & (sessions < pd.Timestamp(test_end))]
                        if not len(test_pos):
                            continue
                        train_pos = positions[phase_mask & (positions + horizon < test_pos[0])]
                        train = joined.iloc[train_pos][columns].dropna()
                        test = joined.iloc[test_pos][columns].dropna()
                        record = {"Phase": phase, "Factor": factor, "Target": target,
                                  "Horizon": horizon, "TestStart": test_start,
                                  "TrainRows": len(train), "TestRows": len(test)}
                        if len(train) < 80 or len(test) < 15:
                            folds.append({**record, "Status": "INSUFFICIENT"})
                            continue
                        last_train_pos = sessions.get_loc(train.index[-1])
                        if last_train_pos + horizon >= test_pos[0]:
                            raise ValueError("training label endpoint reaches test period")
                        y_train = train[outcome].to_numpy(dtype=float)
                        y_test = test[outcome].to_numpy(dtype=float)
                        base, _ = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                                         test[list(baseline)].to_numpy(dtype=float))
                        extra, coefficient = _ridge(
                            train[[*baseline, factor]].to_numpy(dtype=float), y_train,
                            test[[*baseline, factor]].to_numpy(dtype=float),
                        )
                        base_sq = np.square(y_test - base)
                        extra_sq = np.square(y_test - extra)
                        base_errors.extend(base_sq.tolist())
                        extra_errors.extend(extra_sq.tolist())
                        improved += int(extra_sq.mean() < base_sq.mean())
                        folds.append({**record, "Status": "EVALUATED",
                                      "TrainLabelEnd": str(sessions[last_train_pos + horizon].date()),
                                      "BaseMse": float(base_sq.mean()),
                                      "ExtraMse": float(extra_sq.mean()),
                                      "ExtraCoefficient": coefficient})
                    scores.append({
                        "Phase": phase, "Factor": factor, "Target": target,
                        "Horizon": horizon, "PairedRows": len(pair),
                        "Spearman": float(pair[factor].corr(pair[outcome], method="spearman"))
                        if len(pair) >= 20 else np.nan,
                        "HighRows": len(high), "LowRows": len(low),
                        "HighMinusLow": float(high.mean() - low.mean())
                        if len(high) and len(low) else np.nan,
                        "EvaluatedFolds": sum(item["Status"] == "EVALUATED" for item in folds
                                              if item["Phase"] == phase and item["Factor"] == factor
                                              and item["Target"] == target and item["Horizon"] == horizon),
                        "PositiveFolds": improved,
                        "MseReduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                        if base_errors else np.nan,
                    })
    return (pd.DataFrame(coverage), pd.DataFrame(scores), pd.DataFrame(folds),
            pd.DataFrame(redundant, columns=["Factor", "Baseline", "Rows", "AbsSpearman"]))


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=220)
    close = pd.Series(100 + np.arange(len(days)) * 0.03
                      + np.sin(np.arange(len(days)) / 5), index=days)
    index = pd.DataFrame({"Close": close}, index=days)
    etf = pd.DataFrame({"Open": close.iloc[-80:].to_numpy(),
                        "Low": close.iloc[-80:].to_numpy() * 0.99,
                        "Close": close.iloc[-80:].to_numpy()}, index=days[-80:])
    before = _features(index, etf)
    changed = index.copy()
    changed.iloc[-10:, 0] *= 1.2
    after = _features(changed, etf)
    if not np.allclose(before.loc[days[:210], list(FACTORS)].to_numpy(),
                       after.loc[days[:210], list(FACTORS)].to_numpy(), equal_nan=True):
        raise ValueError("factor reads future closes")
    if not (before["position_120"].iloc[:119].isna().all()
            and before["position_120"].iloc[119:].notna().all()):
        raise ValueError("120-day warmup differs")
    if not 0 < _loss_concentration(np.array([-1., -2., 1., -3., 0.])) <= 1:
        raise ValueError("loss concentration differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            research_question="Can long-history index path states transfer into ETF information after listing?",
            hypothesis="Trend position, volatility compression, and concentrated selloffs each have competing future-path explanations.",
            falsification_conditions=(
                "A factor has unstable direction or no increment beyond registered controls",
                "Index-only evidence fails to transfer to post-listing ETF observations",
                "Data coverage, adjustment, source timing, or causal alignment differs",
            ),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED,
            allowed_datasets=(Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value,
                              Dataset.ETF_OHLCV.value, Dataset.TRADING_CALENDAR.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Sector price paths may reflect persistence, crowding, or exhaustion before an ETF exists",),
                information_paths=("T index close and available ETF adjusted close -> T+1 or later price observations",),
                stage_objectives=("Census six competing explanations through three long-history index factors",),
                observation_metrics=("Coverage, redundancy and high-low association",
                                     "Purged chronological ETF and index-only MSE increment and direction"),
                methodology=("Three fixed factors, two horizons, two targets, two phases, five chronological folds",
                             "Training-only ridge standardization with penalty 10"),
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
        requests = (
            ("index", Dataset.DOMESTIC_INDEX_CLOSE_DAILY, "931994.CSI", INDEX_START),
            ("etf", Dataset.ETF_OHLCV, "159326.SZ", ETF_START),
            ("calendar", Dataset.TRADING_CALENDAR, "SSE", INDEX_START),
        )
        frames: dict[str, pd.DataFrame] = {}
        identities: dict[str, dict] = {}
        for name, dataset, symbol, start in requests:
            result = context.data.fetch(DataRequest(dataset, symbol, start, END, END,
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
        if (len(frames["index"]), len(frames["etf"])) != (965, 497):
            raise ValueError("index or ETF history differs from registered coverage")
        if (identities["index"]["metadata"].get("price_scope") != "CLOSE_ONLY"
                or identities["index"]["metadata"].get("available_at")
                != "current session after market close"):
            raise ValueError("index close-only availability contract differs")
        if (identities["etf"]["metadata"].get("adjustment") != "hfq"
                or identities["etf"]["metadata"].get("availability_time_field")
                != "AvailableDate"):
            raise ValueError("ETF adjusted-price contract differs")
        available = pd.to_datetime(frames["etf"]["AvailableDate"], errors="raise")
        if not available.dt.strftime("%H:%M:%S").eq("17:00:00").all():
            raise ValueError("ETF adjusted-price availability differs")
        index, etf, calendar = (_indexed(frames[name]) for name in ("index", "etf", "calendar"))
        open_days = calendar.index[calendar["IsOpen"].eq(1)]
        if not index.index.equals(open_days) or not etf.index.equals(
            open_days[open_days >= pd.Timestamp(ETF_START)]
        ):
            raise ValueError("index or ETF days differ from SSE calendar")
        if (etf[["Open", "High", "Low", "Close", "Amount"]].le(0).any().any()
                or not np.isfinite(etf[["Open", "High", "Low", "Close", "Amount"]]
                                       .to_numpy(dtype=float)).all()):
            raise ValueError("ETF adjusted prices or amount invalid")
        matrix = _features(index, etf)
        labels = _labels(index, etf)
        coverage, scores, folds, redundant = _survey(matrix, labels)
        if len(scores) != 24 or len(folds) != 60:
            raise ValueError("fixed comparison or fold budget differs")
        artifacts = []
        for filename, frame in (
            ("factor_matrix.csv.gz", matrix.reset_index(names="Date")),
            ("future_labels.csv.gz", labels.reset_index(names="Date")),
            ("factor_coverage.csv", coverage), ("factor_scores.csv", scores),
            ("fold_scores.csv", folds), ("redundancy.csv", redundant),
        ):
            frame.to_csv(context.workspace.path(filename), index=False,
                         compression="gzip" if filename.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(
                filename, f"S011-EX06-{filename.split('.')[0]}",
            ))
        summary = {
            "decision": "SURVEY_COMPLETE", "index_sessions": len(index),
            "pre_listing_index_sessions": int((index.index < pd.Timestamp(ETF_START)).sum()),
            "etf_sessions": len(etf), "mechanism_count": 6,
            "factor_count": len(FACTORS), "comparison_count": len(scores),
            "evaluated_folds": int(folds["Status"].eq("EVALUATED").sum()),
            "insufficient_folds": int(folds["Status"].eq("INSUFFICIENT").sum()),
            "redundant_pairs": len(redundant), "source_identities": identities,
            "old_s010_and_s011_overlap_is_development_pool": True,
            "historical_source_publication_and_revision_verified": False,
            "account_replay_performed": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
            encoding="utf-8",
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "S011-EX06-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "SURVEY_COMPLETE", "mechanism_count": 6,
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "account_replay_performed": False},
            diagnostics={"evaluated_folds": summary["evaluated_folds"],
                         "redundant_pairs": summary["redundant_pairs"]},
            artifacts=tuple(artifacts),
        )
