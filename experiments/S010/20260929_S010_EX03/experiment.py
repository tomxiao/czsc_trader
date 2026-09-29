"""S010 EX03: intraday distribution and the observed range-risk mechanism."""

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


EXPERIMENT_ID = "20260929_S010_EX03"
START, CUTOFF = "2024-09-09", "2026-09-28"
RECEIPTS = {
    "20260929_S010_EX01": "df0229ce9fa657c290d9cec10b6d79def2d4db7e6f629c2d3c2a0df3f9f09b77",
    "20260929_S010_EX02": "37487d63f23277b86ab092f0dcc9e2e9f7f61db17fd03bf5ccb627e6af2ff981",
}
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TEST_ENDS = ("2026-01-01", "2026-07-01", "2026-10-01")
HORIZONS = (1, 5, 10)
BASE_0 = ("etf_return_5", "etf_volatility_20")
BASE_1 = (*BASE_0, "tsfresh_range__median")
SEED = 2026092903


def _intraday_features(minute: pd.DataFrame, daily: pd.DataFrame):
    bars = minute.copy()
    day = daily.copy()
    bars["Date"] = pd.to_datetime(bars["Date"], errors="raise")
    day["Date"] = pd.to_datetime(day["Date"], errors="raise").dt.normalize()
    if bars["Date"].isna().any() or day["Date"].isna().any():
        raise ValueError("missing intraday or daily timestamp")
    if bars["Date"].duplicated().any() or day["Date"].duplicated().any():
        raise ValueError("duplicate intraday bar or daily session")
    day = day.sort_values("Date").set_index("Date")
    rows = []
    opens = []
    for session, group in bars.groupby(bars["Date"].dt.normalize(), sort=True):
        group = group.sort_values("Date")
        if len(group) != 8 or session not in day.index:
            raise ValueError("intraday session has missing bars or daily reference")
        item = day.loc[session]
        close = group["Close"].to_numpy(dtype=float)
        high = group["High"].to_numpy(dtype=float)
        low = group["Low"].to_numpy(dtype=float)
        volume = group["Volume"].to_numpy(dtype=float)
        amount = group["Amount"].to_numpy(dtype=float)
        if (
            not np.isfinite(np.r_[close, high, low, volume, amount]).all()
            or (close <= 0).any()
            or (volume < 0).any()
            or (amount < 0).any()
        ):
            raise ValueError("invalid intraday bar")
        for field, observed in (("High", high.max()), ("Low", low.min()),
                                ("Close", close[-1]), ("Volume", volume.sum()),
                                ("Amount", amount.sum())):
            if not np.isclose(observed, float(item[field]), atol=1e-5, rtol=1e-6):
                raise ValueError(f"intraday {field} differs from daily reference")
        first_open = float(group["Open"].iloc[0])
        daily_open = float(item["Open"])
        if not np.isclose(first_open, daily_open, atol=1e-5, rtol=1e-6):
            opens.append({"Date": session, "daily_open": daily_open,
                          "first_30m_open": first_open})
        total_range = high.max() - low.min()
        total_volume = volume.sum()
        rows.append({
            "Date": session,
            "intra_first_to_close": close[-1] / close[0] - 1,
            "intra_afternoon_return": close[-1] / close[3] - 1,
            "intra_last_hour_return": close[-1] / close[5] - 1,
            "intra_afternoon_volume_share": volume[4:].sum() / total_volume if total_volume else np.nan,
            "intra_last_hour_volume_share": volume[6:].sum() / total_volume if total_volume else np.nan,
            "intra_max_bar_volume_share": volume.max() / total_volume if total_volume else np.nan,
            "intra_realized_vol": float(np.sqrt(np.square(np.diff(np.log(close))).sum())),
            "intra_last_hour_range_share": (high[6:].max() - low[6:].min()) / total_range
            if total_range else np.nan,
            "intra_high_bar": int(np.argmax(high) + 1),
            "intra_low_bar": int(np.argmin(low) + 1),
            "intra_close_location": (close[-1] - low.min()) / total_range if total_range else np.nan,
        })
    result = pd.DataFrame(rows).set_index("Date").sort_index()
    if not result.index.equals(day.index):
        raise ValueError("intraday and daily session calendars differ")
    result["intra_afternoon_volume_share_5"] = result["intra_afternoon_volume_share"].rolling(5).mean()
    result["intra_afternoon_volume_share_20"] = result["intra_afternoon_volume_share"].rolling(20).mean()
    return result, pd.DataFrame(opens, columns=["Date", "daily_open", "first_30m_open"])


def _ridge(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    intercept = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - intercept))
    return intercept + future @ weights


def _folds(index: pd.DatetimeIndex, horizon: int):
    for start, end in zip(TEST_STARTS, TEST_ENDS):
        test = np.flatnonzero((index >= pd.Timestamp(start)) & (index < pd.Timestamp(end)))
        if not len(test):
            continue
        train = np.flatnonzero(np.arange(len(index)) + 1 + horizon < test[0])
        yield start, train, test


