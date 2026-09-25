from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import DataRequest, DataStatus, Dataset
import numpy as np
import pandas as pd
from research_experiment import (
    ExperimentCapabilities, ExperimentCapability, ExperimentDefinition, ExperimentDependency,
    ExperimentMode, ExperimentOutcome, ExperimentProtocol, ExperimentResult, ExperimentStage, ResearchExperiment,
)


EXPERIMENT_ID = "20260925_S009_EX08"
PREDECESSOR = "20260925_S009_EX07"
PREDECESSOR_RECEIPT = "a70a22bc624017354fed4ad43df5fbf779232aeb20d6226164b9403b7be0c349"
INPUT_HASH = "d3db6a903bb75c4f4abf0bf8ca290311a627b5451e56bafe2c3b75c2f37e9994"
EX06_LEDGER_SHA256 = "9ad5367ff9c6c7abb11b9ee503dfcae5b43fa73702a8cf10f2bb1427d6e39808"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
SYMBOL = "159915.SZ"
WINDOWS = (20, 60)
CONTROLS = ("PriceReturn5", "PriceReturn20", "PriceReturn60", "PriceReturn120", "PriceVolatility20")
START, END = "2013-07-29", "2024-12-31"
HORIZON = 20
SEED = 2026090801
BOOTSTRAP_REPETITIONS = 2000


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _predict(train: pd.DataFrame, test: pd.DataFrame, fields: tuple[str, ...]) -> np.ndarray:
    x = train.loc[:, fields].to_numpy(dtype=float)
    y = train["Outcome"].to_numpy(dtype=float)
    z = test.loc[:, fields].to_numpy(dtype=float)
    center = x.mean(axis=0)
    scale = x.std(axis=0)
    if np.any(scale == 0) or np.any(~np.isfinite(scale)):
        raise ValueError("unusable design scale")
    design = np.column_stack((np.ones(len(x)), (x - center) / scale))
    if np.linalg.matrix_rank(design) != design.shape[1]:
        raise ValueError("design is rank deficient")
    beta = np.linalg.lstsq(design, y, rcond=None)[0]
    return np.column_stack((np.ones(len(z)), (z - center) / scale)) @ beta


def _rank_ic(left: pd.Series | np.ndarray, right: pd.Series | np.ndarray) -> float:
    return float(pd.Series(np.asarray(left)).corr(pd.Series(np.asarray(right)), method="spearman"))


def _bh(values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().sort_values()
    adjusted = valid.to_numpy() * len(valid) / np.arange(1, len(valid) + 1)
    result.loc[valid.index] = np.minimum(np.minimum.accumulate(adjusted[::-1])[::-1], 1.0)
    return result


def _bootstrap_pvalue(series: pd.Series, seed: int) -> float:
    values = series.to_numpy(dtype=float)
    observed = float(values.mean())
    centered = values - observed
    length = len(values)
    blocks = (length + HORIZON - 1) // HORIZON
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, length - HORIZON + 1, size=(BOOTSTRAP_REPETITIONS, blocks))
    indices = (starts[:, :, None] + np.arange(HORIZON)).reshape(BOOTSTRAP_REPETITIONS, -1)[:, :length]
    null_means = centered[indices].mean(axis=1)
    return float((1 + np.count_nonzero(null_means >= observed)) / (BOOTSTRAP_REPETITIONS + 1))


