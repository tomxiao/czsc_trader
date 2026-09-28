"""S011 EX09: technical successor to the 30-minute feature data gate."""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import numpy as np
import pandas as pd

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
    experiment_source_sha256,
)


EXPERIMENT_ID = "20260928_S011_EX09"
PREDECESSOR = "20260928_S011_EX07"
PREDECESSOR_RECEIPT = "880c200549e4f8da5abaca569b502461b5255876403543fb1f7bdff8f1549491"
TECHNICAL_PREDECESSOR = "20260928_S011_EX08"
EX08_SOURCE_SHA256 = "7c666da2b67978ab4652deee2c8cb4aab8f422bcf739aad6fa031ba888b38ba6"
EX08_MANIFEST_SHA256 = "ec5811f3447df10485804b1bfe4644d6543d84c4a80dfdd2fa7e49efe13b33ca"
START = "2024-09-09"
END = "2026-09-24"
SEED = 2026092808
EXPECTED_TIMES = (
    "10:00:00",
    "10:30:00",
    "11:00:00",
    "11:30:00",
    "13:30:00",
    "14:00:00",
    "14:30:00",
    "15:00:00",
)
CORRELATION_LIMIT = 0.85
MINIMUM_INTRADAY_DAYS = 470
MINIMUM_CALENDAR_COVERAGE = 0.95
MINIMUM_COMPLETE_ROWS = 450
MINIMUM_FEATURE_COVERAGE = 0.95
MINIMUM_UNIQUE_VALUES = 50
MINIMUM_SELECTED_FEATURES = 6
MINIMUM_DENSE_FEATURES = 5
REFERENCE_SESSIONS = 120
MINIMUM_REFERENCE_SESSIONS = 60
STATE_QUANTILE = 0.20
COOLDOWN_SESSIONS = 3
ROLLING_DENSITY_SESSIONS = 60
MINIMUM_DENSITY_MEDIAN = 5.0
MINIMUM_DENSITY_P10 = 2.0
FEATURES = (
    "OpeningHourReturn",
    "AfternoonReturn",
    "TailAcceleration",
    "OpeningHourVolumeShare",
    "TailVolumeShare",
    "DownVolumeShare",
    "RealizedVolatilityRatio20",
    "CloseLocation",
)

ex08_root = Path(__file__).resolve().parent.parent / TECHNICAL_PREDECESSOR
if (
    experiment_source_sha256(ex08_root, ("experiment.py", "run_experiment.py"))
    != EX08_SOURCE_SHA256
):
    raise ValueError("EX08 frozen implementation differs")
if sha256((ex08_root / "experiment_manifest.json").read_bytes()).hexdigest() != (
    EX08_MANIFEST_SHA256
):
    raise ValueError("EX08 technical-failure manifest differs")


def _normalize_intraday(frame: pd.DataFrame) -> pd.DataFrame:
    required = ("Date", "Open", "High", "Low", "Close", "Volume", "Amount")
    missing = sorted(set(required).difference(frame.columns))
    if missing:
        raise ValueError(f"intraday input is missing fields: {missing}")
    output = frame.loc[:, required].copy()
    output["Date"] = pd.to_datetime(output["Date"], errors="raise")
    if output["Date"].duplicated().any():
        raise ValueError("intraday input contains duplicate timestamps")
    for column in required[1:]:
        output[column] = pd.to_numeric(output[column], errors="raise").astype(float)
    if not np.isfinite(output.loc[:, required[1:]].to_numpy(dtype=float)).all():
        raise ValueError("intraday input contains non-finite values")
    if not output[["Open", "High", "Low", "Close"]].gt(0).all().all():
        raise ValueError("intraday prices must be positive")
    if output[["Volume", "Amount"]].lt(0).any().any():
        raise ValueError("intraday activity must be non-negative")
    output["TradeDate"] = output["Date"].dt.normalize()
    output["Time"] = output["Date"].dt.strftime("%H:%M:%S")
    return output.sort_values("Date").reset_index(drop=True)


