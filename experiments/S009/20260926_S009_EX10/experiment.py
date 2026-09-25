from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path

from czsc_trader.data import load_execution_prices
from dataflows import DataCoverageRequirement, DataRequest, DataStatus, Dataset
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


EXPERIMENT_ID = "20260926_S009_EX10"
PREDECESSOR = "20260926_S009_EX09"
PREDECESSOR_RECEIPT = "b7db0491134c114a40a443ae816df06c99724f8864e649762268302789e1cd39"
POLICY_HASH = "e4cbd292506fd5ec1e85ccbca0ab37b8bbfdc2cea8e0f186fef27f18a22fe525"
VIX_HASH = "58fe62696cd8f5dfff9cfa0dcda9af19aa0a42b7cb8576faf94204a225e1b219"
SHARE_HASHES = {
    "510050.SH": "9364d1e1a8aa7c07ecd622101bc171c6b5887df4429f41a8f2ad367c2a38411d",
    "510300.SH": "49c56544a3de9eb30b4dad39e56b2eec5522c7897c1ac4f94a7db2bc8c8c52c4",
    "159915.SZ": "d3db6a903bb75c4f4abf0bf8ca290311a627b5451e56bafe2c3b75c2f37e9994",
}
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
EX08_COMPONENT_PANEL_SHA256 = "d398767e4f2e98e1eac51b4146ea7bfdd3de678701efdf98dddd8130e8eeb564"
START, POLICY_START, END = "2013-07-29", "2014-03-28", "2024-12-31"
HORIZON = 20
SEED = 2026091001
BOOTSTRAP_REPETITIONS = 2000
PRIOR_EXPLORATORY_COMPARISONS = 18
POLICY_FEATURE = "PolicyUncertaintySurge20"
PRICE_FIELDS = (
    "PriceReturn5",
    "PriceReturn20",
    "PriceReturn60",
    "PriceReturn120",
    "PriceVolatility20",
)
VIX_FIELDS = ("VIXReturn20", "VIXSurge20")
LIQUIDITY_FIELDS = tuple(
    f"{symbol}_ShareFlow{window}"
    for symbol in SHARE_HASHES
    for window in (20, 60)
)
BASELINES = {
    "PRICE": PRICE_FIELDS,
    "PRICE_VIX": (*PRICE_FIELDS, *VIX_FIELDS),
    "PRICE_LIQUIDITY": (*PRICE_FIELDS, *LIQUIDITY_FIELDS),
    "PRICE_VIX_LIQUIDITY": (*PRICE_FIELDS, *VIX_FIELDS, *LIQUIDITY_FIELDS),
}
PRIMARY_BASELINE = "PRICE_VIX_LIQUIDITY"


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _predict(
    train: pd.DataFrame,
    test: pd.DataFrame,
    fields: tuple[str, ...],
) -> tuple[np.ndarray, int, float]:
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
    return float(pd.Series(np.asarray(left)).corr(pd.Series(np.asarray(right)), method="spearman"))


def _bh(values: pd.Series) -> pd.Series:
    result = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna().sort_values()
    adjusted = valid.to_numpy() * len(valid) / np.arange(1, len(valid) + 1)
    result.loc[valid.index] = np.minimum(np.minimum.accumulate(adjusted[::-1])[::-1], 1.0)
    return result


def _bootstrap(series: pd.Series, seed: int) -> tuple[float, float, float]:
    values = series.to_numpy(dtype=float)
    observed = float(values.mean())
    length = len(values)
    blocks = (length + HORIZON - 1) // HORIZON
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, length - HORIZON + 1, size=(BOOTSTRAP_REPETITIONS, blocks))
    indices = (starts[:, :, None] + np.arange(HORIZON)).reshape(
        BOOTSTRAP_REPETITIONS, -1
    )[:, :length]
    sampled = values[indices].mean(axis=1)
    centered = values - observed
    null_means = centered[indices].mean(axis=1)
    p_value = float((1 + np.count_nonzero(null_means >= observed)) / (BOOTSTRAP_REPETITIONS + 1))
    lower, upper = np.quantile(sampled, [0.025, 0.975])
    return p_value, float(lower), float(upper)


