"""S011 EX07: frozen price-volume information increment test."""

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


EXPERIMENT_ID = "20260928_S011_EX07"
PREDECESSOR = "20260928_S011_EX06"
PREDECESSOR_RECEIPT = "2aebd2d959507e4123eb942344df4eeaad48a742dd3c77a4dc47f9fa8eb8bba2"
FEATURE_LEDGER_SHA256 = "e78f2e91b7f15067d4150268846880beac1c9be13d387e718dfdb1f02ae33aed"
EX06_MANIFEST_SHA256 = "46fe82cc657c07753c769b8f9006ee8c1c2f2aa42c06ba484c14c08b84323692"
START = "2024-10-24"
END = "2026-09-24"
HORIZON = 10
MINIMUM_TRAINING_ROWS = 160
RIDGE_PENALTY = 1.0
BOOTSTRAP_REPETITIONS = 2000
ROUNDTRIP_HURDLE = 0.002
SEED = 2026092807
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


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _future_open_return(opens: pd.Series, horizon: int) -> pd.Series:
    values = pd.to_numeric(opens, errors="raise").astype(float)
    if not values.gt(0).all():
        raise ValueError("execution opens must be positive")
    return values.shift(-(horizon + 1)) / values.shift(-1) - 1.0


def _ridge_predict(
    train: pd.DataFrame, test: pd.DataFrame
) -> tuple[float, dict[str, float], float]:
    x = train.loc[:, FEATURES].to_numpy(dtype=float)
    y = train["Outcome"].to_numpy(dtype=float)
    z = test.loc[list(FEATURES)].to_numpy(dtype=float)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    if np.any(~np.isfinite(scale)) or np.any(scale == 0):
        raise ValueError("walk-forward design has a constant or invalid feature")
    standardized = (x - center) / scale
    design = np.column_stack((np.ones(len(x)), standardized))
    penalty = np.diag([0.0, *([RIDGE_PENALTY] * len(FEATURES))])
    gram = design.T @ design + penalty
    coefficients = np.linalg.solve(gram, design.T @ y)
    future = np.concatenate(([1.0], (z - center) / scale))
    prediction = float(future @ coefficients)
    named = {name: float(value) for name, value in zip(FEATURES, coefficients[1:])}
    return prediction, named, float(np.linalg.cond(gram))


