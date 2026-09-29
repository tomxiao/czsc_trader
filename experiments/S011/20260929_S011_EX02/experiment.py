"""S011 EX02: fixed market, flow and selloff-repair factor comparison."""

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


START, END = "2024-12-26", "2026-09-28"
HORIZONS = (1, 5, 10)
WINDOWS = (("2025-07-01", "2026-01-01"),
           ("2026-01-01", "2026-07-01"),
           ("2026-07-01", "2026-10-01"))
FACTORS = (
    "market_return_5", "small_vs_large_5", "growth_vs_large_5", "market_drawdown_20",
    "known_share_change_1", "known_share_change_5", "share_acceleration",
    "share_price_feedback", "selloff_amount_1", "joint_selloff_5",
    "relative_selloff_10", "joint_selloff_1",
)
BASE = ("etf_return_1", "etf_return_5", "range_median_20",
        "amount_ratio_20", "theme_return_1")
REQUESTS = (
    ("etf", Dataset.ETF_OHLCV, "159326.SZ"),
    ("shares", Dataset.ETF_SHARE_SIZE, "159326.SZ"),
    ("csi300", Dataset.DOMESTIC_INDEX_DAILY, "000300.SH"),
    ("csi500", Dataset.DOMESTIC_INDEX_DAILY, "000905.SH"),
    ("chinext", Dataset.DOMESTIC_INDEX_DAILY, "399006.SZ"),
    ("theme", Dataset.DOMESTIC_INDEX_CLOSE_DAILY, "931994.CSI"),
)


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="raise").dt.normalize()
    if result["Date"].duplicated().any() or not result["Date"].is_monotonic_increasing:
        raise ValueError("source dates are duplicated or unordered")
    return result.set_index("Date")


