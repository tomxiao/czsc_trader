"""S011 EX06: technical successor to the price-volume feature data gate."""

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


EXPERIMENT_ID = "20260928_S011_EX06"
PREDECESSOR = "20260928_S011_EX04"
PREDECESSOR_RECEIPT = "3bb4bce488cb459c84254f273a54cdf2816c606585942a80e7d7fefa1797e87b"
TECHNICAL_PREDECESSOR = "20260928_S011_EX05"
EX05_SOURCE_SHA256 = "4ad3706d7ddb1356cca7cefbd9af55cff9d8fce580fd7fec113bf20739d0d8d7"
EX05_MANIFEST_SHA256 = "c9e76e158b12ca06c9cb40471c161ec10a96d08415f68031359b547ea3eafe4c"
START = "2024-09-09"
THEME_START = "2024-10-24"
END = "2026-09-24"
SEED = 2026092805
CORRELATION_LIMIT = 0.85
MINIMUM_COMPLETE_ROWS = 350
MINIMUM_COVERAGE = 0.95
MINIMUM_UNIQUE_VALUES = 50
MINIMUM_SELECTED_FEATURES = 5
MINIMUM_DENSE_FEATURES = 4
REFERENCE_SESSIONS = 120
MINIMUM_REFERENCE_SESSIONS = 60
STATE_QUANTILE = 0.20
COOLDOWN_SESSIONS = 3
ROLLING_DENSITY_SESSIONS = 60
MINIMUM_DENSITY_MEDIAN = 5.0
MINIMUM_DENSITY_P10 = 2.0
FEATURES = (
    "TrendReturn20",
    "TrendEfficiency20",
    "VolatilityRatio5To20",
    "VolumeShock20",
    "SignedVolumePressure20",
    "LogAmihud20",
    "ThemeRelativeReturn20",
    "ShareChange5",
)

ex05_root = Path(__file__).resolve().parent.parent / TECHNICAL_PREDECESSOR
if (
    experiment_source_sha256(ex05_root, ("experiment.py", "run_experiment.py"))
    != EX05_SOURCE_SHA256
):
    raise ValueError("EX05 frozen implementation differs")
if sha256((ex05_root / "experiment_manifest.json").read_bytes()).hexdigest() != (
    EX05_MANIFEST_SHA256
):
    raise ValueError("EX05 technical-failure manifest differs")


def _daily_frame(frame: pd.DataFrame, required: tuple[str, ...]) -> pd.DataFrame:
    missing = sorted(set(("Date", *required)).difference(frame.columns))
    if missing:
        raise ValueError(f"daily input is missing fields: {missing}")
    output = frame.loc[:, ("Date", *required)].copy()
    output["Date"] = pd.to_datetime(output["Date"], errors="raise").dt.normalize()
    if output["Date"].duplicated().any():
        raise ValueError("daily input contains duplicate dates")
    for column in required:
        output[column] = pd.to_numeric(output[column], errors="raise").astype(float)
    output = output.sort_values("Date").set_index("Date")
    if not np.isfinite(output.to_numpy(dtype=float)).all():
        raise ValueError("daily input contains non-finite values")
    return output


def _align_share_change(share_frame: pd.DataFrame, trading_dates: pd.DatetimeIndex) -> pd.DataFrame:
    shares = _daily_frame(share_frame, ("TotalShare",))
    if not shares["TotalShare"].gt(0).all():
        raise ValueError("ETF shares must be positive")
    shares["ShareChange5"] = np.log(shares["TotalShare"]).diff(5)
    rows: list[dict[str, object]] = []
    for source_date, row in shares.dropna(subset=["ShareChange5"]).iterrows():
        position = int(trading_dates.searchsorted(source_date, side="right"))
        if position >= len(trading_dates):
            continue
        rows.append(
            {
                "Date": trading_dates[position],
                "ShareSourceDate": source_date,
                "ShareChange5": float(row["ShareChange5"]),
            }
        )
    aligned = pd.DataFrame(rows)
    if aligned.empty:
        raise ValueError("ETF share changes cannot be aligned to later sessions")
    aligned = aligned.sort_values(["Date", "ShareSourceDate"]).drop_duplicates("Date", keep="last")
    return aligned.set_index("Date").sort_index()


