from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
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
import statsmodels.api as sm


EX75 = "20260924_S008_EX75"
EX75_RECEIPT = "b9960087006c4861efa7e595398fe6ff40b96b3f1808f6816d1c4088a2b0fe40"
EX16_PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
EXECUTION_MANIFEST_SHA256 = "fc5aac30019deed1c04204b7e3a967963782bf0e8bfbe5da3e1b1ce420a832a8"
START, CUTOFF = "2013-01-01", "2024-12-31"
DISCOVERY_END, CONFIRMATION_START = "2018-12-31", "2019-01-01"
DATASETS = (
    (Dataset.US_REAL_YIELD_DAILY, None),
    (Dataset.US_CPI_RELEASE, None),
    (Dataset.US_NOMINAL_YIELD_DAILY, None),
    (Dataset.US_ISM_PMI_RELEASE, None),
    (Dataset.US_FEDERAL_BUDGET_RELEASE, None),
    (Dataset.GLOBAL_INDEX_DAILY, "SPX"),
)
FEATURES = (
    "RealYieldFall", "CpiVolRise", "CpiOr", "PmiBelow50",
    "PmiDecline", "PmiOr", "DeficitMA12Increase", "StockBondCorrProxy",
)
CONTROLS = (
    "rate_us_real_10y_level",
    "rate_us_real_10y_change_20d",
    "currency_usdcnh_return_20d",
    "price_return_20d",
)
HORIZONS = (5, 20, 60)


def _asof(series: pd.Series, through: pd.Timestamp) -> float:
    prior = series.loc[series.index <= through]
    return float(prior.iloc[-1]) if not prior.empty else float("nan")


def _last_values(series: pd.Series, through: pd.Timestamp, count: int) -> pd.Series:
    return series.loc[series.index <= through].tail(count)


def _ic(x: pd.Series, y: pd.Series) -> float | None:
    pair = pd.concat([x.rename("x"), y.rename("y")], axis=1).dropna()
    if len(pair) < 3 or pair["x"].nunique() < 2 or pair["y"].nunique() < 2:
        return None
    return float(pair["x"].corr(pair["y"], method="spearman"))


def _partial_ic(frame: pd.DataFrame) -> float | None:
    complete = frame.loc[:, ["score", "outcome", *CONTROLS]].dropna()
    if len(complete) < 30 or complete["score"].nunique() < 2:
        return None
    design = sm.add_constant(complete.loc[:, CONTROLS].astype(float), has_constant="add")
    score_residual = sm.OLS(complete["score"].astype(float), design).fit().resid
    outcome_residual = sm.OLS(complete["outcome"].astype(float), design).fit().resid
    return _ic(score_residual, outcome_residual)