def _scores(features: pd.DataFrame, inherited: pd.DataFrame, labels: pd.DataFrame):
    joined = inherited[[*BASE_1]].join(features).join(labels).replace([np.inf, -np.inf], np.nan)
    index = pd.DatetimeIndex(joined.index)
    details = []
    totals = []
    for factor in features.columns:
        for horizon in HORIZONS:
            label = f"open_return_{horizon}"
            for baseline_name, baseline in (("PRICE", BASE_0), ("PRICE_RANGE", BASE_1)):
                base_errors = []
                extra_errors = []
                positive_folds = 0
                for start, train_positions, test_positions in _folds(index, horizon):
                    columns = [*baseline, factor, label]
                    train = joined.iloc[train_positions][columns].dropna()
                    test = joined.iloc[test_positions][columns].dropna()
                    if len(train) < 80 or len(test) < 15:
                        details.append({"factor": factor, "horizon": horizon, "baseline": baseline_name,
                                        "test_start": start, "status": "INSUFFICIENT", "train_rows": len(train),
                                        "test_rows": len(test), "base_mse": np.nan, "extra_mse": np.nan})
                        continue
                    label_end = index[index.get_loc(train.index[-1]) + 1 + horizon]
                    if label_end >= test.index[0]:
                        raise ValueError("training label crosses chronological test boundary")
                    y_train = train[label].to_numpy(dtype=float)
                    y_test = test[label].to_numpy(dtype=float)
                    base = _ridge(train[list(baseline)].to_numpy(dtype=float), y_train,
                                  test[list(baseline)].to_numpy(dtype=float))
                    expanded = [*baseline, factor]
                    extra = _ridge(train[expanded].to_numpy(dtype=float), y_train,
                                   test[expanded].to_numpy(dtype=float))
                    b = np.square(y_test - base)
                    e = np.square(y_test - extra)
                    base_errors.extend(b)
                    extra_errors.extend(e)
                    positive_folds += e.mean() < b.mean()
                    details.append({"factor": factor, "horizon": horizon, "baseline": baseline_name,
                                    "test_start": start, "status": "EVALUATED", "train_rows": len(train),
                                    "test_rows": len(test), "train_label_end": label_end.date().isoformat(),
                                    "base_mse": float(b.mean()), "extra_mse": float(e.mean())})
                totals.append({"factor": factor, "horizon": horizon, "baseline": baseline_name,
                               "oos_rows": len(base_errors), "positive_folds": positive_folds,
                               "mse_reduction": float(1 - np.mean(extra_errors) / np.mean(base_errors))
                               if base_errors else np.nan})
    return pd.DataFrame(totals), pd.DataFrame(details)


def _range_states(inherited: pd.DataFrame, labels: pd.DataFrame):
    measure = inherited["tsfresh_range__median"]
    outcome = labels["open_return_5"]
    index = pd.DatetimeIndex(inherited.index)
    rows = []
    for start, train_positions, test_positions in _folds(index, 5):
        history = measure.iloc[train_positions].dropna()
        if len(history) < 80:
            continue
        q25, q75 = history.quantile([0.25, 0.75])
        for position in test_positions:
            value = measure.iloc[position]
            future = outcome.iloc[position]
            if not np.isfinite(value) or not np.isfinite(future):
                continue
            state = "HIGH" if value >= q75 else "LOW" if value <= q25 else "MID"
            rows.append({"Date": index[position], "test_start": start, "state": state,
                         "range_median": value, "training_q25": q25, "training_q75": q75,
                         "future_5d_open_return": future,
                         "roundtrip_20bp_proxy": future - 0.002})
    result = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    if result.empty:
        raise ValueError("no chronological range state observations")
    rng = np.random.default_rng(SEED)
    length = len(result)
    width = 10
    starts = np.arange(length - width + 1)
    contrasts = []
    for _ in range(2000):
        draw = rng.choice(starts, size=int(np.ceil(length / width)), replace=True)
        positions = (draw[:, None] + np.arange(width)).reshape(-1)[:length]
        sample = result.iloc[positions]
        high = sample.loc[sample["state"].eq("HIGH"), "future_5d_open_return"]
        low = sample.loc[sample["state"].eq("LOW"), "future_5d_open_return"]
        if not high.empty and not low.empty:
            contrasts.append(float(high.mean() - low.mean()))
    ci = list(np.quantile(contrasts, [0.025, 0.975])) if contrasts else [None, None]
    return result, [None if value is None else float(value) for value in ci]


