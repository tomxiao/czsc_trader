from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import Dataset
import numpy as np
import pandas as pd
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


EXPERIMENT_ID = "20260925_S008_EX88"
PREDECESSOR = "20260925_S008_EX87"
PREDECESSOR_RECEIPT = "40689943d49e0f9832ac0f372803e77fa9b891d652f6e19fd96d5a1a2af73020"
PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
PRICE = (
    "price_return_5d",
    "price_return_20d",
    "price_return_60d",
    "price_return_120d",
    "price_volatility_20",
)
SGE = ("gold_sge_return_5d", "gold_sge_return_20d", "gold_sge_trend_distance_60")
FX = ("currency_usdcnh_return_20d",)
VARIANTS = {
    "PRICE": PRICE,
    "PRICE+SGE": PRICE + SGE,
    "PRICE+FX": PRICE + FX,
    "PRICE+SGE+FX": PRICE + SGE + FX,
}
STATES = ("START", "PERSIST", "PULLBACK", "WEAK")
HORIZONS = (20, 60)
EVALUATION_YEARS = tuple(range(2019, 2025))
SEED = 20260925
BOOTSTRAP_REPETITIONS = 2000


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _future_open_return(opens: pd.Series, horizon: int) -> pd.Series:
    # A T-close decision first fills at T+1 open; H sessions later is T+H+1 open.
    return opens.shift(-(horizon + 1)) / opens.shift(-1) - 1.0


def _states(frame: pd.DataFrame) -> pd.Series:
    short = frame["price_return_20d"].gt(0)
    medium = frame["price_return_60d"].gt(0)
    values = np.select(
        (~medium & short, medium & short, medium & ~short, ~medium & ~short),
        STATES,
        default="",
    )
    return pd.Series(values, index=frame.index, name="State")


def _ols_predict(
    train: pd.DataFrame, test: pd.DataFrame, fields: tuple[str, ...]
) -> tuple[np.ndarray | None, int, float | None]:
    x = train.loc[:, fields].to_numpy(dtype=float)
    y = train["Outcome"].to_numpy(dtype=float)
    z = test.loc[:, fields].to_numpy(dtype=float)
    if len(x) <= len(fields) + 1:
        return None, 0, None
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    if np.any(~np.isfinite(scale)) or np.any(scale == 0):
        return None, 0, None
    design = np.column_stack((np.ones(len(x)), (x - center) / scale))
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        return None, rank, float(np.linalg.cond(design))
    coefficients = np.linalg.lstsq(design, y, rcond=None)[0]
    future = np.column_stack((np.ones(len(z)), (z - center) / scale))
    return future @ coefficients, rank, float(np.linalg.cond(design))