def _bootstrap_positive(frame: pd.DataFrame, seed: int) -> float | None:
    pair = frame.loc[:, ["score", "outcome"]].dropna()
    if len(pair) < 50 or pair["score"].nunique() < 2:
        return None
    ranked = pair.rank(method="average", pct=True).to_numpy(dtype=float)
    n = len(ranked)
    rng = np.random.default_rng(seed)
    starts = rng.integers(0, n, size=(500, (n + 2) // 3))
    indices = ((starts[:, :, None] + np.arange(3)) % n).reshape(500, -1)[:, :n]
    samples = ranked[indices]
    x = samples[:, :, 0] - samples[:, :, 0].mean(axis=1, keepdims=True)
    y = samples[:, :, 1] - samples[:, :, 1].mean(axis=1, keepdims=True)
    denominator = np.sqrt((x * x).sum(axis=1) * (y * y).sum(axis=1))
    correlations = (x * y).sum(axis=1) / denominator
    valid = correlations[np.isfinite(correlations)]
    return float(np.mean(valid > 0)) if len(valid) >= 475 else None


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX76",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Which Tushare-supported gold factor information paths remain useful after causal and existing-state checks?",
            hypothesis="At least one published macro path adds stable upside participation information beyond existing state controls.",
            falsification_conditions=(
                "DFLS identity or causal boundary differs from EX75",
                "A prior-month feature leaks a future source observation",
                "Apparent effects reverse across development subperiods or disappear after controls",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097601,
            allowed_datasets=tuple(item[0].value for item in DATASETS),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Opportunity cost, inflation, growth, fiscal credit and cross-asset stress can change gold demand",
                    "The same information may already be priced or reversed by monetary-policy responses",
                ),
                information_paths=tuple(FEATURES),
                stage_objectives=(
                    "Audit all preregistered Tushare factor paths without selecting a strategy",
                    "Separate raw association from existing-state overlap and temporal instability",
                ),
                observation_metrics=(
                    "5/20/60-session rank IC, partial IC, annual direction and block bootstrap",
                    "binary signal class counts and conditional forward-return difference",
                ),
                methodology=(
                    "Verify EX75 identity and synthetic precheck before reading development returns",
                    "Use only prior-month US closes and releases available by the fifth SSE decision close",
                    "Keep both previously viewed subperiods labelled as development evidence",
                ),
                predecessor_experiment_ids=(EX75,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
                ExperimentDependency("statsmodels", sm.__version__),
                ExperimentDependency("tushare", "1.4.29"),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX75]
        if predecessor.receipt_sha256 != EX75_RECEIPT:
            raise ValueError("EX75 receipt differs")
        if predecessor.facts.get("decision") != "PROCEED_TUSHARE_FACTOR_INFORMATION_AUDIT":
            raise ValueError("EX75 did not pass the data gate")
        hashes = dict(predecessor.facts["content_sha256_by_dataset"])
        frames = {}
        for dataset, symbol in DATASETS:
            publication = context.data.fetch(DataRequest(
                dataset, symbol, START, CUTOFF, "2024-12-01",
                options={"env_file": ".env"},
            ))
            if publication.status is not DataStatus.READY or publication.identity is None:
                raise RuntimeError(f"DFLS {dataset.value} is not READY")
            if publication.identity.content_sha256 != hashes[dataset.value]:
                raise ValueError(f"DFLS {dataset.value} source identity changed")
            frames[dataset] = publication.dataframe.copy().sort_values("Date")

        root = Path(__file__).resolve().parents[3]
        control_path = root / "experiments" / "S008" / "20260923_S008_EX16" / "artifacts" / "causal_feature_panel.csv.gz"
        if sha256(control_path.read_bytes()).hexdigest() != EX16_PANEL_SHA256:
            raise ValueError("EX16 causal feature panel identity changed")
        controls = pd.read_csv(control_path, compression="gzip", parse_dates=["Date"]).set_index("Date").sort_index()[list(CONTROLS)]
        if sha256((root / "data" / "raw" / "518880_execution_manifest.json").read_bytes()).hexdigest() != EXECUTION_MANIFEST_SHA256:
            raise ValueError("execution-price manifest identity changed")

        real = frames[Dataset.US_REAL_YIELD_DAILY].set_index("Date")["RealYield10YPercent"].astype(float)
        cpi = frames[Dataset.US_CPI_RELEASE].set_index("AvailableDate")["YoYPercent"].astype(float)
        nominal = frames[Dataset.US_NOMINAL_YIELD_DAILY].set_index("Date")["NominalYield10YPercent"].astype(float)
        pmi = frames[Dataset.US_ISM_PMI_RELEASE].set_index("AvailableDate")["PmiIndex"].astype(float)
        balance = frames[Dataset.US_FEDERAL_BUDGET_RELEASE].set_index("AvailableDate")["BudgetBalanceBillionUSD"].astype(float)
        spx = frames[Dataset.GLOBAL_INDEX_DAILY].set_index("Date")["PercentChange"].astype(float)
        if any(series.index.has_duplicates for series in (real, cpi, nominal, pmi, balance, spx)):
            raise ValueError("factor input has duplicate source or available date")
        joint = pd.concat([spx.rename("equity"), nominal.diff().mul(-1).rename("bond_proxy")], axis=1, join="inner").dropna()
        correlation = joint["equity"].rolling(252, min_periods=252).corr(joint["bond_proxy"])

        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        prices = load_execution_prices(root / "data" / "raw", symbol="518880.SH", asset_type="etf", cutoff=CUTOFF)
        prices["Date"] = pd.to_datetime(prices["dt"]).dt.normalize()
        prices = prices.set_index("Date").sort_index()
        if not prices.index.equals(controls.index):
            raise ValueError("ETF execution and EX16 control calendars differ")
        opens = prices["open"].astype(float)
        outcomes = {h: opens.shift(-(h + 1)).div(opens.shift(-1)).sub(1) for h in HORIZONS}
        exits = {h: pd.Series(prices.index, index=prices.index).shift(-(h + 1)) for h in HORIZONS}

        monthly = []
        for _, group in prices.groupby(prices.index.to_period("M")):
            if len(group) < 5:
                continue
            decision = group.index[4]
            if decision < pd.Timestamp("2013-08-01") or decision > pd.Timestamp(CUTOFF):
                continue
            prior_month = (decision.to_period("M") - 1).to_timestamp(how="end").normalize()
            two_months = (decision.to_period("M") - 2).to_timestamp(how="end").normalize()
            real_fall = _asof(real, two_months) - _asof(real, prior_month)
            cpi_known = _last_values(cpi, decision, 7)
            cpi_vol = cpi_known.rolling(6, min_periods=6).std(ddof=0)
            cpi_delta = float(cpi_vol.iloc[-1] - cpi_vol.iloc[-2]) if len(cpi_vol) >= 7 else float("nan")
            cpi_or = float(cpi_known.iloc[-1] > cpi_known.iloc[-2] or cpi_delta > 0) if np.isfinite(cpi_delta) else float("nan")
            pmi_known = _last_values(pmi, decision, 2)
            pmi_below = 50.0 - float(pmi_known.iloc[-1]) if len(pmi_known) == 2 else float("nan")
            pmi_decline = float(pmi_known.iloc[-2] - pmi_known.iloc[-1]) if len(pmi_known) == 2 else float("nan")
            pmi_or = float(pmi_below > 0 or pmi_decline > 0) if len(pmi_known) == 2 else float("nan")
            budget_known = _last_values(balance, decision, 13)
            deficit_ma = budget_known.mul(-1).rolling(12, min_periods=12).mean()
            deficit_delta = float(deficit_ma.iloc[-1] - deficit_ma.iloc[-2]) if len(deficit_ma) == 13 else float("nan")
            nominal_rise = _asof(nominal, prior_month) - _asof(nominal, two_months)
            corr_now = _asof(correlation, prior_month)
            corr_prev = _asof(correlation, two_months)
            corr_proxy = float(nominal_rise > 0 and corr_now < 0 and corr_now < corr_prev) if np.isfinite(corr_now) and np.isfinite(corr_prev) else float("nan")
            monthly.append({
                "Date": decision,
                "RealYieldFall": real_fall,
                "CpiVolRise": cpi_delta,
                "CpiOr": cpi_or,
                "PmiBelow50": pmi_below,
                "PmiDecline": pmi_decline,
                "PmiOr": pmi_or,
                "DeficitMA12Increase": deficit_delta,
                "StockBondCorrProxy": corr_proxy,
            })
        panel = pd.DataFrame(monthly).set_index("Date").sort_index()
        if panel.empty or len(panel) != 137 or not panel.index.isin(controls.index).all():
            raise ValueError("monthly decision panel differs from the preregistered calendar")
        for h in HORIZONS:
            panel[f"Forward{h}"] = outcomes[h].loc[panel.index]
            panel[f"ExitDate{h}"] = exits[h].loc[panel.index]
        panel.index.name = "Date"
        panel_path = context.workspace.path("causal_monthly_factor_panel.csv")
        panel.to_csv(panel_path, float_format="%.12f", lineterminator="\n")

        ledger = []
        for ordinal, feature in enumerate(FEATURES):
            for h in HORIZONS:
                records = {}
                for period, start, end in (
                    ("discovery", pd.Timestamp("2013-08-01"), pd.Timestamp(DISCOVERY_END)),
                    ("confirmation", pd.Timestamp(CONFIRMATION_START), pd.Timestamp(CUTOFF)),
                ):
                    mask = panel.index.to_series().ge(start) & panel.index.to_series().le(end) & panel[f"ExitDate{h}"].le(end)
                    dates = panel.index[mask]
                    records[period] = pd.DataFrame({
                        "score": panel.loc[dates, feature],
                        "outcome": panel.loc[dates, f"Forward{h}"],
                    }).join(controls).dropna(subset=["score", "outcome"])
                d, c = records["discovery"], records["confirmation"]
                annual = {
                    str(year): _ic(c.loc[c.index.year == year, "score"], c.loc[c.index.year == year, "outcome"])
                    for year in range(2019, 2025)
                }
                bullish = c.loc[c["score"].gt(0), "outcome"]
                bearish = c.loc[c["score"].le(0), "outcome"]
                ledger.append({
                    "Feature": feature,
                    "Horizon": h,
                    "DiscoveryN": len(d),
                    "ConfirmationN": len(c),
                    "ConfirmationUniqueValues": int(c["score"].nunique()),
                    "DiscoveryIC": _ic(d["score"], d["outcome"]),
                    "ConfirmationIC": _ic(c["score"], c["outcome"]),
                    "ConfirmationPartialIC": _partial_ic(c),
                    "ConfirmationPositiveYears": sum(value is not None and value > 0 for value in annual.values()),
                    "ConfirmationAnnualIC": json.dumps(annual, sort_keys=True, allow_nan=False),
                    "ConfirmationBootstrapPositive": _bootstrap_positive(c, 2026097601 + ordinal * 100 + h),
                    "ConfirmationScorePositiveN": len(bullish),
                    "ConfirmationScoreNonpositiveN": len(bearish),
                    "ConfirmationMeanSpread": float(bullish.mean() - bearish.mean()) if len(bullish) and len(bearish) else None,
                })
        ledger_frame = pd.DataFrame(ledger)
        ledger_path = context.workspace.path("information_path_ledger.csv")
        ledger_frame.to_csv(ledger_path, index=False, float_format="%.12f", lineterminator="\n")
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={
                "decision": "DISCOVERY_ONLY_TUSHARE_FACTOR_REVIEW_REQUIRED",
                "monthly_decisions": len(panel),
                "audited_paths": len(ledger_frame),
                "reads_previously_viewed_development_subperiods": True,
            },
            diagnostics={
                "reads_real_returns": True,
                "reads_sealed_validation": False,
                "selects_prototype": False,
                "searches_parameters": False,
                "creates_candidate": False,
            },
            artifacts=(
                context.workspace.register_artifact("causal_monthly_factor_panel.csv", "development-monthly-factor-panel"),
                context.workspace.register_artifact("information_path_ledger.csv", "tushare-factor-information-ledger"),
            ),
        )
