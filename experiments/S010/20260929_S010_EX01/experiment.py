"""S010 EX01: source-bound, broad first-pass ETF factor survey."""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import numpy as np
import pandas as pd
import tsfresh
from dataflows import DataRequest, Dataset
from research_experiment import (
    ExperimentCapabilities,
    ExperimentCapability,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)
from tsfresh import extract_features


EXPERIMENT_ID = "20260929_S010_EX01"
START = "2024-09-09"
CUTOFF = "2026-09-28"
SEED = 2026092901
HORIZONS = (1, 5, 10)
TEST_STARTS = ("2025-07-01", "2026-01-01", "2026-07-01")
TSFRESH_WINDOW = 20
TSFRESH_PARAMETERS = {
    "mean": None,
    "median": None,
    "standard_deviation": None,
    "skewness": None,
    "kurtosis": None,
    "maximum": None,
    "minimum": None,
    "mean_abs_change": None,
    "abs_energy": None,
    "autocorrelation": [{"lag": 1}],
    "linear_trend": [{"attr": "slope"}],
    "quantile": [{"q": 0.1}, {"q": 0.9}],
}
INPUTS = (
    ("etf", Dataset.ETF_OHLCV, "159326.SZ"),
    ("execution", Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ"),
    ("shares", Dataset.ETF_SHARE_SIZE, "159326.SZ"),
    ("csi300", Dataset.DOMESTIC_INDEX_DAILY, "000300.SH"),
    ("csi500", Dataset.DOMESTIC_INDEX_DAILY, "000905.SH"),
)


def _checked_frame(frame: pd.DataFrame, *, price: bool) -> pd.DataFrame:
    result = frame.copy()
    result["Date"] = pd.to_datetime(result["Date"], errors="raise").dt.normalize()
    result = result.sort_values("Date").reset_index(drop=True)
    if result.empty or result["Date"].isna().any() or result["Date"].duplicated().any():
        raise ValueError("empty, missing or duplicate input dates")
    if price:
        for column in ("Open", "High", "Low", "Close"):
            if column not in result or not np.isfinite(result[column]).all():
                raise ValueError(f"invalid {column} input")
            if result[column].le(0).any():
                raise ValueError(f"nonpositive {column} input")
        if result["High"].lt(result[["Open", "Close", "Low"]].max(axis=1)).any():
            raise ValueError("daily high below another price")
        if result["Low"].gt(result[["Open", "Close", "High"]].min(axis=1)).any():
            raise ValueError("daily low above another price")
    return result


def _manual_features(
    etf: pd.DataFrame, shares: pd.DataFrame, csi300: pd.DataFrame, csi500: pd.DataFrame
) -> pd.DataFrame:
    dates = pd.DatetimeIndex(etf["Date"])
    close = pd.Series(etf["Close"].to_numpy(dtype=float), index=dates)
    opened = pd.Series(etf["Open"].to_numpy(dtype=float), index=dates)
    high = pd.Series(etf["High"].to_numpy(dtype=float), index=dates)
    low = pd.Series(etf["Low"].to_numpy(dtype=float), index=dates)
    volume = pd.Series(etf["Volume"].to_numpy(dtype=float), index=dates)
    amount = pd.Series(etf["Amount"].to_numpy(dtype=float), index=dates)
    if (volume < 0).any() or (amount < 0).any():
        raise ValueError("negative ETF volume or amount")
    one = close.pct_change(fill_method=None)
    range_day = (high - low) / close
    result = pd.DataFrame(index=dates)
    for window in (1, 3, 5, 10, 20, 40):
        result[f"etf_return_{window}"] = close.pct_change(window, fill_method=None)
    for window in (5, 10, 20):
        result[f"etf_volatility_{window}"] = one.rolling(window).std()
        result[f"etf_range_{window}"] = range_day.rolling(window).mean()
    for window in (5, 10, 20, 40):
        result[f"etf_ma_distance_{window}"] = close / close.rolling(window).mean() - 1
    for window in (10, 20, 40):
        result[f"etf_drawdown_{window}"] = close / close.rolling(window).max() - 1
        result[f"etf_breakout_{window}"] = close / high.rolling(window).max() - 1
    result["etf_gap"] = opened / close.shift(1) - 1
    result["etf_body"] = close / opened - 1
    result["etf_close_location"] = (close - low) / (high - low).replace(0, np.nan)
    result["etf_amihud"] = one.abs() / amount.replace(0, np.nan)
    for name, values in (("volume", volume), ("amount", amount)):
        log_values = np.log1p(values)
        for window in (5, 20):
            scale = log_values.rolling(window).std().replace(0, np.nan)
            result[f"etf_{name}_z_{window}"] = (
                log_values - log_values.rolling(window).mean()
            ) / scale
    shares_frame = _checked_frame(shares, price=False)
    total = shares_frame.set_index("Date")["TotalShare"].astype(float)
    if not np.isfinite(total).all() or total.le(0).any():
        raise ValueError("invalid ETF share size")
    # D's fund shares are published D+1 08:30, so D+1 close is the first decision close.
    known_shares = total.reindex(dates).shift(1)
    for window in (1, 5, 20):
        result[f"known_share_change_{window}"] = known_shares.pct_change(
            window, fill_method=None
        )
    for name, raw in (("csi300", csi300), ("csi500", csi500)):
        source = _checked_frame(raw, price=True)
        series = source.set_index("Date")["Close"].astype(float).reindex(dates)
        if series.isna().any():
            raise ValueError(f"{name} calendar does not cover ETF sessions")
        for window in (1, 5, 20):
            index_return = series.pct_change(window, fill_method=None)
            result[f"{name}_return_{window}"] = index_return
            result[f"etf_excess_{name}_{window}"] = result[f"etf_return_{window}"] - index_return
        result[f"{name}_volatility_20"] = series.pct_change(fill_method=None).rolling(20).std()
    result["csi500_minus_csi300_20"] = (
        result["csi500_return_20"] - result["csi300_return_20"]
    )
    result.index.name = "Date"
    return result


def _tsfresh_features(etf: pd.DataFrame) -> pd.DataFrame:
    dates = pd.DatetimeIndex(etf["Date"])
    close = pd.Series(etf["Close"].to_numpy(dtype=float), index=dates)
    high = pd.Series(etf["High"].to_numpy(dtype=float), index=dates)
    low = pd.Series(etf["Low"].to_numpy(dtype=float), index=dates)
    volume = pd.Series(etf["Volume"].to_numpy(dtype=float), index=dates)
    signals = {
        "return": close.pct_change(fill_method=None).fillna(0).to_numpy(dtype=float),
        "range": ((high - low) / close).to_numpy(dtype=float),
        "volume_change": np.log1p(volume).diff().fillna(0).to_numpy(dtype=float),
    }
    ids = np.repeat(np.arange(TSFRESH_WINDOW - 1, len(etf)), TSFRESH_WINDOW)
    times = np.tile(np.arange(TSFRESH_WINDOW), len(etf) - TSFRESH_WINDOW + 1)
    starts = ids - TSFRESH_WINDOW + 1
    records = []
    for kind, series in signals.items():
        records.append(pd.DataFrame({
            "id": ids,
            "time": times,
            "kind": kind,
            "value": series[starts + times],
        }))
    long = pd.concat(records, ignore_index=True)
    extracted = extract_features(
        long, column_id="id", column_sort="time", column_kind="kind",
        column_value="value", default_fc_parameters=TSFRESH_PARAMETERS,
        disable_progressbar=True, n_jobs=1,
    )
    extracted = extracted.add_prefix("tsfresh_")
    extracted.index = dates[extracted.index.to_numpy(dtype=int)]
    return extracted.reindex(dates)


def _labels(etf: pd.DataFrame, execution: pd.DataFrame) -> pd.DataFrame:
    trade = _checked_frame(execution, price=True)
    dates = pd.DatetimeIndex(etf["Date"])
    if not trade["Date"].equals(pd.Series(dates)):
        raise ValueError("adjusted and executable ETF sessions do not match")
    opens = pd.Series(trade["Open"].to_numpy(dtype=float), index=dates)
    result = pd.DataFrame(index=dates)
    for horizon in HORIZONS:
        result[f"open_return_{horizon}"] = opens.shift(-(horizon + 1)) / opens.shift(-1) - 1
    result.index.name = "Date"
    return result


def _ridge_prediction(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    center = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale == 0] = 1.0
    x = (train_x - center) / scale
    future = (test_x - center) / scale
    target_mean = train_y.mean()
    weights = np.linalg.solve(x.T @ x + 10.0 * np.eye(x.shape[1]), x.T @ (train_y - target_mean))
    return target_mean + future @ weights


def _sequential_increment(data: pd.DataFrame, factor: str, label: str) -> tuple[float, int]:
    columns = ["etf_return_5", "etf_volatility_20"]
    sample = data[[*columns, factor, label]].replace([np.inf, -np.inf], np.nan).dropna()
    if factor in columns:
        return 0.0, 0
    squared_base = []
    squared_extra = []
    for start, end in zip(TEST_STARTS, (*TEST_STARTS[1:], "2026-10-01")):
        train = sample.loc[sample.index < pd.Timestamp(start)]
        test = sample.loc[(sample.index >= pd.Timestamp(start)) & (sample.index < pd.Timestamp(end))]
        if len(train) < 80 or len(test) < 15:
            continue
        y_train = train[label].to_numpy(dtype=float)
        y_test = test[label].to_numpy(dtype=float)
        base = _ridge_prediction(train[columns].to_numpy(dtype=float), y_train, test[columns].to_numpy(dtype=float))
        expanded = [*columns, factor]
        extra = _ridge_prediction(train[expanded].to_numpy(dtype=float), y_train, test[expanded].to_numpy(dtype=float))
        squared_base.extend((y_test - base) ** 2)
        squared_extra.extend((y_test - extra) ** 2)
    if not squared_base:
        return float("nan"), 0
    return float(1 - np.mean(squared_extra) / np.mean(squared_base)), len(squared_base)


def _survey(features: pd.DataFrame, labels: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    features = features.replace([np.inf, -np.inf], np.nan)
    joined = features.join(labels)
    quality = []
    scored = []
    for factor in features.columns:
        series = features[factor]
        valid = series.dropna()
        unique = valid.nunique()
        usable = len(valid) >= 150 and unique >= 5
        quality.append({"factor": factor, "finite_rows": len(valid), "missing_rows": int(series.isna().sum()),
                        "unique_values": int(unique), "usable": bool(usable)})
        if not usable:
            continue
        for horizon in HORIZONS:
            label = f"open_return_{horizon}"
            pair = joined[[factor, label]].dropna()
            if len(pair) < 150:
                continue
            low = pair[factor].quantile(0.25)
            high = pair[factor].quantile(0.75)
            spread = pair.loc[pair[factor].ge(high), label].mean() - pair.loc[pair[factor].le(low), label].mean()
            annual = []
            for _, part in pair.groupby(pair.index.year):
                if len(part) >= 40 and part[factor].nunique() >= 5:
                    annual.append(float(part[factor].corr(part[label], method="spearman")))
            increment, tested = _sequential_increment(joined, factor, label)
            scored.append({"factor": factor, "horizon": horizon, "paired_rows": len(pair),
                           "rank_ic": float(pair[factor].corr(pair[label], method="spearman")),
                           "quartile_spread": float(spread), "annual_ic": json.dumps(annual),
                           "positive_annual_ic": sum(value > 0 for value in annual),
                           "negative_annual_ic": sum(value < 0 for value in annual),
                           "incremental_mse_reduction": increment, "oos_rows": tested})
    return pd.DataFrame(quality), pd.DataFrame(scored)


def _synthetic_precheck() -> None:
    dates = pd.bdate_range("2020-01-01", periods=55)
    close = 1 + np.arange(len(dates)) * 0.001
    etf = pd.DataFrame({"Date": dates, "Open": close, "High": close * 1.01,
                        "Low": close * 0.99, "Close": close * 1.002,
                        "Volume": np.arange(len(dates)) + 100,
                        "Amount": np.arange(len(dates)) + 1000})
    shares = pd.DataFrame({"Date": dates, "TotalShare": np.arange(len(dates)) + 1000})
    manual = _manual_features(etf, shares, etf, etf)
    shape = _tsfresh_features(etf)
    labels = _labels(etf, etf)
    if not pd.isna(manual["known_share_change_1"].iloc[1]) or manual["known_share_change_1"].iloc[2] <= 0:
        raise ValueError("synthetic share publication lag failed")
    if not np.isclose(labels["open_return_5"].iloc[0], close[6] / close[1] - 1):
        raise ValueError("synthetic future-open label shifted")
    if shape.shape[1] < 30 or shape.index[0] != dates[0]:
        raise ValueError("synthetic tsfresh window extraction failed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1, experiment_id=EXPERIMENT_ID, strategy_id="S010",
            mode=ExperimentMode.FORMAL,
            research_question="Which causal ETF, fund-share and broad-index factors contain forward-open information beyond a simple price baseline?",
            hypothesis="At least one factor family may offer stable forward-open information after controlling for elementary price momentum and volatility.",
            falsification_conditions=(
                "Required DFLS input identity, causal timing or quality fails",
                "No factor has usable coverage or stable direction",
                "Sequential baseline comparisons show no incremental information",
            ),
            development_cutoff=date(2026, 9, 28), validation_cutoff=date(2026, 9, 29),
            random_seed=SEED,
            allowed_datasets=tuple(sorted({item.value for _, item, _ in INPUTS})),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Price discovery, ETF fund flow and broad-market style can influence subsequent ETF returns",),
                information_paths=("T-close price/volume and T-1 published share size -> later open-to-open return",),
                stage_objectives=("Enumerate factor availability and redundancy", "Assess forward-open association and simple baseline increment"),
                observation_metrics=("coverage", "rank IC", "quartile spread", "annual direction", "sequential MSE reduction"),
                methodology=("Frozen manual plus 20-session tsfresh features", "Fixed 1/5/10-session labels", "Three expanding chronological test segments", "No strategy, cost or parameter search"),
            ),
            subjects=("159326.SZ",),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tsfresh", tsfresh.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True, reads_sealed_validation=True),
        )

    def synthetic_precheck(self) -> None:
        _synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        sources = {}
        lineage = {}
        for name, dataset, symbol in INPUTS:
            result = context.data.fetch(DataRequest(
                dataset, symbol, START, CUTOFF, CUTOFF, "daily",
                {"env_file": str(Path(__file__).resolve().parents[3] / ".env")},
            ))
            if not result.ready or result.identity is None:
                detail = result.status.value if result.error is None else f"{result.error.code}: {result.error.message}"
                raise ValueError(f"{name} DFLS data is not ready: {detail}")
            sources[name] = _checked_frame(result.dataframe, price=name != "shares")
            temporal = result.identity.temporal_contract
            lineage[name] = {"dataset": dataset.value, "symbol": symbol,
                             "source": result.identity.source, "rows": len(result.dataframe),
                             "start": result.identity.data_start, "cutoff": result.identity.data_cutoff,
                             "sha256": result.identity.content_sha256,
                             "available_at": temporal.available_at}
        manual = _manual_features(sources["etf"], sources["shares"], sources["csi300"], sources["csi500"])
        automated = _tsfresh_features(sources["etf"])
        features = manual.join(automated)
        if features.columns.duplicated().any() or len(features) < 400:
            raise ValueError("feature survey has insufficient or duplicate features")
        labels = _labels(sources["etf"], sources["execution"])
        quality, scores = _survey(features, labels)
        if scores.empty:
            raise ValueError("no factors could be evaluated")
        duplicate_groups = []
        hashes = {}
        for name in features.columns:
            values = pd.util.hash_pandas_object(features[name], index=False).to_numpy(dtype=np.uint64)
            digest = __import__("hashlib").sha256(values.tobytes()).hexdigest()
            if digest in hashes:
                duplicate_groups.append({"factor": name, "exact_duplicate_of": hashes[digest]})
            else:
                hashes[digest] = name
        artifacts = []
        for filename, frame in (
            ("factor_matrix.csv.gz", features.reset_index()),
            ("future_open_labels.csv.gz", labels.reset_index()),
            ("factor_quality.csv", quality),
            ("factor_scores.csv", scores),
            ("exact_duplicates.csv", pd.DataFrame(duplicate_groups, columns=["factor", "exact_duplicate_of"])),
        ):
            frame.to_csv(context.workspace.path(filename), index=False, lineterminator="\n",
                         compression="gzip" if filename.endswith(".gz") else None)
            artifacts.append(context.workspace.register_artifact(filename, f"S010-EX01-{filename.split('.')[0]}"))
        summary = {"decision": "FACTOR_SURVEY_COMPLETE", "development_cutoff": CUTOFF,
                   "input_identity": lineage, "manual_factor_count": manual.shape[1],
                   "tsfresh_factor_count": automated.shape[1], "factor_count": features.shape[1],
                   "usable_factor_count": int(quality["usable"].sum()),
                   "scored_comparisons": len(scores), "exact_duplicate_count": len(duplicate_groups),
                   "tsfresh_window": TSFRESH_WINDOW, "tsfresh_parameters": TSFRESH_PARAMETERS,
                   "horizons": list(HORIZONS), "test_starts": list(TEST_STARTS),
                   "sealed_date_rows_read": 0, "account_replay_performed": False}
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "S010-EX01-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={"decision": "FACTOR_SURVEY_COMPLETE", "factor_count": features.shape[1],
                   "usable_factor_count": int(quality["usable"].sum()),
                   "scored_comparisons": len(scores), "sealed_date_rows_read": 0},
            diagnostics={"exact_duplicate_count": len(duplicate_groups)},
            artifacts=tuple(artifacts),
        )