def synthetic_precheck() -> None:
    dates = pd.bdate_range("2024-01-01", periods=90)
    sparse = pd.Series(np.linspace(100.0, 110.0, 87), index=dates.delete([5, 15, 30]))
    filled = sparse.reindex(dates).ffill()
    if filled.isna().any() or len(np.log(filled).diff(20).dropna()) != 70:
        raise ValueError("reference-calendar forward-fill transform differs")
    opens = pd.Series(np.linspace(10.0, 12.0, len(dates)), index=dates)
    outcome = np.log(opens.shift(-(HORIZON + 1)) / opens.shift(-1))
    if outcome.last_valid_index() != dates[-HORIZON - 2]:
        raise ValueError("future open alignment differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question="Does a third broad-equity ETF resolve the split 20/60-day liquidity replication?",
            hypothesis="159915 creations support at least one already-frozen broad-liquidity window, yielding majority cross-product evidence.",
            falsification_conditions=(
                "Neither 159915 window passes the unchanged EX06 support criteria",
                "No window reaches support from at least two of the three broad-equity products",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=SEED,
            allowed_datasets=(Dataset.ETF_SHARE_SIZE.value, Dataset.ETF_UNADJUSTED_DAILY.value),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "A third product adjudicates rather than relaxes the rejected two-product same-window gate",
                    "Majority cross-product support limits dependence on one fund's clientele",
                ),
                information_paths=(
                    "Prior broad-equity creations -> investable liquidity -> subsequent gold ETF demand and appreciation",
                ),
                stage_objectives=("Produce or finally reject a development-only broad-liquidity OPPORTUNITY panel",),
                observation_metrics=("paired MSE improvement, rank IC, annual stability, block p-value, majority support",),
                methodology=(
                    "Evaluate only 159915 at the frozen 20/60 windows and 20-session horizon",
                    "Combine results with the hash-pinned EX06 ledger under a two-of-three rule",
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
            raise ValueError("EX07 predecessor receipt differs")
        if predecessor.facts.get("decision") != "PROCEED_TO_THIRD_PROXY_AUDIT":
            raise ValueError("EX07 data-gate decision differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        root = Path(__file__).resolve().parents[3]
        ex06_path = root / "experiments/S009/20260925_S009_EX06/artifacts/information_ledger.csv"
        manifest_path = root / "data/raw/518880_execution_manifest.json"
        if _sha256(ex06_path) != EX06_LEDGER_SHA256 or _sha256(manifest_path) != EXECUTION_MANIFEST_SHA256:
            raise ValueError("frozen input identity differs")
        prior = pd.read_csv(ex06_path)
        prices = load_execution_prices(root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff=END)
        panel = prices.rename(columns={"dt": "Date", "open": "Open", "close": "Close"}).loc[:, ["Date", "Open", "Close"]]
        panel["Date"] = pd.to_datetime(panel["Date"]).dt.normalize()
        panel = panel.sort_values("Date").reset_index(drop=True)
        publication = context.data.fetch(DataRequest(
            Dataset.ETF_SHARE_SIZE, SYMBOL, START, END, END, options={"env_file": ".env"},
        ))
        if publication.status is not DataStatus.READY or publication.identity is None:
            raise RuntimeError("159915 share input is not READY")
        if publication.identity.content_sha256 != INPUT_HASH:
            raise ValueError("159915 share identity differs from EX07")
        source = publication.dataframe.set_index(pd.to_datetime(publication.dataframe["Date"]).dt.normalize())["TotalShare"].astype(float)
        source = source.reindex(pd.DatetimeIndex(panel["Date"])).ffill()
        if source.isna().any():
            raise ValueError("causal forward-fill left unavailable values")
        for window in WINDOWS:
            panel[f"{SYMBOL}_ShareFlow{window}"] = np.log(source).diff(window).to_numpy()
        # Shift one target trading session because source T is only available on T+1 morning.
        feature_names = tuple(f"{SYMBOL}_ShareFlow{window}" for window in WINDOWS)
        panel.loc[:, feature_names] = panel.loc[:, feature_names].shift(1)
        log_close = np.log(panel["Close"])
        panel["PriceReturn5"] = log_close.diff(5)
        panel["PriceReturn20"] = log_close.diff(20)
        panel["PriceReturn60"] = log_close.diff(60)
        panel["PriceReturn120"] = log_close.diff(120)
        panel["PriceVolatility20"] = log_close.diff().rolling(20).std(ddof=0)
        panel["Outcome"] = np.log(panel["Open"].shift(-(HORIZON + 1)) / panel["Open"].shift(-1))
        panel["OutcomeEnd"] = panel["Date"].shift(-(HORIZON + 1))

        prediction_rows: list[dict[str, object]] = []
        for feature in feature_names:
            frame = panel.loc[:, ["Date", *CONTROLS, feature, "Outcome", "OutcomeEnd"]].dropna()
            for year in range(2019, 2025):
                cutoff = pd.Timestamp(year=year, month=1, day=1)
                train = frame.loc[frame["OutcomeEnd"] < cutoff]
                test = frame.loc[frame["Date"].dt.year == year]
                baseline = _predict(train, test, CONTROLS)
                extended = _predict(train, test, (*CONTROLS, feature))
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
            window = int(feature.split("_ShareFlow")[1])
            ledger_rows.append({
                "Feature": feature, "ProxySymbol": SYMBOL, "Window": window, "Horizon": HORIZON,
                "EvaluationN": len(item), "DeltaMSE": float(item["LossImprovement"].mean()),
                "PositiveYears": int((annual["mean"] > 0).sum()),
                "FeatureRankIC": _rank_ic(item["FeatureValue"], item["Outcome"]),
                "FeatureRankIC2019_2021": _rank_ic(early["FeatureValue"], early["Outcome"]),
                "FeatureRankIC2022_2024": _rank_ic(late["FeatureValue"], late["Outcome"]),
                "BaselineRankIC": _rank_ic(item["Outcome"], item["BaselinePrediction"]),
                "ExtendedRankIC": _rank_ic(item["Outcome"], item["ExtendedPrediction"]),
                "PValue": _bootstrap_pvalue(item["LossImprovement"], SEED + feature_index),
            })
        ledger = pd.DataFrame(ledger_rows)
        if len(ledger) != 2:
            raise ValueError("comparison count differs from frozen two paths")
        ledger["QValue"] = _bh(ledger["PValue"])
        supported = (
            ledger["DeltaMSE"].gt(0) & ledger["PositiveYears"].ge(4)
            & ledger["FeatureRankIC2019_2021"].gt(0) & ledger["FeatureRankIC2022_2024"].gt(0)
            & ledger["ExtendedRankIC"].gt(ledger["BaselineRankIC"])
        )
        ledger["EvidenceLabel"] = "NOT_SUPPORTED"
        ledger.loc[supported, "EvidenceLabel"] = "DIRECTIONALLY_STABLE"
        ledger.loc[supported & ledger["PValue"].le(0.10), "EvidenceLabel"] = "NOMINAL_SUPPORTED"
        ledger.loc[supported & ledger["QValue"].le(0.10), "EvidenceLabel"] = "FDR_SUPPORTED"

        panel_rows: list[dict[str, object]] = []
        combined_rows: list[pd.DataFrame] = []
        for window in WINDOWS:
            old = prior.loc[prior["Window"].eq(window)].copy()
            new = ledger.loc[ledger["Window"].eq(window)].copy()
            combined_rows.extend((old, new))
            old_supported = int(old["EvidenceLabel"].ne("NOT_SUPPORTED").sum())
            new_supported = int(new["EvidenceLabel"].ne("NOT_SUPPORTED").sum())
            supported_count = old_supported + new_supported
            eligible = supported_count >= 2
            panel_rows.append({
                "Component": f"BroadLiquidity{window}", "Role": "OPPORTUNITY", "Window": window,
                "Mechanism": "broad-equity ETF creations proxy investable liquidity that subsequently reaches gold",
                "ProxyCount": 3, "SupportedProxyCount": supported_count, "Eligible": eligible,
                "EvidenceOrigin": "POST_HOC_HYPOTHESIS_THIRD_PRODUCT_REPLICATION",
                "Status": "DEVELOPMENT_SUPPORTED_POST_HOC" if eligible else "REJECTED",
            })
        combined = pd.concat(combined_rows, ignore_index=True)
        component_panel = pd.DataFrame(panel_rows)
        eligible_count = int(component_panel["Eligible"].sum())
        predictions.to_csv(context.workspace.path("annual_forward_predictions.csv.gz"), index=False, compression="gzip", lineterminator="\n")
        ledger.to_csv(context.workspace.path("third_proxy_information_ledger.csv"), index=False, float_format="%.12f", lineterminator="\n")
        pd.DataFrame(annual_rows).to_csv(context.workspace.path("annual_loss_improvement.csv"), index=False, float_format="%.12f", lineterminator="\n")
        combined.to_csv(context.workspace.path("combined_proxy_ledger.csv"), index=False, lineterminator="\n")
        component_panel.to_csv(context.workspace.path("component_panel.csv"), index=False, lineterminator="\n")
        pd.DataFrame([
            {"Input": SYMBOL, "Sha256": INPUT_HASH, "Cutoff": END},
            {"Input": "EX06 information ledger", "Sha256": EX06_LEDGER_SHA256, "Cutoff": END},
            {"Input": "518880 execution manifest", "Sha256": EXECUTION_MANIFEST_SHA256, "Cutoff": END},
        ]).to_csv(context.workspace.path("input_identities.csv"), index=False, lineterminator="\n")
        decision = "COMPONENT_PANEL_PRODUCED" if eligible_count else "STOP_NO_MAJORITY_LIQUIDITY_COMPONENT"
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS if eligible_count else ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": decision, "new_comparison_count": len(ledger),
                "third_proxy_supported": int(ledger["EvidenceLabel"].ne("NOT_SUPPORTED").sum()),
                "eligible_components": eligible_count,
            },
            diagnostics={
                "post_hoc_hypothesis": True, "third_product_replication": True,
                "reads_sealed_validation": False, "strategy_rule_created": False, "candidate_created": False,
            },
            artifacts=tuple(context.workspace.register_artifact(name, kind) for name, kind in (
                ("annual_forward_predictions.csv.gz", "third-proxy-annual-forward-predictions"),
                ("third_proxy_information_ledger.csv", "third-proxy-information-ledger"),
                ("annual_loss_improvement.csv", "third-proxy-annual-stability-ledger"),
                ("combined_proxy_ledger.csv", "three-product-combined-proxy-ledger"),
                ("component_panel.csv", "development-opportunity-component-panel"),
                ("input_identities.csv", "pinned-input-identities"),
            )),
        )
