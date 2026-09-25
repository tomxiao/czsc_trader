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


EXPERIMENT_ID = "20260925_S009_EX04"
PREDECESSOR = "20260925_S009_EX03"
PREDECESSOR_RECEIPT = "5c1b6a6c427c7bbe253a237a90ae5898ea3c1d3d402c4f3b37fc580e266e9b65"
PANEL_SHA256 = "17a7f7cce7f008aeb70547777b13ef915b99c71428ff159048143bb8e3dbb506"
CATALOG_SHA256 = "ff198d69be95d534649383e70f4829f512dff30211e1ea4a8e24c34214dd4241"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
CONTROLS = ("PriceReturn5", "PriceReturn20", "PriceReturn60", "PriceReturn120", "PriceVolatility20")
HORIZONS = (5, 20, 60)
EVALUATION_YEARS = tuple(range(2019, 2025))
SEED = 20260904
BOOTSTRAP_REPETITIONS = 2000


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _future_open_return(opens: pd.Series, horizon: int) -> pd.Series:
    return opens.shift(-(horizon + 1)) / opens.shift(-1) - 1.0


def _ols_predict(train: pd.DataFrame, test: pd.DataFrame, fields: tuple[str, ...]) -> tuple[np.ndarray | None, int, float | None]:
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


def _rank_ic(outcome: pd.Series | np.ndarray, signal: pd.Series | np.ndarray) -> float | None:
    value = pd.Series(np.asarray(outcome)).corr(pd.Series(np.asarray(signal)), method="spearman")
    return float(value) if pd.notna(value) else None


def _ranking_diagnostics(outcome: np.ndarray, prediction: np.ndarray) -> dict[str, float | None]:
    if len(outcome) < 5 or np.unique(prediction).size < 5:
        return {"rank_ic": None, "quintile_spread": None, "upside_capture": None, "downside_avoidance": None}
    order = np.argsort(prediction, kind="stable")
    count = max(1, len(order) // 5)
    positive = np.maximum(outcome, 0)
    negative = np.maximum(-outcome, 0)
    return {
        "rank_ic": _rank_ic(outcome, prediction),
        "quintile_spread": float(outcome[order[-count:]].mean() - outcome[order[:count]].mean()),
        "upside_capture": float(positive[prediction > 0].sum() / positive.sum()) if positive.sum() > 0 else None,
        "downside_avoidance": float(negative[prediction <= 0].sum() / negative.sum()) if negative.sum() > 0 else None,
    }


def _bootstrap(calendar: pd.DatetimeIndex, observations: pd.DataFrame, horizon: int, seed: int) -> tuple[float | None, float | None, float | None]:
    series = observations.set_index("Date")["LossImprovement"].reindex(calendar)
    observed = series.dropna()
    if len(observed) < 2 or len(calendar) < horizon:
        return None, None, None
    values = series.to_numpy(dtype=float)
    length = len(values)
    blocks = (length + horizon - 1) // horizon
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, length - horizon + 1, size=(BOOTSTRAP_REPETITIONS, blocks))
    sampled_indices = (starts[:, :, None] + np.arange(horizon)).reshape(BOOTSTRAP_REPETITIONS, -1)[:, :length]
    sampled = values[sampled_indices]
    counts = np.isfinite(sampled).sum(axis=1)
    means = np.divide(np.nansum(sampled, axis=1), counts, out=np.full(BOOTSTRAP_REPETITIONS, np.nan), where=counts > 0)
    valid = means[np.isfinite(means)]
    if len(valid) != BOOTSTRAP_REPETITIONS:
        return None, None, None
    center = float(observed.mean())
    lower, upper = np.quantile(valid, (0.025, 0.975))
    pvalue = (1 + int(np.sum(valid - center >= center))) / (BOOTSTRAP_REPETITIONS + 1)
    return float(lower), float(upper), float(pvalue)


