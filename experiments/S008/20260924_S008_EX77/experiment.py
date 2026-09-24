from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from pathlib import Path

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


EX76 = "20260924_S008_EX76"
EX76_RECEIPT = "5f90b6cfa5bab81174bf1d4cb8cbc770b473b4ce91d14b38711943bf1182f1ea"
EX76_PANEL_SHA256 = "d89fc57148e73cfce4add911c331ee26e20311703fd03e95d92ce75f38d3f154"
EX16_PANEL_SHA256 = "a757cafd1eb1322f4aebe3d68fc5a6792eab9aae8b13eed8f7b83618be2139b4"
FEATURES = ("CpiVolRise", "CpiOr", "PmiBelow50", "PmiDecline", "PmiOr")
CONTROLS = (
    "rate_us_real_10y_level",
    "rate_us_real_10y_change_20d",
    "currency_usdcnh_return_20d",
    "price_return_20d",
)
PERIODS = (("early", 2013, 2018), ("late", 2019, 2024))


def _ic(frame: pd.DataFrame, x: str) -> float | None:
    pair = frame[[x, "Forward20"]].dropna()
    if len(pair) < 6 or pair[x].nunique() < 2 or pair["Forward20"].nunique() < 2:
        return None
    return float(pair[x].corr(pair["Forward20"], method="spearman"))


def _within_year_ic(frame: pd.DataFrame, x: str) -> float | None:
    pair = frame[[x, "Forward20"]].dropna().copy()
    if len(pair) < 12:
        return None
    years = pair.index.year
    ranked = pair.groupby(years).rank(pct=True)
    centered = ranked - ranked.groupby(years).transform("mean")
    if centered[x].std() == 0 or centered["Forward20"].std() == 0:
        return None
    return float(centered[x].corr(centered["Forward20"]))


def _partial_ic(frame: pd.DataFrame, feature: str, alternate: str) -> float | None:
    columns = [feature, "Forward20", alternate, *CONTROLS]
    complete = frame[columns].dropna()
    if len(complete) < 30 or complete[feature].nunique() < 2:
        return None
    ranked = complete.rank(pct=True)
    year_dummies = pd.get_dummies(complete.index.year, drop_first=True, dtype=float)
    design = np.column_stack((
        np.ones(len(complete)),
        ranked[[alternate, *CONTROLS]].to_numpy(dtype=float),
        year_dummies.to_numpy(dtype=float),
    ))
    x = ranked[feature].to_numpy(dtype=float)
    y = ranked["Forward20"].to_numpy(dtype=float)
    rx = x - design @ np.linalg.lstsq(design, x, rcond=None)[0]
    ry = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    if np.std(rx) < 1e-12 or np.std(ry) < 1e-12:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _year_block_difference(early: pd.DataFrame, late: pd.DataFrame, feature: str, seed: int) -> tuple[float | None, float | None, float | None]:
    early_groups = [early.loc[early.index.year == year] for year in range(2013, 2019)]
    late_groups = [late.loc[late.index.year == year] for year in range(2019, 2025)]
    rng = np.random.default_rng(seed)
    differences = []
    for _ in range(1000):
        a = pd.concat([early_groups[i] for i in rng.integers(0, 6, 6)])
        b = pd.concat([late_groups[i] for i in rng.integers(0, 6, 6)])
        a_ic, b_ic = _ic(a, feature), _ic(b, feature)
        if a_ic is not None and b_ic is not None:
            differences.append(b_ic - a_ic)
    if len(differences) < 950:
        return None, None, None
    return (
        float(np.quantile(differences, 0.025)),
        float(np.quantile(differences, 0.975)),
        float(np.mean(np.asarray(differences) > 0)),
    )