def _build_feature_panel(
    etf_frame: pd.DataFrame,
    theme_frame: pd.DataFrame,
    share_frame: pd.DataFrame,
) -> pd.DataFrame:
    etf = _daily_frame(etf_frame, ("Open", "High", "Low", "Close", "Volume", "Amount"))
    theme = _daily_frame(theme_frame, ("Close",))
    if not etf[["Open", "High", "Low", "Close", "Volume", "Amount"]].gt(0).all().all():
        raise ValueError("ETF price, volume and amount must be positive")
    if not theme["Close"].gt(0).all():
        raise ValueError("theme close must be positive")

    panel = etf.copy()
    log_close = np.log(panel["Close"])
    return1 = log_close.diff()
    panel["TrendReturn20"] = log_close.diff(20)
    path_length = return1.abs().rolling(20, min_periods=20).sum()
    panel["TrendEfficiency20"] = panel["TrendReturn20"].abs() / path_length
    volatility5 = return1.rolling(5, min_periods=5).std(ddof=0)
    volatility20 = return1.rolling(20, min_periods=20).std(ddof=0)
    panel["VolatilityRatio5To20"] = volatility5 / volatility20
    prior_volume_median = panel["Volume"].shift(1).rolling(20, min_periods=20).median()
    panel["VolumeShock20"] = np.log(panel["Volume"] / prior_volume_median)
    signed_volume = np.sign(return1) * panel["Volume"]
    panel["SignedVolumePressure20"] = (
        signed_volume.rolling(20, min_periods=20).sum()
        / panel["Volume"].rolling(20, min_periods=20).sum()
    )
    amihud = (return1.abs() / panel["Amount"]).rolling(20, min_periods=20).mean()
    panel["LogAmihud20"] = np.log(amihud)

    theme_close = theme["Close"].reindex(panel.index)
    panel["ThemeRelativeReturn20"] = panel["TrendReturn20"] - np.log(theme_close).diff(20)
    aligned_shares = _align_share_change(share_frame, panel.index)
    panel = panel.join(aligned_shares, how="left")
    return panel


