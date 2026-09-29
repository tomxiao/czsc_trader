"""S011 EX03: lagged constituent-breadth survey with explicit publication caveat."""

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


EXPERIMENT_ID = "20260929_S011_EX03"
START, END = "2024-12-26", "2026-09-28"
WEIGHT_START, STOCK_START = "2024-09-01", "2024-09-09"
LAG_DAYS = 35
HORIZONS = (1, 5, 10)
WINDOWS = (("2025-07-01", "2026-01-01"),
           ("2026-01-01", "2026-07-01"),
           ("2026-07-01", "2026-10-01"))
FACTORS = ("breadth_equal_1", "breadth_equal_5", "breadth_weighted_1",
           "breadth_weighted_5", "broadening_5", "leader_minus_rest_5")
BASE = ("etf_return_1", "etf_return_5", "theme_return_1",
        "range_median_20", "amount_ratio_20")


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    result = frame.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="raise").dt.normalize()
    if result["Date"].duplicated().any() or not result["Date"].is_monotonic_increasing:
        raise ValueError("source dates are duplicated or unordered")
    return result.set_index("Date")


def _basket_features(weights: pd.DataFrame, closes: pd.DataFrame,
                     sessions: pd.DatetimeIndex) -> tuple[pd.DataFrame, pd.DataFrame]:
    weight = weights.copy()
    weight["Date"] = pd.to_datetime(weight["Date"], errors="raise").dt.normalize()
    if weight.duplicated(["Date", "ConstituentSymbol"]).any():
        raise ValueError("weight snapshot has duplicate member")
    if weight["Weight"].le(0).any() or not np.isfinite(weight["Weight"]).all():
        raise ValueError("weight snapshot has invalid weight")
    totals = weight.groupby("Date")["Weight"].sum()
    if totals.lt(99.5).any() or totals.gt(100.5).any():
        raise ValueError("weight snapshot does not sum to approximately 100%")
    stock = closes.copy()
    stock["Date"] = pd.to_datetime(stock["Date"], errors="raise").dt.normalize()
    if stock.duplicated(["Date", "Symbol"]).any():
        raise ValueError("stock close has duplicate symbol-date")
    if stock["Close"].le(0).any() or not np.isfinite(stock["Close"]).all():
        raise ValueError("stock close is invalid")
    price = stock.pivot(index="Date", columns="Symbol", values="Close").reindex(sessions)
    returns = {n: price.pct_change(n, fill_method=None) for n in (1, 5)}
    snapshots = {day: part.set_index("ConstituentSymbol")["Weight"].astype(float)
                 for day, part in weight.groupby("Date")}
    snapshot_dates = pd.DatetimeIndex(sorted(snapshots))
    values, quality = [], []
    for day in sessions:
        position = snapshot_dates.searchsorted(day - pd.Timedelta(days=LAG_DAYS), side="right") - 1
        if position < 0:
            values.append({"Date": day})
            quality.append({"Date": day, "SnapshotDate": "", "AgeDays": np.nan,
                            "Coverage1": 0.0, "Coverage5": 0.0})
            continue
        snapshot_day = snapshot_dates[position]
        selected = snapshots[snapshot_day]
        row: dict[str, object] = {"Date": day}
        covered = {}
        for n in (1, 5):
            period = returns[n].loc[day].reindex(selected.index)
            valid = period.notna()
            covered[n] = float(selected[valid].sum() / selected.sum())
            if covered[n] < 0.95:
                continue
            usable = period[valid]
            active = selected[valid]
            row[f"breadth_equal_{n}"] = float(usable.gt(0).mean())
            row[f"breadth_weighted_{n}"] = float(active[usable.gt(0)].sum() / active.sum())
            if n == 5:
                top = selected.nlargest(10).index
                leading = usable.index.isin(top)
                if (active[leading].sum() / selected.reindex(top).sum() >= 0.95
                        and active[~leading].sum() / selected.drop(top).sum() >= 0.95):
                    row["leader_minus_rest_5"] = float(
                        np.average(usable[leading], weights=active[leading])
                        - np.average(usable[~leading], weights=active[~leading])
                    )
        values.append(row)
        quality.append({"Date": day, "SnapshotDate": snapshot_day.date().isoformat(),
                        "AgeDays": (day - snapshot_day).days,
                        "Coverage1": covered[1], "Coverage5": covered[5]})
    result = pd.DataFrame(values).set_index("Date").reindex(sessions)
    for name in FACTORS:
        if name not in result:
            result[name] = np.nan
    result["broadening_5"] = result["breadth_equal_1"] - result["breadth_equal_1"].shift(5)
    return result[list(FACTORS)], pd.DataFrame(quality)