def _precheck() -> None:
    days = pd.bdate_range("2024-01-01", periods=800)
    daily = pd.DataFrame({"Date": days, "Open": 1.0, "High": 1.02, "Low": 0.98,
                          "Close": 1.0, "Volume": 800.0, "Amount": 800.0})
    minute = pd.DataFrame({"Date": [day + pd.Timedelta(hours=10) + pd.Timedelta(minutes=30 * i)
                                   for day in days for i in range(8)],
                           "Open": 1.0, "High": 1.02, "Low": 0.98, "Close": 1.0,
                           "Volume": 100.0, "Amount": 100.0})
    features, opens = _intraday_features(minute, daily)
    if len(features) != 800 or len(features.columns) != 13 or not opens.empty:
        raise ValueError("synthetic intraday feature boundary failed")
    first = next(_folds(pd.DatetimeIndex(days), 5))
    if days[first[1][-1] + 6] >= days[first[2][0]]:
        raise ValueError("synthetic label purge failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Do causal intraday price/volume shapes add information beyond daily price and range state, and does high range mark a later loss?",
            hypothesis="Intraday concentration or closing pressure may distinguish informative volatility from transient range expansion.",
            falsification_conditions=("Intraday bars fail daily reconciliation", "Intraday factors add no chronological information", "High range does not isolate adverse future-open outcomes"),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED, allowed_datasets=(Dataset.ETF_OHLCV.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Trading concentration and volatility can reflect distinct information and liquidity motives",),
                information_paths=("T intraday distribution and prior range -> subsequent executable-session prices",),
                stage_objectives=("Reconcile 30m data", "Audit range-state loss mechanism", "Measure incremental intraday information"),
                observation_metrics=("coverage", "per-fold and combined MSE", "range-state forward return", "block interval"),
                methodology=("Thirteen fixed intraday features", "Purged three-segment ridge comparisons", "Training-only range quartiles", "Ten-session moving-block interval"),
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
        prior = root.parent / "20260929_S010_EX01" / "artifacts"
        inherited = pd.read_csv(prior / "factor_matrix.csv.gz", parse_dates=["Date"]).set_index("Date")
        labels = pd.read_csv(prior / "future_open_labels.csv.gz", parse_dates=["Date"]).set_index("Date")
        if not inherited.index.equals(labels.index) or inherited.index.duplicated().any():
            raise ValueError("predecessor factor and label dates differ")
        data = {}
        lineage = {}
        for name, frequency in (("minute", "30m"), ("daily", "daily")):
            result = context.data.fetch(DataRequest(
                Dataset.ETF_OHLCV, "159326.SZ", START, CUTOFF, CUTOFF, frequency,
                {"env_file": str(root.parents[2] / ".env")},
            ))
            if not result.ready or result.identity is None:
                error = result.error
                raise ValueError(f"{frequency} DFLS unavailable: {result.status.value}"
                                 + ("" if error is None else f" {error.code}: {error.message}"))
            data[name] = result.dataframe
            lineage[name] = {"dataset": result.identity.dataset, "source": result.identity.source,
                             "rows": len(result.dataframe), "start": result.identity.data_start,
                             "cutoff": result.identity.data_cutoff,
                             "sha256": result.identity.content_sha256,
                             "available_at": result.identity.temporal_contract.available_at}
        features, opens = _intraday_features(data["minute"], data["daily"])
        if not features.index.equals(inherited.index):
            raise ValueError("intraday and predecessor trading dates differ")
        scores, folds = _scores(features, inherited, labels)
        states, interval = _range_states(inherited, labels)
        quality = pd.DataFrame({"factor": features.columns,
                                "finite_rows": features.notna().sum().to_numpy(),
                                "missing_rows": features.isna().sum().to_numpy(),
                                "unique_values": features.nunique().to_numpy()})
        correlation = features.corr(min_periods=150)
        near = [{"factor_a": a, "factor_b": b, "pearson": float(correlation.loc[a, b])}
                for i, a in enumerate(features.columns) for b in features.columns[i + 1:]
                if np.isfinite(correlation.loc[a, b]) and abs(correlation.loc[a, b]) >= 0.995]
        outputs = (
            ("intraday_features.csv.gz", features.reset_index()),
            ("intraday_quality.csv", quality),
            ("intraday_scores.csv", scores),
            ("intraday_fold_scores.csv", folds),
            ("range_states.csv", states),
            ("near_duplicates.csv", pd.DataFrame(near, columns=["factor_a", "factor_b", "pearson"])),
            ("open_discrepancies.csv", opens),
        )
        artifacts = []
        for name, frame in outputs:
            frame.to_csv(context.workspace.path(name), index=False, lineterminator="\n",
                         compression="gzip" if name.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(name, f"S010-EX03-{name.split('.')[0]}"))
        high = states.loc[states["state"].eq("HIGH"), "future_5d_open_return"]
        low = states.loc[states["state"].eq("LOW"), "future_5d_open_return"]
        summary = {"decision": "INTRADAY_REVIEW_COMPLETE", "input_identity": lineage,
                   "intraday_factor_count": features.shape[1], "comparison_count": len(scores),
                   "open_discrepancy_days": len(opens), "near_duplicate_pairs": len(near),
                   "range_state_days": len(states), "range_high_days": len(high), "range_low_days": len(low),
                   "range_high_mean": float(high.mean()) if len(high) else None,
                   "range_low_mean": float(low.mean()) if len(low) else None,
                   "range_high_20bp_proxy_mean": float(high.mean() - 0.002) if len(high) else None,
                   "range_high_minus_low_ci95": interval,
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX03-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": summary["decision"], "intraday_factor_count": features.shape[1],
                   "open_discrepancy_days": len(opens), "sealed_date_rows_read": 0},
            diagnostics={"range_high_days": len(high), "range_low_days": len(low)},
            artifacts=tuple(artifacts),
        )