def _bh(values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().sort_values()
    if valid.empty:
        return result
    adjusted = valid.to_numpy() * len(valid) / np.arange(1, len(valid) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result.loc[valid.index] = np.minimum(adjusted, 1.0)
    return result


def _ranking_diagnostics(outcome: np.ndarray, prediction: np.ndarray) -> dict[str, float | None]:
    if len(outcome) < 5 or np.unique(prediction).size < 5:
        return {"rank_ic": None, "quintile_spread": None, "upside_capture": None, "downside_avoidance": None}
    rank_ic = pd.Series(outcome).corr(pd.Series(prediction), method="spearman")
    order = np.argsort(prediction, kind="stable")
    count = max(1, len(order) // 5)
    spread = float(outcome[order[-count:]].mean() - outcome[order[:count]].mean())
    positive = np.maximum(outcome, 0)
    negative = np.maximum(-outcome, 0)
    upside = float(positive[prediction > 0].sum() / positive.sum()) if positive.sum() > 0 else None
    avoidance = float(negative[prediction <= 0].sum() / negative.sum()) if negative.sum() > 0 else None
    return {
        "rank_ic": float(rank_ic) if pd.notna(rank_ic) else None,
        "quintile_spread": spread,
        "upside_capture": upside,
        "downside_avoidance": avoidance,
    }


def _bootstrap(
    calendar: pd.DatetimeIndex,
    observations: pd.DataFrame,
    horizon: int,
    repetitions: int,
    seed: int,
) -> tuple[float | None, float | None, float | None, int]:
    series = observations.set_index("Date")["LossImprovement"].reindex(calendar)
    observed = series.dropna()
    state_days = series.notna().to_numpy()
    runs = int(np.sum(state_days & ~np.r_[False, state_days[:-1]]))
    if len(observed) < 2 or runs < 2 or len(calendar) < horizon:
        return None, None, None, runs
    values = series.to_numpy(dtype=float)
    length = len(values)
    blocks = (length + horizon - 1) // horizon
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, length - horizon + 1, size=(repetitions, blocks))
    sampled_indices = (starts[:, :, None] + np.arange(horizon)).reshape(repetitions, -1)[:, :length]
    sampled = values[sampled_indices]
    counts = np.isfinite(sampled).sum(axis=1)
    means = np.divide(
        np.nansum(sampled, axis=1),
        counts,
        out=np.full(repetitions, np.nan),
        where=counts > 0,
    )
    valid = means[np.isfinite(means)]
    if len(valid) != repetitions:
        return None, None, None, runs
    center = float(observed.mean())
    lower, upper = np.quantile(valid, (0.025, 0.975))
    # Resampling the centered loss differences represents the zero-improvement null.
    pvalue = (1 + int(np.sum(valid - center >= center))) / (repetitions + 1)
    return float(lower), float(upper), float(pvalue), runs


def _audit(frame: pd.DataFrame, repetitions: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    source = frame.copy()
    if not source.index.is_unique or not source.index.is_monotonic_increasing:
        raise ValueError("market dates must be unique and ordered")
    if source.index.max() > pd.Timestamp("2024-12-31") or source["Open"].isna().any():
        raise ValueError("missing open or date beyond development cutoff")
    for field in set(PRICE + SGE + FX):
        if field not in source:
            raise ValueError(f"missing frozen factor: {field}")
    original_dates = pd.Series(source.index, index=source.index)
    source["State"] = _states(source)
    coverage = source.loc[source[list(set(PRICE + SGE + FX))].notna().all(axis=1)]
    coverage = coverage.assign(Year=coverage.index.year)
    counts = coverage.groupby(["Year", "State"]).size()
    coverage_rows = [
        {"Year": year, "State": state, "EligibleSessions": int(counts.get((year, state), 0))}
        for year in range(2013, 2025) for state in STATES
    ]
    prediction_rows: list[dict[str, object]] = []
    fit_rows: list[dict[str, object]] = []
    all_fields = list(dict.fromkeys(PRICE + SGE + FX))
    for horizon in HORIZONS:
        eligible = source.copy()
        eligible["Outcome"] = _future_open_return(source["Open"], horizon)
        eligible["OutcomeEnd"] = original_dates.shift(-(horizon + 1))
        eligible = eligible.dropna(subset=all_fields + ["Outcome", "OutcomeEnd"])
        for year in EVALUATION_YEARS:
            first_day = pd.Timestamp(year=year, month=1, day=1)
            train_history = eligible.loc[eligible["OutcomeEnd"] < first_day]
            test_history = eligible.loc[eligible.index.year == year]
            for state in STATES:
                train = train_history.loc[train_history["State"] == state]
                test = test_history.loc[test_history["State"] == state]
                if test.empty:
                    continue
                pred: dict[str, np.ndarray | None] = {}
                for variant, fields in VARIANTS.items():
                    output, rank, condition = _ols_predict(train, test, fields)
                    pred[variant] = output
                    fit_rows.append({
                        "Horizon": horizon, "Year": year, "State": state,
                        "Variant": variant, "TrainingN": len(train), "EvaluationN": len(test),
                        "DesignRank": rank, "ConditionNumber": condition,
                        "Identifiable": output is not None,
                    })
                for row, (dt, item) in enumerate(test.iterrows()):
                    prediction_rows.append({
                        "Date": dt, "Year": year, "State": state, "Horizon": horizon,
                        "Outcome": float(item["Outcome"]),
                        **{
                            "Prediction_" + variant: (
                                float(values[row]) if values is not None else np.nan
                            )
                            for variant, values in pred.items()
                        },
                    })
    predictions = pd.DataFrame(prediction_rows).sort_values(["Horizon", "Date"])
    fits = pd.DataFrame(fit_rows)
    comparisons: list[dict[str, object]] = []
    for horizon in HORIZONS:
        cal = predictions.loc[predictions["Horizon"] == horizon, "Date"].sort_values().unique()
        calendar = pd.DatetimeIndex(cal)
        for state in STATES:
            group = predictions.loc[
                (predictions["Horizon"] == horizon) & (predictions["State"] == state)
            ]
            for variant in tuple(VARIANTS)[1:]:
                name = "Prediction_" + variant
                pair = group.dropna(subset=["Prediction_PRICE", name]).copy()
                if pair.empty:
                    comparisons.append({
                        "Horizon": horizon, "State": state, "Variant": variant,
                        "EvaluationN": 0, "Status": "UNIDENTIFIABLE",
                    })
                    continue
                outcome = pair["Outcome"].to_numpy(dtype=float)
                base = pair["Prediction_PRICE"].to_numpy(dtype=float)
                extended = pair[name].to_numpy(dtype=float)
                pair["LossImprovement"] = (outcome - base) ** 2 - (outcome - extended) ** 2
                lower, upper, pvalue, runs = _bootstrap(
                    calendar, pair[["Date", "LossImprovement"]], horizon,
                    repetitions, SEED + horizon + STATES.index(state) * 100 + list(VARIANTS).index(variant),
                )
                baseline = _ranking_diagnostics(outcome, base)
                extension = _ranking_diagnostics(outcome, extended)
                annual = pair.groupby("Year")["LossImprovement"].agg(["count", "mean"])
                comparisons.append({
                    "Horizon": horizon, "State": state, "Variant": variant,
                    "EvaluationN": len(pair), "StateRuns": runs,
                    "BaselineMSE": float(np.mean((outcome - base) ** 2)),
                    "ExtendedMSE": float(np.mean((outcome - extended) ** 2)),
                    "DeltaMSE": float(pair["LossImprovement"].mean()),
                    "CI95Lower": lower, "CI95Upper": upper, "PValue": pvalue,
                    "BaselineRankIC": baseline["rank_ic"],
                    "ExtendedRankIC": extension["rank_ic"],
                    "BaselineQuintileSpread": baseline["quintile_spread"],
                    "ExtendedQuintileSpread": extension["quintile_spread"],
                    "BaselineUpsideCaptureProxy": baseline["upside_capture"],
                    "ExtendedUpsideCaptureProxy": extension["upside_capture"],
                    "BaselineDownsideAvoidanceProxy": baseline["downside_avoidance"],
                    "ExtendedDownsideAvoidanceProxy": extension["downside_avoidance"],
                    "PositiveYears": int((annual["mean"] > 0).sum()),
                    "EvaluableYears": len(annual),
                    "Status": "ESTIMATED" if pvalue is not None else "INSUFFICIENT_BLOCKS",
                })
    ledger = pd.DataFrame(comparisons)
    if len(ledger) != 24:
        raise ValueError(f"comparison count differs: {len(ledger)} != 24")
    ledger["QValue"] = _bh(pd.to_numeric(ledger["PValue"], errors="coerce"))
    ledger["ExploratoryClue"] = (
        ledger["DeltaMSE"].gt(0) & ledger["QValue"].le(0.10)
    )
    return predictions, fits, ledger, pd.DataFrame(coverage_rows)


def synthetic_precheck() -> None:
    opens = pd.Series([10.0, 11.0, 12.0, 15.0], index=pd.bdate_range("2014-01-01", periods=4))
    if not np.isclose(float(_future_open_return(opens, 2).iloc[0]), 15 / 11 - 1):
        raise ValueError("T+1 to T+H+1 open return alignment differs")
    sample = pd.DataFrame({
        "price_return_20d": [-0.01, 0.01, -0.01, 0.01],
        "price_return_60d": [-0.02, -0.02, 0.02, 0.02],
    })
    if tuple(_states(sample)) != ("WEAK", "START", "PULLBACK", "PERSIST"):
        raise ValueError("ex-ante state mapping differs")
    if not np.allclose(_bh(pd.Series([0.01, 0.10])).to_numpy(), [0.02, 0.10]):
        raise ValueError("BH correction differs")
    dates = pd.bdate_range("2013-07-29", "2024-12-31")
    rng = np.random.default_rng(88)
    fields = list(dict.fromkeys(PRICE + SGE + FX))
    fake = pd.DataFrame(
        rng.normal(size=(len(dates), len(fields))), index=dates, columns=fields
    )
    fake["Open"] = 100 * np.exp(np.cumsum(rng.normal(scale=0.01, size=len(dates))))
    predictions, fits, ledger, coverage = _audit(fake, 10)
    if len(ledger) != 24 or predictions.empty or fits.empty or len(coverage) != 48:
        raise ValueError("full synthetic audit shape differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Do causal gold and currency inputs add conditional upside information beyond the ETF price baseline?",
            hypothesis="SGE gold or USD/CNH may incrementally identify upside start, persistence or recovery in an ex-ante ETF price state.",
            falsification_conditions=(
                "Incremental prediction loss is not lower than the price-only baseline",
                "Apparent improvement is concentrated in one year or unidentifiable due to collinearity",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "A gold ETF follows domestic RMB gold; SGE gold may only duplicate its price",
                    "Currency translation may change RMB gold opportunities but must add to the observed ETF price",
                ),
                information_paths=(
                    "Prior-session SGE -> ex-ante price state -> future open-to-open ETF return",
                    "Prior-session USD/CNH -> ex-ante price state -> future open-to-open ETF return",
                ),
                stage_objectives=("Audit conditional incremental information without constructing a trading rule",),
                observation_metrics=("Paired out-of-fold MSE, rank IC, upside and downside proxies, annual stability",),
                methodology=(
                    "Pin EX16 panel and ETF execution manifest",
                    "Use fixed four price states, two horizons and four predictor blocks",
                    "Fit annual expanding OLS with label maturity purge",
                    "Compare 24 paired loss paths with calendar block bootstrap and BH correction",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX87 predecessor receipt differs")
        root = Path(__file__).resolve().parents[3]
        panel_path = root / "experiments/S008/20260923_S008_EX16/artifacts/causal_feature_panel.csv.gz"
        manifest_path = root / "data/raw/518880_execution_manifest.json"
        if _sha256(panel_path) != PANEL_SHA256 or _sha256(manifest_path) != EXECUTION_MANIFEST_SHA256:
            raise ValueError("frozen input identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        panel = pd.read_csv(panel_path, parse_dates=["Date"]).set_index("Date").sort_index()
        prices = load_execution_prices(
            root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff="2024-12-31"
        )
        if "dt" not in prices:
            raise ValueError("public execution price date column missing")
        opens = prices.set_index("dt")["open"].sort_index().astype(float)
        if panel.index.max() != pd.Timestamp("2024-12-31") or not panel.index.is_unique:
            raise ValueError("development panel boundary differs")
        if not panel.index.isin(opens.index).all():
            raise ValueError("execution opens do not cover the causal panel")
        frame = panel[list(dict.fromkeys(PRICE + SGE + FX))].copy()
        frame["Open"] = opens.reindex(frame.index)
        if not frame["Open"].gt(0).all():
            raise ValueError("missing or nonpositive execution open")
        predictions, fits, ledger, coverage = _audit(frame, BOOTSTRAP_REPETITIONS)
        predictions.to_csv(context.workspace.path("yearly_predictions.csv"), index=False, lineterminator="\n")
        fits.to_csv(context.workspace.path("model_fits.csv"), index=False, lineterminator="\n")
        ledger.to_csv(context.workspace.path("incremental_comparisons.csv"), index=False, lineterminator="\n")
        coverage.to_csv(context.workspace.path("state_coverage.csv"), index=False, lineterminator="\n")
        pd.DataFrame([
            {"Input": "EX16 causal feature panel", "Sha256": PANEL_SHA256, "Cutoff": "2024-12-31"},
            {"Input": "ETF execution manifest", "Sha256": EXECUTION_MANIFEST_SHA256, "Cutoff": "2024-12-31"},
        ]).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        clues = ledger.loc[ledger["ExploratoryClue"], ["State", "Horizon", "Variant"]].to_dict("records")
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": "REVIEW_CONDITIONAL_UPSIDE_INFORMATION",
                "comparison_count": len(ledger),
                "identifiable_comparisons": int(ledger["PValue"].notna().sum()),
                "exploratory_clues": clues,
                "evaluation_rows": len(predictions),
                "development_cutoff": "2024-12-31",
            },
            diagnostics={
                "discovery_only": True,
                "independent_out_of_sample": False,
                "reads_sealed_validation": False,
                "alpha_claim": False,
                "candidate_created": False,
            },
            artifacts=tuple(
                context.workspace.register_artifact(name, kind)
                for name, kind in (
                    ("yearly_predictions.csv", "annual-forward-predictions"),
                    ("model_fits.csv", "ols-identifiability-ledger"),
                    ("incremental_comparisons.csv", "multiplicity-adjusted-incremental-tests"),
                    ("state_coverage.csv", "ex-ante-state-coverage"),
                    ("input_identities.csv", "pinned-input-identities"),
                )
            ),
        )