def _daily_calendar(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "Date" not in frame:
        raise ValueError("daily calendar input is missing Date")
    dates = pd.to_datetime(frame["Date"], errors="raise").dt.normalize()
    if dates.duplicated().any():
        raise ValueError("daily calendar contains duplicate dates")
    return pd.DatetimeIndex(dates.sort_values())


def _day_features(group: pd.DataFrame) -> dict[str, object]:
    ordered = group.sort_values("Date").reset_index(drop=True)
    if tuple(ordered["Time"]) != EXPECTED_TIMES:
        raise ValueError(f"{ordered['TradeDate'].iloc[0].date()}: 30-minute timestamps differ")
    total_volume = float(ordered["Volume"].sum())
    day_high = float(ordered["High"].max())
    day_low = float(ordered["Low"].min())
    if total_volume <= 0 or day_high <= day_low:
        raise ValueError("intraday day has zero activity or price range")
    bar_returns = ordered["Close"].div(ordered["Close"].shift(1)).sub(1.0)
    bar_returns.iloc[0] = ordered["Close"].iloc[0] / ordered["Open"].iloc[0] - 1.0
    opening_return = ordered["Close"].iloc[1] / ordered["Open"].iloc[0] - 1.0
    afternoon_return = ordered["Close"].iloc[7] / ordered["Open"].iloc[4] - 1.0
    pre_tail_return = ordered["Close"].iloc[5] / ordered["Open"].iloc[4] - 1.0
    tail_return = ordered["Close"].iloc[7] / ordered["Open"].iloc[6] - 1.0
    return {
        "Date": ordered["TradeDate"].iloc[0],
        "OpeningHourReturn": float(opening_return),
        "AfternoonReturn": float(afternoon_return),
        "TailAcceleration": float(tail_return - pre_tail_return),
        "OpeningHourVolumeShare": float(ordered["Volume"].iloc[:2].sum() / total_volume),
        "TailVolumeShare": float(ordered["Volume"].iloc[-2:].sum() / total_volume),
        "DownVolumeShare": float(ordered.loc[bar_returns.lt(0), "Volume"].sum() / total_volume),
        "RealizedVolatility": float(np.sqrt(np.square(bar_returns).sum())),
        "CloseLocation": float((ordered["Close"].iloc[-1] - day_low) / (day_high - day_low)),
    }


def _build_feature_panel(
    intraday_frame: pd.DataFrame, daily_frame: pd.DataFrame
) -> tuple[pd.DataFrame, dict[str, object]]:
    intraday = _normalize_intraday(intraday_frame)
    calendar = _daily_calendar(daily_frame)
    grouped = intraday.groupby("TradeDate", sort=True)
    rows = [_day_features(group) for _, group in grouped]
    panel = pd.DataFrame(rows).set_index("Date").sort_index()
    unexpected = panel.index.difference(calendar)
    covered = calendar.intersection(panel.index)
    if not unexpected.empty:
        raise ValueError("intraday data contains dates outside the daily calendar")
    prior_volatility = panel["RealizedVolatility"].shift(1).rolling(20, min_periods=20).median()
    panel["RealizedVolatilityRatio20"] = panel["RealizedVolatility"] / prior_volatility
    coverage = {
        "DailySessions": len(calendar),
        "IntradaySessions": len(panel),
        "CoveredSessions": len(covered),
        "CalendarCoverage": float(len(covered) / len(calendar)),
        "UnexpectedSessions": len(unexpected),
        "Bars": len(intraday),
        "BarsPerSessionMinimum": int(grouped.size().min()),
        "BarsPerSessionMaximum": int(grouped.size().max()),
    }
    return panel, coverage


def _feature_quality(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    first_ready = max(panel[name].first_valid_index() for name in FEATURES)
    eligible = panel.loc[first_ready:].copy()
    rows: list[dict[str, object]] = []
    for name in FEATURES:
        values = eligible[name]
        rows.append(
            {
                "Feature": name,
                "FirstReadyDate": panel[name].first_valid_index(),
                "EligibleRows": len(eligible),
                "AvailableRows": int(values.notna().sum()),
                "Coverage": float(values.notna().mean()),
                "Finite": bool(values.dropna().map(np.isfinite).all()),
                "UniqueValues": int(values.nunique(dropna=True)),
            }
        )
    return eligible, pd.DataFrame(rows)


def _select_nonredundant(correlation: pd.DataFrame) -> tuple[list[str], dict[str, str]]:
    selected: list[str] = []
    removed: dict[str, str] = {}
    for feature in FEATURES:
        if not selected:
            selected.append(feature)
            continue
        relationships = correlation.loc[feature, selected].abs()
        closest = str(relationships.idxmax())
        if float(relationships.max()) >= CORRELATION_LIMIT:
            removed[feature] = closest
        else:
            selected.append(feature)
    return selected, removed


def _cooldown(states: pd.Series) -> pd.Series:
    accepted = pd.Series(False, index=states.index)
    last_position = -COOLDOWN_SESSIONS - 1
    for position, active in enumerate(states.fillna(False).to_numpy(dtype=bool)):
        if active and position - last_position > COOLDOWN_SESSIONS:
            accepted.iloc[position] = True
            last_position = position
    return accepted


def _density_summary(eligible: pd.DataFrame, selected: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for feature in selected:
        values = eligible[feature]
        prior = values.shift(1).rolling(REFERENCE_SESSIONS, min_periods=MINIMUM_REFERENCE_SESSIONS)
        low = prior.quantile(STATE_QUANTILE)
        high = prior.quantile(1.0 - STATE_QUANTILE)
        extreme = values.le(low) | values.ge(high)
        accepted = _cooldown(extreme)
        ready = low.notna() & high.notna()
        rolling = (
            accepted.loc[ready]
            .astype(int)
            .rolling(
                ROLLING_DENSITY_SESSIONS,
                min_periods=ROLLING_DENSITY_SESSIONS,
            )
            .sum()
            .dropna()
        )
        if rolling.empty:
            median = p10 = minimum = maximum = 0.0
        else:
            median = float(rolling.median())
            p10 = float(rolling.quantile(0.10))
            minimum = float(rolling.min())
            maximum = float(rolling.max())
        rows.append(
            {
                "Feature": feature,
                "RawExtremeStates": int(extreme.loc[ready].sum()),
                "IndependentStates": int(accepted.loc[ready].sum()),
                "Rolling60Median": median,
                "Rolling60P10": p10,
                "Rolling60Minimum": minimum,
                "Rolling60Maximum": maximum,
                "DensityPass": bool(
                    median >= MINIMUM_DENSITY_MEDIAN and p10 >= MINIMUM_DENSITY_P10
                ),
            }
        )
    return pd.DataFrame(rows)


def synthetic_precheck() -> None:
    dates = pd.bdate_range("2024-01-02", periods=500)
    timestamps = [
        day + pd.Timedelta(hours=int(value[:2]), minutes=int(value[3:5]))
        for day in dates
        for value in EXPECTED_TIMES
    ]
    position = np.arange(len(timestamps), dtype=float)
    close = 1.0 + 0.00005 * position + 0.01 * np.sin(position / 13.0)
    intraday = pd.DataFrame(
        {
            "Date": timestamps,
            "Open": close * (1.0 - 0.001 * np.sin(position / 5.0)),
            "High": close * 1.004,
            "Low": close * 0.996,
            "Close": close,
            "Volume": 100_000 + 30_000 * (1.1 + np.sin(position / 7.0)),
            "Amount": (100_000 + 30_000 * (1.1 + np.sin(position / 7.0))) * close,
        }
    )
    daily = pd.DataFrame({"Date": dates})
    panel, coverage = _build_feature_panel(intraday, daily)
    eligible, quality = _feature_quality(panel)
    complete = eligible.loc[:, FEATURES].dropna()
    correlation = complete.corr(method="spearman")
    selected, _ = _select_nonredundant(correlation)
    density = _density_summary(eligible, selected)
    if coverage["CalendarCoverage"] != 1.0 or len(complete) < 450:
        raise ValueError("synthetic intraday coverage is invalid")
    if quality["Finite"].eq(False).any() or not selected or density.empty:
        raise ValueError("synthetic intraday feature construction is invalid")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Can a small causal set of 30-minute path features provide complete, "
                "nonredundant and sufficiently changing daily states?"
            ),
            hypothesis=(
                "Opening, afternoon and tail participation leave distinct intraday states "
                "that daily aggregates cannot fully represent."
            ),
            falsification_conditions=(
                "Intraday coverage or numeric validity is insufficient",
                "Fewer than six features survive the frozen redundancy rule",
                "Fewer than five retained features satisfy the frozen state-density gate",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=(
                Dataset.ETF_OHLCV.value,
                Dataset.ETF_UNADJUSTED_DAILY.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Trading pressure can differ across the opening, afternoon and closing windows",
                    "Only a complete trading day may define one close-known state",
                ),
                information_paths=(
                    "Intraday participation path -> close-known continuation or exhaustion state -> later tradable move",
                ),
                stage_objectives=(
                    "Freeze a small causal intraday feature set without reading later outcomes",
                    "Audit coverage, redundancy and state density before any return test",
                ),
                observation_metrics=(
                    "complete 30-minute session coverage",
                    "feature coverage and pairwise Spearman redundancy",
                    "rolling 60-session independent extreme-state density",
                ),
                methodology=(
                    "Use eight mechanism-defined 30-minute path features in a fixed order",
                    "Remove features at absolute Spearman correlation of 0.85 or higher",
                    "Use lagged rolling quantiles and a three-session cooldown for density only",
                    "Do not read post-state returns or select trading rules",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(),
            subjects=("159326.SZ",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX07 predecessor receipt differs")
        intraday_result = context.data.fetch(
            DataRequest(
                Dataset.ETF_OHLCV,
                "159326.SZ",
                START,
                END,
                END,
                "30m",
                {"env_file": ".env"},
            )
        )
        daily_result = context.data.fetch(
            DataRequest(
                Dataset.ETF_UNADJUSTED_DAILY,
                "159326.SZ",
                START,
                END,
                END,
                options={"env_file": ".env"},
            )
        )
        for key, result in (("intraday", intraday_result), ("daily", daily_result)):
            if result.status is not DataStatus.READY or result.identity is None:
                raise ValueError(f"{key} DFLS request failed: {result.status.value}")

        panel, coverage = _build_feature_panel(intraday_result.dataframe, daily_result.dataframe)
        eligible, quality = _feature_quality(panel)
        complete = eligible.loc[:, FEATURES].dropna()
        correlation = complete.corr(method="spearman")
        selected, removed = _select_nonredundant(correlation)
        density = _density_summary(eligible, selected)

        source_pass = bool(
            coverage["IntradaySessions"] >= MINIMUM_INTRADAY_DAYS
            and coverage["CalendarCoverage"] >= MINIMUM_CALENDAR_COVERAGE
            and coverage["UnexpectedSessions"] == 0
            and coverage["BarsPerSessionMinimum"] == len(EXPECTED_TIMES)
            and coverage["BarsPerSessionMaximum"] == len(EXPECTED_TIMES)
        )
        feature_pass = bool(
            len(complete) >= MINIMUM_COMPLETE_ROWS
            and quality["Coverage"].ge(MINIMUM_FEATURE_COVERAGE).all()
            and quality["Finite"].all()
            and quality["UniqueValues"].ge(MINIMUM_UNIQUE_VALUES).all()
        )
        selection_pass = len(selected) >= MINIMUM_SELECTED_FEATURES
        dense_count = int(density["DensityPass"].sum())
        density_pass = dense_count >= MINIMUM_DENSE_FEATURES
        passes = source_pass and feature_pass and selection_pass and density_pass
        decision = (
            "PROCEED_TO_FIXED_INTRADAY_INFORMATION_TEST"
            if passes
            else "STOP_INTRADAY_FEATURE_SET_ON_DATA_OR_DENSITY"
        )
        summary = {
            "decision": decision,
            "checks": {
                "intraday_source_quality": source_pass,
                "feature_quality": feature_pass,
                "minimum_selected_features": selection_pass,
                "minimum_dense_features": density_pass,
            },
            "coverage": coverage,
            "eligible_rows": len(eligible),
            "complete_rows": len(complete),
            "selected_features": selected,
            "removed_features": removed,
            "dense_feature_count": dense_count,
            "reads_post_state_returns": False,
            "candidate_created": False,
            "strategy_rule_created": False,
        }
        panel.reset_index().to_csv(
            context.workspace.path("intraday_feature_ledger.csv.gz"),
            index=False,
            compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
            lineterminator="\n",
            date_format="%Y-%m-%d",
        )
        quality.to_csv(
            context.workspace.path("feature_quality.csv"), index=False, lineterminator="\n"
        )
        correlation.to_csv(context.workspace.path("correlation_matrix.csv"), lineterminator="\n")
        density.to_csv(
            context.workspace.path("density_summary.csv"), index=False, lineterminator="\n"
        )
        identities = pd.DataFrame(
            [
                {
                    "Input": key,
                    "Dataset": result.identity.dataset,
                    "Symbol": result.identity.symbol,
                    "Rows": len(result.dataframe),
                    "DataStart": result.identity.data_start,
                    "DataCutoff": result.identity.data_cutoff,
                    "ContentSha256": result.identity.content_sha256,
                }
                for key, result in (
                    ("intraday", intraday_result),
                    ("daily", daily_result),
                )
            ]
        )
        identities.to_csv(
            context.workspace.path("input_identities.csv"), index=False, lineterminator="\n"
        )
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        artifacts = tuple(
            context.workspace.register_artifact(name, kind)
            for name, kind in (
                ("intraday_feature_ledger.csv.gz", "causal-intraday-feature-ledger"),
                ("feature_quality.csv", "intraday-feature-quality-audit"),
                ("correlation_matrix.csv", "intraday-feature-redundancy-audit"),
                ("density_summary.csv", "intraday-state-density-audit"),
                ("input_identities.csv", "pinned-input-identities"),
                ("summary.json", "intraday-data-gate-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passes else ExperimentOutcome.FAIL,
            facts={
                "decision": decision,
                "intraday_sessions": coverage["IntradaySessions"],
                "calendar_coverage": coverage["CalendarCoverage"],
                "complete_rows": len(complete),
                "selected_feature_count": len(selected),
                "dense_feature_count": dense_count,
            },
            diagnostics={
                "checks": summary["checks"],
                "selected_features": selected,
                "removed_features": removed,
                "reads_post_state_returns": False,
                "candidate_created": False,
            },
            artifacts=artifacts,
        )