def _audit(frame: pd.DataFrame, catalog: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("market dates must be unique and ordered")
    if frame.index.max() > pd.Timestamp("2024-12-31") or not frame["Open"].gt(0).all():
        raise ValueError("execution inputs exceed cutoff or contain invalid open")
    features = tuple(catalog["Feature"].astype(str))
    required = [*CONTROLS, *features]
    missing = [field for field in required if field not in frame]
    if missing:
        raise ValueError(f"missing frozen fields: {missing}")
    original_dates = pd.Series(frame.index, index=frame.index)
    prediction_rows: list[dict[str, object]] = []
    fit_rows: list[dict[str, object]] = []
    for horizon in HORIZONS:
        eligible = frame.copy()
        eligible["Outcome"] = _future_open_return(frame["Open"], horizon)
        eligible["OutcomeEnd"] = original_dates.shift(-(horizon + 1))
        eligible = eligible.dropna(subset=required + ["Outcome", "OutcomeEnd"])
        for year in EVALUATION_YEARS:
            first_day = pd.Timestamp(year=year, month=1, day=1)
            train = eligible.loc[eligible["OutcomeEnd"] < first_day]
            test = eligible.loc[eligible.index.year == year]
            if test.empty:
                continue
            baseline, base_rank, base_condition = _ols_predict(train, test, CONTROLS)
            if baseline is None:
                raise ValueError(f"baseline unidentifiable for horizon={horizon}, year={year}")
            for feature_index, feature in enumerate(features):
                fields = CONTROLS + (feature,)
                extended, rank, condition = _ols_predict(train, test, fields)
                fit_rows.append({
                    "Horizon": horizon, "Year": year, "Feature": feature,
                    "TrainingN": len(train), "EvaluationN": len(test),
                    "BaselineRank": base_rank, "BaselineConditionNumber": base_condition,
                    "ExtendedRank": rank, "ExtendedConditionNumber": condition,
                    "Identifiable": extended is not None,
                })
                if extended is None:
                    continue
                for row, (dt, item) in enumerate(test.iterrows()):
                    prediction_rows.append({
                        "Date": dt, "Year": year, "Horizon": horizon, "Feature": feature,
                        "Outcome": float(item["Outcome"]), "FeatureValue": float(item[feature]),
                        "BaselinePrediction": float(baseline[row]), "ExtendedPrediction": float(extended[row]),
                    })
    predictions = pd.DataFrame(prediction_rows).sort_values(["Horizon", "Feature", "Date"])
    fits = pd.DataFrame(fit_rows)
    ledger_rows: list[dict[str, object]] = []
    catalog_index = catalog.set_index("Feature")
    for path_index, (key, group) in enumerate(predictions.groupby(["Horizon", "Feature"], sort=True)):
        horizon, feature = key
        pair = group.copy()
        outcome = pair["Outcome"].to_numpy(dtype=float)
        baseline = pair["BaselinePrediction"].to_numpy(dtype=float)
        extended = pair["ExtendedPrediction"].to_numpy(dtype=float)
        pair["LossImprovement"] = (outcome - baseline) ** 2 - (outcome - extended) ** 2
        calendar = pd.DatetimeIndex(sorted(predictions.loc[predictions["Horizon"] == horizon, "Date"].unique()))
        lower, upper, pvalue = _bootstrap(calendar, pair[["Date", "LossImprovement"]], int(horizon), SEED + path_index)
        annual = pair.groupby("Year")["LossImprovement"].agg(["count", "mean"])
        discovery = pair.loc[pair["Year"] <= 2021]
        confirmation = pair.loc[pair["Year"] >= 2022]
        base_diag = _ranking_diagnostics(outcome, baseline)
        ext_diag = _ranking_diagnostics(outcome, extended)
        meta = catalog_index.loc[feature]
        ledger_rows.append({
            "Horizon": int(horizon), "Feature": feature, "Window": int(meta["Window"]),
            "Family": str(meta["Family"]), "Role": str(meta["Role"]),
            "ExpectedAssociation": str(meta["ExpectedAssociation"]), "EvaluationN": len(pair),
            "BaselineMSE": float(np.mean((outcome - baseline) ** 2)),
            "ExtendedMSE": float(np.mean((outcome - extended) ** 2)),
            "DeltaMSE": float(pair["LossImprovement"].mean()), "CI95Lower": lower, "CI95Upper": upper,
            "PValue": pvalue, "PositiveYears": int((annual["mean"] > 0).sum()),
            "EvaluableYears": len(annual), "FeatureRankIC2019_2021": _rank_ic(discovery["Outcome"], discovery["FeatureValue"]),
            "FeatureRankIC2022_2024": _rank_ic(confirmation["Outcome"], confirmation["FeatureValue"]),
            "BaselineRankIC": base_diag["rank_ic"], "ExtendedRankIC": ext_diag["rank_ic"],
            "BaselineQuintileSpread": base_diag["quintile_spread"], "ExtendedQuintileSpread": ext_diag["quintile_spread"],
            "BaselineUpsideCaptureProxy": base_diag["upside_capture"], "ExtendedUpsideCaptureProxy": ext_diag["upside_capture"],
            "BaselineDownsideAvoidanceProxy": base_diag["downside_avoidance"], "ExtendedDownsideAvoidanceProxy": ext_diag["downside_avoidance"],
        })
    ledger = pd.DataFrame(ledger_rows)
    if len(ledger) != 63:
        raise ValueError(f"comparison count differs: {len(ledger)} != 63")
    ledger["QValue"] = _bh(pd.to_numeric(ledger["PValue"], errors="coerce"))
    direction = (
        ledger["FeatureRankIC2019_2021"].gt(0)
        & ledger["FeatureRankIC2022_2024"].gt(0)
        & ledger["ExtendedRankIC"].gt(ledger["BaselineRankIC"])
    )
    stable = ledger["DeltaMSE"].gt(0) & ledger["PositiveYears"].ge(4) & direction
    ledger["EvidenceLabel"] = "NOT_SUPPORTED"
    ledger.loc[stable, "EvidenceLabel"] = "DIRECTIONALLY_STABLE"
    ledger.loc[stable & ledger["PValue"].le(0.10), "EvidenceLabel"] = "NOMINAL_SUPPORTED"
    ledger.loc[stable & ledger["QValue"].le(0.10), "EvidenceLabel"] = "FDR_SUPPORTED"
    ledger["PanelEligible"] = (
        ledger["Horizon"].eq(20)
        & ~ledger["Role"].eq("RISK_CONTEXT")
        & ledger["EvidenceLabel"].isin(("FDR_SUPPORTED", "NOMINAL_SUPPORTED", "DIRECTIONALLY_STABLE"))
    )
    annual = predictions.assign(
        LossImprovement=(predictions["Outcome"] - predictions["BaselinePrediction"]) ** 2
        - (predictions["Outcome"] - predictions["ExtendedPrediction"]) ** 2
    ).groupby(["Horizon", "Feature", "Year"], as_index=False)["LossImprovement"].agg(["count", "mean"]).reset_index()
    return predictions, fits, ledger, annual


def synthetic_precheck() -> None:
    opens = pd.Series([10.0, 11.0, 12.0, 15.0], index=pd.bdate_range("2014-01-01", periods=4))
    if not np.isclose(float(_future_open_return(opens, 2).iloc[0]), 15 / 11 - 1):
        raise ValueError("T+1 to T+H+1 open alignment differs")
    if not np.allclose(_bh(pd.Series([0.01, 0.10])).to_numpy(), [0.02, 0.10]):
        raise ValueError("BH correction differs")
    rng = np.random.default_rng(4)
    dates = pd.bdate_range("2013-07-29", "2024-12-31")
    features = [f"F{i}" for i in range(21)]
    fake = pd.DataFrame(rng.normal(size=(len(dates), len(CONTROLS) + len(features))), index=dates, columns=[*CONTROLS, *features])
    fake["Open"] = 100 * np.exp(np.cumsum(rng.normal(scale=0.01, size=len(dates))))
    catalog = pd.DataFrame({"Feature": features, "Window": [20] * 21, "Family": ["SYNTHETIC"] * 21, "Role": ["OPPORTUNITY"] * 21, "ExpectedAssociation": ["POSITIVE"] * 21})
    predictions, fits, ledger, annual = _audit(fake, catalog)
    if len(ledger) != 63 or predictions.empty or fits.empty or annual.empty:
        raise ValueError("synthetic information audit shape differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Do causal RMB-gold transmission gaps and ETF flows add stable upside information beyond target price history?",
            hypothesis="Lagged global/domestic parity gaps confirmed by broad ETF demand may identify still-tradable upside in 518880.",
            falsification_conditions=(
                "No 20-session OPPORTUNITY path passes the frozen direction and annual-stability requirements",
                "Incremental prediction loss is not lower than the common price baseline after multiplicity accounting",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_UNADJUSTED_DAILY.value,),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "An income-seeking gold strategy must identify participation in upside, not merely suppress exposure",
                    "International gold, RMB translation, domestic spot and broad ETF demand may transmit with different lags",
                ),
                information_paths=(
                    "Prior observable parity gap -> remaining RMB-gold repricing -> future ETF upside",
                    "Prior observable peer and common share flow -> demand confirmation -> future ETF upside",
                ),
                stage_objectives=("Audit incremental opportunity information before constructing any trading rule",),
                observation_metrics=("Paired MSE improvement, rank IC, quintile spread, upside capture, downside avoidance, annual stability",),
                methodology=(
                    "Pin EX03 panel, catalog and the managed execution manifest",
                    "Evaluate 63 frozen paths by annual-forward OLS with label maturity purge",
                    "Use horizon-length calendar block bootstrap and one global BH correction",
                    "Allow only supported 20-session non-risk paths into component role review",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__), ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX03 predecessor receipt differs")
        root = Path(__file__).resolve().parents[3]
        panel_path = root / "experiments/S009/20260925_S009_EX03/artifacts/parity_causal_panel.csv.gz"
        catalog_path = root / "experiments/S009/20260925_S009_EX03/artifacts/feature_catalog.csv"
        manifest_path = root / "data/raw/518880_execution_manifest.json"
        if (_sha256(panel_path), _sha256(catalog_path), _sha256(manifest_path)) != (PANEL_SHA256, CATALOG_SHA256, EXECUTION_MANIFEST_SHA256):
            raise ValueError("frozen input identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        panel = pd.read_csv(panel_path, parse_dates=["Date"]).set_index("Date").sort_index()
        catalog = pd.read_csv(catalog_path)
        prices = load_execution_prices(root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff="2024-12-31")
        opens = prices.set_index("dt")["open"].sort_index().astype(float)
        if panel.index.max() != pd.Timestamp("2024-12-31") or not panel.index.isin(opens.index).all():
            raise ValueError("development panel boundary or execution coverage differs")
        frame = panel[[*CONTROLS, *catalog["Feature"].astype(str).tolist()]].copy()
        frame["Open"] = opens.reindex(frame.index)
        predictions, fits, ledger, annual = _audit(frame, catalog)
        predictions.to_csv(context.workspace.path("annual_forward_predictions.csv.gz"), index=False, compression="gzip", lineterminator="\n")
        fits.to_csv(context.workspace.path("model_fits.csv"), index=False, lineterminator="\n")
        ledger.to_csv(context.workspace.path("information_ledger.csv"), index=False, lineterminator="\n")
        annual.to_csv(context.workspace.path("annual_loss_improvement.csv"), index=False, lineterminator="\n")
        pd.DataFrame([
            {"Input": "EX03 parity panel", "Sha256": PANEL_SHA256, "Cutoff": "2024-12-31"},
            {"Input": "EX03 feature catalog", "Sha256": CATALOG_SHA256, "Cutoff": "2024-12-31"},
            {"Input": "ETF execution manifest", "Sha256": EXECUTION_MANIFEST_SHA256, "Cutoff": "2024-12-31"},
        ]).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        eligible = ledger.loc[ledger["PanelEligible"]]
        opportunity = eligible.loc[eligible["Role"].eq("OPPORTUNITY")]
        decision = "PROCEED_TO_COMPONENT_ROLE_REVIEW" if not opportunity.empty else "STOP_NO_SUPPORTED_OPPORTUNITY_INFORMATION"
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if not opportunity.empty else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision,
                "comparison_count": len(ledger),
                "fdr_supported": int(ledger["EvidenceLabel"].eq("FDR_SUPPORTED").sum()),
                "nominal_supported": int(ledger["EvidenceLabel"].eq("NOMINAL_SUPPORTED").sum()),
                "directionally_stable": int(ledger["EvidenceLabel"].eq("DIRECTIONALLY_STABLE").sum()),
                "panel_eligible": int(eligible.shape[0]),
                "opportunity_eligible": int(opportunity.shape[0]),
            },
            diagnostics={"discovery_only": True, "reads_sealed_validation": False, "candidate_created": False, "strategy_rule_created": False},
            artifacts=tuple(context.workspace.register_artifact(name, kind) for name, kind in (
                ("annual_forward_predictions.csv.gz", "annual-forward-path-predictions"),
                ("model_fits.csv", "ols-identifiability-ledger"),
                ("information_ledger.csv", "multiplicity-adjusted-opportunity-information-ledger"),
                ("annual_loss_improvement.csv", "annual-stability-ledger"),
                ("input_identities.csv", "pinned-input-identities"),
            )),
        )