def _walk_forward(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = [*FEATURES, "Outcome", "RawETFOutcome", "ThemeOutcome", "OutcomeEnd"]
    eligible = frame.dropna(subset=required).copy().sort_index()
    predictions: list[dict[str, object]] = []
    fits: list[dict[str, object]] = []
    for decision_date, row in eligible.iterrows():
        train = eligible.loc[eligible["OutcomeEnd"].lt(decision_date)]
        if len(train) < MINIMUM_TRAINING_ROWS:
            continue
        baseline = float(train["Outcome"].mean())
        prediction, coefficients, condition = _ridge_predict(train, row)
        predictions.append(
            {
                "Date": decision_date,
                "OutcomeEnd": row["OutcomeEnd"],
                "Outcome": float(row["Outcome"]),
                "RawETFOutcome": float(row["RawETFOutcome"]),
                "ThemeOutcome": float(row["ThemeOutcome"]),
                "BaselinePrediction": baseline,
                "ExtendedPrediction": prediction,
            }
        )
        fits.append(
            {
                "Date": decision_date,
                "TrainingN": len(train),
                "TrainingMaxOutcomeEnd": train["OutcomeEnd"].max(),
                "GramConditionNumber": condition,
                **{f"Coefficient_{name}": value for name, value in coefficients.items()},
            }
        )
    prediction_frame = pd.DataFrame(predictions)
    fit_frame = pd.DataFrame(fits)
    if prediction_frame.empty or fit_frame.empty:
        raise ValueError("walk-forward evaluation produced no predictions")
    if not fit_frame["TrainingMaxOutcomeEnd"].lt(fit_frame["Date"]).all():
        raise ValueError("walk-forward training contains an immature label")
    prediction_frame["LossImprovement"] = (
        prediction_frame["Outcome"] - prediction_frame["BaselinePrediction"]
    ) ** 2 - (prediction_frame["Outcome"] - prediction_frame["ExtendedPrediction"]) ** 2
    return prediction_frame, fit_frame


def _rank_ic(first: pd.Series, second: pd.Series) -> float:
    value = first.corr(second, method="spearman")
    if pd.isna(value):
        raise ValueError("rank correlation is unavailable")
    return float(value)


def _block_bootstrap(values: pd.Series) -> dict[str, float]:
    observed = pd.to_numeric(values, errors="raise").to_numpy(dtype=float)
    if len(observed) < HORIZON * 3:
        raise ValueError("insufficient observations for block bootstrap")
    starts = np.arange(len(observed) - HORIZON + 1)
    blocks = int(np.ceil(len(observed) / HORIZON))
    rng = np.random.default_rng(SEED)
    means = np.empty(BOOTSTRAP_REPETITIONS, dtype=float)
    for index in range(BOOTSTRAP_REPETITIONS):
        draw = rng.choice(starts, size=blocks, replace=True)
        positions = (draw[:, None] + np.arange(HORIZON)).reshape(-1)[: len(observed)]
        means[index] = float(observed[positions].mean())
    lower, upper = np.quantile(means, (0.025, 0.975))
    pvalue = (1 + int(np.sum(means <= 0.0))) / (BOOTSTRAP_REPETITIONS + 1)
    return {
        "mean": float(observed.mean()),
        "ci95_lower": float(lower),
        "ci95_upper": float(upper),
        "one_sided_pvalue": float(pvalue),
    }


def _quintile_diagnostics(predictions: pd.DataFrame) -> dict[str, float]:
    ordered = predictions.sort_values("ExtendedPrediction", kind="mergesort")
    count = len(ordered) // 5
    if count < 1:
        raise ValueError("insufficient observations for quintile diagnostics")
    low = ordered.iloc[:count]
    high = ordered.iloc[-count:]
    return {
        "group_size": count,
        "low_theme_excess_mean": float(low["Outcome"].mean()),
        "high_theme_excess_mean": float(high["Outcome"].mean()),
        "theme_excess_spread": float(high["Outcome"].mean() - low["Outcome"].mean()),
        "high_raw_etf_mean": float(high["RawETFOutcome"].mean()),
    }


def _indexed(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
    value = frame.copy()
    value["Date"] = pd.to_datetime(value["Date"], errors="raise").dt.normalize()
    if value["Date"].duplicated().any():
        raise ValueError(f"{prefix} input contains duplicate dates")
    return value.set_index("Date").sort_index().add_prefix(prefix)


def _build_panel(features: pd.DataFrame, etf: pd.DataFrame, theme: pd.DataFrame) -> pd.DataFrame:
    feature_frame = features.copy()
    feature_frame["Date"] = pd.to_datetime(feature_frame["Date"], errors="raise").dt.normalize()
    if feature_frame["Date"].duplicated().any():
        raise ValueError("feature ledger contains duplicate dates")
    missing = sorted(set(FEATURES).difference(feature_frame.columns))
    if missing:
        raise ValueError(f"feature ledger is missing fields: {missing}")
    panel = feature_frame.set_index("Date").loc[:, FEATURES].sort_index()
    panel = panel.join(_indexed(etf, "ETF"), how="inner")
    panel = panel.join(_indexed(theme, "Theme"), how="inner")
    panel["RawETFOutcome"] = _future_open_return(panel["ETFOpen"], HORIZON)
    panel["ThemeOutcome"] = _future_open_return(panel["ThemeOpen"], HORIZON)
    panel["Outcome"] = panel["RawETFOutcome"] - panel["ThemeOutcome"]
    dates = pd.Series(panel.index, index=panel.index)
    panel["OutcomeEnd"] = dates.shift(-(HORIZON + 1))
    return panel


def synthetic_precheck() -> None:
    opens = pd.Series([10.0, 11.0, 12.0, 15.0], index=pd.bdate_range("2024-01-01", periods=4))
    if not np.isclose(float(_future_open_return(opens, 2).iloc[0]), 15 / 11 - 1):
        raise ValueError("T+1 to T+H+1 alignment changed")
    rng = np.random.default_rng(SEED)
    dates = pd.bdate_range("2020-01-01", periods=520)
    synthetic = pd.DataFrame(index=dates)
    for feature in FEATURES:
        synthetic[feature] = rng.normal(size=len(dates))
    synthetic["Outcome"] = (
        0.004 * synthetic[FEATURES[0]]
        - 0.003 * synthetic[FEATURES[3]]
        + rng.normal(scale=0.01, size=len(dates))
    )
    synthetic["RawETFOutcome"] = synthetic["Outcome"] + 0.002
    synthetic["ThemeOutcome"] = 0.002
    synthetic["OutcomeEnd"] = pd.Series(dates, index=dates).shift(-(HORIZON + 1))
    predictions, fits = _walk_forward(synthetic)
    if len(predictions) < 200 or not fits["TrainingMaxOutcomeEnd"].lt(fits["Date"]).all():
        raise ValueError("synthetic walk-forward boundary changed")
    bootstrap = _block_bootstrap(predictions["LossImprovement"])
    if not all(np.isfinite(value) for value in bootstrap.values()):
        raise ValueError("synthetic bootstrap is invalid")
    if HORIZON != 10 or MINIMUM_TRAINING_ROWS != 160 or RIDGE_PENALTY != 1.0:
        raise ValueError("frozen information-test constants changed")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S011",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Does the frozen eight-feature trading-state set predict executable "
                "10-session theme-excess return in causal walk-forward evaluation?"
            ),
            hypothesis=(
                "Joint price, volume, liquidity, relative-strength and ETF-share states "
                "contain residual participation information beyond the unconditional mean."
            ),
            falsification_conditions=(
                "The feature model does not reduce paired squared loss",
                "Prediction direction is not positive in both calendar years",
                "The prediction quintile spread does not clear 20 basis points",
            ),
            development_cutoff=date(2026, 9, 24),
            random_seed=SEED,
            allowed_datasets=(
                Dataset.ETF_UNADJUSTED_DAILY.value,
                Dataset.DOMESTIC_INDEX_DAILY.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Alpha is return remaining after the tracked theme move",
                    "A close-known state may execute no earlier than the next open",
                ),
                information_paths=(
                    "Frozen joint trading state -> residual participation or exhaustion -> 10-session theme-excess return",
                ),
                stage_objectives=(
                    "Run exactly one fixed linear return-information test for the EX06 set",
                ),
                observation_metrics=(
                    "walk-forward paired loss improvement and block p-value",
                    "overall and annual prediction rank correlation",
                    "prediction quintile theme-excess spread and raw ETF upside",
                ),
                methodology=(
                    "Pin the EX06 feature ledger and receipt",
                    "Use T+1 to T+11 open returns and label-maturity-purged expanding training",
                    "Compare fixed Ridge penalty 1.0 with the mature historical-mean baseline",
                    "Stop the frozen linear set on any frozen gate failure",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            subjects=("159326.SZ",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX06 predecessor receipt differs")
        root = Path(__file__).resolve().parents[3]
        ex06 = root / "experiments" / "S011" / PREDECESSOR
        ledger_path = ex06 / "artifacts" / "feature_ledger.csv.gz"
        if (
            _sha256(ledger_path) != FEATURE_LEDGER_SHA256
            or _sha256(ex06 / "experiment_manifest.json") != EX06_MANIFEST_SHA256
        ):
            raise ValueError("EX06 frozen feature ledger or manifest identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)

        specifications = (
            ("etf", Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ"),
            ("theme", Dataset.DOMESTIC_INDEX_DAILY, "931994.CSI"),
        )
        frames: dict[str, pd.DataFrame] = {}
        identities: list[dict[str, object]] = []
        for key, dataset, symbol in specifications:
            result = context.data.fetch(
                DataRequest(
                    dataset,
                    symbol,
                    START,
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
        identities.append(
            {
                "Input": "feature_ledger",
                "Dataset": "experiment_artifact",
                "Symbol": "159326.SZ",
                "Rows": None,
                "DataStart": START,
                "DataCutoff": END,
                "ContentSha256": FEATURE_LEDGER_SHA256,
            }
        )

        feature_ledger = pd.read_csv(ledger_path, parse_dates=["Date"])
        panel = _build_panel(feature_ledger, frames["etf"], frames["theme"])
        predictions, fits = _walk_forward(panel)
        bootstrap = _block_bootstrap(predictions["LossImprovement"])
        quintiles = _quintile_diagnostics(predictions)
        annual = (
            predictions.assign(Year=pd.to_datetime(predictions["Date"]).dt.year)
            .groupby("Year")
            .apply(
                lambda group: pd.Series(
                    {
                        "N": len(group),
                        "PredictionOutcomeRankIC": _rank_ic(
                            group["ExtendedPrediction"], group["Outcome"]
                        ),
                        "MeanThemeExcessOutcome": float(group["Outcome"].mean()),
                    }
                ),
                include_groups=False,
            )
            .reset_index()
        )
        annual_ics = {
            int(row.Year): float(row.PredictionOutcomeRankIC)
            for row in annual.itertuples(index=False)
        }
        overall_rank_ic = _rank_ic(predictions["ExtendedPrediction"], predictions["Outcome"])
        checks = {
            "evaluation_rows": len(predictions) >= 200,
            "positive_loss_improvement": bootstrap["mean"] > 0,
            "bootstrap_pvalue": bootstrap["one_sided_pvalue"] <= 0.10,
            "positive_overall_rank_ic": overall_rank_ic > 0,
            "positive_rank_ic_2025": annual_ics.get(2025, 0.0) > 0,
            "positive_rank_ic_2026": annual_ics.get(2026, 0.0) > 0,
            "quintile_spread_clears_hurdle": quintiles["theme_excess_spread"] > ROUNDTRIP_HURDLE,
            "positive_high_quintile_raw_return": quintiles["high_raw_etf_mean"] > 0,
        }
        qualifies = all(checks.values())
        decision = (
            "PROCEED_TO_PRICE_VOLUME_COMPONENT_ROLE_REVIEW"
            if qualifies
            else "STOP_FROZEN_LINEAR_PRICE_VOLUME_SET"
        )
        summary = {
            "decision": decision,
            "checks": checks,
            "evaluation_rows": len(predictions),
            "horizon_sessions": HORIZON,
            "minimum_training_rows": MINIMUM_TRAINING_ROWS,
            "ridge_penalty": RIDGE_PENALTY,
            "loss_improvement": bootstrap,
            "overall_rank_ic": overall_rank_ic,
            "annual_rank_ic": {str(key): value for key, value in annual_ics.items()},
            "quintiles": quintiles,
            "roundtrip_hurdle": ROUNDTRIP_HURDLE,
            "reads_real_returns": True,
            "reads_sealed_validation": False,
            "candidate_created": False,
            "strategy_rule_created": False,
        }
        predictions.to_csv(
            context.workspace.path("walk_forward_predictions.csv.gz"),
            index=False,
            compression={"method": "gzip", "compresslevel": 9, "mtime": 0},
            lineterminator="\n",
            date_format="%Y-%m-%d",
        )
        fits.to_csv(
            context.workspace.path("walk_forward_fits.csv"),
            index=False,
            lineterminator="\n",
            date_format="%Y-%m-%d",
        )
        annual.to_csv(
            context.workspace.path("annual_diagnostics.csv"), index=False, lineterminator="\n"
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
                ("walk_forward_predictions.csv.gz", "causal-walk-forward-predictions"),
                ("walk_forward_fits.csv", "label-maturity-ridge-fit-ledger"),
                ("annual_diagnostics.csv", "annual-direction-diagnostics"),
                ("input_identities.csv", "pinned-input-identities"),
                ("summary.json", "price-volume-information-test-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if qualifies else ExperimentOutcome.FAIL,
            facts={
                "decision": decision,
                "evaluation_rows": len(predictions),
                "loss_improvement": bootstrap["mean"],
                "bootstrap_pvalue": bootstrap["one_sided_pvalue"],
                "overall_rank_ic": overall_rank_ic,
                "theme_excess_quintile_spread": quintiles["theme_excess_spread"],
            },
            diagnostics={
                "checks": checks,
                "annual_rank_ic": summary["annual_rank_ic"],
                "reads_sealed_validation": False,
                "candidate_created": False,
            },
            artifacts=artifacts,
        )