def _matrix(frames: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    sources = {name: _indexed(frame) for name, frame in frames.items()}
    etf = sources["etf"]
    for name in ("csi300", "csi500", "chinext", "theme"):
        if not etf.index.equals(sources[name].index):
            raise ValueError(f"{name} sessions do not match ETF")
    if len(etf) != 426 or len(sources["shares"]) < 426:
        raise ValueError("ETF or share coverage differs from registered range")
    for name, frame in sources.items():
        if "Close" in frame and (frame["Close"].le(0).any() or not np.isfinite(frame["Close"]).all()):
            raise ValueError(f"{name} has invalid close")
    if etf[["Open", "High", "Low", "Amount"]].le(0).any().any():
        raise ValueError("ETF OHLC or amount is invalid")
    shares = sources["shares"]["TotalShare"].astype(float)
    if shares.le(0).any() or not np.isfinite(shares).all():
        raise ValueError("ETF share size is invalid")
    close = etf["Close"].astype(float)
    ret1 = close.pct_change(fill_method=None)
    ret5 = close.pct_change(5, fill_method=None)
    c300 = sources["csi300"]["Close"].astype(float)
    c500 = sources["csi500"]["Close"].astype(float)
    growth = sources["chinext"]["Close"].astype(float)
    m1, m5, m10 = (c300.pct_change(n, fill_method=None) for n in (1, 5, 10))
    result = pd.DataFrame(index=etf.index)
    result["market_return_5"] = m5
    result["small_vs_large_5"] = c500.pct_change(5, fill_method=None) - m5
    result["growth_vs_large_5"] = growth.pct_change(5, fill_method=None) - m5
    result["market_drawdown_20"] = c300 / c300.rolling(20).max() - 1
    # The source labels D shares as available on D+1 about 08:30; at T close use at most D=T-1.
    known = shares.reindex(etf.index).shift(1)
    flow1 = known.pct_change(fill_method=None)
    flow5 = known.pct_change(5, fill_method=None)
    result["known_share_change_1"] = flow1
    result["known_share_change_5"] = flow5
    result["share_acceleration"] = flow1 - flow5 / 5
    result["share_price_feedback"] = flow5 * ret5
    amount = etf["Amount"].astype(float)
    amount_ratio = amount / amount.shift(1).rolling(20).mean()
    result["selloff_amount_1"] = (-ret1).clip(lower=0) * (amount_ratio - 1).clip(lower=0)
    result["joint_selloff_5"] = (-ret5).clip(lower=0) * (-m5).clip(lower=0)
    result["relative_selloff_10"] = (
        m10 - close.pct_change(10, fill_method=None)
    ).clip(lower=0)
    result["joint_selloff_1"] = (-ret1).clip(lower=0) * (-m1).clip(lower=0)
    result["etf_return_1"] = ret1
    result["etf_return_5"] = ret5
    result["range_median_20"] = ((etf["High"] - etf["Low"]) / close).rolling(20).median()
    result["amount_ratio_20"] = amount_ratio
    result["theme_return_1"] = sources["theme"]["Close"].pct_change(fill_method=None)
    labels = pd.DataFrame(index=etf.index)
    entry = etf["Open"].shift(-1)
    for horizon in HORIZONS:
        labels[f"future_hfq_{horizon}"] = close.shift(-horizon) / entry - 1
    daily = pd.DataFrame({"etf": ret1, "csi300": m1,
                          "csi500": c500.pct_change(fill_method=None),
                          "chinext": growth.pct_change(fill_method=None)})
    return result.replace([np.inf, -np.inf], np.nan), labels, daily


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> tuple[np.ndarray, float]:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1
    x = (train_x - center) / scale
    weights = np.linalg.solve(x.T @ x + 10 * np.eye(x.shape[1]),
                              x.T @ (train_y - train_y.mean()))
    return train_y.mean() + ((test_x - center) / scale) @ weights, float(weights[-1])


def _survey(matrix: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    joined = matrix.join(labels)
    sessions = pd.DatetimeIndex(joined.index)
    coverage, scores, folds = [], [], []
    for factor in FACTORS:
        valid = matrix[factor].dropna()
        coverage.append({"Factor": factor, "FiniteRows": len(valid),
                         "UniqueValues": int(valid.nunique()),
                         "FirstFiniteDate": str(valid.index.min().date()) if len(valid) else ""})
        for horizon in HORIZONS:
            outcome = f"future_hfq_{horizon}"
            pair = joined[[factor, outcome]].dropna()
            rho = pair[factor].corr(pair[outcome], method="spearman") if len(pair) >= 20 else np.nan
            q25, q75 = pair[factor].quantile([0.25, 0.75]) if len(pair) else (np.nan, np.nan)
            spread = np.nan
            if q75 > q25:
                spread = pair.loc[pair[factor].ge(q75), outcome].mean() - pair.loc[
                    pair[factor].le(q25), outcome].mean()
            base_errors, extra_errors = [], []
            positive = 0
            for test_start, test_end in WINDOWS:
                test_positions = np.flatnonzero(
                    (sessions >= pd.Timestamp(test_start)) & (sessions < pd.Timestamp(test_end))
                )
                if not len(test_positions):
                    continue
                train_positions = np.flatnonzero(np.arange(len(sessions)) + horizon < test_positions[0])
                cols = [*BASE, factor, outcome]
                train = joined.iloc[train_positions][cols].dropna()
                test = joined.iloc[test_positions][cols].dropna()
                if len(train) < 80 or len(test) < 15:
                    folds.append({"Factor": factor, "Horizon": horizon, "TestStart": test_start,
                                  "Status": "INSUFFICIENT", "TrainRows": len(train),
                                  "TestRows": len(test)})
                    continue
                end_position = sessions.get_loc(train.index[-1]) + horizon
                if end_position >= test_positions[0]:
                    raise ValueError("training label overlaps test window")
                y_train = train[outcome].to_numpy(dtype=float)
                y_test = test[outcome].to_numpy(dtype=float)
                base, _ = _ridge(train[list(BASE)].to_numpy(dtype=float), y_train,
                                 test[list(BASE)].to_numpy(dtype=float))
                extra, coefficient = _ridge(train[[*BASE, factor]].to_numpy(dtype=float), y_train,
                                            test[[*BASE, factor]].to_numpy(dtype=float))
                base_sq = np.square(y_test - base)
                extra_sq = np.square(y_test - extra)
                base_errors.extend(base_sq.tolist())
                extra_errors.extend(extra_sq.tolist())
                positive += int(extra_sq.mean() < base_sq.mean())
                folds.append({"Factor": factor, "Horizon": horizon, "TestStart": test_start,
                              "Status": "EVALUATED", "TrainRows": len(train),
                              "TestRows": len(test), "TrainLabelEnd": str(sessions[end_position].date()),
                              "BaseMse": float(base_sq.mean()), "ExtraMse": float(extra_sq.mean()),
                              "ExtraCoefficient": coefficient})
            scores.append({"Factor": factor, "Horizon": horizon, "PairedRows": len(pair),
                           "Spearman": float(rho) if np.isfinite(rho) else np.nan,
                           "HighMinusLow": float(spread) if np.isfinite(spread) else np.nan,
                           "PositiveFolds": positive,
                           "EvaluatedFolds": sum(row["Status"] == "EVALUATED" for row in folds
                                                 if row["Factor"] == factor and row["Horizon"] == horizon),
                           "MseReduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                           if base_errors else np.nan})
    return pd.DataFrame(coverage), pd.DataFrame(scores), pd.DataFrame(folds)


def _attribution(daily: pd.DataFrame) -> list[dict[str, float | str | int]]:
    result = []
    for start, end in (("2024-12-26", "2025-07-01"), *WINDOWS):
        subset = daily.loc[(daily.index >= start) & (daily.index < end)].dropna()
        x = np.column_stack([np.ones(len(subset)), subset[["csi300", "csi500", "chinext"]]])
        y = subset["etf"].to_numpy(dtype=float)
        weight = np.linalg.lstsq(x, y, rcond=None)[0]
        total = np.square(y - y.mean()).sum()
        r2 = 1 - np.square(y - x @ weight).sum() / total if total > 0 else np.nan
        result.append({"Start": start, "EndExclusive": end, "Rows": len(subset),
                       "ContemporaneousR2": float(r2)})
    return result


def _precheck() -> None:
    dates = pd.date_range("2026-01-05", periods=30, freq="D")
    shares = pd.Series(np.arange(30, dtype=float) + 100, index=dates)
    known = shares.shift(1)
    if known.iloc[1] != shares.iloc[0] or not pd.isna(known.iloc[0]):
        raise ValueError("share availability lag failed")
    train = np.array([[1.0], [2.0], [3.0]])
    predicted, coefficient = _ridge(train, np.array([1.0, 2.0, 3.0]), train)
    if not np.isfinite(predicted).all() or coefficient <= 0:
        raise ValueError("ridge implementation failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id="20260929_S011_EX02", strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            research_question="Do market/style, known ETF shares, or selloff repair explain later ETF returns?",
            hypothesis="Market beta, reflexive ETF flows, and forced-sale repair make distinct next-session predictions.",
            falsification_conditions=(
                "Market movement does not explain ETF variation or its state adds no future information",
                "Known share changes merely follow prices or add no future information",
                "Selloff states fail to recover in the later executable window",
                "Data, adjustment or chronological contract fails",
            ),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092902,
            allowed_datasets=tuple(sorted({item[1].value for item in REQUESTS})),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("ETF gains may reflect market repricing, flows or repair after forced sales",),
                information_paths=("T close indices and ETF bars; T-1 ETF shares -> T+1 order",),
                stage_objectives=("Compare three mechanisms on aligned future ETF returns",),
                observation_metrics=("Coverage, rank relationship, chronological MSE increment",
                                     "Contemporaneous market explanation and adverse folds"),
                methodology=("12 fixed factors, three future horizons", "Three purged chronological folds",
                             "Training-only ridge standardization; alpha 10"),
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
        env_file = str(Path(__file__).resolve().parents[3] / ".env")
        frames, identities = {}, {}
        for name, dataset, symbol in REQUESTS:
            result = context.data.fetch(DataRequest(
                dataset, symbol, START, END, None, "daily", {"env_file": env_file},
            ))
            if not result.ready or result.identity is None:
                error = result.error
                raise ValueError(f"{name} DFLS unavailable: {result.status.value}"
                                 + ("" if error is None else f" {error.code}: {error.message}"))
            if name == "etf" and result.identity.metadata.get("adjustment") != "hfq":
                raise ValueError("ETF adjustment is not hfq")
            if name == "shares" and result.identity.metadata.get("available_at") != "T+1 08:30 Asia/Shanghai":
                raise ValueError("ETF share publication contract differs")
            frames[name] = result.dataframe.copy()
            identities[name] = {"dataset": dataset.value, "symbol": symbol,
                                "content_sha256": result.identity.content_sha256,
                                "rows": len(result.dataframe),
                                "metadata": dict(result.identity.metadata)}
        matrix, labels, daily = _matrix(frames)
        if tuple(matrix[list(FACTORS)].columns) != FACTORS:
            raise ValueError("factor census differs")
        coverage, scores, folds = _survey(matrix, labels)
        attribution = _attribution(daily)
        if len(scores) != 36 or len(folds) != 108:
            raise ValueError("score or fold count differs")
        artifacts = []
        for filename, frame in (("factor_matrix.csv.gz", matrix.reset_index(names="Date")),
                                ("future_labels.csv.gz", labels.reset_index(names="Date")),
                                ("factor_coverage.csv", coverage),
                                ("factor_scores.csv", scores), ("fold_scores.csv", folds)):
            frame.to_csv(context.workspace.path(filename), index=False,
                         compression="gzip" if filename.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(filename, f"S011-EX02-{filename.split('.')[0]}"))
        context.workspace.path("attribution.json").write_text(
            json.dumps(attribution, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("attribution.json", "S011-EX02-attribution"))
        summary = {"decision": "SURVEY_COMPLETE", "sessions": len(matrix),
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "evaluated_folds": int(folds["Status"].eq("EVALUATED").sum()),
                   "insufficient_folds": int(folds["Status"].eq("INSUFFICIENT").sum()),
                   "source_identities": identities, "mechanism_4_status": "PUBLICATION_TIME_UNVERIFIED",
                   "old_evidence_overlap_is_development_pool": True,
                   "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S011-EX02-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "SURVEY_COMPLETE", "factor_count": len(FACTORS),
                   "comparison_count": len(scores), "account_replay_performed": False},
            diagnostics={"evaluated_folds": summary["evaluated_folds"]}, artifacts=tuple(artifacts),
        )
