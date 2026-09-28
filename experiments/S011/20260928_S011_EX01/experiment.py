"""S011 EX01: complete tsfresh shape census without future returns."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json

from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
import pyarrow
from research_experiment import (
    ExperimentCapabilities,
    ExperimentDefinition,
    ExperimentDependency,
    ExperimentMode,
    ExperimentOutcome,
    ExperimentProtocol,
    ExperimentResult,
    ExperimentStage,
    ResearchExperiment,
)
import tsfresh
from tsfresh import extract_features
from tsfresh.feature_extraction import ComprehensiveFCParameters


EXPERIMENT_ID = "20260928_S011_EX01"
SYMBOL = "159326.SZ"
START = "2024-09-09"
CUTOFF = "2026-09-24"
DAILY_WINDOWS = (10, 20, 60)
INTRADAY_WINDOWS = (16, 40, 80)
MAX_WORKERS = 1


def _bounded_ratio(numerator: pd.Series, denominator: pd.Series) -> np.ndarray:
    values = numerator.to_numpy(dtype=float) / denominator.to_numpy(dtype=float)
    values[~np.isfinite(values)] = np.nan
    return values


def _daily_sequences(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    close = frame["Close"].astype(float)
    return {
        "return": np.log(close).diff().to_numpy(dtype=float),
        "log_amount": np.log1p(frame["Amount"].astype(float)).to_numpy(dtype=float),
        "range": _bounded_ratio(frame["High"] - frame["Low"], close.shift()),
        "close_location": _bounded_ratio(frame["Close"] - frame["Low"], frame["High"] - frame["Low"]),
    }


def _intraday_sequences(frame: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "bar_return": np.log(frame["Close"].astype(float) / frame["Open"].astype(float)).to_numpy(dtype=float),
        "log_amount": np.log1p(frame["Amount"].astype(float)).to_numpy(dtype=float),
        "range": _bounded_ratio(frame["High"] - frame["Low"], frame["Open"]),
    }


def _window_rows(
    sequences: dict[str, np.ndarray], window: int, sample_ends: tuple[tuple[int, int], ...]
) -> pd.DataFrame:
    rows: list[tuple[int, int, str, float]] = []
    for sample_id, end in sample_ends:
        start = end - window + 1
        if start < 0:
            continue
        for kind, series in sequences.items():
            values = series[start : end + 1]
            if len(values) != window or not np.isfinite(values).all():
                continue
            rows.extend((sample_id, position, kind, float(value)) for position, value in enumerate(values))
    return pd.DataFrame(rows, columns=("id", "time", "kind", "value"))


def _extract(long_frame: pd.DataFrame, settings: dict[str, object]) -> pd.DataFrame:
    if long_frame.empty:
        raise ValueError("no valid trailing samples for tsfresh")
    features = extract_features(
        long_frame,
        column_id="id",
        column_sort="time",
        column_kind="kind",
        column_value="value",
        default_fc_parameters=settings,
        n_jobs=MAX_WORKERS,
        disable_progressbar=True,
        impute_function=None,
    )
    if features.empty:
        raise ValueError("tsfresh returned no feature columns")
    return features.sort_index(axis=0).sort_index(axis=1)


def _quality(features: pd.DataFrame, label: str, window: int) -> list[dict[str, object]]:
    values = features.to_numpy(dtype=np.float64)
    rows: list[dict[str, object]] = []
    for column_index, feature_name in enumerate(features.columns):
        series = values[:, column_index]
        finite = np.isfinite(series)
        valid = series[finite]
        digest = sha256(finite.tobytes() + np.where(finite, series, 0.0).tobytes()).hexdigest()
        name_parts = feature_name.split("__", 2)
        rows.append({
            "Panel": label,
            "Window": window,
            "Feature": feature_name,
            "RawSeries": name_parts[0],
            "Calculator": name_parts[1] if len(name_parts) > 1 else "unknown",
            "Samples": len(series),
            "Finite": int(finite.sum()),
            "Coverage": float(finite.mean()),
            "Std": float(np.std(valid)) if len(valid) else np.nan,
            "UniqueFinite": int(np.unique(valid).size),
            "ExactColumnSha256": digest,
        })
    return rows


def _prepare_frames(daily: pd.DataFrame, intraday: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = daily.copy().sort_values("Date").reset_index(drop=True)
    intraday = intraday.copy().sort_values("Date").reset_index(drop=True)
    daily["Date"] = pd.to_datetime(daily["Date"])
    intraday["Date"] = pd.to_datetime(intraday["Date"])
    if len(daily) != 496 or len(intraday) != 3968:
        raise ValueError("frozen ETF data row counts changed")
    daily_dates = pd.DatetimeIndex(daily["Date"])
    intraday_dates = intraday["Date"].dt.normalize()
    counts = intraday_dates.value_counts().sort_index()
    if not counts.index.equals(daily_dates) or not counts.eq(8).all():
        raise ValueError("30-minute and daily calendars do not align as eight bars per session")
    return daily, intraday


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question="Which trailing ETF price-volume time-series shapes are causally calculable?",
            hypothesis="Daily and intraday OHLCV may contain diverse nonredundant state descriptions worth later return tests.",
            falsification_conditions=(
                "Either governed ETF OHLCV input fails its fixed data gate",
                "Daily and 30-minute trading calendars differ",
                "Complete tsfresh configuration cannot be executed or archived",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=20260913,
            allowed_datasets=(Dataset.ETF_OHLCV.value,),
            subjects=(SYMBOL,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=("Trading behavior may change price, volume and volatility shapes before later returns",),
                information_paths=("Trailing ETF OHLCV shape -> later tradable price behavior, not tested here",),
                stage_objectives=("Enumerate complete tsfresh daily and intraday shapes without future returns",),
                observation_metrics=("Feature coverage, variance, undefined values and exact redundancy",),
                methodology=("Use governed fixed-window OHLCV, trailing-only windows and all comprehensive calculators",),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("pyarrow", pyarrow.__version__),
                ExperimentDependency("tsfresh", tsfresh.__version__),
            ),
            capabilities=ExperimentCapabilities(),
        )

    def synthetic_precheck(self) -> None:
        series = {"x": np.arange(12, dtype=float)}
        samples = _window_rows(series, 4, ((1, 5), (2, 6)))
        observed = samples.loc[samples["id"].eq(1), "value"].tolist()
        if observed != [2.0, 3.0, 4.0, 5.0]:
            raise ValueError("trailing window includes a future observation")
        features = extract_features(
            samples,
            column_id="id",
            column_sort="time",
            column_kind="kind",
            column_value="value",
            default_fc_parameters={"mean": None},
            n_jobs=1,
            disable_progressbar=True,
        )
        if not np.isclose(features.loc[1, "x__mean"], 3.5):
            raise ValueError("synthetic tsfresh extraction differs")
        settings = ComprehensiveFCParameters()
        if len(settings) != 75 or sum(1 if item is None else len(item) for item in settings.values()) != 788:
            raise ValueError("installed tsfresh comprehensive scope changed")

    def execute(self, context) -> ExperimentResult:
        input_rows: list[dict[str, object]] = []
        frames: dict[str, pd.DataFrame] = {}
        for label, frequency in (("daily", "daily"), ("30m", "30m")):
            result = context.data.fetch(DataRequest(
                dataset=Dataset.ETF_OHLCV,
                symbol=SYMBOL,
                start=START,
                end=CUTOFF,
                required_cutoff=CUTOFF,
                frequency=frequency,
                options={"env_file": ".env"},
            ))
            if result.status is not DataStatus.READY or result.identity is None:
                raise RuntimeError(f"governed {label} ETF data not READY: {result.error}")
            identity = result.identity
            input_rows.append({
                "Panel": label,
                "Dataset": identity.dataset,
                "Source": identity.source,
                "Symbol": identity.symbol,
                "Rows": len(result.dataframe),
                "Start": identity.data_start,
                "Cutoff": identity.data_cutoff,
                "Sha256": identity.content_sha256,
                "AvailableAt": identity.temporal_contract.available_at,
            })
            frames[label] = result.dataframe
        daily, intraday = _prepare_frames(frames["daily"], frames["30m"])
        daily_sequences = _daily_sequences(daily)
        intraday_sequences = _intraday_sequences(intraday)
        settings = ComprehensiveFCParameters()
        parameterizations = sum(1 if item is None else len(item) for item in settings.values())
        quality_rows: list[dict[str, object]] = []
        artifacts = []
        panel_summary: list[dict[str, object]] = []
        for label, windows, sequences in (
            ("daily", DAILY_WINDOWS, daily_sequences),
            ("30m", INTRADAY_WINDOWS, intraday_sequences),
        ):
            for window in windows:
                if label == "daily":
                    sample_ends = tuple((day, day) for day in range(window, len(daily)))
                else:
                    first_day = (window + 7) // 8 - 1
                    sample_ends = tuple((day, (day + 1) * 8 - 1) for day in range(first_day, len(daily)))
                long_frame = _window_rows(sequences, window, sample_ends)
                features = _extract(long_frame, settings)
                quality_rows.extend(_quality(features, label, window))
                artifact_name = f"tsfresh_{label}_w{window}.parquet"
                features.to_parquet(context.workspace.path(artifact_name), compression="zstd", index=True)
                artifacts.append(context.workspace.register_artifact(artifact_name, "tsfresh-feature-panel"))
                panel_summary.append({
                    "panel": label,
                    "window": window,
                    "samples": len(features),
                    "features": len(features.columns),
                    "kind_count": len(sequences),
                })
        quality = pd.DataFrame(quality_rows)
        quality.to_csv(
            context.workspace.path("factor_quality.csv.gz"),
            index=False,
            compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
            lineterminator="\n",
        )
        artifacts.append(context.workspace.register_artifact("factor_quality.csv.gz", "factor-quality-ledger"))
        pd.DataFrame(input_rows).to_csv(
            context.workspace.path("input_identities.csv"), index=False, lineterminator="\n"
        )
        artifacts.append(context.workspace.register_artifact("input_identities.csv", "governed-input-identities"))
        summary = {
            "decision": "WIDE_SHAPE_CENSUS_COMPLETE",
            "parameterizations_per_raw_series": parameterizations,
            "panels": panel_summary,
            "factor_columns": len(quality),
            "coverage_95": int(quality["Coverage"].ge(0.95).sum()),
            "undefined": int(quality["Finite"].eq(0).sum()),
            "constant": int(quality["UniqueFinite"].le(1).sum()),
            "exact_duplicate_columns": int(quality.duplicated(["Panel", "Window", "ExactColumnSha256"]).sum()),
            "reads_real_returns": False,
        }
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        artifacts.append(context.workspace.register_artifact("summary.json", "census-summary"))
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": summary["decision"],
                "factor_columns": summary["factor_columns"],
                "coverage_95": summary["coverage_95"],
                "undefined": summary["undefined"],
                "exact_duplicate_columns": summary["exact_duplicate_columns"],
            },
            diagnostics={"reads_real_returns": False, "creates_candidate": False},
            artifacts=tuple(artifacts),
        )