def synthetic_precheck() -> None:
    dates = pd.bdate_range("2024-01-01", periods=160)
    source = pd.DataFrame({
        "AvailableDate": dates,
        "PolicyUncertaintyIndex": np.linspace(100.0, 180.0, len(dates)),
    })
    decisions = pd.DataFrame({"Date": dates[1:]})
    aligned = pd.merge_asof(
        decisions,
        source,
        left_on="Date",
        right_on="AvailableDate",
        direction="backward",
        allow_exact_matches=False,
    )
    feature = np.log(
        aligned["PolicyUncertaintyIndex"].rolling(20).mean()
        / aligned["PolicyUncertaintyIndex"].rolling(120).mean()
    )
    if feature.notna().sum() != len(aligned) - 119:
        raise ValueError("policy uncertainty transform differs")
    if not aligned["AvailableDate"].lt(aligned["Date"]).all():
        raise ValueError("strict-prior policy alignment differs")
    if not np.allclose(_bh(pd.Series([0.01, 0.10])).to_numpy(), [0.02, 0.10]):
        raise ValueError("BH correction differs")


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id=EXPERIMENT_ID,
            strategy_id="S009",
            mode=ExperimentMode.DISCOVERY,
            research_question=(
                "Does causal U.S. policy uncertainty add 20-day upside information beyond price, VIX, and broad liquidity?"
            ),
            hypothesis=(
                "A rise in news-based policy uncertainty drives safe-haven allocation that remains distinct from "
                "market volatility and broad-equity ETF creation flows."
            ),
            falsification_conditions=(
                "The primary combined baseline has non-positive loss improvement or fewer than four positive years",
                "Early or late rank IC is non-positive, model rank does not improve, or BH q exceeds 0.10",
                "The feature has absolute correlation of at least 0.50 with VIX or any liquidity proxy",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=SEED,
            allowed_datasets=(
                Dataset.US_POLICY_UNCERTAINTY_DAILY.value,
                Dataset.VIX_DAILY.value,
                Dataset.ETF_SHARE_SIZE.value,
                Dataset.ETF_UNADJUSTED_DAILY.value,
            ),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "A return-seeking component must explain remaining upside beyond existing opportunity information",
                    "Policy news is a participant-behavior input, while VIX and ETF creations are market-price and flow inputs",
                ),
                information_paths=(
                    "Policy-news uncertainty -> global safe-haven allocation -> later RMB gold ETF appreciation",
                ),
                stage_objectives=(
                    "Add or reject one policy-uncertainty OPPORTUNITY component under the strongest combined baseline",
                ),
                observation_metrics=(
                    "paired MSE improvement, annual stability, rank IC, block-bootstrap p/q, redundancy correlations",
                ),
                methodology=(
                    "Evaluate one frozen feature against four annual-forward baselines at a 20-session horizon",
                    "Use only the strongest price-plus-VIX-plus-liquidity baseline for component admission",
                ),
                predecessor_experiment_ids=(PREDECESSOR,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
            subjects=("518880.SH",),
        )

    def synthetic_precheck(self) -> None:
        synthetic_precheck()

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[PREDECESSOR]
        if predecessor.receipt_sha256 != PREDECESSOR_RECEIPT:
            raise ValueError("EX09 predecessor receipt differs")
        if predecessor.facts.get("decision") != "PROCEED_TO_POLICY_UNCERTAINTY_INFORMATION_AUDIT":
            raise ValueError("EX09 data-gate decision differs")
        if predecessor.facts.get("input_sha256") != POLICY_HASH:
            raise ValueError("EX09 policy input identity differs")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)

        root = Path(__file__).resolve().parents[3]
        manifest_path = root / "data/raw/518880_execution_manifest.json"
        component_path = root / "experiments/S009/20260925_S009_EX08/artifacts/component_panel.csv"
        if _sha256(manifest_path) != EXECUTION_MANIFEST_SHA256:
            raise ValueError("execution price manifest differs")
        if _sha256(component_path) != EX08_COMPONENT_PANEL_SHA256:
            raise ValueError("EX08 component panel differs")

        prices = load_execution_prices(
            root / "data/raw", symbol="518880.SH", asset_type="etf", cutoff=END
        )
        panel = prices.rename(columns={"dt": "Date", "open": "Open", "close": "Close"}).loc[
            :, ["Date", "Open", "Close"]
        ]
        panel["Date"] = pd.to_datetime(panel["Date"]).dt.normalize()
        panel = panel.sort_values("Date").reset_index(drop=True)

        publications = {}
        policy = context.data.fetch(DataRequest(
            Dataset.US_POLICY_UNCERTAINTY_DAILY,
            None,
            POLICY_START,
            END,
            None,
            options={"env_file": ".env"},
            coverage=DataCoverageRequirement(maximum_start_lag_days=0, minimum_rows=3900),
        ))
        if policy.status is not DataStatus.READY or policy.identity is None:
            raise RuntimeError("policy uncertainty input is not READY")
        if policy.identity.content_sha256 != POLICY_HASH:
            raise ValueError("policy uncertainty input identity differs")
        publications["USEPUINDXD"] = policy
        source = policy.dataframe.rename(columns={"Date": "ObservationDate"}).sort_values(
            ["AvailableDate", "ObservationDate"]
        )
        panel = pd.merge_asof(
            panel,
            source.loc[:, ["ObservationDate", "AvailableDate", "PolicyUncertaintyIndex"]],
            left_on="Date",
            right_on="AvailableDate",
            direction="backward",
            allow_exact_matches=False,
        )
        if not panel.loc[panel["AvailableDate"].notna(), "AvailableDate"].lt(
            panel.loc[panel["AvailableDate"].notna(), "Date"]
        ).all():
            raise ValueError("policy uncertainty is not strictly prior")
        panel[POLICY_FEATURE] = np.log(
            panel["PolicyUncertaintyIndex"].rolling(20).mean()
            / panel["PolicyUncertaintyIndex"].rolling(120).mean()
        )

        vix = context.data.fetch(DataRequest(
            Dataset.VIX_DAILY,
            "VIX",
            POLICY_START,
            END,
            END,
            options={"env_file": ".env"},
        ))
        if vix.status is not DataStatus.READY or vix.identity is None:
            raise RuntimeError("VIX input is not READY")
        if vix.identity.content_sha256 != VIX_HASH:
            raise ValueError("VIX input identity differs")
        publications["VIX"] = vix
        vix_source = vix.dataframe.loc[:, ["Date", "Close"]].copy().sort_values("Date")
        vix_source["VIXReturn20"] = np.log(vix_source["Close"]).diff(20)
        vix_source["VIXSurge20"] = np.log(
            vix_source["Close"].rolling(20).mean() / vix_source["Close"].rolling(120).mean()
        )
        panel = pd.merge_asof(
            panel.sort_values("Date"),
            vix_source.loc[:, ["Date", *VIX_FIELDS]].rename(columns={"Date": "VIXDate"}),
            left_on="Date",
            right_on="VIXDate",
            direction="backward",
            allow_exact_matches=False,
        )

        for symbol in ("510050.SH", "510300.SH"):
            item = context.data.fetch(DataRequest(
                Dataset.ETF_SHARE_SIZE,
                symbol,
                START,
                END,
                END,
                options={"env_file": ".env"},
            ))
            if item.status is not DataStatus.READY or item.identity is None:
                raise RuntimeError(f"{symbol} share input is not READY")
            if item.identity.content_sha256 != SHARE_HASHES[symbol]:
                raise ValueError(f"{symbol} share identity differs")
            publications[symbol] = item
            shares = item.dataframe.loc[:, ["Date", "TotalShare"]].rename(
                columns={"Date": "ShareDate"}
            ).sort_values("ShareDate")
            for window in (20, 60):
                shares[f"{symbol}_ShareFlow{window}"] = np.log(shares["TotalShare"]).diff(window)
            panel = pd.merge_asof(
                panel.sort_values("Date"),
                shares.loc[:, ["ShareDate", f"{symbol}_ShareFlow20", f"{symbol}_ShareFlow60"]],
                left_on="Date",
                right_on="ShareDate",
                direction="backward",
                allow_exact_matches=False,
            )

        symbol = "159915.SZ"
        item = context.data.fetch(DataRequest(
            Dataset.ETF_SHARE_SIZE,
            symbol,
            START,
            END,
            END,
            options={"env_file": ".env"},
        ))
        if item.status is not DataStatus.READY or item.identity is None:
            raise RuntimeError(f"{symbol} share input is not READY")
        if item.identity.content_sha256 != SHARE_HASHES[symbol]:
            raise ValueError(f"{symbol} share identity differs")
        publications[symbol] = item
        shares = item.dataframe.set_index(
            pd.to_datetime(item.dataframe["Date"]).dt.normalize()
        )["TotalShare"].astype(float)
        shares = shares.reindex(pd.DatetimeIndex(panel["Date"])).ffill()
        if shares.isna().any():
            raise ValueError("159915 causal forward-fill left unavailable values")
        for window in (20, 60):
            panel[f"{symbol}_ShareFlow{window}"] = np.log(shares).diff(window).shift(1).to_numpy()

        log_close = np.log(panel["Close"])
        panel["PriceReturn5"] = log_close.diff(5)
        panel["PriceReturn20"] = log_close.diff(20)
        panel["PriceReturn60"] = log_close.diff(60)
        panel["PriceReturn120"] = log_close.diff(120)
        panel["PriceVolatility20"] = log_close.diff().rolling(20).std(ddof=0)
        panel["Outcome"] = np.log(panel["Open"].shift(-(HORIZON + 1)) / panel["Open"].shift(-1))
        panel["OutcomeEnd"] = panel["Date"].shift(-(HORIZON + 1))

        prediction_rows = []
        annual_rows = []
        summary_rows = []
        for baseline_index, (name, fields) in enumerate(BASELINES.items()):
            frame = panel.loc[:, ["Date", *fields, POLICY_FEATURE, "Outcome", "OutcomeEnd"]].dropna()
            parts = []
            ranks = []
            conditions = []
            for year in range(2019, 2025):
                cutoff = pd.Timestamp(year=year, month=1, day=1)
                train = frame.loc[frame["OutcomeEnd"] < cutoff]
                test = frame.loc[frame["Date"].dt.year == year]
                baseline, baseline_rank, baseline_condition = _predict(train, test, fields)
                extended, extended_rank, extended_condition = _predict(
                    train, test, (*fields, POLICY_FEATURE)
                )
                part = test.loc[:, ["Date", POLICY_FEATURE, "Outcome"]].copy()
                part["Baseline"] = name
                part["Year"] = year
                part["BaselinePrediction"] = baseline
                part["ExtendedPrediction"] = extended
                part["LossImprovement"] = (
                    (part["Outcome"].to_numpy() - baseline) ** 2
                    - (part["Outcome"].to_numpy() - extended) ** 2
                )
                parts.append(part)
                ranks.append((baseline_rank, extended_rank))
                conditions.append((baseline_condition, extended_condition))
                annual_rows.append({
                    "Baseline": name,
                    "Year": year,
                    "N": len(part),
                    "DeltaMSE": float(part["LossImprovement"].mean()),
                    "FeatureRankIC": _rank_ic(part[POLICY_FEATURE], part["Outcome"]),
                })
            predictions = pd.concat(parts, ignore_index=True)
            prediction_rows.append(predictions)
            early = predictions.loc[predictions["Year"] <= 2021]
            late = predictions.loc[predictions["Year"] >= 2022]
            p_value, lower, upper = _bootstrap(
                predictions["LossImprovement"], SEED + baseline_index
            )
            summary_rows.append({
                "Baseline": name,
                "N": len(predictions),
                "DeltaMSE": float(predictions["LossImprovement"].mean()),
                "Bootstrap95Lower": lower,
                "Bootstrap95Upper": upper,
                "PositiveYears": int(
                    (predictions.groupby("Year")["LossImprovement"].mean() > 0).sum()
                ),
                "FeatureRankIC": _rank_ic(predictions[POLICY_FEATURE], predictions["Outcome"]),
                "FeatureRankIC2019_2021": _rank_ic(early[POLICY_FEATURE], early["Outcome"]),
                "FeatureRankIC2022_2024": _rank_ic(late[POLICY_FEATURE], late["Outcome"]),
                "BaselineRankIC": _rank_ic(predictions["Outcome"], predictions["BaselinePrediction"]),
                "ExtendedRankIC": _rank_ic(predictions["Outcome"], predictions["ExtendedPrediction"]),
                "PValue": p_value,
                "MinimumBaselineRank": min(item[0] for item in ranks),
                "MinimumExtendedRank": min(item[1] for item in ranks),
                "MaximumBaselineCondition": max(item[0] for item in conditions),
                "MaximumExtendedCondition": max(item[1] for item in conditions),
            })

        summary = pd.DataFrame(summary_rows)
        summary["QValue"] = _bh(summary["PValue"])
        correlations = []
        evaluation = panel.loc[panel["Date"].dt.year.between(2019, 2024)]
        for field in (*VIX_FIELDS, *LIQUIDITY_FIELDS):
            pair = evaluation.loc[:, [POLICY_FEATURE, field]].dropna()
            correlations.append({
                "Comparator": field,
                "N": len(pair),
                "Spearman": _rank_ic(pair[POLICY_FEATURE], pair[field]),
            })
        correlation_frame = pd.DataFrame(correlations)
        maximum_abs_correlation = float(correlation_frame["Spearman"].abs().max())
        primary = summary.loc[summary["Baseline"].eq(PRIMARY_BASELINE)].iloc[0]
        eligible = bool(
            primary["DeltaMSE"] > 0
            and primary["PositiveYears"] >= 4
            and primary["FeatureRankIC2019_2021"] > 0
            and primary["FeatureRankIC2022_2024"] > 0
            and primary["ExtendedRankIC"] > primary["BaselineRankIC"]
            and primary["QValue"] <= 0.10
            and maximum_abs_correlation < 0.50
        )

        prior_panel = pd.read_csv(component_path)
        component_decision = pd.DataFrame([{
            "Component": "PolicyUncertainty20",
            "Role": "OPPORTUNITY",
            "Window": 20,
            "Mechanism": "global policy-news uncertainty drives safe-haven allocation to gold",
            "Eligible": eligible,
            "PrimaryBaseline": PRIMARY_BASELINE,
            "PrimaryDeltaMSE": float(primary["DeltaMSE"]),
            "PositiveYears": int(primary["PositiveYears"]),
            "PrimaryQValue": float(primary["QValue"]),
            "MaximumAbsComparatorCorrelation": maximum_abs_correlation,
            "EvidenceOrigin": "POST_HOC_FRED_DISCOVERY_FORMAL_DEVELOPMENT_AUDIT",
            "Status": "DEVELOPMENT_SUPPORTED_POST_HOC" if eligible else "REJECTED",
        }])
        component_panel = prior_panel.copy()
        if eligible:
            component_panel = pd.concat([
                component_panel,
                pd.DataFrame([{
                    "Component": "PolicyUncertainty20",
                    "Role": "OPPORTUNITY",
                    "Window": 20,
                    "Mechanism": "global policy-news uncertainty drives safe-haven allocation to gold",
                    "ProxyCount": 1,
                    "SupportedProxyCount": 1,
                    "Eligible": True,
                    "EvidenceOrigin": "POST_HOC_FRED_DISCOVERY_FORMAL_DEVELOPMENT_AUDIT",
                    "Status": "DEVELOPMENT_SUPPORTED_POST_HOC",
                }]),
            ], ignore_index=True)

        pd.concat(prediction_rows, ignore_index=True).to_csv(
            context.workspace.path("annual_forward_predictions.csv.gz"),
            index=False,
            float_format="%.12f",
            compression="gzip",
            lineterminator="\n",
        )
        pd.DataFrame(annual_rows).to_csv(
            context.workspace.path("annual_loss_improvement.csv"),
            index=False,
            float_format="%.12f",
            lineterminator="\n",
        )
        summary.to_csv(
            context.workspace.path("baseline_comparison_ledger.csv"),
            index=False,
            float_format="%.12f",
            lineterminator="\n",
        )
        correlation_frame.to_csv(
            context.workspace.path("redundancy_correlations.csv"),
            index=False,
            float_format="%.12f",
            lineterminator="\n",
        )
        component_decision.to_csv(
            context.workspace.path("policy_component_decision.csv"),
            index=False,
            float_format="%.12f",
            lineterminator="\n",
        )
        component_panel.to_csv(
            context.workspace.path("component_panel.csv"), index=False, lineterminator="\n"
        )
        identities = pd.DataFrame([
            {
                "Input": name,
                "ContentSha256": item.identity.content_sha256,
                "DataStart": item.identity.data_start,
                "DataCutoff": item.identity.data_cutoff,
            }
            for name, item in publications.items()
        ])
        identities.to_csv(
            context.workspace.path("input_identities.csv"), index=False, lineterminator="\n"
        )
        decision = "COMPONENT_PANEL_EXPANDED" if eligible else "KEEP_EXISTING_PANEL_NO_NEW_COMPONENT"
        return ExperimentResult(
            outcome=ExperimentOutcome.PASS,
            facts={
                "decision": decision,
                "new_component_eligible": eligible,
                "component_count": len(component_panel),
                "primary_delta_mse": float(primary["DeltaMSE"]),
                "primary_positive_years": int(primary["PositiveYears"]),
                "primary_q_value": float(primary["QValue"]),
                "maximum_abs_comparator_correlation": maximum_abs_correlation,
                "formal_comparisons": len(summary),
                "prior_exploratory_comparisons": PRIOR_EXPLORATORY_COMPARISONS,
            },
            diagnostics={
                "reads_real_returns": True,
                "reads_sealed_validation": False,
                "evidence_status": "DISCOVERY_ONLY_POST_HOC",
            },
            artifacts=(
                context.workspace.register_artifact(
                    "annual_forward_predictions.csv.gz", "policy-uncertainty-annual-forward-predictions"
                ),
                context.workspace.register_artifact(
                    "annual_loss_improvement.csv", "policy-uncertainty-annual-loss-improvement"
                ),
                context.workspace.register_artifact(
                    "baseline_comparison_ledger.csv", "policy-uncertainty-baseline-comparison-ledger"
                ),
                context.workspace.register_artifact(
                    "redundancy_correlations.csv", "policy-uncertainty-redundancy-correlations"
                ),
                context.workspace.register_artifact(
                    "policy_component_decision.csv", "policy-uncertainty-component-decision"
                ),
                context.workspace.register_artifact(
                    "component_panel.csv", "expanded-S009-component-panel"
                ),
                context.workspace.register_artifact(
                    "input_identities.csv", "policy-uncertainty-input-identities"
                ),
            ),
        )
