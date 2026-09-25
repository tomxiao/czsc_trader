from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import DataRequest, DataStatus, Dataset
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


EXPERIMENT_ID = "20260925_S009_EX06"
PREDECESSOR = "20260925_S009_EX05"
PREDECESSOR_RECEIPT = "bea365ffd49f5d7ab860546771a526bbc412e10439e66ab661d3e6fc4b574248"
INPUT_HASHES = {
    "510050.SH": "9364d1e1a8aa7c07ecd622101bc171c6b5887df4429f41a8f2ad367c2a38411d",
    "510300.SH": "49c56544a3de9eb30b4dad39e56b2eec5522c7897c1ac4f94a7db2bc8c8c52c4",
}
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
SYMBOLS = tuple(INPUT_HASHES)
WINDOWS = (20, 60)
CONTROLS = ("PriceReturn5", "PriceReturn20", "PriceReturn60", "PriceReturn120", "PriceVolatility20")
START, END = "2013-07-29", "2024-12-31"
HORIZON = 20
SEED = 2026090601
BOOTSTRAP_REPETITIONS = 2000


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _predict(train: pd.DataFrame, test: pd.DataFrame, fields: tuple[str, ...]) -> tuple[np.ndarray, int, float]:
    x = train.loc[:, fields].to_numpy(dtype=float)
    y = train["Outcome"].to_numpy(dtype=float)
    z = test.loc[:, fields].to_numpy(dtype=float)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    if np.any(scale == 0) or np.any(~np.isfinite(scale)):
        raise ValueError("unusable design scale")
    design = np.column_stack((np.ones(len(x)), (x - center) / scale))
    rank = int(np.linalg.matrix_rank(design))
    if rank != design.shape[1]:
        raise ValueError("design is rank deficient")
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    prediction = np.column_stack((np.ones(len(z)), (z - center) / scale)) @ beta
    return prediction, rank, float(np.linalg.cond(design))


def _rank_ic(left: pd.Series | np.ndarray, right: pd.Series | np.ndarray) -> float:
    value = pd.Series(np.asarray(left)).corr(pd.Series(np.asarray(right)), method="spearman")
    return float(value)


def _bh(values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().sort_values()
    adjusted = valid.to_numpy() * len(valid) / np.arange(1, len(valid) + 1)
    adjusted = np.minimum.accumulate(adjusted[::-1])[::-1]
    result.loc[valid.index] = np.minimum(adjusted, 1.0)
    return result


def _bootstrap_pvalue(series: pd.Series, seed: int) -> float:
    values = series.to_numpy(dtype=float)
    observed = float(np.mean(values))
    centered = values - observed
    length = len(values)
    blocks = (length + HORIZON - 1) // HORIZON
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, length - HORIZON + 1, size=(BOOTSTRAP_REPETITIONS, blocks))
    indices = (starts[:, :, None] + np.arange(HORIZON)).reshape(BOOTSTRAP_REPETITIONS, -1)[:, :length]
    null_means = centered[indices].mean(axis=1)
    return float((1 + np.count_nonzero(null_means >= observed)) / (BOOTSTRAP_REPETITIONS + 1))