def _feature_quality(panel: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    first_ready = max(panel[name].first_valid_index() for name in FEATURES)
    eligible = panel.loc[first_ready:].copy()
    rows: list[dict[str, object]] = []
    for name in FEATURES:
        values = eligible[name]
        finite = values.dropna().map(np.isfinite).all()
        rows.append(
            {
                "Feature": name,
                "FirstReadyDate": panel[name].first_valid_index(),
                "EligibleRows": len(eligible),
                "AvailableRows": int(values.notna().sum()),
                "Coverage": float(values.notna().mean()),
                "Finite": bool(finite),
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
    dates = pd.bdate_range("2024-01-02", periods=420)
    phase = np.arange(len(dates), dtype=float)
    close = 1.0 + 0.001 * phase + 0.03 * np.sin(phase / 11.0)
    etf = pd.DataFrame(
        {
            "Date": dates,
            "Open": close * (1.0 + 0.001 * np.sin(phase / 3.0)),
            "High": close * 1.012,
            "Low": close * 0.988,
            "Close": close,
            "Volume": 1_000_000 + 200_000 * (1.1 + np.sin(phase / 7.0)),
            "Amount": (1_000_000 + 200_000 * (1.1 + np.sin(phase / 7.0))) * close,
        }
    )
    theme = pd.DataFrame(
        {"Date": dates, "Close": 1000.0 + 0.5 * phase + 20.0 * np.sin(phase / 17.0)}
    )
    shares = pd.DataFrame(
        {
            "Date": dates,
            "TotalShare": 1_000_000_000 + 1_000_000 * phase + 5_000_000 * np.sin(phase / 9.0),
        }
    )
    panel = _build_feature_panel(etf, theme, shares)
    eligible, quality = _feature_quality(panel)
    complete = eligible.loc[:, FEATURES].dropna()
    correlation = complete.corr(method="spearman")
    selected, _ = _select_nonredundant(correlation)
    density = _density_summary(eligible, selected)
    if len(complete) < 300 or quality["Finite"].eq(False).any():
        raise ValueError("synthetic feature construction is invalid")
    if not selected or density.empty:
        raise ValueError("synthetic selection or density path is empty")
    changed = etf.copy()
    changed.loc[changed.index[-1], "Close"] *= 1.2
    changed.loc[changed.index[-1], "Volume"] *= 2.0
    changed.loc[changed.index[-1], "Amount"] *= 2.0
    changed_panel = _build_feature_panel(changed, theme, shares)
    pd.testing.assert_frame_equal(
        panel.loc[panel.index[:-1], FEATURES],
        changed_panel.loc[changed_panel.index[:-1], FEATURES],
    )


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Can a small causal set of price-volume, relative-price and ETF-share "
                "features provide complete, nonredundant and sufficiently changing states?"
            ),
            hypothesis=(
                "Trading participation and direct ETF creation-redemption pressure leave "
                "distinct observable states that are dense enough for later alpha testing."
            ),
            falsification_conditions=(
                "Feature coverage or numeric validity is insufficient",
                "Fewer than five features survive the frozen redundancy rule",
                "Fewer than four retained features satisfy the frozen state-density gate",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=(
                Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.DOMESTIC_INDEX_DAILY.value,
                Dataset.ETF_SHARE_SIZE.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Price, volume and primary-market flows summarize revealed trading behavior",
                    "Only information observable by the decision session may define a state",
                ),
                information_paths=(
                    "Persistent or exhausted participation -> observable price-volume state -> residual tradable move",
                    "ETF creation-redemption change -> next-session observable supply-demand state -> residual tradable move",
                ),
                stage_objectives=(
                    "Freeze a small causal feature set without reading future outcomes",
                    "Audit coverage, redundancy and state density before any return test",
                ),
                observation_metrics=(
                    "feature coverage and unique values",
                    "pairwise Spearman redundancy",
                    "rolling 60-session independent extreme-state density",
                ),
                methodology=(
                    "Use eight mechanism-defined features in a fixed order",
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
            raise ValueError("EX04 predecessor receipt differs")

        specifications = (
            ("etf", Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ", START),
            ("theme", Dataset.DOMESTIC_INDEX_DAILY, "931994.CSI", THEME_START),
            ("shares", Dataset.ETF_SHARE_SIZE, "159326.SZ", START),
        )
        frames: dict[str, pd.DataFrame] = {}
        identities: list[dict[str, object]] = []
        for key, dataset, symbol, request_start in specifications:
            result = context.data.fetch(
                DataRequest(
                    dataset,
                    symbol,
                    request_start,
                    END,
                    END,
                    options={"env_file": ".env"},
                )
            )
            if result.status is not DataStatus.READY or result.identity is None:
                raise ValueError(f"{key} DFLS request failed: {result.status.value}")
            frames[key] = result.dataframe.copy()
            identities.append(
                {
                    "Input": key,
                    "Dataset": result.identity.dataset,
                    "Symbol": result.identity.symbol,
                    "Rows": len(result.dataframe),
                    "DataStart": result.identity.data_start,
                    "DataCutoff": result.identity.data_cutoff,
                    "ContentSha256": result.identity.content_sha256,
                }
            )

        panel = _build_feature_panel(frames["etf"], frames["theme"], frames["shares"])
        eligible, quality = _feature_quality(panel)
        complete = eligible.loc[:, FEATURES].dropna()
        correlation = complete.corr(method="spearman")
        selected, removed = _select_nonredundant(correlation)
        density = _density_summary(eligible, selected)

        quality_pass = bool(
            len(complete) >= MINIMUM_COMPLETE_ROWS
            and quality["Coverage"].ge(MINIMUM_COVERAGE).all()
            and quality["Finite"].all()
            and quality["UniqueValues"].ge(MINIMUM_UNIQUE_VALUES).all()
        )
        selection_pass = len(selected) >= MINIMUM_SELECTED_FEATURES
        dense_count = int(density["DensityPass"].sum())
        density_pass = dense_count >= MINIMUM_DENSE_FEATURES
        passes = quality_pass and selection_pass and density_pass
        decision = (
            "PROCEED_TO_FIXED_PRICE_VOLUME_INFORMATION_TEST"
            if passes
            else "STOP_PRICE_VOLUME_FEATURE_SET_ON_DATA_OR_DENSITY"
        )
        summary = {
            "decision": decision,
            "checks": {
                "feature_quality": quality_pass,
                "minimum_selected_features": selection_pass,
                "minimum_dense_features": density_pass,
            },
            "eligible_rows": len(eligible),
            "complete_rows": len(complete),
            "selected_features": selected,
            "removed_features": removed,
            "dense_feature_count": dense_count,
            "reads_post_state_returns": False,
            "candidate_created": False,
            "strategy_rule_created": False,
        }

        ledger = panel.reset_index()
        ledger.to_csv(
            context.workspace.path("feature_ledger.csv.gz"),
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
        pd.DataFrame(identities).to_csv(
            context.workspace.path("input_identities.csv"), index=False, lineterminator="\n"
        )
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        artifacts = tuple(
            context.workspace.register_artifact(name, kind)
            for name, kind in (
                ("feature_ledger.csv.gz", "causal-price-volume-feature-ledger"),
                ("feature_quality.csv", "feature-quality-audit"),
                ("correlation_matrix.csv", "feature-redundancy-audit"),
                ("density_summary.csv", "feature-state-density-audit"),
                ("input_identities.csv", "pinned-input-identities"),
                ("summary.json", "price-volume-data-gate-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if passes else ExperimentOutcome.FAIL,
            facts={
                "decision": decision,
                "eligible_rows": len(eligible),
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
