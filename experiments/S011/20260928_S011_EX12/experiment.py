"""S011 EX12: return-blind tsfresh time-series factor census."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from importlib.metadata import version
import json
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
from tsfresh.feature_extraction import feature_calculators as fc

from dataflows import DataRequest, DataStatus, Dataset
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


EXPERIMENT_ID = "20260928_S011_EX12"
PREDECESSOR = "20260928_S011_EX11"
PREDECESSOR_RECEIPT = "d47cbf1f83ead77621f389491c2474510db6e78e162adf2f77d39224f92d9119"
EX11_CATALOG_SHA256 = "4cf81f0c378922d3f61ef774f68c3c9aac61900d9f1aeada30392c6cc2b838c2"
EX11_MANIFEST_SHA256 = "e351e74c2b8d65bf46eed16546c7ff783bcdb6831682fcc7af6e9380d61d0cf4"
SOURCE_SHA256 = {
    "etf_daily": "a197ebc57a54591c0c4a226ec1f7c64cf67bc0ca698968f6cfd582d656608ca3",
    "etf_30m": "8926257d0b2bb6c378f27c2555373b056416e1008b3880fe4bbd4ce987901131",
    "theme_daily": "720f251694ef27558a984e0988b33aca29af8a25aeee859f3352ac252cb6ceb7",
}
START = "2024-09-09"
THEME_START = "2024-10-24"
END = "2026-09-24"
SEED = 2026092812
DAILY_WINDOWS = (20, 60)
BAR_WINDOWS = (40, 80)
CALCULATOR_NAMES = (
    "absolute_sum_of_changes",
    "mean_abs_change",
    "cid_ce_normalized",
    "count_above_mean",
    "longest_strike_above_mean",
    "skewness",
)
REQUESTS = (
    ("etf_daily", Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ", START, "daily"),
    ("etf_30m", Dataset.ETF_OHLCV, "159326.SZ", START, "30m"),
    ("theme_daily", Dataset.DOMESTIC_INDEX_DAILY, "931994.CSI", THEME_START, "daily"),
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _calculators() -> dict[str, Callable[[np.ndarray], float]]:
    return {
        "absolute_sum_of_changes": fc.absolute_sum_of_changes,
        "mean_abs_change": fc.mean_abs_change,
        "cid_ce_normalized": lambda x: fc.cid_ce(x, normalize=True),
        "count_above_mean": fc.count_above_mean,
        "longest_strike_above_mean": fc.longest_strike_above_mean,
        "skewness": fc.skewness,
    }


def _rolling(series: pd.Series, window: int, calculator: Callable) -> pd.Series:
    return series.rolling(window, min_periods=window).apply(
        lambda values: float(calculator(np.asarray(values, dtype=float))),
        raw=True,
    )


def _indexed(frame: pd.DataFrame) -> pd.DataFrame:
    value = frame.copy()
    value["Date"] = pd.to_datetime(value["Date"], errors="raise").dt.normalize()
    if value["Date"].duplicated().any():
        raise ValueError("daily input contains duplicate dates")
    return value.set_index("Date").sort_index()


def _build_panel(
    etf_frame: pd.DataFrame,
    bar_frame: pd.DataFrame,
    theme_frame: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    etf = _indexed(etf_frame)
    theme = _indexed(theme_frame)
    close = pd.to_numeric(etf["Close"], errors="raise")
    volume = pd.to_numeric(etf["Volume"], errors="raise")
    theme_close = pd.to_numeric(theme["Close"], errors="raise").reindex(etf.index)
    if not close.gt(0).all() or not volume.gt(0).all() or not theme["Close"].gt(0).all():
        raise ValueError("price and volume inputs must be positive")
    daily_inputs = {
        "ETFReturn1": np.log(close).diff(),
        "ETFRange": (etf["High"] - etf["Low"]) / close,
        "ETFLogVolumeChange1": np.log(volume).diff(),
        "ETFThemeExcessReturn1": np.log(close).diff() - np.log(theme_close).diff(),
    }

    bars = bar_frame.copy()
    bars["Date"] = pd.to_datetime(bars["Date"], errors="raise")
    if bars["Date"].duplicated().any():
        raise ValueError("30-minute source contains duplicate timestamps")
    bars = bars.sort_values("Date").set_index("Date")
    bar_dates = bars.index.normalize()
    counts = pd.Series(1, index=bars.index).groupby(bar_dates).sum()
    if not counts.eq(8).all():
        raise ValueError("30-minute input must contain eight bars per session")
    bar_open = pd.to_numeric(bars["Open"], errors="raise")
    bar_close = pd.to_numeric(bars["Close"], errors="raise")
    bar_volume = pd.to_numeric(bars["Volume"], errors="raise")
    if not bar_open.gt(0).all() or not bar_close.gt(0).all() or not bar_volume.ge(0).all():
        raise ValueError("30-minute prices and volume must be valid")
    previous_close = bar_close.groupby(bar_dates).shift(1).fillna(bar_open)
    total_volume = bar_volume.groupby(bar_dates).transform("sum")
    if not total_volume.gt(0).all():
        raise ValueError("30-minute daily volume must be positive")
    bar_inputs = {
        "BarReturn": np.log(bar_close / previous_close),
        "BarVolumeShare": bar_volume / total_volume,
    }
    panel = pd.DataFrame(index=etf.index)
    metadata: list[dict[str, object]] = []
    for source_name, series in daily_inputs.items():
        for window in DAILY_WINDOWS:
            for calculator_name, calculator in _calculators().items():
                name = f"TSF_Daily_{source_name}_{calculator_name}_{window}"
                panel[name] = _rolling(series, window, calculator)
                metadata.append(
                    {
                        "Factor": name,
                        "Input": source_name,
                        "Frequency": "daily",
                        "Window": window,
                        "Calculator": calculator_name,
                        "DecisionAvailability": "SAME_SESSION_CLOSE",
                    }
                )
    for source_name, series in bar_inputs.items():
        for window in BAR_WINDOWS:
            for calculator_name, calculator in _calculators().items():
                name = f"TSF_30m_{source_name}_{calculator_name}_{window}"
                values = _rolling(series, window, calculator)
                daily_values = values.groupby(bar_dates).last()
                panel[name] = daily_values.reindex(panel.index)
                metadata.append(
                    {
                        "Factor": name,
                        "Input": source_name,
                        "Frequency": "30m",
                        "Window": window,
                        "Calculator": calculator_name,
                        "DecisionAvailability": "SAME_SESSION_CLOSE",
                    }
                )
    panel = panel.replace([np.inf, -np.inf], np.nan)
    return panel, pd.DataFrame(metadata)


def _census(panel: pd.DataFrame, metadata: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    correlation = panel.corr(method="spearman", min_periods=100)
    rows: list[dict[str, object]] = []
    for name in panel.columns:
        series = panel[name]
        valid = series.dropna()
        peer = correlation[name].drop(index=name).abs().dropna()
        closest = None if peer.empty else str(peer.idxmax())
        relationship = None if peer.empty else float(peer.max())
        rows.append(
            {
                "Factor": name,
                "CalendarRows": len(series),
                "AvailableRows": len(valid),
                "Coverage": float(len(valid) / len(series)),
                "FirstDate": None if valid.empty else valid.index.min().date(),
                "LastDate": None if valid.empty else valid.index.max().date(),
                "UniqueValues": int(valid.nunique()),
                "P10": None if valid.empty else float(valid.quantile(0.10)),
                "Median": None if valid.empty else float(valid.median()),
                "P90": None if valid.empty else float(valid.quantile(0.90)),
                "Lag1Autocorrelation": None if len(valid) < 3 else float(series.autocorr()),
                "ClosestFactor": closest,
                "AbsoluteSpearmanWithClosest": relationship,
                "RedundantAt085": bool(relationship is not None and relationship >= 0.85),
            }
        )
    return metadata.merge(pd.DataFrame(rows), on="Factor", validate="one_to_one"), correlation


def synthetic_precheck() -> None:
    dates = pd.bdate_range("2024-01-02", periods=100)
    phase = np.arange(len(dates), dtype=float)
    close = 1.0 + phase * 0.001 + 0.02 * np.sin(phase / 7)
    etf = pd.DataFrame(
        {
            "Date": dates,
            "Open": close * 0.999,
            "High": close * 1.01,
            "Low": close * 0.99,
            "Close": close,
            "Volume": 1_000_000 + phase * 1000,
        }
    )
    theme = pd.DataFrame({"Date": dates, "Close": 100 + phase * 0.1})
    bar_rows = []
    for position, day in enumerate(dates):
        for slot, hour in enumerate(
            ("10:00", "10:30", "11:00", "11:30", "13:30", "14:00", "14:30", "15:00")
        ):
            price = float(close[position] * (1 + slot * 0.0001))
            bar_rows.append(
                {
                    "Date": f"{day.date()} {hour}",
                    "Open": price,
                    "Close": price * 1.0001,
                    "Volume": 1000 + position + slot,
                }
            )
    bars = pd.DataFrame(bar_rows)
    first, metadata = _build_panel(etf, bars, theme)
    if first.shape != (100, 72) or len(metadata) != 72:
        raise ValueError("tsfresh synthetic factor dimensions changed")
    altered = etf.copy()
    altered.loc[99, "Close"] *= 2
    second, _ = _build_panel(altered, bars, theme)
    if not first.iloc[:-1].equals(second.iloc[:-1]):
        raise ValueError("later daily input changed earlier tsfresh factors")
    if not first.filter(like="TSF_30m_").notna().any().all():
        raise ValueError("30-minute tsfresh factors did not materialize")
    if not np.isclose(_calculators()["mean_abs_change"](np.array([1.0, 3.0, 2.0])), 1.5):
        raise ValueError("tsfresh calculator contract changed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "What additional daily and intraday trading-path shapes does a fixed "
                "tsfresh expansion reveal before any future-return scan?"
            ),
            hypothesis=(
                "Trailing time-series shapes may be sufficiently covered and distinct "
                "from the basic factors to motivate new mechanistic questions."
            ),
            falsification_conditions=(
                "Source identities differ from the frozen EX11 census",
                "The deterministic tsfresh expansion yields incomplete or invalid identities",
                "A later observation changes an earlier factor value",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=tuple(sorted({request[1].value for request in REQUESTS})),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Trading participation has temporal shape beyond a single daily aggregate",
                    "Trailing windows may only use information available by T close",
                ),
                information_paths=(
                    "Daily and 30-minute trading paths -> recurring state shapes -> later falsifiable hypotheses",
                ),
                stage_objectives=(
                    "Extend the return-blind EX11 census with a fixed tsfresh calculator grid",
                    "Audit factor coverage, variability, and within-expansion redundancy",
                ),
                observation_metrics=(
                    "factor coverage, distribution and unique values",
                    "absolute Spearman redundancy at 0.85",
                ),
                methodology=(
                    "Apply six fixed tsfresh calculators to four daily and two 30-minute input series",
                    "Use trailing 20/60 sessions and trailing 40/80 bars respectively",
                    "Report all 72 combinations without return-based selection",
                    "Do not read future returns or sealed validation data",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("tsfresh", version("tsfresh")),
            ),
            capabilities=ExperimentCapabilities(),
            subjects=("159326.SZ",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        if context.predecessors[PREDECESSOR].receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX11 predecessor receipt differs")
        root = Path(__file__).resolve().parents[3]
        ex11 = root / "experiments" / "S011" / PREDECESSOR
        if (
            _sha256(ex11 / "artifacts/source_catalog.csv") != EX11_CATALOG_SHA256
            or _sha256(ex11 / "experiment_manifest.json") != EX11_MANIFEST_SHA256
        ):
            raise ValueError("EX11 census identity differs")
        frames: dict[str, pd.DataFrame] = {}
        identities: list[dict[str, object]] = []
        for key, dataset, symbol, start, frequency in REQUESTS:
            result = context.data.fetch(
                DataRequest(dataset, symbol, start, END, END, frequency, {"env_file": ".env"})
            )
            if result.status is not DataStatus.READY or result.identity is None:
                raise ValueError(f"{key} DFLS request failed: {result.status.value}")
            if result.identity.content_sha256 != SOURCE_SHA256[key]:
                raise ValueError(f"{key} source identity differs from EX11")
            frames[key] = result.dataframe.copy()
            identities.append(
                {
                    "Input": key,
                    "Dataset": dataset.value,
                    "Symbol": symbol,
                    "Rows": len(result.dataframe),
                    "ContentSha256": result.identity.content_sha256,
                    "AvailableAt": result.identity.temporal_contract.available_at,
                }
            )
        panel, metadata = _build_panel(
            frames["etf_daily"], frames["etf_30m"], frames["theme_daily"]
        )
        census, correlation = _census(panel, metadata)
        if len(census) != 72 or census["Factor"].duplicated().any():
            raise ValueError("tsfresh factor grid differs")
        summary = {
            "decision": "TSFRESH_CENSUS_COMPLETE",
            "tsfresh_version": version("tsfresh"),
            "calendar_sessions": len(panel),
            "factor_count": len(census),
            "daily_factor_count": int(census["Frequency"].eq("daily").sum()),
            "intraday_factor_count": int(census["Frequency"].eq("30m").sum()),
            "factors_with_95pct_coverage": int(census["Coverage"].ge(0.95).sum()),
            "redundant_at_085_count": int(census["RedundantAt085"].sum()),
            "reads_future_returns": False,
            "reads_sealed_validation": False,
            "candidate_created": False,
            "alpha_claimed": False,
        }
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False)
        census.to_csv(context.workspace.path("tsfresh_factor_census.csv"), index=False)
        correlation.to_csv(context.workspace.path("tsfresh_spearman.csv"))
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        artifacts = tuple(
            context.workspace.register_artifact(name, kind)
            for name, kind in (
                ("input_identities.csv", "pinned-input-identities"),
                ("tsfresh_factor_census.csv", "return-blind-tsfresh-census"),
                ("tsfresh_spearman.csv", "return-blind-tsfresh-redundancy"),
                ("summary.json", "return-blind-tsfresh-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts=summary,
            diagnostics={"tsfresh_calculators": list(CALCULATOR_NAMES)},
            artifacts=artifacts,
        )
