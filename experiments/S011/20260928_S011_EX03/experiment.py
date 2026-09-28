"""S011 EX03: one frozen sell-side expectation information test."""

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


EXPERIMENT_ID = "20260928_S011_EX03"
PREDECESSOR = "20260928_S011_EX02"
PREDECESSOR_RECEIPT = "365fcd9a147e4edcb4a3bb393706c737e37cb9bff2e44c15f606d0d33601fd73"
TEMPERATURE_SHA256 = "1fa05b10d6a5c902cec67553e8fbada10ded41300dab3a445a7943215a3a4bfa"
EX02_MANIFEST_SHA256 = "7e53324b240bbf26f60aa7c910a9bcd0db841f08d9476e07ed985b1a1354205c"
START = "2024-09-09"
END = "2026-09-24"
HORIZON = 20
MINIMUM_TRAINING_ROWS = 126
BOOTSTRAP_REPETITIONS = 2000
ROUNDTRIP_HURDLE = 0.002
SEED = 2026092803
CONTROLS = (
    "ETFReturn5",
    "ETFReturn20",
    "ETFReturn60",
    "ETFVolatility20",
    "MarketReturn20",
    "ThemeReturn20",
)
FEATURE = "RevisionTemperature20"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _future_open_return(opens: pd.Series, horizon: int) -> pd.Series:
    values = pd.to_numeric(opens, errors="raise").astype(float)
    if not values.gt(0).all():
        raise ValueError("execution opens must be positive")
    return values.shift(-(horizon + 1)) / values.shift(-1) - 1.0


def _log_return(values: pd.Series, window: int) -> pd.Series:
    numeric = pd.to_numeric(values, errors="raise").astype(float)
    if not numeric.gt(0).all():
        raise ValueError("price controls require positive values")
    return np.log(numeric).diff(window)


def _ols_predict(
    train: pd.DataFrame, test: pd.DataFrame, fields: tuple[str, ...]
) -> tuple[np.ndarray, int, float]:
    x = train.loc[:, fields].to_numpy(dtype=float)
    y = train["Outcome"].to_numpy(dtype=float)
    z = test.loc[:, fields].to_numpy(dtype=float)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    if np.any(~np.isfinite(scale)) or np.any(scale == 0):
        raise ValueError("walk-forward design has a constant or invalid field")
    design = np.column_stack((np.ones(len(x)), (x - center) / scale))
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        raise ValueError("walk-forward design is rank deficient")
    condition = float(np.linalg.cond(design))
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    future = np.column_stack((np.ones(len(z)), (z - center) / scale))
    return future @ coefficients, rank, condition