def synthetic_precheck() -> None:
    dates = pd.bdate_range("2024-01-01", periods=80)
    opens = pd.Series(np.linspace(10.0, 12.0, len(dates)), index=dates)
    outcome = np.log(opens.shift(-(HORIZON + 1)) / opens.shift(-1))
    if outcome.first_valid_index() != dates[0] or outcome.last_valid_index() != dates[-HORIZON - 2]:
        raise ValueError("T+1 to T+21 open alignment differs")
    source_dates = pd.Series(dates, index=dates).shift(1)
    if not source_dates.dropna().lt(source_dates.dropna().index).all():
        raise ValueError("source lag differs")
    if not np.allclose(_bh(pd.Series([0.01, 0.10])).to_numpy(), [0.02, 0.10]):
        raise ValueError("BH correction differs")
    sample = pd.Series(np.arange(120, dtype=float))
    value = _bootstrap_pvalue(sample, SEED)
    if not 0 < value <= 1:
        raise ValueError("bootstrap p-value differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Do broad-equity ETF creations replicate as stable 20-day upside information for 518880?",
            hypothesis="Persistent creations in both long-lived broad-equity ETFs proxy broad liquidity that subsequently reaches gold.",
            falsification_conditions=(
                "Either cross-product proxy lacks positive incremental loss improvement and direction stability",
                "No 20/60-session window is supported by both products under the frozen criteria",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value, Dataset.ETF_UNADJUSTED_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "A return-seeking component must identify future upside beyond target price history",
                    "Cross-product agreement is required because the hypothesis was generated after observing one proxy",
                ),
                information_paths=(
                    "Prior broad-equity creations -> broad investable liquidity -> subsequent gold ETF demand and appreciation",
                ),
                stage_objectives=("Produce or reject a development-only OPPORTUNITY component panel",),
                observation_metrics=(
                    "paired MSE improvement, rank IC, annual stability, moving-block p-value, cross-product agreement",
                ),
                methodology=(
                    "Evaluate exactly four frozen proxy-window paths at a 20-session horizon",
                    "Use annual-forward OLS with label maturity purge and a shared price baseline",
                    "Require both products to support the same window before panel admission",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(ExperimentDependency("numpy", np.__version__), ExperimentDependency("pandas", pd.__version__)),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX05 predecessor receipt differs")
        if predecessor.facts.get("decision") != "PROCEED_TO_LIQUIDITY_REPLICATION_AUDIT":
            raise ValueError("EX05 data-gate decision differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parents[3]
        manifest_path = root / "data/raw/518880_execution_manifest.json"
        if _sha256(manifest_path) != EXECUTION_MANIFEST_SHA256:
            raise ValueError("execution price manifest differs")
        prices = load_execution_prices(root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff=END)
        panel = prices.rename(columns={"dt": "Date", "open": "Open", "close": "Close"}).loc[:, ["Date", "Open", "Close"]]
        panel["Date"] = pd.to_datetime(panel["Date"]).dt.normalize()
        panel = panel.sort_values("Date").reset_index(drop=True)
        identities: list[dict[str, object]] = []
        for symbol in SYMBOLS:
            publication = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE, symbol, START, END, END, options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                raise RuntimeError(f"{symbol} share input is not READY")
            if publication.identity.content_sha256 != INPUT_HASHES[symbol]:
                raise ValueError(f"{symbol} share identity differs from EX05")
            source = publication.dataframe.loc[:, ["Date", "TotalShare"]].rename(
                columns={"Date": "SourceDate", "TotalShare": symbol}
            ).sort_values("SourceDate")
            source["SourceDate"] = pd.to_datetime(source["SourceDate"]).dt.normalize()
            for window in WINDOWS:
                source[f"{symbol}_ShareFlow{window}"] = np.log(source[symbol]).diff(window)
            panel = pd.merge_asof(
                panel.sort_values("Date"),
                source.loc[:, ["SourceDate", *[f"{symbol}_ShareFlow{window}" for window in WINDOWS]]],
                left_on="Date",
                right_on="SourceDate",
                direction="backward",
                allow_exact_matches=False,
            ).drop(columns="SourceDate")
            identities.append({"Input": symbol, "ContentSha256": publication.identity.content_sha256, "Cutoff": END})
        log_close = np.log(panel["Close"])
        panel["PriceReturn5"] = log_close.diff(5)
        panel["PriceReturn20"] = log_close.diff(20)
        panel["PriceReturn60"] = log_close.diff(60)
        panel["PriceReturn120"] = log_close.diff(120)
        panel["PriceVolatility20"] = log_close.diff().rolling(20).std(ddof=0)
        panel["Outcome"] = np.log(panel["Open"].shift(-(HORIZON + 1)) / panel["Open"].shift(-1))
        panel["OutcomeEnd"] = panel["Date"].shift(-(HORIZON + 1))

        prediction_rows: list[dict[str, object]] = []
        fit_rows: list[dict[str, object]] = []
        feature_names = tuple(f"{symbol}_ShareFlow{window}" for symbol in SYMBOLS for window in WINDOWS)
        for feature in feature_names:
            frame = panel.loc[:, ["Date", *CONTROLS, feature, "Outcome", "OutcomeEnd"]].dropna()
            for year in range(2019, 2025):
                cutoff = pd.Timestamp(year=year, month=1, day=1)
                train = frame.loc[frame["OutcomeEnd"] < cutoff]
                test = frame.loc[frame["Date"].dt.year == year]
                baseline, base_rank, base_condition = _predict(train, test, CONTROLS)
                extended, ext_rank, ext_condition = _predict(train, test, (*CONTROLS, feature))
                fit_rows.append({
                    "Feature": feature, "Year": year, "TrainingN": len(train), "EvaluationN": len(test),
                    "BaselineRank": base_rank, "BaselineConditionNumber": base_condition,
                    "ExtendedRank": ext_rank, "ExtendedConditionNumber": ext_condition,
                })
                for row, (_, item) in enumerate(test.iterrows()):
                    prediction_rows.append({
                        "Date": item["Date"], "Year": year, "Feature": feature,
                        "FeatureValue": float(item[feature]), "Outcome": float(item["Outcome"]),
                        "BaselinePrediction": float(baseline[row]), "ExtendedPrediction": float(extended[row]),
                    })
        predictions = pd.DataFrame(prediction_rows).sort_values(["Feature", "Date"])
        ledger_rows: list[dict[str, object]] = []
        annual_rows: list[dict[str, object]] = []
        for feature_index, (feature, group) in enumerate(predictions.groupby("Feature", sort=True)):
            item = group.copy()
            item["LossImprovement"] = (
                (item["Outcome"] - item["BaselinePrediction"]) ** 2
                - (item["Outcome"] - item["ExtendedPrediction"]) ** 2
            )
            annual = item.groupby("Year")["LossImprovement"].agg(["count", "mean"])
            for year, row in annual.iterrows():
                annual_rows.append({"Feature": feature, "Year": year, "N": int(row["count"]), "DeltaMSE": float(row["mean"])})
            early = item.loc[item["Year"] <= 2021]
            late = item.loc[item["Year"] >= 2022]
            symbol, tail = feature.split("_ShareFlow")
            baseline_ic = _rank_ic(item["Outcome"], item["BaselinePrediction"])
            extended_ic = _rank_ic(item["Outcome"], item["ExtendedPrediction"])
            ledger_rows.append({
                "Feature": feature, "ProxySymbol": symbol, "Window": int(tail), "Horizon": HORIZON,
                "EvaluationN": len(item), "DeltaMSE": float(item["LossImprovement"].mean()),
                "PositiveYears": int((annual["mean"] > 0).sum()),
                "FeatureRankIC": _rank_ic(item["FeatureValue"], item["Outcome"]),
                "FeatureRankIC2019_2021": _rank_ic(early["FeatureValue"], early["Outcome"]),
                "FeatureRankIC2022_2024": _rank_ic(late["FeatureValue"], late["Outcome"]),
                "BaselineRankIC": baseline_ic, "ExtendedRankIC": extended_ic,
                "PValue": _bootstrap_pvalue(item["LossImprovement"], SEED + feature_index),
            })
        ledger = pd.DataFrame(ledger_rows)
        if len(ledger) != 4:
            raise ValueError("comparison count differs from frozen four paths")
        ledger["QValue"] = _bh(ledger["PValue"])
        supported = (
            ledger["DeltaMSE"].gt(0)
            & ledger["PositiveYears"].ge(4)
            & ledger["FeatureRankIC2019_2021"].gt(0)
            & ledger["FeatureRankIC2022_2024"].gt(0)
            & ledger["ExtendedRankIC"].gt(ledger["BaselineRankIC"])
        )
        ledger["EvidenceLabel"] = "NOT_SUPPORTED"
        ledger.loc[supported, "EvidenceLabel"] = "DIRECTIONALLY_STABLE"
        ledger.loc[supported & ledger["PValue"].le(0.10), "EvidenceLabel"] = "NOMINAL_SUPPORTED"
        ledger.loc[supported & ledger["QValue"].le(0.10), "EvidenceLabel"] = "FDR_SUPPORTED"
        panel_rows: list[dict[str, object]] = []
        for window in WINDOWS:
            group = ledger.loc[ledger["Window"].eq(window)]
            supported_count = int(group["EvidenceLabel"].ne("NOT_SUPPORTED").sum())
            panel_rows.append({
                "Component": f"BroadLiquidity{window}", "Role": "OPPORTUNITY", "Window": window,
                "Mechanism": "broad-equity ETF creations proxy investable liquidity that subsequently reaches gold",
                "ProxyCount": len(group), "SupportedProxyCount": supported_count,
                "Eligible": supported_count == len(SYMBOLS),
                "EvidenceOrigin": "POST_HOC_HYPOTHESIS_CROSS_PRODUCT_REPLICATION",
                "Status": "DEVELOPMENT_SUPPORTED" if supported_count == len(SYMBOLS) else "REJECTED",
            })
        component_panel = pd.DataFrame(panel_rows)
        eligible_count = int(component_panel["Eligible"].sum())
        predictions.to_csv(context.workspace.path("annual_forward_predictions.csv.gz"), index=False, compression="gzip", lineterminator="\n")
        pd.DataFrame(fit_rows).to_csv(context.workspace.path("model_fits.csv"), index=False, lineterminator="\n")
        ledger.to_csv(context.workspace.path("information_ledger.csv"), index=False, float_format="%.12f", lineterminator="\n")
        pd.DataFrame(annual_rows).to_csv(context.workspace.path("annual_loss_improvement.csv"), index=False, float_format="%.12f", lineterminator="\n")
        component_panel.to_csv(context.workspace.path("component_panel.csv"), index=False, lineterminator="\n")
        identities.append({"Input": "518880 execution manifest", "ContentSha256": EXECUTION_MANIFEST_SHA256, "Cutoff": END})
        pd.DataFrame(identities).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        decision = "COMPONENT_PANEL_PRODUCED" if eligible_count else "STOP_NO_REPLICATED_LIQUIDITY_COMPONENT"
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if eligible_count else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision, "comparison_count": len(ledger), "eligible_components": eligible_count,
                "supported_proxies": int(ledger["EvidenceLabel"].ne("NOT_SUPPORTED").sum()),
                "fdr_supported": int(ledger["EvidenceLabel"].eq("FDR_SUPPORTED").sum()),
                "nominal_supported": int(ledger["EvidenceLabel"].eq("NOMINAL_SUPPORTED").sum()),
            },
            diagnostics={
                "post_hoc_hypothesis": True, "cross_product_replication": True,
                "reads_sealed_validation": False, "strategy_rule_created": False, "candidate_created": False,
            },
            artifacts=tuple(context.workspace.register_artifact(name, kind) for name, kind in (
                ("annual_forward_predictions.csv.gz", "liquidity-annual-forward-predictions"),
                ("model_fits.csv", "liquidity-model-fit-ledger"),
                ("information_ledger.csv", "liquidity-information-ledger"),
                ("annual_loss_improvement.csv", "liquidity-annual-stability-ledger"),
                ("component_panel.csv", "development-opportunity-component-panel"),
                ("input_identities.csv", "pinned-input-identities"),
            )),
        )