class Experiment(ResearchExperiment):
    @property
    def definition(self) -> ExperimentDefinition:
        return ExperimentDefinition(
            schema_version=1,
            experiment_id="20260924_S008_EX77",
            strategy_id="S008",
            mode=ExperimentMode.DISCOVERY,
            research_question="Why do Tushare PMI and CPI paths differ between the two already-viewed S008 development periods?",
            hypothesis="The late-period positive association may reflect macro-state dependence, overlapping price state, or a few influential years.",
            falsification_conditions=(
                "EX76 or EX16 evidence identity differs",
                "Any 20-session outcome crosses its period or the 2024 development cutoff",
                "The apparent shift vanishes with calendar-year clusters, year conditioning, or existing-state controls",
            ),
            development_cutoff=date(2024, 12, 31),
            random_seed=2026097701,
            allowed_datasets=("macro.us_cpi_release", "macro.us_ism_pmi_release"),
            protocol=ExperimentProtocol(
                stage=ExperimentStage.FEATURE_DISCOVERY,
                first_principles=(
                    "Gold demand responds differently to inflation risk and growth fear across monetary regimes",
                    "Persistent price trends and shared macro states can create spurious factor associations",
                ),
                information_paths=FEATURES,
                stage_objectives=("Distinguish period shift from shared state, annual concentration and slow-moving information",),
                observation_metrics=("20-session IC and annual-block difference interval", "within-year, controlled, leave-year-out, delayed and prior-price-state IC"),
                methodology=("Hash-verify EX76 and EX16 archived inputs", "Keep both already viewed periods as development-only evidence", "No feature selection or sealed validation"),
                predecessor_experiment_ids=(EX76,),
            ),
            dependencies=(
                ExperimentDependency("numpy", np.__version__),
                ExperimentDependency("pandas", pd.__version__),
            ),
            capabilities=ExperimentCapabilities(reads_real_returns=True),
        )

    def execute(self, context) -> ExperimentResult:
        predecessor = context.predecessors[EX76]
        if predecessor.receipt_sha256 != EX76_RECEIPT:
            raise ValueError("EX76 receipt differs")
        if predecessor.facts.get("decision") != "DISCOVERY_ONLY_TUSHARE_FACTOR_REVIEW_REQUIRED":
            raise ValueError("EX76 predecessor decision differs")
        root = Path(__file__).resolve().parents[3]
        panel_path = root / "experiments" / "S008" / EX76 / "artifacts" / "causal_monthly_factor_panel.csv"
        control_path = root / "experiments" / "S008" / "20260923_S008_EX16" / "artifacts" / "causal_feature_panel.csv.gz"
        if sha256(panel_path.read_bytes()).hexdigest() != EX76_PANEL_SHA256:
            raise ValueError("EX76 monthly panel identity changed")
        if sha256(control_path.read_bytes()).hexdigest() != EX16_PANEL_SHA256:
            raise ValueError("EX16 controls identity changed")
        context.require_capability(ExperimentCapability.READ_REAL_RETURNS)
        panel = pd.read_csv(panel_path, parse_dates=["Date", "ExitDate20"]).set_index("Date").sort_index()
        controls = pd.read_csv(control_path, compression="gzip", parse_dates=["Date"]).set_index("Date").sort_index()[list(CONTROLS)]
        if len(panel) != 137 or panel.index.max() > pd.Timestamp("2024-12-31") or panel.index.has_duplicates:
            raise ValueError("EX76 decision calendar differs")
        if not panel.index.isin(controls.index).all():
            raise ValueError("EX16 controls do not cover decisions")
        if panel["ExitDate20"].dropna().max() > pd.Timestamp("2024-12-31"):
            raise ValueError("20-session label crosses development cutoff")
        panel = panel.join(controls)
        panel["Lag1CpiVolRise"] = panel["CpiVolRise"].shift(1)
        panel["Lag1CpiOr"] = panel["CpiOr"].shift(1)
        panel["Lag1PmiBelow50"] = panel["PmiBelow50"].shift(1)
        panel["Lag1PmiDecline"] = panel["PmiDecline"].shift(1)
        panel["Lag1PmiOr"] = panel["PmiOr"].shift(1)
        periods = {}
        for name, start, end in PERIODS:
            mask = (panel.index.year >= start) & (panel.index.year <= end) & (panel["ExitDate20"].dt.year <= end)
            periods[name] = panel.loc[mask].copy()
        if len(periods["early"]) < 50 or len(periods["late"]) < 50:
            raise ValueError("insufficient monthly observations")
        rows = []
        for ordinal, feature in enumerate(FEATURES):
            alternate = "PmiBelow50" if feature.startswith("Cpi") else "CpiVolRise"
            early = periods["early"][[feature, "Forward20"]].dropna()
            late = periods["late"][[feature, "Forward20"]].dropna()
            ci_lo, ci_hi, probability = _year_block_difference(early, late, feature, 2026097701 + ordinal)
            annual = {str(year): _ic(late.loc[late.index.year == year], feature) for year in range(2019, 2025)}
            leave_year = {str(year): _ic(late.loc[late.index.year != year], feature) for year in range(2019, 2025)}
            period_metrics = {}
            for name in ("early", "late"):
                frame = periods[name].dropna(subset=[feature, "Forward20"])
                period_metrics[name] = {
                    "N": len(frame),
                    "IC": _ic(frame, feature),
                    "WithinYearIC": _within_year_ic(frame, feature),
                    "ControlledYearIC": _partial_ic(frame, feature, alternate),
                    "FactorMedian": float(frame[feature].median()),
                    "FactorPositiveShare": float(frame[feature].gt(0).mean()),
                    "ForwardMean": float(frame["Forward20"].mean()),
                    "LagOneMonthIC": _ic(frame.rename(columns={f"Lag1{feature}": "lagged"}), "lagged"),
                }
            late_raw = periods["late"].dropna(subset=[feature, "Forward20", "price_return_20d"])
            down = late_raw.loc[late_raw["price_return_20d"].le(0)]
            up = late_raw.loc[late_raw["price_return_20d"].gt(0)]
            rows.append({
                "Feature": feature,
                "OtherFamilyControl": alternate,
                "Early": json.dumps(period_metrics["early"], sort_keys=True, allow_nan=False),
                "Late": json.dumps(period_metrics["late"], sort_keys=True, allow_nan=False),
                "LateMinusEarlyYearBlockCI025": ci_lo,
                "LateMinusEarlyYearBlockCI975": ci_hi,
                "YearBlockDifferencePositiveShare": probability,
                "LateAnnualIC": json.dumps(annual, sort_keys=True, allow_nan=False),
                "LateLeaveOneYearOutIC": json.dumps(leave_year, sort_keys=True, allow_nan=False),
                "LatePriorPriceDownN": len(down),
                "LatePriorPriceDownIC": _ic(down, feature),
                "LatePriorPriceUpN": len(up),
                "LatePriorPriceUpIC": _ic(up, feature),
            })
        ledger = pd.DataFrame(rows)
        ledger.to_csv(context.workspace.path("regime_diagnostic_ledger.csv"), index=False, float_format="%.12f", lineterminator="\n")
        return ExperimentResult(
            outcome=ExperimentOutcome.INCONCLUSIVE,
            facts={"decision": "DISCOVERY_ONLY_REGIME_DIAGNOSIS_REVIEW_REQUIRED", "audited_paths": len(ledger), "reads_previously_viewed_development_periods": True},
            diagnostics={"reads_real_returns": True, "reads_sealed_validation": False, "searches_parameters": False, "creates_candidate": False, "source_revision_and_release_clock_unresolved": True},
            artifacts=(context.workspace.register_artifact("regime_diagnostic_ledger.csv", "tushare-pmi-cpi-regime-diagnosis"),),
        )