def _matrix(etf_frame: pd.DataFrame, theme_frame: pd.DataFrame,
            factors: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    etf = _indexed(etf_frame)
    theme = _indexed(theme_frame)
    if len(etf) != 426 or not etf.index.equals(theme.index) or not etf.index.equals(factors.index):
        raise ValueError("ETF, theme and factor sessions differ")
    if etf[["Open", "High", "Low", "Close", "Amount"]].le(0).any().any():
        raise ValueError("ETF OHLC or amount is invalid")
    close = etf["Close"]
    matrix = factors.copy()
    matrix["etf_return_1"] = close.pct_change(fill_method=None)
    matrix["etf_return_5"] = close.pct_change(5, fill_method=None)
    matrix["theme_return_1"] = theme["Close"].pct_change(fill_method=None)
    matrix["range_median_20"] = ((etf["High"] - etf["Low"]) / close).rolling(20).median()
    matrix["amount_ratio_20"] = etf["Amount"] / etf["Amount"].shift(1).rolling(20).mean()
    labels = pd.DataFrame(index=etf.index)
    entry = etf["Open"].shift(-1)
    for horizon in HORIZONS:
        labels[f"future_hfq_{horizon}"] = close.shift(-horizon) / entry - 1
    return matrix.replace([np.inf, -np.inf], np.nan), labels


def _ridge(train_x: np.ndarray, train_y: np.ndarray,
           test_x: np.ndarray) -> tuple[np.ndarray, float]:
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


def _precheck() -> None:
    sessions = pd.date_range("2025-01-01", periods=2, freq="D")
    weights = pd.DataFrame({"Date": ["2024-11-27"] * 2,
                            "ConstituentSymbol": ["A", "B"], "Weight": [50.0, 50.0]})
    closes = pd.DataFrame({"Date": ["2025-01-01", "2025-01-01", "2025-01-02", "2025-01-02"],
                           "Symbol": ["A", "B", "A", "B"], "Close": [100.0, 100.0, 101.0, 99.0]})
    factors, quality = _basket_features(weights, closes, sessions)
    if not pd.isna(factors.iloc[0]["breadth_equal_1"]) or factors.iloc[1]["breadth_equal_1"] != 0.5:
        raise ValueError("synthetic breadth differs")
    if quality.iloc[1]["AgeDays"] != LAG_DAYS + 1:
        raise ValueError("snapshot delay differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S011",
            mode=ExperimentMode.FORMAL,
            research_question="Does constituent participation or concentrated leadership add future ETF information?",
            hypothesis="Broader participation predicts continuation beyond ETF and theme daily controls.",
            falsification_conditions=(
                "Breadth adds no later ETF information or only repeats ETF and theme returns",
                "Leadership is stronger than diffusion or period directions conflict",
                "Stock coverage or 35-day snapshot chronology fails",
            ),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=2026092903,
            allowed_datasets=(Dataset.ETF_OHLCV.value, Dataset.DOMESTIC_INDEX_CLOSE_DAILY.value,
                              Dataset.INDEX_CONSTITUENT_WEIGHT.value, Dataset.STOCK_OHLCV.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("An index rise may broaden across members or remain leader-led",),
                information_paths=("At-least-35-day-old weight snapshot and T stock closes -> T+1 order",),
                stage_objectives=("Audit lagged basket coverage", "Compare breadth and leadership"),
                observation_metrics=("Coverage and lag", "Rank association and quartile spread",
                                     "Purged chronological MSE increment and coefficient"),
                methodology=("Six fixed factors, three future horizons", "Three chronological folds",
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
        requests = (("etf", Dataset.ETF_OHLCV, "159326.SZ", START, "daily"),
                    ("theme", Dataset.DOMESTIC_INDEX_CLOSE_DAILY, "931994.CSI", START, "daily"),
                    ("weights", Dataset.INDEX_CONSTITUENT_WEIGHT, "931994.CSI", WEIGHT_START, "snapshot"))
        frames, identities = {}, {}
        for name, dataset, symbol, first, frequency in requests:
            result = context.data.fetch(DataRequest(
                dataset, symbol, first, END, None, frequency, {"env_file": env_file},
            ))
            if not result.ready or result.identity is None:
                raise ValueError(f"{name} DFLS unavailable: {result.status.value}")
            if name == "etf" and result.identity.metadata.get("adjustment") != "hfq":
                raise ValueError("ETF adjustment is not hfq")
            frames[name] = result.dataframe.copy()
            identities[name] = {"dataset": dataset.value, "symbol": symbol,
                                "content_sha256": result.identity.content_sha256,
                                "rows": len(result.dataframe),
                                "metadata": dict(result.identity.metadata)}
        if len(frames["etf"]) != 426:
            raise ValueError("ETF source does not cover 426 sessions")
        symbols = sorted(frames["weights"]["ConstituentSymbol"].unique())
        stock_rows, stock_identities = [], []
        for position, symbol in enumerate(symbols, start=1):
            result = context.data.fetch(DataRequest(
                Dataset.STOCK_OHLCV, symbol, STOCK_START, END, None, "daily",
                {"env_file": env_file},
            ))
            if not result.ready or result.identity is None:
                raise ValueError(f"stock DFLS unavailable for {symbol}: {result.status.value}")
            if result.identity.metadata.get("adjustment") != "hfq":
                raise ValueError(f"stock adjustment is not hfq: {symbol}")
            stock_rows.append(result.dataframe[["Date", "Close"]].assign(Symbol=symbol))
            stock_identities.append({"symbol": symbol, "rows": len(result.dataframe),
                                     "content_sha256": result.identity.content_sha256})
            if position % 20 == 0:
                print(f"S011 EX03 stock sources inspected: {position}/{len(symbols)}", flush=True)
        sessions = pd.DatetimeIndex(pd.to_datetime(frames["etf"]["Date"]))
        features, quality = _basket_features(
            frames["weights"], pd.concat(stock_rows, ignore_index=True), sessions,
        )
        matrix, labels = _matrix(frames["etf"], frames["theme"], features)
        coverage, scores, folds = _survey(matrix, labels)
        if len(scores) != 18 or len(folds) != 54:
            raise ValueError("score or fold count differs")
        artifacts = []
        for filename, frame in (("factor_matrix.csv.gz", matrix.reset_index(names="Date")),
                                ("future_labels.csv.gz", labels.reset_index(names="Date")),
                                ("daily_quality.csv", quality),
                                ("stock_identities.csv", pd.DataFrame(stock_identities)),
                                ("factor_coverage.csv", coverage),
                                ("factor_scores.csv", scores), ("fold_scores.csv", folds)):
            frame.to_csv(context.workspace.path(filename), index=False,
                         compression="gzip" if filename.endswith(".gz") else None,
                         lineterminator="\n")
            artifacts.append(context.workspace.register_artifact(filename, f"S011-EX03-{filename.split('.')[0]}"))
        summary = {"decision": "PROVISIONAL_SURVEY_COMPLETE", "sessions": len(matrix),
                   "snapshot_count": frames["weights"]["Date"].nunique(),
                   "union_stock_count": len(symbols), "stock_ready_count": len(stock_identities),
                   "lag_calendar_days": LAG_DAYS,
                   "historical_snapshot_publication_verified": False,
                   "factor_count": len(FACTORS), "comparison_count": len(scores),
                   "evaluated_folds": int(folds["Status"].eq("EVALUATED").sum()),
                   "insufficient_folds": int(folds["Status"].eq("INSUFFICIENT").sum()),
                   "source_identities": identities,
                   "old_s010_overlap_is_development_pool": True,
                   "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False, default=str) + "\n",
            encoding="utf-8",
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "S011-EX03-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "factor_count": len(FACTORS),
                   "account_replay_performed": False},
            diagnostics={"evaluated_folds": summary["evaluated_folds"],
                         "stock_ready_count": len(stock_identities)}, artifacts=tuple(artifacts),
        )