def _walk_forward(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    required = [*CONTROLS, FEATURE, "Outcome", "RawETFOutcome", "OutcomeEnd"]
    eligible = frame.dropna(subset=required).copy().sort_index()
    predictions: list[dict[str, object]] = []
    fits: list[dict[str, object]] = []
    for decision_date, row in eligible.iterrows():
        train = eligible.loc[eligible["OutcomeEnd"].lt(decision_date)]
        if len(train) < MINIMUM_TRAINING_ROWS:
            continue
        test = row.to_frame().T
        baseline, base_rank, base_condition = _ols_predict(train, test, CONTROLS)
        extended, ext_rank, ext_condition = _ols_predict(
            train, test, (*CONTROLS, FEATURE)
        )
        predictions.append(
            {
                "Date": decision_date,
                "OutcomeEnd": row["OutcomeEnd"],
                "Outcome": float(row["Outcome"]),
                "RawETFOutcome": float(row["RawETFOutcome"]),
                "MarketOutcome": float(row["MarketOutcome"]),
                "FeatureValue": float(row[FEATURE]),
                "BaselinePrediction": float(baseline[0]),
                "ExtendedPrediction": float(extended[0]),
            }
        )
        fits.append(
            {
                "Date": decision_date,
                "TrainingN": len(train),
                "TrainingMaxOutcomeEnd": train["OutcomeEnd"].max(),
                "BaselineRank": base_rank,
                "BaselineConditionNumber": base_condition,
                "ExtendedRank": ext_rank,
                "ExtendedConditionNumber": ext_condition,
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
    ) ** 2 - (
        prediction_frame["Outcome"] - prediction_frame["ExtendedPrediction"]
    ) ** 2
    prediction_frame["BaselineResidual"] = (
        prediction_frame["Outcome"] - prediction_frame["BaselinePrediction"]
    )
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
    ordered = predictions.sort_values("FeatureValue", kind="mergesort")
    count = len(ordered) // 5
    if count < 1:
        raise ValueError("insufficient observations for quintile diagnostics")
    low = ordered.iloc[:count]
    high = ordered.iloc[-count:]
    return {
        "group_size": count,
        "low_market_excess_mean": float(low["Outcome"].mean()),
        "high_market_excess_mean": float(high["Outcome"].mean()),
        "market_excess_spread": float(high["Outcome"].mean() - low["Outcome"].mean()),
        "high_raw_etf_mean": float(high["RawETFOutcome"].mean()),
    }


def _build_panel(
    temperature: pd.DataFrame,
    etf: pd.DataFrame,
    market: pd.DataFrame,
    theme: pd.DataFrame,
) -> pd.DataFrame:
    def indexed(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        value = frame.copy()
        value["Date"] = pd.to_datetime(value["Date"]).dt.normalize()
        if value["Date"].duplicated().any():
            raise ValueError(f"{prefix} contains duplicate dates")
        return value.set_index("Date").sort_index().add_prefix(prefix)

    temp = temperature.copy()
    temp["Date"] = pd.to_datetime(temp["Date"]).dt.normalize()
    if temp["Date"].duplicated().any():
        raise ValueError("temperature contains duplicate dates")
    panel = temp.set_index("Date")[[FEATURE]].sort_index()
    panel = panel.join(indexed(etf, "ETF"), how="inner")
    panel = panel.join(indexed(market, "Market"), how="inner")
    panel = panel.join(indexed(theme, "Theme"), how="inner")
    panel["ETFReturn5"] = _log_return(panel["ETFClose"], 5)
    panel["ETFReturn20"] = _log_return(panel["ETFClose"], 20)
    panel["ETFReturn60"] = _log_return(panel["ETFClose"], 60)
    panel["ETFVolatility20"] = np.log(panel["ETFClose"]).diff().rolling(20).std(ddof=0)
    panel["MarketReturn20"] = _log_return(panel["MarketClose"], 20)
    panel["ThemeReturn20"] = _log_return(panel["ThemeClose"], 20)
    panel["RawETFOutcome"] = _future_open_return(panel["ETFOpen"], HORIZON)
    panel["MarketOutcome"] = _future_open_return(panel["MarketOpen"], HORIZON)
    panel["Outcome"] = panel["RawETFOutcome"] - panel["MarketOutcome"]
    dates = pd.Series(panel.index, index=panel.index)
    panel["OutcomeEnd"] = dates.shift(-(HORIZON + 1))
    return panel


def synthetic_precheck() -> None:
    opens = pd.Series([10.0, 11.0, 12.0, 15.0], index=pd.bdate_range("2024-01-01", periods=4))
    if not np.isclose(float(_future_open_return(opens, 2).iloc[0]), 15 / 11 - 1):
        raise ValueError("T+1 to T+H+1 alignment changed")
    rng = np.random.default_rng(SEED)
    dates = pd.bdate_range("2020-01-01", periods=500)
    synthetic = pd.DataFrame(index=dates)
    for field in CONTROLS:
        synthetic[field] = rng.normal(size=len(dates))
    synthetic[FEATURE] = rng.normal(size=len(dates))
    synthetic["Outcome"] = 0.01 * synthetic[FEATURE] + rng.normal(scale=0.01, size=len(dates))
    synthetic["RawETFOutcome"] = synthetic["Outcome"] + 0.002
    synthetic["MarketOutcome"] = 0.002
    synthetic["OutcomeEnd"] = pd.Series(dates, index=dates).shift(-(HORIZON + 1))
    predictions, fits = _walk_forward(synthetic)
    if len(predictions) < 200 or not fits["TrainingMaxOutcomeEnd"].lt(fits["Date"]).all():
        raise ValueError("synthetic walk-forward boundary changed")
    bootstrap = _block_bootstrap(predictions["LossImprovement"])
    if not all(np.isfinite(value) for value in bootstrap.values()):
        raise ValueError("synthetic bootstrap is invalid")
    if HORIZON != 20 or MINIMUM_TRAINING_ROWS != 126 or ROUNDTRIP_HURDLE != 0.002:
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
                "Does the frozen sell-side expectation temperature add 20-session "
                "market-excess return information beyond price-state controls?"
            ),
            hypothesis=(
                "Broad upward earnings revisions contain residual repricing information "
                "after own-price, market and theme-price controls."
            ),
            falsification_conditions=(
                "The extended walk-forward model does not reduce paired squared loss",
                "Temperature direction is not positive in both calendar years",
                "The high-minus-low temperature spread does not clear 20 basis points",
                "Extended prediction ranking does not improve on the price baseline",
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
                    "Alpha requires information beyond already observable price state",
                    "A tradable close decision must enter no earlier than the next open",
                ),
                information_paths=(
                    "Causal forecast revision breadth -> residual theme repricing -> 20-session market excess return",
                ),
                stage_objectives=(
                    "Run exactly one frozen return-increment test for the sell-side route",
                ),
                observation_metrics=(
                    "walk-forward paired MSE improvement and block p-value",
                    "annual and residual rank correlation",
                    "temperature quintile market-excess spread and raw ETF upside",
                ),
                methodology=(
                    "Pin the EX02 temperature artifact and receipt",
                    "Use T+1 to T+21 open returns and label-maturity-purged expanding OLS",
                    "Use one horizon, one feature, one 20-session block bootstrap",
                    "Stop the route on any frozen gate failure",
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
            raise ValueError("EX02 predecessor receipt differs")
        root = Path(__file__).resolve().parents[3]
        ex02 = root / "experiments" / "S011" / PREDECESSOR
        temperature_path = ex02 / "artifacts" / "expectation_temperature.csv.gz"
        if (
            _sha256(temperature_path) != TEMPERATURE_SHA256
            or _sha256(ex02 / "experiment_manifest.json") != EX02_MANIFEST_SHA256
        ):
            raise ValueError("EX02 frozen temperature or manifest identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)

        specifications = (
            ("etf", Dataset.ETF_UNADJUSTED_DAILY, "159326.SZ"),
            ("market", Dataset.DOMESTIC_INDEX_DAILY, "000300.SH"),
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
                "Input": "expectation_temperature",
                "Dataset": "experiment_artifact",
                "Symbol": "159326.SZ",
                "Rows": None,
                "DataStart": START,
                "DataCutoff": END,
                "ContentSha256": TEMPERATURE_SHA256,
            }
        )
        temperature = pd.read_csv(temperature_path, parse_dates=["Date"])
        panel = _build_panel(
            temperature, frames["etf"], frames["market"], frames["theme"]
        )
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
                        "FeatureOutcomeRankIC": _rank_ic(
                            group["FeatureValue"], group["Outcome"]
                        ),
                        "MeanMarketExcessOutcome": float(group["Outcome"].mean()),
                    }
                ),
                include_groups=False,
            )
            .reset_index()
        )
        annual_ics = {
            int(row.Year): float(row.FeatureOutcomeRankIC)
            for row in annual.itertuples(index=False)
        }
        baseline_rank_ic = _rank_ic(
            predictions["BaselinePrediction"], predictions["Outcome"]
        )
        extended_rank_ic = _rank_ic(
            predictions["ExtendedPrediction"], predictions["Outcome"]
        )
        residual_rank_ic = _rank_ic(
            predictions["FeatureValue"], predictions["BaselineResidual"]
        )
        checks = {
            "evaluation_rows": len(predictions) >= 200,
            "positive_loss_improvement": bootstrap["mean"] > 0,
            "bootstrap_pvalue": bootstrap["one_sided_pvalue"] <= 0.10,
            "positive_rank_ic_2025": annual_ics.get(2025, 0.0) > 0,
            "positive_rank_ic_2026": annual_ics.get(2026, 0.0) > 0,
            "positive_residual_rank_ic": residual_rank_ic > 0,
            "quintile_spread_clears_hurdle": quintiles["market_excess_spread"]
            > ROUNDTRIP_HURDLE,
            "positive_high_quintile_raw_return": quintiles["high_raw_etf_mean"] > 0,
            "extended_rank_ic_improves": extended_rank_ic > baseline_rank_ic,
        }
        qualifies = all(checks.values())
        decision = (
            "PROCEED_TO_COMPONENT_ROLE_REVIEW"
            if qualifies
            else "STOP_SELL_SIDE_EXPECTATION_PATH"
        )
        summary = {
            "decision": decision,
            "checks": checks,
            "evaluation_rows": len(predictions),
            "horizon_sessions": HORIZON,
            "minimum_training_rows": MINIMUM_TRAINING_ROWS,
            "loss_improvement": bootstrap,
            "annual_rank_ic": {str(key): value for key, value in annual_ics.items()},
            "baseline_rank_ic": baseline_rank_ic,
            "extended_rank_ic": extended_rank_ic,
            "residual_rank_ic": residual_rank_ic,
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
            compression="gzip",
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
            context.workspace.path("annual_diagnostics.csv"),
            index=False,
            lineterminator="\n",
        )
        pd.DataFrame(identities).to_csv(
            context.workspace.path("input_identities.csv"),
            index=False,
            lineterminator="\n",
        )
        context.workspace.path("summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        artifacts = tuple(
            context.workspace.register_artifact(name, kind)
            for name, kind in (
                ("walk_forward_predictions.csv.gz", "causal-walk-forward-predictions"),
                ("walk_forward_fits.csv", "label-maturity-fit-ledger"),
                ("annual_diagnostics.csv", "annual-direction-diagnostics"),
                ("input_identities.csv", "pinned-input-identities"),
                ("summary.json", "sell-side-information-test-summary"),
            )
        )
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if qualifies else ExperimentOutcome.FAIL,
            facts={
                "decision": decision,
                "evaluation_rows": len(predictions),
                "loss_improvement": bootstrap["mean"],
                "bootstrap_pvalue": bootstrap["one_sided_pvalue"],
                "market_excess_quintile_spread": quintiles["market_excess_spread"],
            },
            diagnostics={
                "checks": checks,
                "annual_rank_ic": summary["annual_rank_ic"],
                "reads_sealed_validation": False,
                "candidate_created": False,
            },
            artifacts=artifacts,
        )
